# `kernel.evidence` current implementation

## Executable boundary

`codex-rs/hepta-evidence` is the SQLite-backed authoritative qualification
store. `codex-rs/hepta-agentd` is the named product host and
`codex-rs/hepta-agent-protocol` owns the bounded wire selectors. The production
runtime does not accept arbitrary role lists or raw trust bindings: verification
uses an owner-controlled profile and sealed verified trust snapshot.

Source capability is anchored at commit
`001e557716e884fbd47d5ab2f0ca9f47175f958e`, tree
`6ecfb41b6e18406ea019fbffa3a972aba5cc4baf`. Later documentation and
qualification-trigger commits carry no inherited execution or deployment
authority.

## Core correctness

`identity_assignment.rs` implements a bounded, frame-correct assignment of
required roles to distinct authenticated principals and distinct signing
identities. It rejects empty or duplicate role sets, checks cardinality before
search and enforces a work budget. Tests include the three-role Alice/Bob
counterexample that exposed the prior backtracking corruption and exhaustive
comparison with a cartesian oracle.

`qualification_policy.rs` defines the closed-world
`EvidenceVerificationProfileV1` inventory. Product requests identify a profile;
legacy role vectors are accepted only when they exactly equal one registered
profile. Weakened subsets, empty roles, duplicates and unknown combinations fail
closed.

## Verified trust and append

`VerifiedEvidenceTrustSnapshot` and `VerifiedEvidenceIssuer` are sealed outside
the evidence crate. Production trust schema V2 binds agent, registry generation,
predecessor registry digest, signer policy and issuer/key/role inventory. The
product pins the digest admitted by the signed frontier for the whole process
generation and revalidates the owner file identity around each operation.

`QualificationEvidenceStore::append_receipt` authenticates the exact canonical
envelope, binds candidate/tree/role to the AuthBus subject and commits replay,
qualification row and publication intent in one `BEGIN IMMEDIATE` transaction.
New rows persist the original signature and admitted trust
generation/registry digest. `qualification_commitment.rs` commits those facts
together with principal, key epoch, signing identity, message identity,
sequence, expiry and recording time. Historical rows missing V2 provenance are
never promoted into production-valid rows.

## Verification and product reads

Claim verification runs in a read transaction, applies correction/revocation
lineage and expiry, checks the pinned trust snapshot, enforces the selected
profile and returns a bounded `EvidenceVerificationSummaryV1`.

Agentd exposes stable cursor paging through the `page:v1` selector with a
maximum page size of 128. Profile verification uses `profile:v1`; malformed
reserved selectors fail closed. The product no longer returns an unbounded
evidence vector for a verification decision.

## Recovery snapshot and atomic acceptance

`authenticated_recovery_snapshot()` computes snapshot V2 in one SQLite read
transaction. It includes the migration set, immutable store identity,
qualification high-water, complete authenticated-admission commitment and
AuthBus replay frontier. Scanning is paged and bounded by row and byte limits.

`accept_production_generation_at_snapshot()` executes under one
`BEGIN IMMEDIATE` transaction. It recomputes and compares the expected snapshot,
checks exact next trust generation and predecessor digest, then atomically
accepts trust plus frontier. A changed local database, skipped registry
generation or split acceptance fails closed.

## Durable publication and CAS reconciliation

Migration `0014_evidence_publication.sql` adds durable publication owner,
batch and row-intent tables. Qualification inserts create publication intent in
the same transaction after store enrollment.

`publication.rs` provides owner lease/generation fencing and the states
`prepared`, `dispatching`, `indeterminate` and `acknowledged`. A CAS timeout or
uncertain write is never blindly retried with a new identity. Recovery reads the
authenticated external latest frontier:

- exact proposed frontier: recover the durable acknowledgement;
- expected predecessor: the current fenced owner may retry the same batch;
- any other generation or identity: terminal conflict/recovery required.

Acknowledgement, exact-snapshot comparison, local frontier acceptance and row
intent completion commit atomically.

## External segmented backend

The exported `LockedFileEvidenceFrontierBackend` is the segmented production
adapter. It preserves the legacy active JSONL tail for compatibility, rolls it
into immutable linked segments at 1024 records or 16 MiB, and publishes a
self-authenticating atomic latest index. A stale or absent index is rebuilt from
the authenticated active tail and latest segment; the index never replaces the
record/segment chains.

The adapter verifies private owner-bound roots and files, rejects links and
identity replacement, serializes each store with file locks, requires exact
next-generation CAS and synchronizes file plus directory before success.
Capacity telemetry reports archived/active records and bytes, headroom and
health/elevated alerts. History is preserved; capacity recovery never means
deleting evidence.

## Production backup, build and restore admission

`evidence_backup_manifest.rs` requires a versioned backup object with exact
length and SHA-256, storage backend identity and durable acknowledgement. It
opens and hashes the real object bytes while pinning file and parent-directory
identity.

The same signed manifest binds governed build provenance: repository,
source commit/tree, workflow run/attempt/job, artifact URL/digest, builder,
toolchain, recipe, log and executable digest/length. It also binds a successful
restore witness with restored object/snapshot digests and SQLite integrity-check
digest. Production compares the current executable and signed frontier against
these records before host publication.

## Database lineage

The physical file is `hepta_evidence_2.sqlite`; the checksum-bound migration set
is `0001` through `0016`.

- `0011`: immutable qualification evidence and store identity;
- `0012`: AuthBus recovery state;
- `0013`: immutable accepted frontiers;
- `0014`: publication owner, batch and intent state machine;
- `0015`: accepted monotonic trust generations;
- `0016`: qualification signature/trust provenance.

Production first performs a read-only migration/schema/integrity preflight and
then reopens through the restricted SQLite runtime authorizer. Runtime denies
schema mutation, migration-ledger writes, attach/detach, extension loading and
write-capable pragmas while typed evidence operations remain available.

## Qualification scope

Dedicated workflows run both the exact source and the deterministic merge of
the immutable base and source. They execute evidence tests, Agentd product/profile
tests, Lane-A truth, technical-document verification and implementation-map
verification, retaining command JSON, raw logs and canonical status artifacts.
A source reference, queued run or historical pass is not current execution
evidence.

## Remaining gates

Repository-controlled implementation surfaces for tracks A–C are present.
Track D remains incomplete until the unchanged final head has successful
exact-source, deterministic-merge, CI and architecture receipts with retained
artifact digests.

The following remain external and false until separately witnessed:
independent semantic/security acceptance, deployment of the external rollback
domain, signer/trust ceremonies, target-platform capacity and power-loss tests,
real operator backup/restore and rollback rejection, canary, promotion and
release.

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
