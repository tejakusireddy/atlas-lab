"""Apply explicit runtime grants after migrations using an operator connection.

Roles and their credentials are provisioned separately. Runtime principals never own
schema objects and cannot run this provisioning step successfully.
"""

import argparse
from collections.abc import Mapping

from psycopg import sql

from atlas_campaigns.database import Connection, connect, migrate

READ_TABLES = (
    "dataset_snapshots",
    "dataset_groups",
    "dataset_candidates",
    "campaigns",
    "experiment_batches",
    "approvals",
    "campaign_selections",
    "experiment_runs",
    "run_events",
    "outbox_events",
    "execution_receipts",
    "campaign_trace_contexts",
)
INSERTS = {
    "application": (
        "campaigns",
        "experiment_batches",
        "approvals",
        "campaign_selections",
        "experiment_runs",
        "run_events",
        "outbox_events",
        "audit_events",
        "mutation_keys",
        "campaign_trace_contexts",
        "campaign_analyses",
        "model_artifacts",
        "execution_receipts",
    ),
    "release": ("measurements", "run_events", "outbox_events", "audit_events"),
    "dispatch": ("run_events", "outbox_events", "execution_receipts"),
}
UPDATES = {
    "application": {
        "campaigns": ("status", "version", "budget_used"),
        "experiment_batches": ("status", "version"),
        "experiment_runs": ("status", "version", "protocol_hash", "trace_id"),
    },
    "release": {
        "campaigns": ("version",),  # SELECT FOR UPDATE locks the scientific context.
        "experiment_batches": ("status", "version"),
        "experiment_runs": ("status", "version"),
    },
    "dispatch": {
        "experiment_batches": ("status", "version"),
        "experiment_runs": ("status", "version", "attempt_id", "lease_until", "artifact_directory"),
        "outbox_events": ("published_at",),
    },
}


def apply_runtime_grants(connection: Connection, schema: str, roles: Mapping[str, str]) -> None:
    """Grant only the current workflow's permissions, refusing privileged principals."""
    if set(roles) != set(INSERTS) or len(set(roles.values())) != 3:
        raise ValueError("Three distinct application, release and dispatch roles are required")
    namespace = sql.Identifier(schema)
    with connection.transaction():
        owner = connection.execute(
            """SELECT nspowner, nspowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)
            AS owned FROM pg_namespace WHERE nspname=%s""",
            (schema,),
        ).fetchone()
        if owner is None:
            raise ValueError("Migrate the dedicated application schema first")
        if not owner["owned"]:
            raise ValueError("Apply grants as the migration role that owns the application schema")
        for role in roles.values():
            principal = connection.execute(
                """SELECT oid,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,
                rolcanlogin FROM pg_roles WHERE rolname=%s""",
                (role,),
            ).fetchone()
            if (
                not principal
                or not principal["rolcanlogin"]
                or any(
                    principal[key]
                    for key in (
                        "rolsuper",
                        "rolcreatedb",
                        "rolcreaterole",
                        "rolreplication",
                        "rolbypassrls",
                    )
                )
            ):
                raise ValueError("Runtime roles must be unprivileged login roles")
            oid = principal["oid"]
            inherited = connection.execute(
                "SELECT 1 FROM pg_auth_members WHERE member=%s OR roleid=%s LIMIT 1", (oid, oid)
            ).fetchone()
            owned = connection.execute(
                """SELECT 1 FROM pg_class WHERE relowner=%s
                UNION ALL SELECT 1 FROM pg_namespace WHERE nspowner=%s
                UNION ALL SELECT 1 FROM pg_database WHERE datdba=%s
                UNION ALL SELECT 1 FROM pg_proc WHERE proowner=%s LIMIT 1""",
                (oid,) * 4,
            ).fetchone()
            if inherited or owned:
                raise ValueError("Runtime roles cannot have memberships or own database objects")
        targets = sql.SQL(", ").join(
            [sql.SQL("PUBLIC"), *(sql.Identifier(r) for r in roles.values())]
        )
        connection.execute(sql.SQL("REVOKE ALL ON SCHEMA {} FROM {}").format(namespace, targets))
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            connection.execute(
                sql.SQL("REVOKE ALL ON ALL {} IN SCHEMA {} FROM {}").format(
                    sql.SQL(kind), namespace, targets
                )
            )
        # Table-level revocation does not remove previous column grants.
        columns = connection.execute(
            """SELECT c.relname,array_agg(a.attname ORDER BY a.attnum) AS names
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
            WHERE n.nspname=%s AND c.relkind IN ('r','v','p') GROUP BY c.relname""",
            (schema,),
        ).fetchall()
        for row in columns:
            connection.execute(
                sql.SQL("REVOKE ALL ({}) ON {}.{} FROM {}").format(
                    sql.SQL(", ").join(map(sql.Identifier, row["names"])),
                    namespace,
                    sql.Identifier(row["relname"]),
                    targets,
                )
            )
        # Apply as the schema owner; future migration objects must be explicitly granted.
        for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
            connection.execute(
                sql.SQL(
                    "ALTER DEFAULT PRIVILEGES IN SCHEMA {} REVOKE ALL ON {} FROM PUBLIC"
                ).format(namespace, sql.SQL(kind))
            )
        for profile, role in roles.items():
            grantee = sql.Identifier(role)
            connection.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(namespace, grantee))
            readable = list(READ_TABLES)
            if profile == "application":
                readable += [
                    "measurements",
                    "training_observations",
                    "campaign_analyses",
                    "model_artifacts",
                    "mutation_keys",
                    "audit_events",
                    "schema_migrations",
                ]
            elif profile == "release":
                readable += ["measurements"]
            for table in readable:
                connection.execute(
                    sql.SQL("GRANT SELECT ON {}.{} TO {}").format(
                        namespace, sql.Identifier(table), grantee
                    )
                )
            for table in INSERTS[profile]:
                connection.execute(
                    sql.SQL("GRANT INSERT ON {}.{} TO {}").format(
                        namespace, sql.Identifier(table), grantee
                    )
                )
            for table, names in UPDATES[profile].items():
                connection.execute(
                    sql.SQL("GRANT UPDATE ({}) ON {}.{} TO {}").format(
                        sql.SQL(", ").join(map(sql.Identifier, names)),
                        namespace,
                        sql.Identifier(table),
                        grantee,
                    )
                )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", required=True)
    parser.add_argument(
        "--migrate", action="store_true", help="Migrate and grant in one transaction"
    )
    for profile in INSERTS:
        parser.add_argument(f"--{profile}-role", required=True)
    args = parser.parse_args()
    roles = {profile: getattr(args, f"{profile}_role") for profile in INSERTS}
    with connect() as connection, connection.transaction():
        connection.execute(
            sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(args.schema))
        )
        if args.migrate:
            migrate(connection)
        apply_runtime_grants(connection, args.schema, roles)
    print("Runtime database grants applied.")


if __name__ == "__main__":
    main()
