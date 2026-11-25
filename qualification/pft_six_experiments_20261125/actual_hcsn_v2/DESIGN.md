# Actual SmallHCSN v2: frozen experiment design

## Purpose and identity

This study closes the identifiable implementation and comparison gaps in the prior actual SmallHCSN appendix. It diagnoses feature scale and optimization on train/dev data, then evaluates newly initialized real probability/content models under a common protocol. It does not reuse the old test data or inherit old qualification.

The actual physical kernels remain those in runtime_capsule.tar.gz with SHA256
`7ebe8aed55ce2e209f8be5dd016b4b13a8bb3fe6243b918d9648dd9a7114fe96`.

The initial single-worker formal protocol was independently committed before training at
`d1461abdf87fe8f5059670c7a99fac552fac58d8`. It was superseded, without running formal training or test, by the four-process revision.

The executed protocol is FORMAL_PROTOCOL_v2.json, SHA256
`aad9b709d3ee6a32597487f5ae1eb2c1fc490f74d05320c4d32349fe7f09e7b8`,
published with all five frozen source files at Git commit
`221c4fb6a6ece0fba3d0052a66c9beeca7d1dcd3`.

A separate complete candidate seal is required after all training attempts terminate and before the independent test evaluator can generate labels.

## What the diagnosis established

The diagnosis used new source IDs and only train/dev splits. It measured all five feature groups, centered singular values, effective rank, parameter gradients, drive saturation and the fixed message mask.

At a fixed ridge coefficient equivalent to the old objective, changing only train-fitted feature scaling raised old-parent value/risk dev accuracy:

| Parent | Raw features | Train-standardized features |
| --- | ---: | ---: |
| N16 | 43.750% | 73.438% |
| N64 | 42.188% | 64.063% |

These are new diagnostic dev observations, not rescored old test results. They show that the low score cannot be interpreted as an absence of information in the physical representation. The stronger claim that all deficits were caused by scale is not established.

The raw objective uses a centered design and an unpenalized intercept. A coefficient of .02 in X-transpose-X/n is equivalent to the previous .01 coefficient in X-transpose-X/(2n). This is the same mathematical penalty scaling, not a claim of identical floating-point execution.

The N16 fresh-model finite-difference checks covered raw_cost, input_drive, recurrent and readout parameters. Maximum absolute gradient error was 3.063e-11; maximum relative error was 1.272e-7. The tested fresh initializations had no abs(drive)>3 saturation and zero forbidden sender-from-receiver mask entries.

Feature covariance was highly ill-conditioned. The training-only scaler centers each column and divides by max(training standard deviation, 1e-6). Mean, scale and intercept are fitted only on the relevant training subset and are frozen for dev/test.

Four candidate ridge coefficients were compared on all eight fresh diagnostic width/bank arms. The single coefficient minimizing their mean dev cross entropy was 1e-6; that same coefficient is used in every formal arm. There is no per-arm test-based coefficient selection.

## Pilot and optimization budget

The train/dev pilot tested two physical learning rates over four widths and two feature banks. Twelve arms completed 96 updates; four N64 arms were censored by the pilot's 30 CPU-second limit. Those censored outcomes are retained. Across the pilot, every selected checkpoint was at or before step 64.

The global physical learning rate selected from mean dev cross entropy was 1e-5. The formal study retains 96 updates and raises the optimization budgets to 90 CPU seconds and 240 wall seconds per arm. Hitting either limit is recorded as CENSORED_BUDGET, never as completion of all 96 updates. An atomic update may slightly exceed a limit and its overrun is recorded.

The final-decision cross entropy is optimized. The head learning rate is .001, gradient clipping is 1, and each minibatch contains eight episodes. The initial standardized ridge head is eligible for dev selection; a BP checkpoint is adopted only when its dev final-step cross entropy improves. The original model's earlier multi-time cross entropy objective was not itself label leakage; this study chooses a final-decision objective consistently for all formal arms.

Reaching the update budget does not assert mathematical convergence. Selection histories and last-state weights are preserved, including cases whose best dev checkpoint is initialization or the final budget step.

## Formal factorial and sample-efficiency groups

All physical parameters are initialized afresh with the same mechanism. No old trained parent is used. All arms use the dense backend and float64 physical/model precision.

| Factor | Values |
| --- | --- |
| Width | 8, 16, 32, 64 |
| Initialization seed | 2101, 2102, 2103 |
| Readout feature bank | value/risk, ordinary tanh replacement |
| Message channels | boundary, flow, full |
| Recurrent connection weights | learned, fixed |
| Main training examples | 64 |
| Updates | at most 96, with the same CPU/wall envelope |

