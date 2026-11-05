import os
from collections.abc import Iterator
from uuid import uuid4

import pytest
from atlas_campaigns.database import Connection, connect, migrate
from psycopg import sql


@pytest.fixture
def database() -> Iterator[Connection]:
    dsn = os.environ.get("ATLAS_TEST_DATABASE_URL")
    if not dsn:
        pytest.fail("Set ATLAS_TEST_DATABASE_URL to a disposable local PostgreSQL database")
    schema = "test_" + uuid4().hex
    with connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        try:
            migrate(connection)
            connection.execute(
                "INSERT INTO dataset_snapshots(id,manifest_hash) VALUES (%s,%s)",
                ("synthetic-snapshot", "sha256:" + "0" * 64),
            )
            connection.execute(
                "INSERT INTO dataset_groups VALUES (%s,%s,48)",
                ("synthetic-snapshot", "synthetic-group"),
            )
            yield connection
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
