# `learning.ledger` production convergence

This document records the repository-controlled convergence candidate for the
append-only causal learning ledger. It supplements `DURABLE.md`, `INSPECTION.md`,
`NATIVE_MAPPING.md` and the module guide. It does **not** claim a deployed
production caller, a real production trust root, target-host durability,
independent semantic acceptance, promotion or release.

## Status dimensions

The following dimensions are intentionally independent:

| Dimension | Candidate state |
| --- | --- |
| Work-package planning | `LRN-0` and `LRN-1` remain governed by the canonical package registry |
| Source implementation | convergence source candidate present in `codex-rs/hepta-learning-ledger` |
| Product composition | not established by this source change |
| Production writer | `LedgerWriter` implementation candidate exists; no product host is claimed |
| Qualification | exact-head / synthetic-merge CI must pass for the exact commit |
| Trust deployment | pinned-root mechanism exists; no real root private key or signer distribution is issued here |
| Durability qualification | local file semantics only; target filesystem/power-loss qualification remains external |
| Activation/release | unchanged and external |

## P0 — one strong product write boundary

`LedgerWriter<J>` is the intended production-facing write boundary. It owns:

- a sealed durable learning journal (`DurableLedger` or `SegmentedLedger`);
- one immutable `LearningEvidenceVerifierV1` trust snapshot;
- one independently persisted `IndependentLedgerWitness` acknowledgement chain.

The writer commits only against the independently witnessed predecessor. A
journal suffix that is not yet witnessed blocks new writes; the only permitted
operation is an exact replay of the next unwitnessed event so lost
acknowledgement can be reconciled. The writer acknowledges externally only after
the ledger append and witness append have both synchronized.

The legacy V1 append APIs remain readable and usable by compatibility/qualification
callers. Once an episode is created through `DecisionV2`, the core itself rejects
legacy V1 Outcome and Credit events for that episode (`WeakV1WriteDenied`). This
prevents a product caller from authenticating a decision and then silently
falling back to the weaker outcome/credit semantics.

### Authenticated decisions

`DecisionV2` durably binds generator credential-chain digest, signing-key digest,
controller identity, scope, authority epoch, exact candidate-set digest and the
signed evidence digest. Product admission requires:

- a current root-derived Generator signer;
- exact objective and scope binding;
- complete candidate set with `omitted_count_bound == 0`;
- exact candidate count and canonical candidate digest;
- positive selected propensity and explicit abstain inherited from V1.

### Correction graph

`OutcomeV2` is an append-only outcome revision. The core enforces:

- predecessor existence;
- predecessor belongs to the same episode;
- predecessor is the current episode outcome head;
- a first observation cannot name a predecessor;
- a later observation must name the current head;
- revoked predecessors cannot be corrected.

Because every correction must extend the single current head, forks and cycles
are structurally rejected without rewriting history.

### Conserved credit batch

`CreditBatchV2` is one durable event containing the full allocation vector. The
writer first runs `finalize_credit_batch`; the core repeats the critical
invariants against durable state:

- terminal authenticated outcome must exist;
- batch terminal value must equal the durable terminal outcome value;
- allocator must be independent from generator and observer by principal,
  credential chain, signing key and controller;
- target IDs are canonical and unique;
- no target has already received credit for the same episode/outcome;
- `sum(allocations) + residual == terminal_outcome` exactly in Q32 raw units.

No partial durable allocation rows are emitted by the product write boundary.

### Dataset freeze derived from the ledger

`LedgerWriter::prepare_dataset_freeze` accepts only snapshot identity, producer
and inclusion-policy digest. It does **not** accept caller supplied source rows,
correction cut or revocation cut. From the exact fully witnessed ledger snapshot
it derives:

- exact ledger head and eligible frontier;
- active source record digests;
- delayed-outcome watermark;
- pending and censored counts;
- correction cut from durable correction events;
- revocation cut from durable revocation/unlearning events.

