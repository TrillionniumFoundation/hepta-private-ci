# kernel.evidence technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `kernel.evidence`

**Owner:** `qualification-plane`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `P0.9-EXTERNAL-GATES`

This guide describes the repository implementation of `kernel.evidence` after
the staged correctness, trust, recovery, publication and bounded-operations
closure. It deliberately separates source capability, exact-candidate execution,
external deployment, independent acceptance, canary and release. A later state
must never be inferred from an earlier one.

## 1. Identity, mission and ownership

`kernel.evidence` is the qualification-plane authoritative store for exact
candidate evidence, authenticated admission provenance, independent decision
receipts, monotonic trust/frontier acceptance and durable publication intent.
Its primary owner is `qualification-plane`; `security-authority` independently
reviews trust, signatures, recovery, persistence, concurrency, capacity and
fail-closed production admission.

The module verifies and preserves evidence. It is not a selector, merger,
deployer or release authority and it cannot mint the external principal whose
independent receipt it may store.

## 2. Source binding and implementation status

The declared implementation root is `codex-rs/hepta-evidence`. Product
composition is in `codex-rs/hepta-agentd`, product-wire types are in
`codex-rs/hepta-agent-protocol`, restricted SQLite runtime authority is in
`codex-rs/state`, and qualification/status control is in `.github/workflows`,
`qualification/kernel-evidence` and `scripts`.

The canonical source-capability anchor is commit
`001e557716e884fbd47d5ab2f0ca9f47175f958e`, tree
`6ecfb41b6e18406ea019fbffa3a972aba5cc4baf`. Successor documentation and
qualification-trigger commits do not inherit execution evidence from that
anchor. Repository implementation is present for the A–C closure tracks, while
the exact-source, fixed-base merge, external deployment and governance gates
remain separately evidenced.

Current source capabilities include:

- frame-correct bounded role-independence assignment with exhaustive oracle
  equivalence tests;
- owner-controlled, non-empty and non-degradable verification profiles;
- sealed verified issuer/trust handles with monotonic V2 registry generations;
- complete authenticated-admission commitments and one-transaction recovery
  snapshots;
- atomic trust/frontier acceptance at an exact snapshot;
- fenced durable publication batches with CAS conflict and indeterminate-result
  reconciliation;
- product cursor paging and bounded verification summaries;
- real backup-object byte verification, governed build provenance and restore
  witness binding;
- immutable segmented frontier history, an authenticated latest index and
  capacity telemetry.

These are source claims until the final candidate's retained workflows complete.

## 3. Boundary, responsibilities and non-goals

Authoritative write domains are `qualification_evidence`,
`independent_decision_receipt_v1`, local recovery/trust acceptance and the
publication control tables. Inputs must be typed, versioned, bounded,
canonical and authenticated. Missing authority, stale generation, replay,
scope drift, digest mismatch, invalid lineage and unknown critical fields fail
closed.

Explicit non-goals are provider effect execution, candidate selection, merge
authority, promotion, release, self-issued independent review, silent
production-to-development downgrade and treating local SQLite integrity as an
external rollback oracle.

## 4. Internal architecture and component decomposition

1. **Qualification ledger.** `QualificationEvidenceStore` authenticates and
   appends immutable receipts, maintains correction/revocation lineage, queries
   exact candidate/claim identities and verifies a closed-world profile.
2. **Independence policy.** `identity_assignment.rs` solves bounded role
   assignment without corrupting recursive state; `qualification_policy.rs`
   maps each permitted profile to its claim class and non-empty role set.
3. **Verified trust.** `verified_trust.rs` parses owner-controlled registries,
   validates V2 generation/predecessor continuity and yields sealed issuer and
   snapshot views. Raw bindings are test-only adapters.
4. **Authenticated commitment.** `qualification_commitment.rs` commits the
   envelope together with principal, key epoch, signing identity, AuthBus
   message/sequence/expiry/signature, trust generation/digest and recording
   time.
5. **Recovery snapshot.** `recovery_snapshot.rs` computes migration, evidence,
   replay, store-identity and authenticated-admission frontiers in one SQLite
   read transaction.
6. **Atomic acceptance.** `trust_acceptance.rs` compares the exact expected
   snapshot and atomically accepts the next trust generation and external
   frontier under one `BEGIN IMMEDIATE` transaction.
