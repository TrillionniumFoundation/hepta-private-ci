# `kernel.evidence` current implementation

## Current executable contract

`codex-rs/hepta-evidence` is the SQLite-backed authoritative evidence store for
qualification receipts, historical lineage, durable AuthBus replay state,
provider-effect records, immutable recovery-frontier acceptance, stable cursor
queries and integrity-checked reopen. Canonical JSON and typed digest domains
make equal content idempotent and make reused identity with different semantics
a conflict.

The checked-in migration lineage now includes `0013_recovery_frontier_acceptance.sql`.
Migration `0011_qualification_evidence.sql` owns exact-candidate evidence,
append-only denial triggers and the replay-linked qualification lineage;
`0013` adds immutable local acceptance of externally published recovery
frontiers. Production store opening verifies the migration set before any
runtime writer is admitted.

The native qualification facade is `HeptaEvidenceStore::qualification()`. It
exposes:

- `QualificationEvidenceStore::append_receipt`;
- `QualificationEvidenceStore::query_claim`;
- `QualificationEvidenceStore::query_claim_page` with a stable sequence cursor;
- `QualificationEvidenceStore::verify_chain`.

Append authenticates the issuer with the AuthBus Ed25519 contract, binds
candidate/tree/role to the signed subject and advances durable replay state in
the same SQLite transaction as the evidence insert. Verification preserves
claim classes, evidence expiry, correction/revocation lineage and requires both
distinct authenticated principals and distinct signing identities for required
independent roles. Positive verification reloads the current issuer/key/role
registry; removed, revoked or key-rotated issuers cannot continue satisfying a
claim. Corrections and ordinary revocations are owner-principal/role scoped;
only a currently trusted `security` issuer may cross that boundary for an
emergency revocation.

## Recovery-frontier v2 and external monotonic backend

`EvidenceRecoveryFrontierV2` binds all production recovery facts into one
signed domain:

- immutable store identity and monotonically advancing generation;
- migration-set digest, qualification high-water/frontier and AuthBus replay
  frontier through the ledger root;
- issuer-trust and frontier-signer-registry digests;
- external backend identity digest;
- exact build artifact digest;
- exact-source and deterministic-merge qualification receipt-set digest;
- durable backup-publication digest;
- source commit/tree and signer-policy generation.

`EvidenceFrontierBackend` is the explicit external authority contract:

- `get_latest(store_id)`;
- `compare_and_swap(store_id, expected_generation, new_frontier)`;
- `get_history(store_id, range)`;
- `verify_backend_identity()`.

The repository implementation, `LockedFileEvidenceFrontierBackend`, requires a
separately mounted rollback domain, digest-pins its owner-controlled backend
identity, serializes publishers with an OS file lock, enforces generation CAS,
keeps a bounded append-only hash-chained audit journal and returns a durable
acknowledgement only after file and directory synchronization. It rejects torn
or empty records, stale/skipped generations, directory or identity replacement,
symlinks, hard links, permissive ownership/modes and an append that would exceed
the record or 64 MiB journal bound. Once a write may have become durable but an
acknowledgement is uncertain, the handle is poisoned and fails closed.

The file backend is a concrete production adapter only on storage with coherent
cross-host file locks and durable filesystem semantics. A deployment may
provide another implementation of the same contract, but it must preserve
monotonic generation, authenticated identity, CAS, append-only audit history,
key rotation and durable acknowledgement outside the local rollback domain.

## Agentd development and production modes

Agentd is the named product host. Development mode remains explicitly
configuration gated for local qualification. Production mode is non-degradable:
startup fails with `kernel.evidence recovery_required` unless all of the
following are present and mutually consistent:

- a private current issuer-trust registry;
- a threshold frontier-signer registry with distinct principals, key epochs and
  revocation enforcement;
- a canonical external backend root on a different device from Agent home;
- the latest signed frontier and its pinned backend identity;
- a durable backup-publication receipt;
- the current executable digest;
- an exact-source receipt and a deterministic two-parent merge receipt from the
  same governed pull-request workflow run;
- the exact closed-world five-check inventory, per-command exit state, retained
  log digests and artifact identity;
- the current local SQLite snapshot and ledger root.

External control files are canonical direct children of the private backend
root, opened without following symlinks and checked for stable file and parent
directory identity throughout the read. A successful startup records the
accepted frontier immutably; rollback below a previously accepted generation is
rejected.

## Database and runtime hardening

The evidence runtime uses repository SQLite durability settings, validates
quick-check, migration ledger, schema manifest, canonical evidence rows,
provider projections/effect rows, recovery acceptance and foreign keys on open.
A read-only production preflight neither creates nor migrates. Runtime
connections install a SQLite authorizer that denies schema mutation, attach,
detach, writable pragmas and direct mutation of protected append-only evidence
tables outside the typed store operations. Migration and runtime authority are
therefore separated instead of sharing an unrestricted connection profile.

Database-level `UPDATE` and `DELETE` denial triggers remain the second line of
defense for qualification evidence. Fault coverage includes transactional
insert failure, simulated disk-full behavior, reopen corruption and actual
process-crash recovery. The external backend additionally has an eight-process
CAS contention executable that requires exactly one generation winner.

## Public symbols and source bindings

- qualification records, authentication, chain verification and cursor query:
  `codex-rs/hepta-evidence/src/qualification.rs` and
  `qualification_paging.rs`;
