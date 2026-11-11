# Original Dataset → Q24 projection V1

This component connects original task inputs and authenticated ledger targets to the existing native Q24 trainer. It does not complete the ordinary learning → evaluation → selection → FinalUse loop.

## Authority and current integration boundary

The host must supply the original source reader, the original committed Cell owner, the original `LedgerWriter`, and its existing signed Dataset freeze. No key, enrollment, file authority, source writer, Model publisher, selector, or Root scope is created here. `CellQ24DatasetTaskV1::capture` and `CellQ24TrainingBatchV1::from_original_dataset` still need installation by the authorized ordinary host/StageOwner. Their closed product caller sets remain empty.

The existing native training plan and durable trainer now consume the retained provenance capability: they revalidate it before admission, before returning Candidate or NoUpdate, before durable completion, and during recovery/readback. Cloning a batch retains the same original source and ledger readers. The legacy vector constructor emits only HQ24T001; the new constructor emits HQ24T002, and its digest is included in the optimizer and frozen update rule. Copying encoded bytes cannot create the private capability.

## Frozen ordering and exact mapping

Freeze the inherited inclusion policy plus this versioned projection first; obtain the original signed Dataset freeze; materialize the batch; calculate SGD(batch) and the single-head update rule; then obtain the original Root frozen training scope. The adapter cannot modify or retroactively re-freeze an already registered scope. This ordering avoids a scope/batch digest cycle.

| Ledger field | Required original binding |
| --- | --- |
| decision.record_id | The sealed task's run ID |
| decision.run_snapshot_digest | `cell_q24_dataset_run_snapshot_digest_v1`, hashing every field of the sealed RunStartSnapshot under its own versioned domain |
| decision.policy_digest | Digest of the original source's exact policy output |
| decision.support_digest and outcome.support_digest | The original source publication digest |
| candidate IDs and selected candidate | The actual committed Cell receipt |
| source/model | The original publication and committed Cell definition equal the projection's baseline bundle; RunStart artifact-set identity remains a separate retained field |
| outcome target | The authenticated Terminal outcome for that same decision episode, in the exact frozen unit profile |

This new snapshot convention is explicitly part of the projection. Existing ledger producers using another convention require an explicitly registered compatible projection; a Cell request digest is not a RunStartSnapshot identity. Wiring the ordinary production decision writer and complete StageOwner remains follow-up work.

The original Cell selector is deterministic: it traverses allowed candidates in canonical order and changes selection only for a strictly larger positive score, with deterministic abstention for calibration/resource/deadline failures. The emitted policy is one-hot. The adapter checks that exact policy and requires propensity ONE. Source: [fixed selector implementation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be8adcbb5e9925f72e05330b8fb30509cba4544b/codex-rs/hepta-neuron/src/cell.rs) and [late settlement](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/be8adcbb5e9925f72e05330b8fb30509cba4544b/codex-rs/hepta-neuron/src/cell_types.rs).

## Bounded materialization and failures

The first projection accepts 1–256 rows, width 1–64, at most 512 selected ledger facts, and at most 4,096 original ledger records. Rows follow decision sequence, independent of source-hash order or the order of supplied typed handles. It requires exactly one uncorrected Terminal outcome per original decision. Duplicate tasks/outcomes, Pending, Censored, missing values, superseded sources, unsupported facts, wrong units, and out-of-range raw targets fail explicitly.

Inputs are decoded from the original sealed HQ24I001 observation; caller vectors and supplied labels do not enter this path. Signed Q32 targets must lie within [-8, 8] before conversion and are divided by 256 toward zero to Q24, with no clipping or imputation. For example, raw -257 becomes -1 and raw -255 becomes 0; a missing target never becomes zero.

Materialization authenticates the frozen Dataset signature, reconstructs its full receipt from an exact prefix of the original ledger, and checks current source availability. Before returning, it re-reads the source and the original ledger frontier, snapshot, and selected events, then re-verifies current Dataset authorization. The process mutex does not substitute for the owners' independent currentness/witness contracts.

Historical RunStart execution expiry does not revoke completed experience. Reuse depends on the current Dataset authorization and original source withdrawal/witness checks; training separately enforces its current compute deadline. Expired authorization or changed evidence is an error. Once a durable training claim exists, a failure leaves that operation unresolved; it never becomes a NoUpdate result. NoUpdate remains the actual quantized unchanged-parent outcome.

## Verification and acceptance limits

The focused native tests exercise real ordinary task execution, original source/Cell readback, signed ledger decisions/outcomes/freezes, native training and candidate load, unchanged-parent NoUpdate, recovered trainer guard retention, signed wrong-unit targets, negative conversion, forged/expired freezes, row order, corrections, and original source withdrawal. Issuers, stage credential metadata, and CURRENT custody in these tests are explicit engineering fixtures.

Run the source caller scan and the scoped native suite from the exact candidate checkout. Recorded job status, source SHA/tree, test counts, and transport failures belong to that candidate's verification evidence. This document does not assert a completed ordinary chain, independently authorized B evaluation, real publication/withdrawal/FinalUse acceptance, or daemon/Root process restart recovery.