7. **Publication state machine.** `publication.rs` persists owner leases,
   generation-fenced batches and row intents; it distinguishes prepared,
   dispatching, indeterminate and acknowledged states and reconciles by external
   latest-frontier observation.
8. **External monotonic backend.** `frontier_backend_file` supplies a private,
   separately mounted CAS store. The production adapter keeps an active tail,
   immutable linked segments and an authenticated atomic latest index.
9. **Agentd product host.** `evidence_host.rs` exposes append, stable paging and
   profile verification through explicit development or production profiles.
   `evidence_production.rs` and its included modules perform fail-closed startup,
   backup/build/restore validation and publication driving.
10. **Qualification/status pipeline.** Exact-source and deterministic merge
    lanes emit bounded command records, logs and canonical status artifacts.
    A machine-readable status source generates projections without granting
    external authority.

## 5. Contracts, ports and compatibility

Produced registered contracts remain `DomainRead::qualification_evidenceV1`,
`IndependentDecisionReceiptV1` and the registered module ports. Rust values and
canonical JSON must represent the same semantics and digest scope.

The product verification contract accepts an
`EvidenceVerificationProfileV1`, not a caller-defined role vector. Legacy role
requests are accepted only when they map exactly to a registered profile;
empty, duplicate, weakened or unknown combinations fail closed. The product
query selector supports bounded page size and stable cursor identity. Profile
verification returns `EvidenceVerificationSummaryV1`, which contains state,
profile, count and evidence-set digest instead of an unbounded evidence vector.

The external recovery backend contract is:

```text
get_latest(store_id)
compare_and_swap(store_id, expected_generation, new_frontier)
get_history(store_id, bounded_range)
verify_backend_identity()
```

A successful CAS returns a durable acknowledgement. A write whose durable
outcome is unknown becomes `indeterminate` and can only be resolved by reading
the authenticated latest frontier and matching the exact batch identity.
Production accepts authenticated snapshot V2 and monotonic trust V2; legacy
formats remain development/read compatibility only and cannot be relabelled as
production authority.

## 6. Data authority, persistence and migrations

The physical lineage is `hepta_evidence_2.sqlite`; migrations `0001` through
`0016` are ordered and checksum-bound. The closure-relevant migrations are:

- `0011_qualification_evidence.sql`: append-only exact-candidate rows, immutable
  store identity and update/delete denial triggers;
- `0012_authbus_recovery.sql`: durable recovery facts for AuthBus delivery;
- `0013_recovery_frontier_acceptance.sql`: immutable accepted external
  generations;
- `0014_evidence_publication.sql`: owner fencing, durable publication batches,
  row intents and strict transition triggers;
- `0015_evidence_trust_acceptance.sql`: monotonic accepted trust generations and
  frontier binding;
- `0016_qualification_auth_provenance.sql`: original signature and accepted
  trust-generation provenance for new qualification rows.

A production-valid row must have complete authenticated provenance. Historical
V1 rows with absent signatures remain readable as history but cannot be
manufactured into production-valid V2 provenance.

Corrections and revocations append lineage rather than rewriting facts. Exact
authenticated retries are idempotent; identity reuse with different semantics
conflicts. Runtime connections cannot mutate migrations or schema, attach
databases, enable write-capable pragmas or bypass immutable-row triggers.

## 7. Runtime, concurrency and transaction model

Receipt authentication, replay advancement, qualification insertion and
publication-intent creation share one `BEGIN IMMEDIATE` mutation boundary.
Before commit, sealed issuer/trust handles are revalidated against their pinned
registry identity.

Claim verification uses a stable read transaction. Role assignment has explicit
role, candidate and work bounds. Recovery snapshot V2 reads every component from
one transaction and pages qualification rows rather than materializing an
unbounded table.

Production acceptance compares the signed expected snapshot, validates the next
trust generation and predecessor digest, and writes trust plus frontier
acceptance atomically. Publication uses a durable owner generation and lease;
stale owners cannot mutate a batch. The external segmented backend serializes
each store with a dedicated file lock, appends and synchronizes the active tail,
seals immutable segments and atomically publishes the latest index.

