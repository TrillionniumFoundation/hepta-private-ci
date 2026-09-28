
# `learning.operator` admission contract

This document is the canonical entrypoint for candidate state, failure
scope, recovery action, and qualification evidence. It describes the
existing owners; it does not introduce another runtime or authority.

## State progression

| State | Concrete representation | Meaning |
|---|---|---|
| Raw input | `TabularOperatorPlanV1`, `Vec<WorldModelSampleV1>` | Caller data only; no trust or currentness claim. |
| Structurally validated | V2 compatibility wrappers or `ValidatedTabularOperatorV1` | Shape and digest consistency only. This is not production admission. |
| Source authenticated | `VerifiedTabularOperatorPlanV3` / `VerifiedWorldModelDatasetV3` | Opaque, single-use owner borrow; exact frozen source set and signed row semantics verified. |
| Current at use | `fit_*_verified_v3` revalidation | Ledger membership, correction/revocation cuts, trust epoch, expiry, and role separation are checked again immediately before fitting. |
| Immutable candidate | `TabularPayloadPinV2` + `LoadedTabularOperatorV2` | Complete immutable identity, runtime profile, trust snapshot, epoch, and registry head are host-selected; this still does not prove evaluation or selection. |
| Independently evaluated | sealed `learning.eval` receipt and verified selection evidence | Owned by the evaluator/selector; signatures authenticate evidence but do not prove scientific efficacy. |
| Selected read-only | `PinnedCognitiveRanker::load_evaluated` | Agentd binds the independently selected artifact and revalidates registry, trust, revocation, runtime, and authorization on every read. |

`OperatorAdmissionStageV1` names these states. APIs return opaque types
at the applicable boundaries; callers must not reconstruct state from
booleans or caller-authored digests.

## Failure scope and recovery

`ClassifyOperatorAdmissionFailure` maps dataset-binding and payload
failures to `OperatorFailureDispositionV1`.

- Request-local shape, identity, evidence-set, or arithmetic failures:
  correct the request; do not retry unchanged input.
- Candidate-global model, decoder, grid, or persisted-payload failures:
  reject that candidate.
- Expired, revoked, or trust-context evidence:
  obtain fresh owner evidence and repeat admission.
- Payload-pin movement:
  reload an independently selected immutable candidate.
- Unsupported prediction cells:
  abstain for the decision; do not invalidate the entire candidate.
- Owner I/O, clock regression, or authority violation:
  stop the consumer and preserve evidence.

`OwnerDatasetFailureV1` retains the failed owner operation instead of
flattening freeze, record-read, snapshot, and canonical-payload errors
into one unstructured string.

## Capacity

The compatibility fitter can represent up to 1,000,000 rows and
262,144 cells. The owner-authenticated V3 signing path is deliberately
narrower: at most `MAX_SIGNED_OPERATOR_ROWS = 4096` rows and frozen
source records.

A signed tabular profile must satisfy, before allocation or sorting:

```text
sensor_count × action_count × minimum_samples_per_cell ≤ 4096
```

The other hard limits remain 4,096 sensors, 128 actions, and 64 MiB
persisted payload bytes.

## Performance evidence

Run the explicit end-to-end qualification-core profile:

```bash
cargo test --locked -p codex-hepta-bellman-operator \
  full_v3_qualification_path_profile -- --ignored --nocapture
```

It records dataset freeze, row canonicalization/signing, owner
admission, fit-time revalidation, encoding, create-only persistence,
reload, first prediction, total wall time, payload bytes, and process
peak RSS. These measurements are candidate/host observations, not
acceptance or future-window efficacy evidence.
