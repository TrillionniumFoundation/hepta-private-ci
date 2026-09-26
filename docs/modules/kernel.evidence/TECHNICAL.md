# kernel.evidence technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `kernel.evidence`

**Owner:** `qualification-plane`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.9-EXTERNAL-GATES`

This document is the stable technical guide for `kernel.evidence`. Canonical
identity, ownership, contract, data-authority and delivery facts remain in the
repository registries. The checked-in status source records repository
capabilities and separately records qualification, deployment and governance
gates. Documentation, source implementation, exact-candidate execution,
independent acceptance, deployment, canary, promotion and release are distinct
states and must not be inferred from one another.

## 1. Identity, mission and ownership

`kernel.evidence` preserves exact-candidate qualification evidence and durable
integrity without becoming a selector, deployer or release authority. The
`qualification-plane` owns the evidence semantics and source implementation;
`security-authority` independently reviews trust, signatures, persistence,
recovery, concurrency, resource bounds and fail-closed activation.

The module is a stateful qualification-plane authoritative store. It may own
qualification evidence, immutable decision receipts and recovery acceptance
history. It may not absorb another module's facts, manufacture an external
reviewer, or convert a successful CI command into production authority.

## 2. Source binding and implementation status

The declared exclusive implementation root is `codex-rs/hepta-evidence`.
Product composition is in `codex-rs/hepta-agentd`; SQLite runtime authority
separation is in `codex-rs/state`; qualification and canonical-status control
is in `.github/workflows`, `qualification/kernel-evidence` and `scripts`.

Current repository implementation includes:

- authenticated append, query, cursor paging and chain verification;
- append-only qualification lineage and durable AuthBus replay state;
- recovery-frontier v2 and deterministic ledger-root construction;
- an explicit `EvidenceFrontierBackend` contract;
- a locked-file monotonic CAS backend for a separately mounted rollback domain;
- immutable local frontier acceptance;
- threshold signer rotation and revocation enforcement;
- explicit Agentd development and fail-closed production modes;
- read-only migration preflight and a restricted runtime SQLite authorizer;
- disk-full, process-crash and multi-process contention qualification fixtures;
- split exact-source and deterministic-merge workflow lanes with retained
  diagnostics;
- one canonical machine-readable status source with generated projections.

These are repository capability claims. They do not prove that the final
candidate passed, that an external backend is deployed, or that independent
acceptance, canary, promotion or release occurred.

## 3. Boundary, responsibilities and non-goals

Authoritative write domains are `qualification_evidence` and
`independent_decision_receipt_v1`. The module accepts only typed, bounded,
versioned and authenticated inputs. Missing authority, stale identity, replay,
scope drift, digest mismatch, invalid lineage and unknown critical fields are
hard failures.

Explicitly denied capabilities are:

- runtime provider effect execution;
- selection or merge authority;
- promotion or release authority;
- self-issued independent review;
- silent downgrade from production to development mode;
- treating local SQLite integrity as an external anti-rollback oracle.

Cross-owner mutation must retain authenticated provenance, durable intent,
destination idempotency, acknowledgement and fenced reconciliation. Queue
acceptance or handler completion is never reported as an external terminal
success.

## 4. Internal architecture and component decomposition

The implementation is divided into the following bounded components:

1. **Qualification ledger.** `QualificationEvidenceStore` authenticates and
   appends immutable receipts, performs exact candidate/class queries, exposes
   stable cursor pages and verifies active lineage against current trust.
2. **Replay and delivery durability.** AuthBus admission and outbox state share
   SQLite transactions with evidence mutations and retain consumed replay
   sequences after terminal-history pruning.
3. **Recovery snapshot.** The store computes deterministic migration,
   qualification and replay frontiers plus an immutable store identity.
4. **Recovery-frontier v2.** One signed domain binds generation, ledger root,
   trust registries, backend, build, qualification receipts, backup publication
   and source commit/tree.
5. **External monotonic backend.** The trait provides latest, CAS, history and
   backend-identity verification; the locked-file implementation keeps a
   bounded hash-chained audit journal outside the local rollback domain.
6. **Local acceptance history.** An append-only table records accepted external
   generations and prevents rollback below a previously accepted frontier.
7. **Agentd host.** Development mode admits local qualification composition;
   production mode verifies every external and local identity before attaching
   the product host.
8. **SQLite authority profiles.** Migration connections own schema changes;
   runtime connections use an authorizer that denies protected mutation and
   schema escape.
9. **Qualification/status pipeline.** Separate workflow jobs emit command JSON,
   raw logs and canonical source/merge status artifacts. A checked-in status
   source generates human-readable projections without granting authority.

Configuration affecting trust, backend identity, source identity, build,
signer policy, migration or recovery generation is immutable for one admitted
process generation.

## 5. Contracts, ports and compatibility

Produced contracts include:

- `DomainRead::qualification_evidenceV1`;
- `IndependentDecisionReceiptV1`;
- `ModulePort::kernel.evidence::control.engineering`;
- `ModulePort::kernel.evidence::control.runtime`;
- `ModulePort::kernel.evidence::learning.eval`;
- `ModulePort::kernel.evidence::learning.operator`;
- `ModulePort::kernel.evidence::learning.plasticity`.

Consumed contracts include the registered evaluation, conformance,
reconciliation, fault, local-runtime, longitudinal and unlearning receipts plus
registered domain reads and `ModulePort::platform.types::kernel.evidence`.

Rust values and canonical JSON must represent the same semantics. Every digest
scope includes all authority-relevant fields. Unknown critical fields, invalid
enums, noncanonical order, oversize payloads and incompatible schema revisions
are rejected. Compatibility changes are additive only where a registry allows
them; identifiers and authority interpretation cannot change in place.

The external recovery contract is:

```text
get_latest(store_id)
compare_and_swap(store_id, expected_generation, new_frontier)
get_history(store_id, range)
verify_backend_identity()
```

A successful CAS returns a durable acknowledgement containing backend identity,
store identity, generation, frontier digest and audit sequence. Uncertain write
outcomes poison the handle until operator reconciliation.

## 6. Data authority, persistence and migrations

Migration `0011_qualification_evidence.sql` owns immutable qualification rows,
replay-linked admission state, indexes and database-level `UPDATE`/`DELETE`
denial triggers. Rows bind receipt identity, candidate/source/tree, claim class,
receipt kind, issuer principal/role/key epoch/signing-key digest, AuthBus
message/sequence/expiry, exact payload/envelope digests, predecessor/target
lineage, observation/expiry and bounded asset references.

Corrections and revocations append lineage instead of rewriting history.
Identical authenticated semantics are idempotent; reused identity with changed
semantics conflicts. Ordinary lineage mutation is principal/role scoped; only a
currently trusted `security` role may perform cross-principal emergency
revocation.

Migration `0013_recovery_frontier_acceptance.sql` stores immutable local
acceptance records. Equal retries are idempotent, semantic drift conflicts and
lower generations are rejected across restart.

Migrations are deterministic and checksum-bound. Production admission first
opens a read-only preflight and refuses missing, unknown or incompatible schema.
Only the migration authority may mutate schema. Runtime connections cannot
attach databases, alter schema, enable writable pragmas or directly mutate
protected evidence tables.

## 7. Runtime, concurrency and transaction model

Each logical evidence mutation uses one transaction boundary. Durable replay
advancement and receipt insertion share one `BEGIN IMMEDIATE` transaction.
Cursor paging is ordered by immutable append sequence and binds the query
identity so a cursor cannot be replayed across candidate, tree or claim class.

The external backend holds an exclusive OS file lock across journal read,
expected-generation comparison, append and synchronization. It accepts exactly
the next generation. Every audit record binds the previous record digest and
expected prior generation. The locked-file adapter pins root and journal
directory device/inode identity and rejects symlink, hard-link, owner, mode and
path replacement violations.

The adapter requires storage with coherent cross-host locks and durable file and
directory `fsync` semantics. A deployment on weaker storage does not satisfy the
contract. Other adapters may implement the trait but must preserve authenticated
latest reads, linearizable generation CAS, append-only history, key rotation,
auditability and durable acknowledgement outside the local rollback domain.

Multi-process qualification launches eight independent publishers for one
generation and requires exactly one winner. That is a bounded correctness
fixture, not a production throughput claim.

## 8. Failure semantics, recovery and rollback

Failures distinguish invalid, conflict, unavailable, corrupt, unsupported and
indeterminate outcomes. Invalid or corrupt identity and lineage fail closed.
CAS conflicts report expected and actual generation. Backend unavailability
never falls back to local state. A write that may have reached durable storage
without a durable acknowledgement returns indeterminate and permanently fences
that backend handle.

Production startup performs these recovery checks before product availability:

1. owner-bound production descriptor and role-distinct control files;
2. canonical private external root outside Agent home and on a different
   device;
3. pinned backend identity and current signer registry;
4. exact-source and deterministic-merge qualification receipts from one
   governed pull-request workflow run;
5. exact build, trust-registry, backup-publication and source identities;
6. latest frontier freshness and threshold signatures;
7. local SQLite snapshot and ledger-root equality;
8. immutable acceptance of the verified generation.

Any missing, stale, revoked, malformed or mismatched input enters
`kernel.evidence recovery_required`. A valid but older complete database image
is rejected against a newer external frontier or local accepted generation.

Fault coverage includes transactional insert failure, simulated disk-full
behavior, torn and empty audit tails, directory/identity replacement, process
exit after delivery before acknowledgement, stale lease fencing and reopen
corruption.

## 9. Security, privacy and threat controls

The security posture is least authority, bounded input, digest binding,
owner-controlled trust and independent evidence. Sensitive values are omitted
or represented by digests. Credentials do not enter general logs, prompt
factors, learning data or cross-module receipts.

Frontier v2 binds:

- store identity and strictly monotonic generation;
- migration-set digest, qualification high-water/frontier and AuthBus replay
  frontier through the ledger root;
- issuer-trust and signer-registry digests;
- external backend identity;
- current executable digest;
- exact-source and deterministic-merge receipt-set digest;
- durable backup-publication digest;
- source commit/tree, creation time and signer-policy generation.

The signer registry requires distinct principals, current key epochs and a
threshold. Revoked keys and duplicate principals cannot satisfy the threshold.
Overlap rotation is explicit and generation-bound.

External control files must be canonical direct children of the private backend
root. Agentd opens them without following symlinks and verifies stable file and
parent-directory identity throughout the read. Qualification receipts must
contain exactly the five governed checks, successful command records, retained
log digests, exact artifact identity, matching workflow repository/run/attempt
and canonical source/base/merge parent order. All release-like flags in these
CI receipts must remain false.

## 10. Performance, capacity and hot-path policy

Enforced qualification bounds include:

- canonical receipt at most 256 KiB;
- at most 64 referenced assets;
- at most 256 predecessor edges;
- at most 512 query references;
- at most 32 required independent roles;
- Agentd control frame at most 48 KiB.

External audit journals are bounded to 256 KiB per record, 64 MiB total and one
million records. The next append is rejected before crossing any bound. Active
AuthBus outbox capacity remains bounded globally and per issuer; terminal
history may be pruned without releasing consumed replay sequences.

Before production activation, the selected platform must measure writer
contention, p95/p99 latency, database and journal growth, WAL/checkpoint
behavior, backup publication time, restore time, RPO and RTO. Source tests are
not capacity evidence for a deployment.

## 11. Observability and operations

Safe operational events include mode selection, backend identity digest,
accepted generation, source/tree identity, signer-policy generation,
qualification artifact digest, backup-publication digest, recovery-required
reason class and indeterminate-write fencing. Secret material and raw signing
keys are never logged.

Operators must retain:

- external backend identity and audit history;
- exact-source and deterministic-merge artifacts and digests;
- current issuer and signer registries plus rotation history;
- durable backup-publication acknowledgements;
- immutable accepted-frontier history;
- witnessed restore and rollback-rejection receipts;
- independent acceptance, canary, promotion and release decisions.

Development mode is visibly distinct and cannot satisfy production readiness.
Production mode refuses to start if any mandatory control input is absent. The
locked-file backend requires an operator-confirmed independent mount and storage
semantics; repository code cannot prove that deployment fact.

## 12. Verification and qualification

The focused source suite covers:

- exact authenticated append, replay/idempotency and semantic conflict;
- correction/revocation non-resurrection and current trust/key rotation;
- distinct-principal/signing-key independence;
- canonical corruption, query/traversal bounds and stable cursor paging;
- append-only triggers and runtime SQLite authorizer policy;
- recovery-frontier v2 field binding, ledger-root binding and deterministic
  mutation corpus;
- backend first publish, stale/skipped generation, history, identity drift,
  symlink/hard-link rejection, directory replacement, append bounds, torn/empty
  records and uncertain-write fencing;
- threshold signer overlap rotation and revoked key rejection;
- production receipt closed-world inventory, workflow/artifact identity,
  source/merge parent order and non-release authority boundary;
- production build/trust/backend/backup/frontier/local-snapshot mismatch;
- disk-full injection, actual process crash and eight-process CAS contention;
- canonical status source, exact Git anchor, source inventory and generated
  projection drift.

The dedicated reusable workflow runs the evidence package, Agentd product test,
Lane-A truth, documentation and implementation-map checks on both the exact PR
head and deterministic synthetic merge. Each command emits JSON and a raw log;
later checks and diagnostic uploads run even after an earlier failure. The
stable fan-in check is `Kernel evidence required`, consumed by repository
`CI required`.

A workflow artifact proves only the recorded execution on its bound object.
Independent acceptance and operational activation require separate principals
and retained receipts.

## 13. Implementation sequence and work packages

The repository closure sequence is:

1. repair exact-source regressions without weakening production bounds;
2. split qualification commands and retain diagnostics on failure;
3. implement recovery-frontier v2 and external backend contract;
4. add a concrete monotonic CAS adapter and immutable local acceptance;
5. establish explicit development/production modes and fail-closed admission;
6. separate migration/runtime database authority and add fault/property/
   contention tests;
7. generate all module status views from one canonical source;
8. qualify the exact source and deterministic merge;
9. obtain independent acceptance and deploy the external trust/backup system;
10. complete restore drill, canary, promotion and release through their owners.

Repository implementation through step 7 is present in this candidate. Steps 8
through 10 remain evidence-dependent and are recorded as false until their exact
receipts exist.

The external work package `P0.9-EXTERNAL-GATES` retains independent exact
candidate review, repository ruleset, operator acceptance, trust-root ceremony,
physical platform, promotion and release. Stop conditions include authority
violation, base drift, claim/evidence mismatch, cross-owner write and unbounded
resource/retry.

## 14. Activation, compatibility and retirement

Agentd is the named product caller. Development mode may attach the local host
only under explicit development configuration. Production mode requires current
issuer trust, threshold signer trust, external backend, build identity,
qualification receipts, backup publication and latest frontier; any missing
input fails closed.

Repository implementation of `LockedFileEvidenceFrontierBackend` does not mark
`externalFrontierActive=true`. That state requires deployment on independently
retained storage and an authority receipt bound to this exact candidate.
Likewise, repository tests cannot set `backupRestoreDrilled`,
`independentAcceptance`, `canaryAccepted` or `releaseApproved`.

Compatibility adapters are temporary. Retirement requires all named callers
migrated, no legacy path use, parity where required, preserved historical
interpretability, rehearsed rollback and independent acceptance. Frontier v1
remains a predecessor format and must not be silently accepted as the v2
production identity domain.

## 15. Definition of module completion

Documentation completion requires this guide, canonical status and closed-world
registry validation. Repository source completion requires implementation in
the declared roots, source tests, product composition, exact-source and
synthetic-merge execution receipts, and current implementation-map binding.
Production completion additionally requires:

- deployed authenticated external monotonic storage outside the local rollback
  domain;
- current issuer and threshold signer ceremonies;
- durable backup publication and witnessed restore/rollback rejection;
- independent exact-candidate acceptance;
- measured capacity and recovery objectives on the selected platform;
- canary, promotion and release receipts from their separate authorities;
- repository branch protection requiring the stable qualification fan-in.

No prose, source code, local test or CI workflow may advance those external
states by inference.

## 16. V8.2 implementation-readiness overlay

Ordinary authorized development identifies the Git baseline, owned paths,
contracts, fixtures, fallback and rollback. Runtime coordination still verifies
current source, frozen contract/readiness digests, expiry and zero authority
delta. An execution envelope is not additional permission for ordinary
repository work and never grants independent acceptance or release.

Readiness protocols remain registry-owned. `kernel.evidence` produces the
registered canonical-source, evaluator-independence and assimilation
qualification receipts and consumes the registered capability, migration,
rollback, sandbox, objective and emergency-stop envelopes according to their
current schemas.

## 17. Source implementation receipt

| Operation | Native implementation | Principal tests |
|---|---|---|
| append/query/verify qualification evidence | `codex-rs/hepta-evidence/src/qualification.rs` | `qualification_tests.rs`, Agentd product test |
| stable cursor paging | `codex-rs/hepta-evidence/src/qualification_paging.rs` | `qualification_paging_tests.rs` |
| recovery snapshot and migration/replay frontier | `codex-rs/hepta-evidence/src/recovery_frontier.rs` | recovery snapshot tests |
| frontier v2 signing and ledger root | `codex-rs/hepta-evidence/src/frontier_v2.rs` | `frontier_v2_tests.rs` |
| latest/CAS/history/backend identity | `codex-rs/hepta-evidence/src/frontier_backend.rs` | backend contract tests |
| locked external file backend | `codex-rs/hepta-evidence/src/frontier_backend_file.rs` | file backend and multiprocess tests |
| immutable local acceptance | `codex-rs/hepta-evidence/src/frontier_acceptance.rs` | acceptance and reopen tests |
| production admission | `codex-rs/hepta-agentd/src/evidence_production.rs` | production admission tests |
| threshold signer policy | `codex-rs/hepta-agentd/src/evidence_frontier_signers.rs` | signer rotation/revocation tests |
| issuer trust and product host | `codex-rs/hepta-agentd/src/evidence_trust.rs`, `evidence_host.rs` | `kernel_evidence_product.rs` |
| restricted runtime SQLite | `codex-rs/state/src/sqlite_evidence_runtime.rs` | authorizer tests |
| canonical status and projections | `qualification/kernel-evidence/STATUS_SOURCE.json`, `scripts/kernel_evidence_status.py` | `scripts/tests/test_kernel_evidence_status.py` |
| exact-source and merge qualification | `.github/workflows/hepta-kernel-evidence-qualification.yml` | retained workflow artifacts |

The named product caller is `runtime.agentd`. The stable qualification check is
`Kernel evidence required`, incorporated into `CI required`. Activating it as a
protected-branch requirement remains a repository-administrator operation.

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