`freeze_dataset_from_ledger` recomputes the plan before publication, rejects a
stale plan, authenticates the producer and emits the existing self-verifying
`DatasetSnapshotReceiptV3`.

## P1 — explicit unlearning and trust lineage

### Unlearning lineage

`UnlearningV1` is an authoritative append-only lineage event with:

- independently authenticated revocation authority;
- scope and authority epoch;
- reason and evidence digests;
- canonical source-record IDs;
- dataset IDs to invalidate;
- artifact IDs to invalidate;
- exact predecessor lineage ID for the scope.

The source records become causally inactive without deleting the audit bytes.
The in-memory projection exposes `dataset_is_invalidated` and
`artifact_is_invalidated` so downstream owners can reject derived state. This is
logical non-resurrection lineage, not a claim that remote backups or trained
model parameters have been physically erased.

### Pinned trust root and signer distribution

`LearningTrustRootV1` is host supplied out of band. A remote or repository
manifest cannot replace its root ID/key, scope or objective. A
`SignedLearningTrustManifestV1` contains the complete signer distribution,
authority epoch, generation, predecessor manifest digest and validity window.
`verify_learning_trust_manifest` verifies the root signature before constructing
`LearningEvidenceVerifierV1`.

Manifest rotation is strictly generation ordered and predecessor-bound. Epochs
cannot roll back. The repository deliberately contains no production root
private key and issues no production signer distribution.

### Independent acknowledgement witness

`IndependentLedgerWitness` has its own file, binding, lock and append-only digest
chain (`HEPTLW01`). It stores the minimum externally acknowledged ledger
frontier. It is never derived from the suspect ledger during recovery. Skipped
frontiers fail closed.

## Canonical protocol adapters

The crate exports the canonical registry names:

- `LearningDecisionV1`;
- `OutcomeReceiptV1`;
- `CreditAssignmentReceiptV1`;
- `LearningEpisodeV1`;
- `DatasetSnapshotV1`.

These adapters mirror registry field order, use strict serde decoding with
unknown fields denied, apply the registry 256 KiB wire bound and provide
canonical JSON byte encoding. Native conversion functions make every semantic
loss explicit; for example an `OutcomeReceiptV1` can only be emitted for a
terminal observed outcome.

## P2 — checkpoint/index and long-history verification

`LedgerIndexCheckpointV1` is a rebuildable, digest-bound index checkpoint over an
exact `LedgerSnapshot`. It binds:

- sequence/head digest;
- total and active record counts;
- per-kind counts;
- canonical active-set digest;
- checkpoint digest.

`verify_index_checkpoint` rebuilds from authoritative history and requires exact
identity. Checkpoints are acceleration/integrity artifacts, never a replacement
for the append-only history or the external acknowledgement witness.

The convergence regression suite rebuilds and verifies a 10,000-record history.
Existing segmented-ledger tests continue to exercise segment rotation, sealing,
recovery and histories beyond the V1 single-file limit. These deterministic
regressions are capacity evidence, not target-host latency or power-loss
measurements.

## Failure and recovery boundary

A successful production write has the order:

```text
verify signed evidence
-> validate durable state invariants
-> compare exact witnessed predecessor
-> append and sync ledger event
-> append and sync independent witness
-> publish acknowledgement
```

If ledger sync is uncertain, existing durable poisoning/recovery applies. If the
ledger succeeds and witness persistence fails, `LedgerWriter` poisons itself.
Recovery reopens both stores; the old witness then permits only exact replay of
the next unwitnessed ledger event before any new mutation.

## Remaining external gates

This source candidate cannot self-issue:

- a named production process/callsite using `LedgerWriter` exclusively;
- a real out-of-band root key and current signed signer manifest;
- durable directory ownership and target-filesystem power-loss qualification;
- live independent outcome sources;
- production latency/storage/recovery measurements;
- downstream dataset/artifact physical deletion receipts;
- independent semantic acceptance, canary, selection, promotion or release.

Those facts must remain false/open until their responsible external owners issue
evidence for the exact candidate.