The full factorial has 144 arms. A further 24 arms use nested 16- and 32-example training subsets at widths 16 and 32, both feature banks, full messages and learned recurrent weights. Their 64-example partners are reused from the main factorial. This gives actual independently trained 16/32/64-label comparisons; all labels used for the initial ridge fit are counted.

The initial physical tensor hash must be identical for every arm sharing width and seed. Allocated parameter count varies with width. Freezing recurrent weights intentionally changes the number of trainable coordinates. Active mask entries and actual selected/last updated parameter elements are recorded instead of pretending these counts are equal.

The mask topology remains fixed. “Learned connections” means learning permitted recurrent weight values on that fixed mask, not discovering graph topology. Input projections, local cost parameters and the readout may still train in the fixed-recurrent arm.

Boundary/flow/full are communication-channel ablations. The local QVI boundary law remains active in all arms. These are not a comparison of different boundary solvers.

The ordinary bank replaces only value/risk readout features with tanh(drive) and tanh(raw_mark), retaining equal feature dimension and the same physical model family. It is not a separate conventional RNN. Before optimization, bank partners share physical tensors; after BP, their physical trajectories may differ because their learned parameters differ.

## Data and held-out boundary

Formal data use seed 31415 with new source IDs:

| Split | Source IDs | Episodes |
| --- | --- | ---: |
| Train | 540000–540003 | 64 |
| Dev | 540100–540103 | 64 |
| Test | 540200–540203 | 128 |

The target is sign(A+B), with independent uniform A and B and a delayed B observation. The pre-late Bayes accuracy is 75%, and the fully informed Bayes accuracy is 100%. The data are synthetic, not real user records.

The source, hyperparameter rule, case roster and test-generation descriptor were published before formal training. All 168 training slots must have terminal records before sealing. The separate evaluator checks every candidate and history hash, source/runtime binding, unique case names and exact seal membership before generating any test labels. The candidate seal is then independently committed to Git before test launch.

This is reproducible code/process separation with published ordering, not protection against a hostile administrator who can edit code or inspect memory.

## Safe reuse of dense physical operators

The original physical model updates drift and boundary every two ticks. Between those control refreshes the two dense matrix-exponential operators are identical, although probability/content vectors continue changing.

optimized.py reuses the same differentiable operator within that control epoch. It does not detach its graph, replace density by its mean, alter reset/refractory semantics, change QVI equations, or omit the value solve. The cache is cleared for every forward call and uses the absolute state step when continuing a saved state.

A train-only 24-arm comparison covered all four widths, both feature banks and all three message modes. All five state tensors, logits and features matched exactly; maximum parameter-gradient difference was 2.776e-17. This is a bounded empirical check plus a source-structure argument, not an exhaustive proof over all possible future code.

The cache key relies on the current two operator roles having distinct shape/direction. A future same-shape third operator would require an explicit role key. Physical source hashes are frozen so that future change cannot silently enter this study.

## Parallel execution and cost accounting

The 168 case IDs are assigned by frozen case index modulo four. Each of four independent worker processes receives exactly 42 nonoverlapping cases. Torch intra-op, Torch inter-op and BLAS are each limited to one thread. Each worker requests one CPU quota and a 2 GiB memory limit. pocket4 reported 24 logical CPUs.

CPU time is measured independently in each process, then summed. Wall time reflects up to four concurrent workers on a shared host and possible external contention. The wall-time span is not mislabeled as single-core CPU time. These workers parallelize independent experimental arms; they are not a new decentralized optimization protocol.

Costs separately record data/model setup, physical feature propagation, feature diagnostics, normalization plus all solves and baseline metrics, each ridge solve, all BP updates, dev selection, serialization, file readback, postload state validation and independent test evaluation. Supervision records process startup, total child CPU and peak RSS. Actual dynamic state capacity covers the five tensor fields; step/config metadata and autograd tape are separately scoped.

The three initial analytic heads share one physical feature extraction in this experiment. Their marginal solve costs and shared setup are reported; no invented standalone end-to-end speed ratio is inferred from the tiny solve duration. Previous dependency installation is reused and is not hidden inside a new zero-cost claim.

## Interpretation limits

The decisive scale comparison is raw versus standardized analytic heads on the same newly frozen representation. Full BP versus its initial standardized head is a separate comparison. Feature-bank effects, message effects and learned/fixed recurrent effects are paired by seed and width.

All failures, quality misses, budget censoring and initialization-selected checkpoints remain in the result tables. Three initialization seeds and one fixed synthetic task family support a bounded comparison; sharing a held-out set does not make every factorial row an independent statistical replication.

This study does not establish unique reconstruction of all LLM weights, universal avoidance of backpropagation, real cross-user transfer, learned graph topology, production adoption or decentralized consensus.