## 8. Failure semantics, recovery and rollback

Errors distinguish invalid, conflict, unavailable, corrupt, unsupported and
indeterminate outcomes. Neither backend unavailability nor a weak storage
profile falls back to local success.

Publication recovery rules are:

- `prepared`: no external dispatch has begun and the current owner may resume;
- `dispatching`: CAS has begun and restart must inspect external latest state;
- `indeterminate`: success or failure is unknown and blind retry is forbidden;
- `acknowledged`: the durable acknowledgement, exact snapshot and local
  acceptance are atomically recorded.

If external latest equals the batch's proposed frontier, restart recovers the
acknowledgement. If latest remains at the expected predecessor, the fenced owner
may retry the same batch. A divergent generation or identity is a conflict,
not an invitation to create a new operation ID.

Production startup verifies private control paths, backend identity, signer
trust, exact-source and merge receipts, build provenance, backup object bytes,
restore witness, current executable, trust generation, signed frontier and
local authenticated snapshot before publishing the host.

## 9. Security, privacy and threat controls

The trust boundary is least authority, current generation, bounded input and
complete digest binding. The verified trust snapshot is sealed outside the
crate; product callers cannot forge a raw binding or arbitrary
`IssuerRegistration`. Distinct required roles must be assigned to distinct
principals and distinct signing identities.

The signed frontier binds store/generation, authenticated ledger root, migration
set, issuer and signer registries, backend identity, executable, qualification
receipts, backup manifest and source commit/tree. The backup manifest in turn
binds the real object byte digest/length, storage acknowledgement, governed
build artifact/toolchain/recipe/log and an independent restore witness.

Control files and backup objects are canonical private direct children of the
configured roots, opened without following links and checked for stable
file/directory identities while read. Secrets and signing keys never enter
general evidence payloads or logs.

## 10. Performance, capacity and hot-path policy

Enforced bounds include a 256 KiB canonical receipt, 64 assets, 256 lineage
edges, 512 claim references, at most 32 required roles, a 48 KiB Agentd frame
and product page size at most 128. Verification returns a bounded summary.

Authenticated recovery scanning is paged and bounded by one million
qualification rows, 512 MiB aggregate canonical envelope bytes, fixed per-row
limits and a bounded replay frontier. Normal append avoids recomputing the
whole candidate evidence set unless an independent decision requires it.

The segmented backend rolls over the active tail at 1024 records or 16 MiB,
preserves immutable history, reconstructs a stale index from authenticated
records and exposes record/byte headroom plus health/elevated alerts. These
source bounds are not production throughput evidence. The selected platform
must still measure contention, p95/p99 latency, WAL/checkpoint behavior,
publication lag, segment growth, backup time, restore time, RPO and RTO.

## 11. Observability and operations

Safe operational facts include runtime profile, registry generation/digest,
backend identity, accepted frontier, publication batch/owner generation,
indeterminate reconciliation disposition, source/tree identity, backup/build
digests and capacity/headroom. Raw keys and sensitive payloads are excluded.

Operators retain exact qualification artifacts and logs, registry rotation
history, external segment/index history, backup/storage acknowledgements,
restore witnesses, local accepted generations and external governance
decisions. Capacity alarms must be raised before active rollover or segment
count exhaustion; operators must never recover capacity by deleting history.

## 12. Verification and qualification

Focused tests cover:

- the fixed three-role counterexample, empty/duplicate roles, same-principal
  multi-key cases and exhaustive bounded assignment/oracle equivalence;
- sealed trust compile boundaries, digest pinning, monotonic rotation and stale
  registry rejection;
- authenticated append, replay, idempotency, signature/provenance corruption,
  correction/revocation and current-trust verification;
- one-transaction snapshot consistency, byte/row bounds and atomic
  trust/frontier acceptance;
- owner fencing, every publication transition, crash/reopen, CAS conflict,
  uncertain outcome and startup reconciliation;
- real Agentd paging, malformed selectors and bounded verification summaries;
- backup-object bytes, build provenance, restore witness and production startup
  mismatch cases;
- segmented rollover, stale-index recovery, immutable history, capacity
  telemetry and multiprocess single-winner CAS;
- exact-source and deterministic fixed-base merge qualification with retained
  records and logs.

