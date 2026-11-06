# Production rollout requirements

These requirements remain open and block production deployment. The [G2 local-profile acceptance record](g2-acceptance.md) establishes specific local isolation, recovery, tracing, and scientific guarantees; it does not count these rollout requirements as completed.

| Requirement | Status | Required acceptance evidence |
| --- | --- | --- |
| Production identity and authorization | Open — blocks production | Verified AWS Cognito integration, issuer/audience/expiry validation, action-level authorization and ownership tests, independent reviewer enforcement, and rejection of local demonstration identities in the production profile. |
| Secret management | Open — blocks production | AWS Secrets Manager injection, separate service credentials, rotation/revocation tests, and removal of demonstration credentials from production runtime configuration. The reloadable mounted-file interface is implemented; AWS deployment and database-backed rotation evidence remain pending. |
| Least-privilege database roles | Open — blocks production | Distinct migration, application, measurement-release, and dispatch privileges; no superuser credentials in application services; an executed allow/deny permission matrix protecting measurement writes and immutable scientific/audit records. |
| Constrained instrument dispatch | Open — blocks production | A broker that accepts only approved immutable work orders, verifies hashes and eligibility, restricts commands/images/mounts/resources, preserves single-attempt recovery semantics, and passes adversarial and replay tests. Host Docker/operator access remains outside the application trust boundary. |

Each requirement needs a concrete implementation and executed evidence before its status changes. Local tests, demonstration identities, private oracle file permissions, and trusted host dispatch do not by themselves close these rollout items. The current instrument profile remains simulation-only.

Production collector deployment, dashboards, metrics/log aggregation, disaster recovery, and measured SLOs also remain rollout work described in the G2 acceptance record. Changes to scientific dependencies or decision logic must preserve or explicitly revise the [frozen scientific reference](../reproducibility/scientific-reference.md).

## Database credential interface

Set `ATLAS_RUNTIME_PROFILE=production`, `ATLAS_DATABASE_URL=postgresql://SERVICE@HOST/DATABASE` and `ATLAS_DATABASE_PASSWORD_FILE=/run/secrets/database-password`. Production mode requires all three, an explicit host/user/database, and a password-free connection URL. Missing or unreadable files, conflicting credential sources, malformed secrets and unknown runtime profiles fail closed. Local mode retains the existing development default.

The password is read on every new connection, supporting atomic replacement by the deployment secret provider. Existing connections retain their current PostgreSQL session until closed; rotation must also revoke the old database password and drain existing sessions as required. Unit tests verify file replacement and rejection after removal. This interface does not provision Secrets Manager, rotate PostgreSQL passwords or claim that production authentication is ready.

The selected AWS integration is Cognito for OIDC identity and Secrets Manager for credentials. Mount only the credential for the service's database role, through deployment-managed secret delivery. Do not supply the migration/admin password to application containers or reuse the demonstration Compose database for production. Account, region, network and deployment-specific configuration remain required before an AWS rollout.
