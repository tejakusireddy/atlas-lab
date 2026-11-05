import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from atlas_campaigns.database import Connection, connect, migrate
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import (
    Conflict,
    NotFound,
    create_campaign,
    get_campaign,
    list_campaigns,
)
from psycopg import sql

pytestmark = pytest.mark.integration


def command() -> CreateCampaign:
    return CreateCampaign(
        dataset_snapshot_id="synthetic-snapshot", campaign_group_id="synthetic-group"
    )


def test_create_is_atomic_idempotent_and_owner_scoped(database: Connection) -> None:
    first = create_campaign(database, command(), "scientist", "key", uuid4(), "trace")
    repeated = create_campaign(database, command(), "scientist", "key", uuid4(), "trace")
    assert first == repeated
    assert first.status == "DRAFT"
    for table in ("campaigns", "mutation_keys", "audit_events", "outbox_events"):
        row = database.execute(
            sql.SQL("SELECT count(*) AS count FROM {}").format(sql.Identifier(table))
        ).fetchone()
        assert row is not None and row["count"] == 1
    with pytest.raises(Conflict):
        create_campaign(
            database, command().model_copy(update={"seed": 7}), "scientist", "key", uuid4(), "trace"
        )
    with pytest.raises(NotFound):
        get_campaign(database, first.id, "other-scientist")
    assert list_campaigns(database, "other-scientist") == []


def test_failure_rolls_back_campaign_key_and_outbox(database: Connection) -> None:
    with pytest.raises(RuntimeError), database.transaction():
        create_campaign(database, command(), "scientist", "rollback", uuid4(), "trace")
        raise RuntimeError("injected failure before outer commit")
    assert list_campaigns(database, "scientist") == []
    assert database.execute("SELECT * FROM mutation_keys").fetchone() is None
    assert database.execute("SELECT * FROM outbox_events").fetchone() is None


def test_audit_records_reject_mutation(database: Connection) -> None:
    create_campaign(database, command(), "scientist", "key", uuid4(), "trace")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        database.execute("UPDATE audit_events SET actor_id='tampered'")


def test_migrations_repeat_and_detect_drift(database: Connection, tmp_path: Path) -> None:
    migrate(database)
    for source in Path("sql").glob("*.sql"):
        (tmp_path / source.name).write_text(source.read_text() + "\n-- drift\n")
    with pytest.raises(ValueError, match="changed"):
        migrate(database, tmp_path)


def test_concurrent_duplicate_requests_create_one_campaign(database: Connection) -> None:
    row = database.execute("SELECT current_schema() AS schema").fetchone()
    assert row is not None
    schema = row["schema"]
    dsn = os.environ["ATLAS_TEST_DATABASE_URL"]

    def submit(_: int) -> str:
        with connect(dsn) as connection:
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            return str(
                create_campaign(
                    connection, command(), "scientist", "concurrent", uuid4(), "trace"
                ).id
            )

    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(submit, range(8)))
    assert len(set(ids)) == 1
    assert len(list_campaigns(database, "scientist")) == 1
