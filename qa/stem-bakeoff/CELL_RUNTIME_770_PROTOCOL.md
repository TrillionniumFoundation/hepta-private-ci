# Frozen local 770D Cell runtime continuation

This additive phase starts from commit
`830bcb15089aaf153e5058968b0b3fd5d1391eed`. It closes concrete serving,
training-scale and durable-publication gaps. It does not replace the completed
prospective-action study or reopen its observed holdout for model selection.
Remote CI is outside this phase.

## Scope and acceptance boundaries

1. Serve the existing 27 Granite clean-field770 neural Heads with their exact
   bounded-prior-mixture calibrators. Validate feature, actual predictor and
   independently supplied calibration-context identities before dispatch.
2. Measure 64, 256 and 1024 resident Cell IDs separately from nine frozen
   states per architecture and **one task**. Exact replicas may share immutable
   serving work. New private learning produces a new state and invalidates old
   calibration. Do not silently share mutable optimizer state.
3. Measure scalar versus microbatched private training on the existing
   seed-7/n32 TRAIN bank, with distinct initial seeds for every Cell. This is an
   engineering equality/cost experiment, not a new learning curve or new task.
4. Persist a small real training queue, exercise abandoned-lease recovery and
   generation fencing, and reload its published Head artifacts in a fresh
   process. Recovery restarts a bounded job from its immutable inputs; it does
   not claim to resume an unsaved intermediate Adam state.
5. Preserve all previous numerical inputs and implementations. New outputs
   remain `SHADOW_ONLY / DENY_ALL`. Numerical parity and resource eligibility do
   not grant task-quality or native-production qualification.

## Fixed inputs and portable bundle

The upstream action preparation is
`learning-preparation/preparations/granite_clean_field770` under the completed
prospective-action root. Its seal SHA256 is
`eebed3e3852a93c8099f60dc86ea1b34368cce8969d8cd88576374c3406bfdb0`.
Its feature identity is
`00b09d213137fd60d33b39761d462f69b6e692155f51b7efd77896911cbd62c0`.
Its independently recorded calibration context is
`9f48b18f003d494771dcfb43637d217a17e23fd7ede348bce8261d540ef089c5`.

Bundle preparation verifies the exact upstream input record, feature report,
feature archive, source bindings and action-preparation inventory. It copies
all nine seed/budget states of each linear, gated and rank-4 residual mode,
their full calibrators and original Head manifests. No state is selected by a
performance score. Training inputs are the original seed-7/n32 baseline bank:
32 distinct training bugs, 16 examples per class, unchanged numeric bytes.
Training source text is represented by its original byte digest and source
record binding; it remains recoverable from the prior complete archive.

Serving inputs are the first 64 original pre-outcome input rows ordered by
SHA256(source_id), with exact source-record bindings and float32 vectors.
The serving selection never reads outcome labels. Batch sizes 1, 16 and 64 use
prefixes of this fixed order. These are known historical inputs used only for
numerical and systems regression. They are not an independent quality set.

The bundle has an external manifest digest, safe relative paths, a complete
file inventory and portable provenance. A caller must supply the expected
manifest digest. An altered bundle cannot bless itself by changing its own
manifest. No Encoder, checkpoint download, new embedding or label acquisition
is required in this phase.

## Serving experiment

- Three modes, three Cell counts, three input batch sizes: 27 conditions.
- Each count cycles the nine frozen states in `(seed, budget)` order. A
  homogeneous cohort has nine unique Head/calibration states and one task.
- Single-thread BLAS; one warm-up per path, seven timed repetitions with
  alternating path order. Report raw samples and descriptive p50/p95.
- Compare all-physical batched evaluation with exact-state reuse and fanout.
  Physical reference weights are actually allocated, not just counted aliases.
  Apply the original bounded calibrator; do not reimplement its probability
  formula. Calibration of repeated states may group equal records in both
  paths, so an intentionally slow per-Cell validation loop is not the baseline.
