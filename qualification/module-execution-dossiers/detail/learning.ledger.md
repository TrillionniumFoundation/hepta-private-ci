# learning.ledger: implementation design

Parent: `docs/modules/learning.ledger/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: additive native source implementation candidate; current exact-head and
synthetic-merge CI determine source qualification. Product execution,
independent acceptance, activation, promotion and release remain separate.
Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`.
Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Root: `codex-rs/hepta-learning-ledger`.
Packages: `LRN-0-CAUSAL-LEARNING-CONTRACTS`, `LRN-1-DURABLE-EPISODE-LEDGER`.

Concrete source mappings are recorded in
`../../../codex-rs/hepta-learning-ledger/NATIVE_MAPPING.md` and the Lane E
implementation matrix. Preserve the existing store and execution spine; do not
create a parallel causal ledger.

## 2. Public operations and contract details

Design operations remain `append_decision`, `append_outcome`,
`append_correction_or_revoke` and `freeze_dataset`. Stable V1 event and durable
encoding remains readable. Additive native surfaces now include:

- `LearningEvidenceVerifierV1` and `verify_signed_role_separation` for host-owned
  Ed25519 trust admission;
- `verify_independent_roles`, `validate_authenticated_outcome`,
  `validate_candidate_set_completeness`, `finalize_credit_batch` and
  `freeze_dataset` for V2 causal semantics;
- `LedgerWitnessStore` plus `WitnessedLearningLedger` /
  `AcknowledgedLearningJournal` for sync-before-ack witness gating;
- atomic `append_batch` on both durable backends;
- `append_conserved_credit_batch_v1` for conservation-to-durable-commit binding;
- `freeze_dataset_from_ledger_v3` for ledger-derived dataset membership;
- `DatasetSnapshotReceiptV3` for independently recomputable dataset identity.

V1 records are never automatically relabelled V2. Raw durable journal APIs are
recovery/maintenance surfaces; source-level product composition should use the
acknowledged port when returning durable success.

## 3. State records and transaction design

The module owns `learning_episode_ledger`, `learning_credit_ledger` and
`learning_unlearning_lineage`. Decision rows bind objective, policy, complete
candidate set, chosen action and propensity. Outcome rows bind an observer and
terminality. Credit rows bind episode/outcome/artifact allocation. Revocation is
append-only and excludes affected causal descendants from active projections.

`AuthenticatedPrincipalV1` binds principal, credential-chain digest, signing-key
digest, scope, authority epoch and validity window. `LearningEvidenceVerifierV1`
adds host-owned trust context, Ed25519 signature verification, role admission,
revocation and payload binding. Cryptographic admission authenticates an
attestation; it does not prove scientific truth or organizational independence.

A witnessed single append performs causal validation, predecessor check, frame
write, journal `sync_all`, in-memory publication, independent witness append and
witness `sync_all` before returning success. An atomic batch validates the whole
ordered suffix against a cloned core and verifies capacity before writing,
performs one contiguous durable write/sync, publishes the complete staged core,
then advances the witness to the batch terminal head.

`append_conserved_credit_batch_v1` additionally derives the actual active
terminal outcome value from the acknowledged ledger, validates V2 conservation,
builds deterministic per-target V1 credit identities and atomically persists the
whole allocation set with the V2 batch digest as support lineage.

## 4. Recovery, witness and retry

`DurableLedger` retains HEPTLR01 framing; `SegmentedLedger` retains HEPTLS02
rotation/sealing. A raw recovered journal may contain a valid complete suffix
beyond the last external acknowledgement after acknowledgement loss.

`LedgerWitnessStore` is a separate append-only monotonic witness capability.
`WitnessedLearningLedger::attach` rejects a non-empty journal when the witness is
empty, validates any non-empty witness as an exact prefix of recovered history,
and may reconcile a longer canonical suffix by advancing the witness before the
consumer is exposed. A mismatched or later witness fails closed.

A separate witness file is source support for independence, not proof of an
independent operational failure domain. Production qualification must prove
separate administration/rollback scope, parent-directory durability, backup and
restore isolation and current authenticated ownership.