The final execution evidence must be produced on the unchanged integration head;
queued, skipped, cancelled, action-required or historical runs are not passes.

## 13. Implementation sequence and work packages

The existing protocol was completed in four tracks rather than replaced:

1. **A — trustworthy decision:** fixed role backtracking, closed verification
   profiles and sealed verified trust;
2. **B — durable recovery:** authenticated commitments, transactional snapshot,
   monotonic trust/frontier acceptance and fenced publication reconciliation;
3. **C — product and longevity:** Agentd paging/summary, explicit modes,
   backup/build/restore proof and segmented long-term history;
4. **D — integration evidence:** synchronize documentation and implementation
   mapping, then qualify one exact source and one deterministic merge candidate.

A–C are source implemented at the canonical source anchor. D remains open until
the final head has successful retained receipts and all required repository
checks complete.

## 14. Activation, compatibility and retirement

Development mode is visibly distinct and cannot satisfy production readiness.
Production has no downgrade path: any absent, legacy, stale, revoked, malformed
or mismatched control input returns `kernel.evidence recovery_required`.

Source implementation of the external adapter does not establish that it is
deployed on an independently retained device with coherent locks and durable
`fsync`. Compatibility paths may be retired only after all callers migrate,
historical evidence remains interpretable, rollback is rehearsed and an
independent principal accepts the exact candidate.

## 15. Definition of module completion

Repository source completion requires current source mapping, formatted and
linted Rust, evidence and Agentd tests, builds, documentation checks, exact-head
and fixed-base merge receipts and retained artifact digests.

Production completion additionally requires independent storage provisioning,
signer and trust ceremonies, measured capacity/recovery objectives, a real
witnessed backup/restore and rollback-rejection drill, independent
exact-candidate acceptance, operator acceptance, canary and release approval.
Those external states remain false until their own receipts exist.

## 16. Current claim boundary

The repository may claim that A–C implementation surfaces exist and are wired
to the named product host. It may not claim final execution, deployment,
independent acceptance or release from source presence or from this document.
The checked-in status source below is authoritative for persistent gate state.

## 17. Source implementation receipt

| Concern | Native implementation | Principal tests |
|---|---|---|
| bounded independent-role assignment | `identity_assignment.rs`, `qualification_policy.rs` | fixed counterexample and exhaustive oracle tests |
| verified trust boundary | `verified_trust.rs`, `trust_acceptance.rs` | trust boundary, rotation and atomic acceptance tests |
| authenticated append and commitment | `qualification.rs`, `qualification_commitment.rs` | qualification/provenance tests |
| transactional recovery snapshot V2 | `recovery_snapshot.rs`, `recovery_frontier.rs` | recovery snapshot tests |
| fenced durable publication | `publication.rs`, migration `0014` | publication and crash/reconciliation tests |
| segmented monotonic backend | `frontier_backend_file/segmented/*` | rollover, recovery, capacity and multiprocess tests |
| Agentd paging and bounded verification | `evidence_host.rs`, protocol `evidence.rs` | product paging/profile tests |
| production backup/build/restore admission | `evidence_production.rs`, `evidence_backup_manifest.rs` | production admission tests |
| exact source and fixed-base merge evidence | qualification and convergence workflows | retained source/merge artifacts |

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `001e557716e884fbd47d5ab2f0ca9f47175f958e`
- Source anchor tree: `6ecfb41b6e18406ea019fbffa3a972aba5cc4baf`
- Canonical status SHA-256: `efe917d985790cbb41f3bdc2083e7596abc211d4bfee63ace066e84dadd8f99e`
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
| Owner-controlled non-degradable verification profiles | `true` |
| Sealed monotonic verified trust snapshots | `true` |
| Single-transaction authenticated recovery snapshot V2 | `true` |
| Complete authenticated-admission commitment | `true` |
| Durable fenced publication and CAS reconciliation | `true` |
| Bounded product verification summaries | `true` |
| Real backup-object byte verification | `true` |
| Governed source-to-executable build provenance | `true` |
| Backup restore-witness binding | `true` |
| Immutable segmented frontier history | `true` |
| Self-authenticating atomic latest-frontier index | `true` |
| Frontier rollover and capacity observability | `true` |

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
