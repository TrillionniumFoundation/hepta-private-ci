# kernel.evidence: implementation design

Parent: `docs/modules/kernel.evidence/TECHNICAL.md`. Lane:
`LANE-A-FOUNDATION`. Common requirements: `../EXECUTION_SEMANTICS.md` and
`../TECHNICAL.md`.

Status: repository implementation now includes authenticated exact-candidate
qualification storage/query/verification, Agentd development and fail-closed
production modes, recovery-frontier v2, threshold signer rotation, an external
monotonic backend contract with a locked-file adapter, immutable local frontier
acceptance, runtime SQLite authorizer, stable cursor paging, fault injection,
multi-process contention coverage and canonical status generation. Exact
candidate execution, independent acceptance, deployed external storage,
backup/restore drill, canary, promotion and release remain separate evidence
gates.

## 1. Source and work envelope

Primary root: `codex-rs/hepta-evidence`.
Product composition: `codex-rs/hepta-agentd`.
SQLite runtime enforcement: `codex-rs/state`.
Qualification/status control: `.github/workflows`, `qualification/kernel-evidence`
and `scripts/kernel_evidence_status.py`.

The native qualification contract is exposed through
`HeptaEvidenceStore::qualification() -> QualificationEvidenceStore`. This typed
facade preserves the legacy governance `HeptaEvidenceStore::append_receipt`
without overloading its semantics.

## 2. Public operations and authority contracts

Qualification operations are:

- `append_receipt(authenticated_issuer, signed_message, envelope)`;
- `query_claim(candidate, claim_class)`;
- `query_claim_page(candidate, claim_class, cursor)`;
- `verify_chain(request, current_trust)`.

External recovery operations are the `EvidenceFrontierBackend` trait:

- `get_latest(store_id)`;
- `compare_and_swap(store_id, expected_generation, new_frontier)`;
- `get_history(store_id, range)`;
- `verify_backend_identity()`.

Agentd exposes the evidence operations through its bounded control path. It
reloads current issuer trust immediately before physical append and before a
positive verification. Production startup additionally consumes a signer
registry, exact-source and deterministic-merge receipts, external backend
identity, durable backup receipt, build digest and latest signed frontier. None
of these inputs grants merge, promotion or release authority.

## 3. Evidence state and transaction design

Migration `0011_qualification_evidence.sql` owns append-only
`qualification_evidence`, replay-linked admission state and database denial
triggers. It stores candidate/source/tree, claim class, receipt kind, issuer
principal/role/key epoch/signing-key digest, AuthBus message and sequence,
payload/envelope digests, predecessor/target lineage, observation/expiry and
bounded asset references. Replay advancement and evidence insertion share one
`BEGIN IMMEDIATE` transaction.

Corrections and revocations append lineage instead of rewriting history. Equal
authenticated semantics are idempotent; identity reuse with changed semantics
conflicts. Normal corrections/revocations are issuer principal and role scoped;
only a currently trusted `security` role may perform cross-principal emergency
revocation.

Migration `0013_recovery_frontier_acceptance.sql` records immutable locally
accepted frontier generation/digest/backend identity. An identical retry is
idempotent, semantic drift conflicts and a lower generation is rejected after
restart.

## 4. Recovery-frontier v2

`EvidenceRecoveryFrontierV2` signs and hashes:

1. store identity and strictly monotonic frontier generation;
2. migration set, qualification frontier and AuthBus replay frontier through a
   deterministic ledger root;
3. issuer-trust and signer-registry digests;
4. external backend identity;
5. current build artifact;
6. exact-source plus deterministic-merge qualification receipt set;
7. durable backup-publication receipt;
8. source commit/tree, creation time and signer-policy generation.

Frontier structure validation rejects zero generation, noncanonical Git/digest
identities, ledger-root mismatch, unordered/duplicate signatures and malformed
signature encodings. A deterministic byte-mutation corpus supplements targeted
field-binding tests; any structurally valid mutation must change the frontier
digest.

## 5. External monotonic backend

`LockedFileEvidenceFrontierBackend` is the repository production adapter for a
separately mounted rollback domain with coherent OS locking and durable
filesystem semantics. Bootstrap requires a private canonical root on a
different device from local Agent state and a digest-pinned backend identity.

Each store maps to a private append-only JSONL journal whose records bind audit
sequence, expected generation, complete frontier, frontier digest, prior-record
digest and backend identity. The adapter:

