# memory.retrieval policy reference

## Policy ownership and admission

A production policy is protected host configuration, not a per-request choice. Its digest belongs to the coherent Lane C generation vector. Changes require a complete authenticated context rotation and fresh qualification.

`channel_weights` must have unique valid channels and bounded non-negative weights. A zero weight disables semantic contribution and cannot satisfy coverage, but does not excuse malformed or over-capacity raw input. `maximum_candidates` is a hard per-channel bound. `maximum_results` bounds the final output. `minimum_total_score` defines score admission. `minimum_distinct_channels` counts positive-weight admitted evidence. OOD and contradiction decisions must operate on admitted evidence rather than arbitrary low-score additions.

`maximum_ood` is a policy bound, not evidence that a calibrated OOD estimator exists. The current SQLite adapter supplies zero OOD and the baseline policy allows maximum OOD one, score floor zero and one-channel coverage. That is an owner-compatible ranking baseline, not calibrated production safety. Do not convert 'missing OOD estimate' to a calibrated zero-risk claim.

## HNMF dynamics

`minimum_activation` is strictly in `(0, 1]`; zero activation never counts as active support. `leak` and `lateral_inhibition` are bounded in `[0, 1]`. Zero-weight synapses must not expand semantic support, alter activation or create contradiction evidence. Active confidence is the checked fixed-point ratio `sum(activation * confidence) / sum(activation)`, with explicit zero-denominator handling. Node, edge, hop, step, population and active-node bounds are hard limits.

Receipt counts and bounds must be checked against the same enumeration/admission scope. Input permutation must preserve canonical decisions. Adding a below-admission candidate must not remove an admitted high-score result unless separate admitted safety evidence justifies that change. Zero-weight edges may change the full snapshot identity but must not change selected content or the semantic disposition.

## Contradiction semantics and migration blocker

The intended evidence key includes an owner-defined proposition digest, scope/time identity, explicit stance and source/generation binding. Opposite stances on the same proposition constitute a conflict; same-side corroboration does not. Duplicate channels are retrieval observations, not independent truth assertions. A record reporting a contradiction is not automatically an assertion of the negative side of every proposition it mentions.

The current Rust accessor names are `Supports` and `Opposes`. They are still derived from `RetrievalChannelV1`, not carried as explicit owner facts in the native candidate/union payload. That compatibility implementation remains insufficient. Do not claim the explicit evidence migration is finished until owner metadata, aggregation, canonical digest/validation, final selection and cross-channel regression tests all preserve the actual proposition/stance pair.

## Vector candidate contract

The bounded vector snapshot binds generation-vector digest, owner generation, model digest, dimension, exact record/revision/content and supplied OOD values. Queries must match the model and generation, use bounded fixed-point components and remain within candidate limits. The current normalized-L1 implementation is a deterministic precomputed-vector baseline, not a text-encoding model or an ANN deployment. The encoder/tokenizer/preprocessor provenance and calibrated OOD estimator must be independently composed and qualified before promotion.

## Product modes

| Mode | Required behavior | Current implementation boundary |
| --- | --- | --- |
| compatibility | Preserve owner-ranked delivery | Existing process selector |
| shadow | Execute candidate path; deliver compatibility only; retain paired receipts | Runtime dispatch not completed |
| canary | Authenticated deterministic cohort; candidate delivery only inside cohort; retain comparison | Runtime dispatch and rollout controller not completed |
| required | Require a current authenticated context; fail closed on absence, expiry or mismatch | Existing `hnmf-required` selector plus explicit host composition |

Do not pass `shadow`, `canary` or `required` as invented environment aliases. The current selector accepts `compatibility` and `hnmf-required`; other values fail validation.

## Calibration and approval

Freeze a new policy digest and predeclared thresholds before collecting the acceptance sample. Retain domain/shift partitions, calibration error, false acceptance, false abstention and source-independence limitations. Match baseline and candidate host/workload identities. Require current-head tests, reviewed evidence, canary comparison and rollback rehearsal. Never tune thresholds on the acceptance sample and then relabel that same sample an independent pass.
