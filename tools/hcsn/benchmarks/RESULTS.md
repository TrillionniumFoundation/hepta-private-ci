# Sequence experiment results

Completed: **60 training runs**, five seeds, three synthetic tasks and four model variants. All runs use independent validation/test data, and model checkpoints are selected only by validation loss. The source hashes and every run are retained in `sequence_results.json`.

## Accuracy

Percent; ID reports mean ± sample standard deviation across five paired seeds. OOD doubles the sequence length from 32 to 64. Chance accuracy is 25%.

| Task | Model | Parameters | ID accuracy | 64-step accuracy | Corrupted-input accuracy |
|---|---|---:|---:|---:|---:|
| memory | hcsn | 6178 | 99.84 ± 0.35 | 14.49 | — |
| memory | sigmoid | 6178 | 100.00 ± 0.00 | 7.93 | — |
| memory | gru | 6257 | 26.56 ± 2.05 | 25.86 | — |
| memory | transformer | 6166 | 100.00 ± 0.00 | 100.00 | — |
| retrieval | hcsn | 6178 | 29.61 ± 2.00 | 25.66 | — |
| retrieval | sigmoid | 6178 | 29.34 ± 2.45 | 26.48 | — |
| retrieval | gru | 6257 | 48.98 ± 3.63 | 46.45 | — |
| retrieval | transformer | 6166 | 100.00 ± 0.00 | 99.96 | — |
| irregular | hcsn | 6178 | 81.80 ± 1.55 | 74.65 | 71.91 |
| irregular | sigmoid | 6178 | 81.68 ± 1.93 | 74.80 | 71.84 |
| irregular | gru | 6257 | 76.95 ± 1.37 | 78.79 | 70.94 |
| irregular | transformer | 6166 | 79.18 ± 5.64 | 38.12 | 70.94 |

## Incremental value of the put activation

The sigmoid ablation preserves the full fast/slow dynamics, call branch, learned boundary and parameter count. It changes only the put nonlinearity, matching its value and slope at zero. Paired differences below are HCSN minus sigmoid, in percentage points. Intervals are nominal 95% Student-t intervals over five paired seed differences; they are exploratory and not adjusted for multiple comparisons.

| Task | Mean paired difference | Nominal 95% interval |
|---|---:|---:|
| memory | -0.156 | [-0.590, +0.278] |
| retrieval | +0.273 | [-3.111, +3.658] |
| irregular | +0.117 | [-2.532, +2.766] |

The experiment does **not** establish an incremental learning benefit from the put shape. HCSN and the sigmoid variant both do well at the trained memory length but fail substantially on doubled length. HCSN associative retrieval remains near chance while the small Transformer solves the generated task. The irregular-input result favors the fast/slow architecture under this fixed protocol, but it does not isolate a benefit from the financial operator.

## Gradient validation

Float64 finite differences of input, recurrence, boundary and time-constant parameters agree with autodiff to a maximum absolute error of **9.51e-08**. The q derivative at the boundary is exactly **0.5** in this JAX implementation; the normalized call derivative is zero. Both neighboring values at ±1e-6 also match their analytic derivatives.

These checks concern the implemented discrete update. They do not claim an exact nonlinear ODE solution. The additional float32 checks in the training receipt have larger cancellation error and are not used as the stronger gradient acceptance test.

## Compute and interpretation limits

- Parameters: 6178 HCSN/sigmoid, 6257 GRU, 6166 Transformer. The difference between the largest and smallest count is 1.48%.
- Every run: 300 Adam updates, batch 32, 9600 presented training examples; fixed learning rate 0.003; no hyperparameter search.
- This is an equal-update/data and approximately equal-parameter experiment, not equal FLOPs or equal wall time. Lack of baseline hyperparameter search limits architecture-wide claims.
- Timing uses CPU reference code with four cores and shared-machine contention. The legacy `warm_training_seconds` field excludes only the first update; weakly typed scalar parameters can trigger a second JIT compilation for a new signature. Cache reuse means this is not a per-seed constant cost. All training-time fields are reference diagnostics and cannot support a pure-warm speed or energy comparison. Latency is a median of 20 warmed batch-32 evaluations that include loss, accuracy and Brier score; it is not pure logits inference, p95/p99 or streaming latency, and cannot be directly compared with the encoder experiment's logits-only latency.
- Process RSS is a cumulative high-water mark including JIT caches across several models. It is not a per-model memory comparison. Energy was not measured.
- The longest sequence test has 64 positions. This report covers synthetic sequences only; the separate frozen-text-head experiment does not constitute full-backbone or multimodal pretraining evidence.
- Source-code SHA-256 and per-split data fingerprints are recorded. All negative runs are included; no seed was dropped.

## Gate decision

**Full-backbone promotion is not justified by this experiment.** The specific missing evidence is (1) robust length generalization, (2) adequate content-addressed retrieval, and (3) an incremental benefit beyond the same dynamics with an ordinary sigmoid. The fixed protocol can still serve as a reference for a preregistered follow-up. A future fix should use new held-out data after its design is frozen; reusing these observed OOD scores for tuning would invalidate their held-out role.
