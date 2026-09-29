# kernel.evidence: implementation and execution dossier

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane:
`LANE-A-FOUNDATION`. Shared execution rules:
`qualification/module-execution-dossiers/EXECUTION_SEMANTICS.md` and the parent
technical guide.

This dossier distinguishes source presence, exact-candidate execution,
independent acceptance, deployment, canary and release. It does not convert one
state into another.

## 1. Source and product boundary

Primary owner root: `codex-rs/hepta-evidence`.

Named product surfaces:

- `codex-rs/hepta-agentd` — explicit development/production host,
  fail-closed production admission and publication driver;
- `codex-rs/hepta-agent-protocol` — bounded paging/profile wire selectors;
- `codex-rs/state` — restricted evidence SQLite runtime connections;
- `.github/workflows`, `qualification/kernel-evidence` and `scripts` — exact
  candidate qualification and canonical status projection.

The direct A–C source-capability anchor is
`001e557716e884fbd47d5ab2f0ca9f47175f958e`, tree
`6ecfb41b6e18406ea019fbffa3a972aba5cc4baf`. Later documentation/metadata heads
must obtain their own exact-source and fixed-base merge execution receipts.

## 2. Trusted decision API

The product verification boundary accepts an
`EvidenceVerificationProfileV1`, not a caller-selected role vector. The
closed-world profile determines the claim class and a non-empty minimum role
set. Empty, duplicate, weakened or unknown role combinations fail closed.

`identity_assignment.rs` assigns required roles to distinct authenticated
principals and distinct signing identities without corrupting recursive search
state. Native tests contain the fixed three-role Alice/Bob counterexample,
cardinality/work-budget cases and exhaustive comparison with a cartesian oracle.

`VerifiedEvidenceTrustSnapshot` and `VerifiedEvidenceIssuer` are sealed outside
the evidence crate. Production cannot supply arbitrary binding slices or
construct an issuer registration. Trust schema V2 binds agent identity,
monotonic registry generation, predecessor registry digest, signer policy and
issuer/key/role inventory. Raw adapters are limited to crate tests.

## 3. Authenticated append and lineage

`QualificationEvidenceStore::append_receipt` consumes a sealed issuer and trust
snapshot. It validates canonical envelope/candidate/role identity, authenticates
the exact AuthBus subject and payload, checks current trust, expiry, lineage,
idempotency and replay, and commits replay advancement, qualification row and
publication intent in one `BEGIN IMMEDIATE` transaction.

Migration `0011_qualification_evidence.sql` owns append-only qualification rows
and immutable store identity. Migration
`0016_qualification_auth_provenance.sql` persists the original admission
signature and admitted trust generation/digest for new rows. Historical rows
without original V2 provenance remain readable history but cannot be promoted
into production-valid authenticated snapshot V2.

`qualification_commitment.rs` commits envelope, principal, key epoch, signing
identity, message/sequence/expiry/signature, accepted trust identity and
recording time. Corrections and revocations append lineage. Ordinary lineage
mutation is principal/role scoped; explicit current `security` authority is the
only cross-principal emergency revocation path.

## 4. Query, paging and verification

Claim verification executes under one read transaction, reconstructs canonical
rows, applies correction/revocation and expiry, checks the pinned current trust
snapshot, then enforces the owner profile and distinct-identity assignment.

Agentd product query supports stable append-sequence cursors with page size at
most 128 and binds the cursor to candidate, tree and claim class. Product
verification returns a bounded `EvidenceVerificationSummaryV1` containing state,
profile, reference count and evidence-set digest rather than an unbounded vector.
Malformed reserved selectors fail closed.

## 5. Authenticated recovery snapshot V2

`authenticated_recovery_snapshot()` reads migration records, immutable store
identity, qualification rows and AuthBus replay frontier through one SQLite read
transaction. Qualification scanning uses keyset pages and enforces row,
per-envelope, aggregate-byte, replay and migration bounds.

The snapshot commits complete authenticated admission provenance rather than only
the public envelope digest. Field-mutation, concurrent-writer/WAL epoch,
enrollment, capacity and reopen tests exercise this boundary. Historical V1
snapshot decoding remains a readability feature; production requires V2 and
must never relabel a V1 signature as V2.

## 6. Atomic trust and frontier acceptance

Migration `0013_recovery_frontier_acceptance.sql` stores immutable accepted
external generations. Migration `0015_evidence_trust_acceptance.sql` stores
monotonic accepted trust generations and their frontier binding.

`accept_production_generation_at_snapshot()` runs under one
`BEGIN IMMEDIATE` transaction. It recomputes the expected authenticated snapshot,
requires exact next trust generation and predecessor digest, and atomically
records trust plus frontier acceptance. Snapshot drift, lower/skipped generation,
semantic conflict and partial acceptance fail closed across restart.

## 7. Durable publication state machine

Migration `0014_evidence_publication.sql` owns the singleton publication owner,
monotonic owner generation/lease, immutable publication batches and per-evidence
row intents. Triggers deny deletion and invalid transitions.

The durable states are:

```text
prepared -> dispatching -> acknowledged
                      \-> indeterminate
indeterminate -> acknowledged
```

Each batch binds exact expected/proposed generation, authenticated local
snapshot and proposed frontier. A stale owner generation cannot dispatch or
acknowledge it. CAS uncertainty remains durable; restart reads authenticated
external latest state:

- latest equals the proposed frontier: recover the acknowledgement;
- latest equals the expected predecessor: the current fenced owner may retry
  the same batch;
- any other identity/generation: conflict and recovery required.

