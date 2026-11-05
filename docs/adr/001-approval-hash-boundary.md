# ADR 001: Bind approvals to an immutable execution payload

Status: accepted for the simulation-only work-order contract.

The design requires approval metadata and a plan hash, but including that hash and the approval identifier inside the bytes being hashed creates a self-reference. An approval must also remain bound to every execution-affecting field.

`RunPlan` contains the complete immutable execution payload: campaign/batch/run identity, dataset snapshot, creator, policy version, candidate order, instrument profile, labware/deck configuration, liquid declaration, available source volume, and transfers. `plan_hash` is computed from its versioned canonical JSON representation. Approval identity, approver, decision, expiry, and the resulting plan hash belong in a separate persisted approval envelope.

Dispatch must revalidate the payload, recompute its hash, check the independent approval and expiry, and compile the same payload. Any payload change requires a new approval. Protocol bytes receive a separate content hash. Nothing in this contract permits physical dispatch.

The first supported profile is intentionally narrow: one Flex single-channel 1000 uL pipette, one 1000 uL tip rack, a reservoir, a destination plate, and water-placeholder transfers. Conservative policy limits cap each destination at 200 uL and reserve 500 uL in the source. Additional labware and operations require explicit profile versions and validation evidence.
