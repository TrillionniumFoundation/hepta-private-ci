# learning.artifacts compatibility and versioning policy

## Stable facade

Production consumers import `codex_hepta_learning_artifacts::stable`. The crate root remains available to repository-owned implementations and qualification code, but it is not a blanket stability promise. Low-level encoders, storage repair helpers and internal owner state are deliberately excluded from the stable facade.

## Compatibility classes

### Durable wire and state formats

Registry snapshots, payload receipts, head witnesses, transaction checkpoints, withdrawal/lifecycle snapshots and audit/qualification receipts are versioned durable protocols. Readers reject unknown magic/schema versions and noncanonical encodings. A format change requires a new version, retained old reader fixtures and an explicit migration or coexistence plan.

### Host protocol

Authenticated command envelopes and action names are independently versioned. Unknown fields are rejected unless a future schema explicitly declares forward-compatible extension fields. Authorization is per action; adding an action is not a compatible broadening of an existing credential.

### Stable Rust facade

Before 1.0, incompatible changes to the stable facade require a minor version bump, migration note and repository-wide caller update in the same change. After 1.0, semantic versioning applies: additive backward-compatible API in minor releases and breaking changes only in major releases.

### Internal API

Items outside `stable` may change with repository-owned callers, but durable records and claim boundaries remain protected. Internal refactoring cannot reinterpret an existing receipt or silently grant new authority.

## Migration rules

Every migration declares:

- source and target schema versions;
- exact source fixture digests;
- deterministic transformation and target digest;
- rollback/coexistence window;
- capacity and recovery bounds;
- treatment of revoked, tombstoned and nonterminal records;
- target-host crash points;
- independent acceptance evidence.

Migrations write new create-only state and then advance an authenticated pointer/head. They never edit an acknowledged immutable object in place. A crash leaves either the old admitted state or a recoverable new candidate; it never promotes an unverified partial migration.

## 1.0 entry criteria

The crate may advance from `0.1.0` toward 1.0 only after:

- the stable facade and durable formats have named owners;
- exact-source and ordered-parent receipts are routinely green;
- production transport/action authorization and target-host durability are qualified;
- migration and restore fixtures cover every supported durable version;
- capacity limits and benchmark profiles are published;
- all production callers use the stable facade;
- deprecation and support windows are documented;
- independent operator acceptance is recorded.

Version advancement does not itself grant activation, promotion or release authority.