Local acknowledgement validates the backend acknowledgement and atomically
accepts the frontier, completes the batch and marks its row intents anchored.
A new operation ID cannot erase an unknown result.

## 8. External monotonic and segmented backend

`EvidenceFrontierBackend` exposes authenticated latest, exact-next-generation
CAS, bounded history and backend identity verification.

The exported production `LockedFileEvidenceFrontierBackend` uses a private
separately mounted root, an active JSONL tail, immutable hash-linked segments
and a self-authenticating atomic latest index. Per-store locks serialize CAS.
Files/directories are owner/mode/link checked and opened without following
links. Success is returned only after the relevant file and directory state is
synchronized.

The active tail rolls at 1024 records or 16 MiB. A missing or stale index is
reconstructed from authenticated history; it never replaces the active/segment
chains. Historical acknowledgements are recovered only after the matching record
is located and re-synchronized. Capacity projection exposes archived/active
records and bytes, headroom and alert state. Normal operation never deletes
history to recover capacity.

Thread and eight-process tests require exactly one winner per generation. These
are correctness fixtures, not target-platform throughput or power-loss proof.

## 9. Agentd production admission

Development and production are explicit typed profiles. Production cannot route
through the legacy V1 verifier or silently fall back to development.

Before host publication, production verifies:

1. owner-controlled descriptor and role-distinct canonical private files;
2. external backend identity and current threshold signer registry;
3. exact-source and deterministic fixed-base merge receipts from one governed
   PR workflow run/attempt with exactly the registered command/log inventory;
4. source/base/merge parent ordering and retained artifact identity;
5. current trust V2 generation/digest and signed frontier freshness;
6. current executable digest and governed build provenance;
7. actual backup object byte length/digest and durable storage acknowledgement;
8. successful independent restore witness bound to object, restored snapshot and
   SQLite integrity-check digest;
9. exact local authenticated snapshot/ledger root;
10. atomic trust/frontier acceptance.

Missing, stale, legacy, revoked, malformed or mismatched inputs return
`kernel.evidence recovery_required`. Non-Unix production admission remains
unsupported and fails closed.

## 10. SQLite runtime authority

Production first performs a read-only existing-lineage migration/schema,
canonical-row, provenance, trigger, publication/trust and foreign-key preflight.
It then reopens the same database through the restricted runtime authorizer.

Runtime denies DDL, attach/detach, migration-ledger writes, extension loading and
write-capable pragmas. Immutable-row triggers remain an independent backstop.
Normal typed evidence/publication inserts remain available. Migration authority
and runtime writer authority are therefore distinct.

The checksum-bound physical lineage is `hepta_evidence_2.sqlite`, migrations
`0001` through `0016`; the closure-specific migrations are `0011` through
`0016` as described above and in `STORE_V1.md`.

## 11. Resource and operational bounds

Enforced source bounds include 256 KiB canonical receipts, 64 assets, 256
lineage edges, 512 claim references, 32 required roles, 48 KiB Agentd frames and
128 product page rows. Recovery additionally enforces one million qualification
rows, 512 MiB aggregate canonical-envelope bytes, 16,384 replay rows and 1,024
migration rows.

Safe observations include runtime profile, trust generation/digest, accepted
frontier, publication batch/owner generation, indeterminate reconciliation
state, backup/build identity and segmented-backend capacity. Raw signing keys and
sensitive evidence payloads are not logged.

Activation still requires measured contention, p95/p99 latency, storage growth,
publication lag, backup/restore time, RPO and RTO on the selected platform.
Source constants and synthetic tests are not deployment measurements.

## 12. Qualification pipeline

The direct PR workflow has no path filter and runs both exact source and a
deterministic ordered-parent merge of the immutable PR base and source. The
governed inventory includes evidence tests, Agentd product/profile tests, Lane-A
truth, documentation and implementation-map checks. Command JSON and raw logs
are retained even when an earlier command fails; final fan-in is fail closed.

Separate bounded-core and publication diagnostics expose solver/oracle,
recovery-protocol, formatting and native publication failures without replacing
the full package and architecture checks. Candidate/record validators reject
dirty or substituted Git objects, missing test execution, noninteger exits,
unsafe/reused/changing log files, run/attempt/job drift, malformed artifacts and
wrong merge parent order.

Queued, pending, skipped, cancelled and action-required states are not passes.
Any source repair creates a new candidate and invalidates earlier exact-head
execution claims.

## 13. Current claim boundary

Repository source contains the A–C implementation surfaces and their test
oracles. Repository completion still requires successful formatting, strict
lint, native tests/builds, docs/maps, exact-source, fixed-base merge, general CI
and architecture results for the unchanged final head with retained artifact
digests.

The repository does not prove that the external backend is deployed on an
independent durable device, that a target host survived power loss, that backup
and rollback rejection were independently witnessed, that an independent
reviewer accepted the exact candidate, or that canary/release authorities acted.
Those gates remain false until their own receipts exist.

<!-- BEGIN GENERATED KERNEL EVIDENCE STATUS -->
## Canonical kernel.evidence status

This block is generated from
`qualification/kernel-evidence/STATUS_SOURCE.json` by
`python3 scripts/kernel_evidence_status.py sync`. Hand-written prose cannot
override these facts. Workflow receipts may prove the current candidate, but
cannot self-issue independent acceptance, deployment, canary or release.

- Source anchor commit: `9108f9b1b2c73d6defb6b536d87ce76834eb5abb`
- Source anchor tree: `2606b7df789e1f50a22465998cd607060636782c`
- Canonical status SHA-256: `848dce603e2d5e78561730ede309a115f822e918d786e772a132b23add62577f`
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
