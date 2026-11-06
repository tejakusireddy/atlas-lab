# Production rollout requirements

These requirements remain open and block production deployment. The [G2 local-profile acceptance record](g2-acceptance.md) establishes specific local isolation, recovery, tracing, and scientific guarantees; it does not count these rollout requirements as completed.

| Requirement | Status | Required acceptance evidence |
| --- | --- | --- |
| Production identity and authorization | Open — blocks production | Verified identity-provider integration, issuer/audience/expiry validation, action-level authorization and ownership tests, independent reviewer enforcement, and rejection of local demonstration identities in the production profile. |
| Secret management | Open — blocks production | Managed secret injection, separate service credentials, rotation/revocation tests, and removal of demonstration credentials from production runtime configuration. |
| Least-privilege database roles | Open — blocks production | Distinct migration, application, measurement-release, and dispatch privileges; no superuser credentials in application services; an executed allow/deny permission matrix protecting measurement writes and immutable scientific/audit records. |
| Constrained instrument dispatch | Open — blocks production | A broker that accepts only approved immutable work orders, verifies hashes and eligibility, restricts commands/images/mounts/resources, preserves single-attempt recovery semantics, and passes adversarial and replay tests. Host Docker/operator access remains outside the application trust boundary. |

Each requirement needs a concrete implementation and executed evidence before its status changes. Local tests, demonstration identities, private oracle file permissions, and trusted host dispatch do not by themselves close these rollout items. The current instrument profile remains simulation-only.

Production collector deployment, dashboards, metrics/log aggregation, disaster recovery, and measured SLOs also remain rollout work described in the G2 acceptance record. Changes to scientific dependencies or decision logic must preserve or explicitly revise the [frozen scientific reference](../reproducibility/scientific-reference.md).
