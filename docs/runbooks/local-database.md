# Local campaign database

```sh
make db-up
make migrate
make integration
```

The Compose service uses an immutable PostgreSQL 17 image digest, a dedicated `atlas-lab` project/volume, and loopback port 55432. Credentials are local demonstration defaults. Do not expose this service publicly or reuse these credentials outside local development. `ATLAS_DATABASE_URL` overrides the application DSN; `ATLAS_TEST_DATABASE_URL` overrides the test DSN.

Migrations run inside one transaction under a PostgreSQL advisory lock. Applied SQL checksums are retained and checked on every invocation. Change an existing migration only before it has been applied; otherwise add a new numbered migration. This runner supports forward migrations only. Backups and operational rollback procedures are not yet implemented.

The campaign service requires a registered dataset/group, checks candidate count against budget, and creates the draft campaign together with its scoped idempotency reservation, audit event, and outbox event. Reusing a key with a different body conflicts. Same-key concurrent requests serialize in PostgreSQL. Read operations scope records to their owner.

Integration tests create isolated schemas named `test_<uuid>` and drop only those schemas during cleanup. They exercise transaction rollback, concurrent deduplication, owner isolation, immutable audit entries, and migration checksum drift. Do not point the tests at a production database.

Database credentials currently have local administrative privileges. Audit triggers protect ordinary update/delete statements, not a privileged administrator able to change the schema. Least-privilege deployment roles, outbox delivery, and the execution/reconciliation workflow remain separate implementation steps. The outbox currently records events but has no running dispatcher.
