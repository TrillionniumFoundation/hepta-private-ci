# control.engineering production-closure contract

This document defines the repository-controlled closure added after the SQLite v10
convergence. It is subordinate to the canonical module registries and does not change
the module's authority ceiling. `production_implementation`, deployment, merge and
release remain false until every external receipt described below is independently
provided and verified.

## 1. Exact-blob observation and merge identity

`sourceBase` remains immutable provenance and its commit/tree object identity is always
validated. Path-only legacy maps use `path_object_provenance_v1`: a historical squash
may remove the source commit from ancestry only when every declared source/evidence path
is still object-equivalent. Exact-blob maps use `object_provenance_v1`; their current
bytes remain independently bound by per-operation Git blobs and `sourceObjects`.

A current observation may use `observationIdentityMode=path_object_equivalence_v1` in
both modes. The observed commit need not be an ancestor after a squash, but every
observed source/evidence path must exist at both commits and
`git diff -- <observed paths>` must be empty. Explicit `ancestor_only` and
`ancestor_provenance_v1` remain available where graph ancestry is part of the contract.
A missing provenance object, wrong provenance tree, changed observed path or stale HEAD
blob therefore fails closed.

Repository policy requires merge commits for changes touching the module, its exact
map, or its required workflows. Pull requests declare
`CONTROL_ENGINEERING_MERGE_METHOD=merge_commit`; post-merge main qualification rejects
a one-parent squash/rebase commit that changed an exact path. This is defense in depth:
path-equivalent observations remain verifiable, while the preferred integration method
preserves reviewed commit ancestry.

## 2. Required qualification topology

`blocking-ci.yml` invokes `control-engineering-required.yml`, so the protected
`CI required` context depends on this module rather than treating it as optional.

For pull requests the required workflow runs:

1. source-head and deterministic base-merge lanes;
2. exact gap/document/map verification;
3. the complete Python owner suite on a real Linux Bubblewrap host;
4. API snapshot, status, syntax/lint, type and coverage checks;
5. the evaluator-owned real mutation campaign;
6. bounded concurrency/crash/WAL/disk-full qualification;
7. the named repository product caller and retained per-lane receipts;
8. a non-author, non-bot `APPROVED` review bound to the current head SHA.

For a push to `main`, the same required workflow executes an exact-main source lane and
retains a post-merge product receipt plus runtime `STATUS` artifact. Product-caller
failure is therefore a release blocker through `CI required`.

## 3. Worker registration governance

Initial admission remains `register_worker`. Subsequent changes use typed authority
receipts:

- `renew_worker_registration` binds the previous profile digest and expected revision;
- capacity cannot shrink below durable active reservations;
- path scope cannot orphan an active claim;
- signing identity cannot change through renewal;
- `rotate_worker_signing_identity` requires the old profile/signing identity and no
  active or awaiting-completion claim;
- identical acknowledgement-loss replay is revision-stable.

Neither transition grants execution or merge authority.

## 4. Clock and expiry policy

Receipt wall time and local elapsed time are distinct. `ClockPolicy` bounds future
skew, observation age and receipt lifetime. Cross-principal receipts use wall time;
local timeout budgets use a monotonic clock. Production callers inject a clock policy
and must treat clock-health failure as unavailable rather than extending timestamps.

## 5. Audit checkpoint and owner-state anchor

`AuditCheckpointReceipt` binds:

- exact source commit/tree;
- audit sequence and event digest;
- the full durable owner snapshot digest;
- a deterministic per-table owner-state root;
- the predecessor checkpoint digest;
- signer identity and validity window.

Creating a checkpoint still performs a full verification. Once an externally trusted
checkpoint exists, `verify_audit_suffix` recomputes only later audit events. Per-table
anchors identify changed owner tables between checkpoints. Checkpoints are evidence,
not compaction or authority, and full offline verification remains available.

## 6. SQLite capacity and migration policy

There is no universal built-in production threshold. Each target supplies a reviewed
`SQLiteCapacityPolicy` with database/WAL/event/worker/claim/latency/recovery ceilings and
a migration-warning percentage. `evaluate_sqlite_capacity` distinguishes hard-limit
failure from an early migration threshold. An operator acceptance receipt binds both
the policy and observation digests.

The scheduled soak workflow measures concurrency, WAL checkpointing, repeated committed
crash/reopen cycles, controlled `SQLITE_FULL` rollback and database growth. A target
that crosses a hard limit is rejected; a target that crosses its migration threshold
must open an external durable-coordination migration before growth continues.

## 7. External provider adapters

Real production providers are invoked only through absolute, no-shell commands using
canonical JSON on stdin. The adapter supplies a small fixed environment plus explicitly
passed `HEPTA_PROVIDER_*` values, bounds execution time/output, suppresses raw stderr and
binds each response to provider ID, operation and request digest. Production provider
IDs containing fixture/test/mock markers are rejected.

Five independent provider roles are required:

- distributed lease/revocation frontier;
- immutable audit publication;
- external key custody and signature verification;
- CI completion observer;
- integration terminal observer.

`ProviderTrustStore` delegates typed sign/verify operations to an external HSM/KMS or
trust service command. Distinct provider IDs are mandatory; their returned typed
receipts still pass the existing signature, context, frontier and role-separation
verifiers.

## 8. Recovery and operator acceptance

`rehearse_backup_restore` uses SQLite online backup, reopens the backup through
`EngineeringStore`, verifies schema/audit/owner snapshot equality and emits a signed
receipt. `production_acceptance.py` runs only on the admitted production runner and
collects:

- signed audit checkpoint;
- backup/restore rehearsal;
- capacity decision;
- real provider bundle;
- exact target/source identity.

It emits a production-acceptance **candidate** with every authority field false.
An independent operator signs `OperatorAcceptanceReceipt`, binding deployment/canary,
rollback, independent review, capacity and provider evidence. The verification CLI
checks that receipt but still does not mutate canonical
`production_implementation`; that change requires a later reviewed repository change
whose exact-main qualification also passes.

## 9. Canonical status

`STATUS.json` is generated deterministically from `IMPLEMENTATION_MAP.json`. It is the
single tracked status projection used by prose. CI additionally emits a runtime status
bound to the exact tested commit/tree/run. Prose must not override either record.
