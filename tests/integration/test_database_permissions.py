import os
import secrets
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from atlas_campaigns.analysis import analyze
from atlas_campaigns.database import Connection, connect
from atlas_campaigns.execution import claim_next, enqueue_simulation, record_receipt, transition
from atlas_campaigns.permissions import apply_runtime_grants
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests.integration.test_execution import approved_run

pytestmark = pytest.mark.integration


@pytest.fixture
def runtime_roles(database: Connection) -> Iterator[dict[str, Connection]]:
    schema = database.execute("SELECT current_schema() AS name").fetchone()
    assert schema is not None
    names = {
        profile: f"test_{profile}_{uuid4().hex}"
        for profile in ("application", "release", "dispatch")
    }
    passwords = {profile: secrets.token_urlsafe(32) for profile in names}
    try:
        for profile, name in names.items():
            database.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                    "NOREPLICATION NOBYPASSRLS PASSWORD {}"
                ).format(sql.Identifier(name), sql.Literal(passwords[profile]))
            )
        apply_runtime_grants(database, schema["name"], names)
        apply_runtime_grants(database, schema["name"], names)  # Provisioning is repeatable.
        with ExitStack() as stack:
            sessions = {
                profile: stack.enter_context(
                    connect(
                        make_conninfo(
                            os.environ["ATLAS_TEST_DATABASE_URL"],
                            user=name,
                            password=passwords[profile],
                            options=f"-csearch_path={schema['name']}",
                        )
                    )
                )
                for profile, name in names.items()
            }
            for profile, session in sessions.items():
                row = session.execute("SELECT current_user AS name").fetchone()
                assert row is not None and row["name"] == names[profile]
            yield sessions
    finally:
        for name in names.values():
            database.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)))
            database.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def test_workflow_uses_separate_logins(
    runtime_roles: dict[str, Connection], tmp_path: Path
) -> None:
    application = runtime_roles["application"]
    release = runtime_roles["release"]
    dispatch = runtime_roles["dispatch"]
    run_id = approved_run(application)
    enqueue_simulation(application, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    claimed = claim_next(dispatch, tmp_path)
    assert claimed is not None
    record_receipt(
        dispatch,
        claimed,
        {
            "run_id": str(run_id),
            "protocol_hash": claimed["protocol_hash"],
            "simulator_version": "10.1.0",
            "status": "SIMULATED",
        },
    )
    simulated = transition(dispatch, claimed, "SIMULATED", "trace")
    release.execute("SELECT * FROM campaigns FOR UPDATE").fetchall()
    pending = transition(release, simulated, "MEASUREMENT_PENDING", "trace")
    selections = release.execute("SELECT * FROM campaign_selections").fetchall()
    for selection in selections:
        release.execute(
            """INSERT INTO measurements (id,run_id,campaign_id,candidate_id,snapshot_id,
            manifest_hash,oracle_hash,source_citation,source_kind,measurement_mode,units,qc_state)
            VALUES (%s,%s,%s,%s,%s,'fixture','fixture','fixture','missing',
            'historical_replay','percent','UNOBSERVED')""",
            (
                uuid4(),
                run_id,
                selection["campaign_id"],
                selection["candidate_id"],
                selection["snapshot_id"],
            ),
        )
    complete = transition(release, pending, "QC_COMPLETE", "trace")
    result = analyze(
        application,
        UUID(str(run_id)),
        complete["version"],
        "scientist",
        "analyze",
        uuid4(),
        "trace",
    )
    assert result["snapshot_hash"].startswith("sha256:")


def test_runtime_permission_matrix(runtime_roles: dict[str, Connection]) -> None:
    denied_for_all = (
        "CREATE TABLE forbidden (id integer)",
        "CREATE ROLE forbidden_role",
        "TRUNCATE measurements",
        "ALTER TABLE measurements DISABLE TRIGGER ALL",
        "DELETE FROM audit_events",
        "UPDATE campaign_analyses SET snapshot='{}'",
        "UPDATE approvals SET actor_id='attacker'",
        "UPDATE dataset_candidates SET input_record='{}'",
        "UPDATE experiment_runs SET approval_id=gen_random_uuid()",
    )
    for profile, session in runtime_roles.items():
        statements = list(denied_for_all)
        if profile != "dispatch":
            statements += [
                "INSERT INTO execution_receipts DEFAULT VALUES",
                "INSERT INTO reconciliation_results DEFAULT VALUES",
            ]
        if profile != "release":
            statements += ["INSERT INTO measurements DEFAULT VALUES"]
        if profile != "application":
            statements += [
                "INSERT INTO approvals DEFAULT VALUES",
                "INSERT INTO campaigns DEFAULT VALUES",
                "INSERT INTO model_artifacts DEFAULT VALUES",
                "SELECT * FROM model_artifacts",
            ]
        for statement in statements:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                session.execute(statement)
        row = session.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()
        assert row is not None and not row["rolsuper"]


def test_privileged_role_configuration_is_rejected(database: Connection) -> None:
    schema = database.execute("SELECT current_schema() AS name,current_user AS owner").fetchone()
    assert schema is not None
    with pytest.raises(ValueError, match="distinct"):
        apply_runtime_grants(
            database,
            schema["name"],
            dict.fromkeys(("application", "release", "dispatch"), str(schema["owner"])),
        )
    with pytest.raises(ValueError, match="unprivileged"):
        apply_runtime_grants(
            database,
            schema["name"],
            {
                "application": str(schema["owner"]),
                "release": "absent_release",
                "dispatch": "absent_dispatch",
            },
        )


def test_password_rotation_and_login_revocation(
    database: Connection,
    runtime_roles: dict[str, Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from psycopg.conninfo import conninfo_to_dict

    session = runtime_roles["application"]
    principal = session.execute("SELECT current_user AS name").fetchone()
    assert principal is not None
    role = sql.Identifier(principal["name"])
    first, second = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    database.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(role, sql.Literal(first)))
    parameters = conninfo_to_dict(os.environ["ATLAS_TEST_DATABASE_URL"])
    parameters.pop("password", None)
    parameters["user"] = principal["name"]
    password_file = tmp_path / "database-password"
    password_file.write_text(first)
    monkeypatch.setenv("ATLAS_RUNTIME_PROFILE", "production")
    monkeypatch.setenv("ATLAS_DATABASE_URL", make_conninfo("", **parameters))
    monkeypatch.setenv("ATLAS_DATABASE_PASSWORD_FILE", str(password_file))
    with connect() as initial:
        assert initial.execute("SELECT 1").fetchone() is not None
    database.execute(sql.SQL("ALTER ROLE {} PASSWORD {}").format(role, sql.Literal(second)))
    with pytest.raises(psycopg.OperationalError, match="password authentication failed"):
        connect()
    replacement = tmp_path / "replacement"
    replacement.write_text(second)
    replacement.replace(password_file)
    with connect() as rotated:
        assert rotated.execute("SELECT 1").fetchone() is not None
    database.execute(sql.SQL("ALTER ROLE {} NOLOGIN").format(role))
    with pytest.raises(psycopg.OperationalError, match="not permitted to log in"):
        connect()
    # PostgreSQL does not terminate existing sessions on password change or NOLOGIN.
    assert session.execute("SELECT 1").fetchone() is not None
