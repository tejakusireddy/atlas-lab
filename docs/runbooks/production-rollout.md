# Production rollout requirements

These requirements remain open and block production deployment. The [G2 local-profile acceptance record](g2-acceptance.md) establishes specific local isolation, recovery, tracing, and scientific guarantees; it does not count these rollout requirements as completed.

| Requirement | Status | Required acceptance evidence |
| --- | --- | --- |
| Production identity and authorization | Open — blocks production | Verified AWS Cognito integration, issuer/audience/expiry validation, action-level authorization and ownership tests, independent reviewer enforcement, and rejection of local demonstration identities in the production profile. |
| Secret management | Open — blocks production | AWS Secrets Manager injection, separate service credentials, rotation/revocation tests, and removal of demonstration credentials from production runtime configuration. The reloadable mounted-file interface is implemented; AWS deployment and database-backed rotation evidence remain pending. |
| Least-privilege database roles | Open — blocks production | Explicit application/release/dispatch grants and an executed PostgreSQL login permission matrix are implemented. Deployment with distinct migration ownership and service credentials, database-wide PUBLIC privilege review and AWS secret-delivery evidence remain required. PostgreSQL password rotation and login revocation are exercised locally. |
| Constrained instrument dispatch | Open — blocks production | A broker that accepts only approved immutable work orders, verifies hashes and eligibility, restricts commands/images/mounts/resources, preserves single-attempt recovery semantics, and passes adversarial and replay tests. Host Docker/operator access remains outside the application trust boundary. |

Each requirement needs a concrete implementation and executed evidence before its status changes. Local tests, demonstration identities, private oracle file permissions, and trusted host dispatch do not by themselves close these rollout items. The current instrument profile remains simulation-only.

Production collector deployment, dashboards, metrics/log aggregation, disaster recovery, and measured SLOs also remain rollout work described in the G2 acceptance record. Changes to scientific dependencies or decision logic must preserve or explicitly revise the [frozen scientific reference](../reproducibility/scientific-reference.md).

## Database credential interface

Set `ATLAS_RUNTIME_PROFILE=production`, `ATLAS_DATABASE_URL=postgresql://SERVICE@HOST/DATABASE` and `ATLAS_DATABASE_PASSWORD_FILE=/run/secrets/database-password`. Production mode requires all three, an explicit host/user/database, and a password-free connection URL. Missing or unreadable files, conflicting credential sources, malformed secrets and unknown runtime profiles fail closed. Local mode retains the existing development default.

The password is read on every new connection, supporting atomic replacement by the deployment secret provider. Existing connections retain their current PostgreSQL session until closed; rotation must also revoke the old database password and drain existing sessions as required. Unit tests verify file replacement and rejection after removal. PostgreSQL integration tests additionally verify that the old password fails after rotation, the replacement credential succeeds, and NOLOGIN prevents new connections while existing sessions remain active. This interface does not provision Secrets Manager, rotate PostgreSQL passwords or claim that production authentication is ready.

The selected AWS integration is Cognito for OIDC identity and Secrets Manager for credentials. Mount only the credential for the service's database role, through deployment-managed secret delivery. Do not supply the migration/admin password to application containers or reuse the demonstration Compose database for production. Account, region, network and deployment-specific configuration remain required before an AWS rollout.

## Runtime database grants

Run migrations as the dedicated schema owner. An operator must first create three distinct unprivileged PostgreSQL LOGIN roles with separately delivered credentials, no role memberships and no owned objects. Never give runtime services the migration role or its password. On a dedicated deployment database, provision grants with:

```sh
uv run --locked python -m atlas_campaigns.permissions --schema atlas --migrate \
  --application-role atlas_application --release-role atlas_release \
  --dispatch-role atlas_dispatch
```

The schema must already exist and be owned by the current migration role. The command applies migrations and grants in one transaction, revokes existing PUBLIC/runtime grants in that schema (including column grants), and grants only explicit table and column permissions. Re-run after every migration; new tables receive no runtime grants automatically. Set each runtime connection's `search_path` to the dedicated application schema through its connection configuration. Do not apply this to the existing demonstration database's public schema.

| Capability | Application | Measurement release | Dispatch |
| --- | --- | --- | --- |
| Create campaigns, approvals and selections | Yes | No | No |
| Insert measurements | No | Yes | No |
| Insert model artifacts and analysis snapshots | Yes | No | No |
| Claim dispatch intents and set attempt/lease/artifact path | No | No | Yes |
| Insert execution receipts | Yes, existing reviewer reconciliation | No | Yes |
| Update/delete immutable measurements, approvals, snapshots or audit records | No | No | No |
| DDL, role creation, truncate or disable triggers | No | No | No |

`tests/integration/test_database_permissions.py` authenticates as real, temporary password-protected logins and executes both the allowed workflow and denied statements. These grants restrict database capabilities; campaign ownership and independent review remain enforced by the application. The current reconciliation endpoint requires application receipt insertion; narrowing receipt writes to a broker requires moving that endpoint's privileged operation behind the dispatch boundary.

PostgreSQL grants are additive. Deployment must separately remove unsafe database-wide PUBLIC privileges, review extension/security-definer functions, restrict network access, and verify that runtime roles cannot access other schemas or assume operator roles. The grant tool rejects elevated roles, memberships and ownership; it does not reconfigure an existing shared cluster. The demonstration Compose credentials remain local-only. A production role rollout is still open until services actually use these separate credentials and the deployment permission matrix passes.
