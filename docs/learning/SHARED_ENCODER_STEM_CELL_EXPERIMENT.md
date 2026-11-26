# Shared Encoder “Stem Cell” Selection: E0–E4 Gate

Status: experiment-only; **no model selection, release authority, or physical Cell split**.
Base audited: `main@78fdb0cf8537e3a84fc6e0a849707559c80881e8` (2026-10-14 inspection).

## Hypothesis and scope

Compare one shared, frozen text Encoder and per-Cell trainable light gated heads against duplicated 421M-parameter model weights **and** against an already-shared 421M baseline. Neither independent duplicated weights nor 421M deployed topology may be assumed without runtime evidence. The winning Encoder is the one that yields the greatest **future-window incremental utility under constrained memory, compute, calibration and negative transfer**, not the highest embedding retrieval score.

Candidate arms to resolve to immutable model revisions, weights, tokenizer, preprocessing, pooling and inference backend before running:
- `mmbert-small`: generic multilingual/token-level representation candidate.
- `granite-embedding-97m-r2`: compact retrieval-oriented candidate; evaluate task-head suitability too.
- `modernbert-base`: 768-dimensional compatibility/control candidate. Requires separately versioned <=512-dimensional projection; never silently truncate.
- `deployed-421m`: real measured deployment/teacher; do not assume a separate model copy per Cell.
- `no-change`: frozen existing system, including existing route, encoder and head, at the same prediction timestamps.

Published parameter counts, dimensions and model descriptions are *selection hypotheses*, not deployed resource receipts or proof of quality. Record exact revision and license before acquiring weights.

## E0: real runtime baseline (hard prerequisite)

Required evidence per run: source commit; machine/device identity; model and tokenizer manifest digests; weights and preprocessing digests; backend/runtime revision; precision and quantization; Q24 normalization/profile; observed active parameter count; resident/shared/private bytes; transient peak; CPU/GPU time; p50/p95/p99; throughput; queueing; checkpoint/WAL bytes; NDU version; timestamped future evaluation window; actual invocation and execution receipts. Absence of any required observation is `INCOMPLETE`, not zero and not a passed benchmark.

## E1–E2: representation and adaptation

- Freeze all Encoder weights. Allow only a strictly bounded, per-Cell low-rank/gated Head and Q24 private state to update; enumerate *all* head weights, calibration parameters and optimizer/checkpoint bytes.
- Compare ranks 2, 8, 16 under both equal-step and equal-total-training-FLOP conditions; if head totals differ, record both and introduce matched-parameter controls.
- Hold raw events, labels and label availability timestamps fixed. Measure tokenizer output lengths and truncation fractions by arm, then report normalized cost and matched-token windows.
- Use sealed chronological train/validation/future-test splits, including environment changes, recurring old tasks and OOD. No future-test labels for selection/training, no same-example embedding leakage across splits.
- Ablate sentence pooling vs selected token/latent slots, full BF16 feature vs deterministic normalized Q24, and frozen Head vs continuously learned Head vs split/merge/distill.
- Run at least three fixed seeds. Report confidence intervals and paired utility deltas, calibration ECE, OOD false accepts, negative transfer on preexisting tasks and learning-curve area. An empty test set or missing baseline is a hard reject.

## E3: data plane and authority constraints

Current contracts have `MAX_INPUT_FEATURES = 512` in `hepta-neuron/src/runtime_types.rs` and `MAX_FEATURES = 512` in `hepta-infer-core/src/neuron_feature.rs`; `NeuronFeatureRequestV1.feature_vector_q24: Vec<i64>`, with a clone in `hepta-neuron/src/inference_control.rs`. Therefore **no zero-copy execution claim** is valid yet.

Prototype a new opt-in shared `FeatureSnapshotRef` carrying feature content digest, frozen encoder/tokenizer/preprocessor/normalizer/quantizer digests, generation, authorization scope, feature shape, read-only buffer identity and lifecycle lease. Content digest alone confers no authority. Bind first use and final use to scope/generation/fence; reject stale refs, mismatched shape and wrong decoder generation. Keep existing V1 request wire semantics for replay compatibility. Benchmark actual copies, allocations, caching invalidation and batch dispatch, not just internal pointer reuse.

## E4: scale and deployment

Measure 64, 256, 1024, 4096 Cells on **target hosts** with fixed real arrival rates, Top-K distribution and representative sequences, at cold and warm cache, including recovery, WAL and backpressure. Partition Encoder/Head/route CPU, GPU, RSS and latency. Never extrapolate a 4096-Cell production pass solely from theoretical weight storage.

## Decision rule

1. Reject if evidence missing, timeline contaminated, signatures/authority/fence invalid, calibration/OOD regressions over predefined limits, or p99/memory exceeds device caps.
2. Compare frozen no-change utility on exactly the same future windows. Require positive paired lower confidence bound for NDU net benefit after resource cost and negative transfer.
3. Among survivors choose a Pareto-optimal model on future utility, total p99 latency, transient and resident bytes, active compute and operational complexity. No winner can be named solely from model-card metrics.
4. Evaluator issues read-only scored report; Selector produces an independently reviewable decision; Executor alone may stage a signed artifact and execute CAS / child migration / CNS route cutover / supervisor generation fence, with durable receipts and recovery. Selection does not itself promote.
5. Keep existing 421M deployment as measured control/teacher/backstop until the replacement passes all gates.

## Required report schema

One record per arm × seed × future-window:
`{experiment_id, arm_id, model_revision, source_commit, hardware_id, seed, train_cutoff, prediction_commit_time, label_available_after, future_window_id, n_examples, no_change_utility, candidate_utility, paired_delta, ci_lower, ci_upper, negative_transfer, ece, ood_false_accept_rate, shared_resident_bytes, per_cell_resident_bytes, transient_peak_bytes, tokens_encoded, batch_size, throughput_per_s, p50_us, p95_us, p99_us, checkpoint_bytes, verified_runtime_receipt_id, artifact_manifest_digest, authority_fence, status}`.

Status `PASS` requires actual witnessed runtime receipts, not syntactically valid digests. Non-ready/incomplete results must remain clearly marked `INCOMPLETE` or `REJECTED`. No model downloads, eval dataset changes, production cutovers or promotion authorized by this document.