- holds an exclusive OS file lock across read/compare/append/fsync;
- accepts only exact next-generation CAS;
- preflights record-count, per-frame and 64 MiB journal bounds before writing;
- rejects torn or empty frames and any broken hash/generation sequence;
- pins root and journal directory device/inode identity;
- opens directories and files with `O_NOFOLLOW`/`O_CLOEXEC`, rejects hard links
  and enforces owner/private modes;
- returns a durable acknowledgement only after file and directory sync;
- poisons the handle after an uncertain write, forcing operator reconciliation.

The adapter does not claim safety on a filesystem whose lock or sync guarantees
are weaker than this contract. Other backend implementations may be supplied
but must preserve the same authenticated latest/CAS/history/identity semantics.

## 6. Agentd fail-closed production admission

Development composition remains explicit and local. Production mode cannot
fall back to development behavior. Before host attachment it verifies:

1. owner-bound production descriptor and role-distinct external files;
2. canonical external root outside Agent home;
3. current issuer trust and threshold signer policy with revocation/key epochs;
4. exact-source and deterministic merge receipts from the same repository,
   workflow run and attempt;
5. exactly the five governed checks (`evidence-tests`, `agentd-product-test`,
   `lane-a-truth`, `docs`, `implementation-maps`), each with a successful
   command record and retained log digest;
6. exact artifact URL/digest and source/base/merge parent ordering;
7. current executable digest, backend identity and latest frontier freshness;
8. durable backup publication bound to the same snapshot/backend/generation;
9. local SQLite recovery snapshot and ledger root;
10. immutable acceptance of the verified frontier.

External files must be canonical direct children of the private root. They are
opened without following symlinks; file and parent directory identities must
remain stable throughout the read. Missing, stale, malformed, revoked,
unqualified or mismatched evidence returns `kernel.evidence recovery_required`.

## 7. SQLite/runtime hardening

Production preflight is read-only and verifies migration compatibility before a
runtime writer exists. Runtime connections install a SQLite authorizer that
denies attach/detach, schema mutation, writable pragmas and direct mutation of
protected append-only evidence tables. Migration and runtime connections
therefore have distinct authority. Database triggers remain an independent
backstop against qualification-row update/delete.

Fault tests cover transactional insert failure, simulated disk-full behavior,
corrupt reopen, crash after delivery before acknowledgement and stale lease
fencing. The external backend has thread and eight-process publisher contention
tests, requiring exactly one winner per generation.

## 8. Capacity and performance profile

Enforced qualification ceilings include 256 KiB canonical receipt, 64 assets,
256 predecessor edges, 512 query references and 32 required independent roles.
Agentd retains the stricter 48 KiB control-frame bound. Frontier journals are
bounded to 256 KiB per record, 64 MiB total and one million records, with append
rejected before a bound is crossed.

The multi-process contention case is a qualification benchmark, not production
throughput evidence. Activation still requires measured latency, lock
contention, storage growth, backup publication and recovery objectives on the
selected deployment platform.

## 9. Qualification and status pipeline

The dedicated reusable workflow exposes independent steps for evidence tests,
Agentd product tests, Lane-A truth, docs and implementation maps on both the
exact source head and deterministic base/source merge. Commands continue after
failure; each emits JSON plus a raw log, and diagnostics/status artifacts upload
under `if: always()`. A final fail-closed job exposes the stable check name
`Kernel evidence required`; `blocking-ci.yml` incorporates it into `CI required`.
Repository administration must still configure branch protection to require
that fan-in.

`qualification/kernel-evidence/STATUS_SOURCE.json` is the only checked-in state
source. It binds repository capabilities to an exact prior commit/tree and a
closed-world source-path inventory. `scripts/kernel_evidence_status.py`
validates drift and generates status blocks in the technical guide, current
implementation, traceability matrix, this dossier and release dashboard. It
allows persistent qualification to advance only with a workflow run and
artifact digest, and external gates only with candidate-bound authority
receipts.

## 10. Verification and remaining gates

Focused source oracles include qualification/replay/lineage tests,
frontier-v2 signing-domain and mutation tests, backend CAS/audit/identity tests,
threshold signer rotation/revocation tests, production admission receipt and
control-file tests, disk-full/crash tests, stable paging, SQLite authorizer and
multi-process contention.

The current repository does **not** by itself prove:

- that this final source and merge candidate passed all checks;
- that the external backend is deployed in an independent rollback domain;
- that a backup was durably published and restored in a witnessed drill;
- that an independent reviewer accepted the exact candidate;
- that a canary, promotion or release authority approved activation.

Those states remain false in the canonical source until exact external evidence
is recorded. CI cannot self-sign them.

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