## 5. Dataset freeze and lineage

The compatibility `freeze_dataset` API still accepts an already prepared V2
request. The strict source-composition path is `freeze_dataset_from_ledger_v3`:
it replays the supplied authoritative snapshot, derives the actual head,
frontier, active objective membership, relevant revocation cut and pending V1
outcome count, then emits a self-verifying V3 receipt. The caller cannot provide
a replacement source-record list or ledger head on this path.

V1 does not represent censored outcome state, so the strict V1 compatibility
path does not fabricate censoring facts. Full delayed/censored outcome semantics
remain bound to authenticated V2 evidence and the product host's observation
watermark.

Logical revocation and dataset exclusion do not physically erase historical
journal bytes, backups, already distributed artifacts or trained model weights.
Physical erasure and model unlearning remain separate externally evidenced
capabilities.

## 6. Capacity and performance profile

Existing bounded limits remain authoritative: the V1 file profile is bounded,
segmented history is bounded and the pure core retains a bounded complete
history in memory. Atomic batches do not add compaction or constant-time
recovery. Target-host latency, throughput, disk-full behavior, power-loss
semantics and long-history resource measurements remain qualification evidence,
not source claims.

## 7. Concrete verification cases

Existing cases remain required:

- LEDGER-01: acknowledgement loss reconciles the committed event from its
  original identity and anchor;
- LEDGER-02: truncating acknowledged history fails anchored recovery;
- LEDGER-03: generator posing as an independent observer is rejected by real
  host authentication, not string comparison;
- LEDGER-04: delayed/corrected outcomes and revoked ancestry change dataset
  eligibility without rewriting history.

Additional owner-crate cases exercise witness persistence/recovery, refusal to
promote non-empty unwitnessed history, witnessed lost-ack reconciliation,
terminal-head batch witnessing, durable conserved-credit publication and
ledger-derived dataset membership. These tests are source identities until the
exact-candidate workflow records their execution.

## 8. Current native implementation

- **Durable state:** `DurableLedger` and `SegmentedLedger` retain the original
  causal chain and bounded persistence formats; both now expose an atomic
  ordered-batch commit surface.
- **Acknowledgement frontier:** `LedgerWitnessStore` persists a checksum-bound
  monotonic anchor history in a host-supplied independent file capability.
  `WitnessedLearningLedger` seals this to the consumer-facing
  `AcknowledgedLearningJournal` port.
- **Evidence admission:** `LearningEvidenceVerifierV1` verifies host-owned trust
  context, Ed25519 signatures, roles, validity, revocation and payload digests.
- **Credit closure:** `append_conserved_credit_batch_v1` binds V2 exact
  conservation to actual terminal ledger state and one witnessed durable batch.
- **Dataset closure:** `freeze_dataset_from_ledger_v3` derives membership and
  logical revocation state from replayed ledger history before emitting a
  self-verifying V3 receipt.
- **Operating references:** `DURABLE.md`, `LOCK_OWNERSHIP.md`, `INSPECTION.md`
  and `NATIVE_MAPPING.md` in the owner crate.

## 9. Native closure and remaining evidence

Repository-controlled source verification is performed by
`../../../scripts/hepta-lane-e-closure.py` and
`.github/workflows/hepta-lane-e-gap-closure.yml`. The Lane E workflow compiles
and tests owner crates, executes the cross-crate causal chain, applies strict
Clippy/rustfmt and, for pull requests, checks an ordered-parent synthetic merge.
A push does not fabricate a PR base identity.

The source candidate still cannot self-issue the following product evidence:

- the name and identity of a live production caller using the acknowledged port;
- the production trust-root/signer distribution and operational rotation path;
- proof that the physical ledger writer, witness and their directories are
  exclusively owned and independently durable on the target host;
- live independent terminal outcomes and future-calendar evidence;
- target-host crash, power-loss, disk-full, latency, throughput and restore
  measurements;
- physical erasure / backup purge / model-weight unlearning evidence;
- independent semantic acceptance, canary, selection, promotion or release.

Those gates remain fail-closed until the responsible external owners issue
immutable receipts for the exact candidate. Source completion is not activation.