- Logical versus physical logits/probabilities must be bitwise identical.
  Independent scalar Head logits must meet absolute error <=1e-9 and
  probabilities <=1e-12; no relative tolerance is added. Classification,
  maximum-probability acceptance and positive-action masks must match exactly.
  The masks use threshold 0.7 and remain separate in the API.
- Exercise top-3 routing with fixed source-independent logical scores; report
  served masks and actual computations, without claiming task relevance.
- Exercise warm cache hits, capacity/eviction, contradictory source content,
  stale feature/generation, missing entry, and caller mutation rejection or
  isolation. Unserved probability slots are zero with an explicit false mask.
- A fresh process reloads the portable bundle and reproduces fixed output
  digests for all three modes at 1024 Cell IDs and 64 input rows. This is an
  argument/file allowlist, not an OS security boundary.

No speedup threshold is used to pick an implementation or discard a condition.
Report construction, validation, routing, compute, calibration, scatter,
cache, output allocation and recovery overhead. Report actual owned arrays
separately from serialized metadata and whole-process RSS. A shared CPU timing
sample is not a production latency SLO or isolated capacity measurement.

## Private-gradient experiment

- Modes linear/gated/residual, rank 4; scales 64/256/1024; one task.
- Cell `i` starts with seed `1000000+i`; the two implementations start from
  identical weights, and different Cells have distinct initial states.
- 20 Adam updates per Cell, learning rate .02, L2 .001, existing balanced
  loss and clipping semantics. No tuning, calibration or heldout rows enter
  the optimizer. Reuse the unchanged `NumpyCellHead.train` and
  `MicrobatchCellTrainer` algorithms.
- Microbatch 8, explicit 512 MiB conservative tensor envelope. Include retained
  parameters, two Adam moments, shared bank and the declared workspace bound;
  separately account for caller copies, snapshots and whole-process RSS.
- Scalar and microbatched final parameters and loss must satisfy both atol and
  rtol 1e-10. Report actual maximum errors and bitwise status. This tolerance
  is fixed before executing real conditions and cannot be widened afterward.
- Save every final microbatched parameter array and its digest. Scalar arrays
  are compared in memory and retain their digests; they need not be stored a
  second time. Preserve all failed attempts and their costs.
- Reload saved final tensors in a fresh process and verify deterministic
  first/last Cell predictions on the frozen training feature prefix.

The nine conditions execute 161,280 private optimizer updates across the two
matched implementations (2 * 20 * 3 * (64+256+1024)). They do not establish
1,344 or 4,032 learned tasks, and their losses are training diagnostics only.

## Durable queue experiment

Use the existing persistent queue, with explicit bounded capacity and one
worker. Publish at least one real n32, 20-step Head per mode. Bind all input,
initial-state, feature, task, generation and optimizer identities in the job.
An abandoned lease is reclaimed in a fresh process using a documented injected
logical clock; do not call simulated time a real delayed-service measurement.
Reject the old token and stale generation. Verify final artifact manifests,
tensor digests and predictions after reopening in another process.

Updated Heads are **uncalibrated** until separately fitted calibration binds
their new predictor digest. Old calibrators must reject them. Queue completion
alone cannot turn a raw trained checkpoint into an authorized action policy.

## Closure and costs

Record code/input pins before real execution and verify them afterward.
Keep one append-only stage log; never rewrite a failed observation as success.
All stages include outer wall/parent CPU/child CPU where measured; nested
components are diagnostic breakdowns, not additional totals. Unknown energy,
price, Python metadata size and unmeasured orchestration remain unknown.
Prior Encoder/research costs are referenced as historical, not charged again
as work executed here. Save a self-contained input/output archive, restore it
under a different path, and perform the selected fresh-process regressions.

Local closure requires the actual adapters, complete declared conditions,
fixed parity checks, bounds/fencing tests and portable restore to pass. It
does not close the earlier zero positive-action coverage, absent consistent
gating gain, independent-task diversity, or native-production quality gates.
Those need new predeclared evidence on new data, rather than a renamed test.