- recovery-frontier signing domain and ledger root: `frontier_v2.rs`;
- external backend contract and locked-file adapter: `frontier_backend.rs` and
  `frontier_backend_file.rs`;
- immutable local acceptance: `frontier_acceptance.rs` plus migration `0013`;
- store open, schema verification and injected storage faults: `store.rs` and
  `store/runtime.rs`;
- SQLite production authorizer: `codex-rs/state/src/sqlite_evidence_runtime.rs`;
- Agentd production admission: `codex-rs/hepta-agentd/src/evidence_production.rs`;
- signer threshold, rotation and revocation: `evidence_frontier_signers.rs`;
- issuer trust boundary: `evidence_trust.rs`;
- mode selection and fail-closed startup composition: `evidence_host.rs`,
  `lib.rs` and `main.rs`.

The pre-existing governance `HeptaEvidenceStore::append_receipt` remains for
backward compatibility. The qualification operation is the typed
`QualificationEvidenceStore::append_receipt`; the receivers are different and
callers cannot silently cross the boundary.

## Qualification and canonical status

`.github/workflows/hepta-kernel-evidence-qualification.yml` executes the exact
PR head and deterministic synthetic merge as separately visible jobs. Every
command writes its own JSON record and raw log. Later checks continue after an
earlier failure, and diagnostics/status artifacts upload under `if: always()`.
`Kernel evidence required` is the stable fan-in check consumed by
`blocking-ci.yml` and therefore by the repository `CI required` fan-in.

`qualification/kernel-evidence/STATUS_SOURCE.json` is the single checked-in
machine-readable source for repository capabilities and persistent external
gates. `scripts/kernel_evidence_status.py` validates its exact Git anchor and
source inventory, then generates the status blocks in the technical guide,
this implementation document, traceability matrix, execution dossier and
release dashboard. Workflow receipts may overlay current execution facts, but
cannot self-issue independent acceptance, deployment, canary, promotion or
release.

## Remaining external gates and non-claims

Repository implementation is not evidence that the backend has been deployed
on independent storage. The following remain false until separate authorities
produce exact-candidate receipts:

- exact-source plus deterministic-merge qualification for the final candidate;
- independent external acceptance;
- a deployed external frontier service and signer ceremony;
- a witnessed backup/restore and rollback-rejection drill;
- canary acceptance, promotion and release.

The locked-file backend does not claim semantics on a network filesystem whose
locks or `fsync` durability are weaker than its contract. The contention test is
a bounded qualification benchmark, not a production throughput claim. An
external operator must set the repository required-check rule; the workflow and
stable check name cannot grant repository-administration authority themselves.

## Verification

Focused coverage includes:

- qualification, replay, correction/revocation, trust rotation, reopen
  corruption, query bounds and concurrent writers;
- frontier-v2 signing-domain and deterministic mutation corpus tests;
- backend stale/skipped generation, torn/empty tail, identity/directory
  replacement, append-bound and concurrent publisher tests;
- threshold distinct-principal signing, overlap rotation and revoked signer
  rejection;
- production receipt closed-world inventory, workflow/artifact binding,
  source/merge parent order, build/trust/backup/frontier mismatch and local
  snapshot rejection;
- disk-full injection, process crash and eight-process CAS contention;
- canonical-status source/projection drift tests.

The authoritative commands are retained in the qualification workflow. A local
command or source reference is not a pass receipt; only the exact candidate's
retained workflow artifact establishes execution, and only an independent
principal can establish acceptance.

See [RECOVERY_FRONTIER_V1.md](RECOVERY_FRONTIER_V1.md) for the predecessor
format and migration threat model, and
[`qualification/kernel-evidence/TRACEABILITY.md`](../../../qualification/kernel-evidence/TRACEABILITY.md)
for requirement-to-source/test mapping.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `88a46b13d5479370812ca2b680e77972fb770767`
- Source anchor tree: `94776711df64f9630c3dfd40b3a44f320d7d85ea`
- Canonical status SHA-256: `c55c659e400adc86c1e658b332f87c041ef8e1db7d218c6dae1b60c653fb8e1e`
- Workflow run ID: `none`
- Retained artifact digest: `none`

### Repository implementation capabilities

| Capability | Implemented |
| --- | --- |
| Recovery-frontier v2 signing domain | `true` |
| External monotonic CAS backend adapter | `true` |
| Fail-closed Agentd production mode | `true` |
| Immutable local frontier acceptance history | `true` |
| Distinct-principal threshold and key-epoch rotation | `true` |
| Read-only production migration preflight | `true` |
| Stable append-sequence cursor pagination | `true` |
| Database update/delete denial triggers | `true` |
| SQLite authorizer callback | `true` |
| Disk-full fault injection | `true` |
| Multi-process contention benchmark | `true` |

### Qualification, deployment and governance gates

| Gate | State | Persistent authority receipt |
| --- | --- | --- |
| Exact-source qualification | `false` | none |
| Deterministic-merge qualification | `false` | none |
| Independent acceptance | `false` | none |
| External frontier active | `false` | none |
| Backup/restore drill | `false` | none |
| Canary accepted | `false` | none |
| Release approved | `false` | none |

> Repository implementation is not deployment evidence. A CI workflow receipt
> is not independent acceptance or release authority.
<!-- END GENERATED KERNEL EVIDENCE STATUS -->
