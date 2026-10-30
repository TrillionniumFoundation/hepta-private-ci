# HCSN v4 regularized associative memory: measured results

The frozen 105-run confirmation matrix is complete. The combined FullHX every-seed/every-length acceptance gate failed. Retrieval passed at all five seeds and all three test lengths. Memory seed 2 at L128 reached 93.84765625%, below the declared 95% minimum. This result is limited to the declared synthetic sequence family and budget.

## What changed and why

The previous eight-slot memory suffered learned address collisions. v4 replaces it with learned bounded key/value projections, normalized Gram/cross-value statistics, a C1 generic write gate, and a final-query ridge solve. FullHX, toy HCSN, sigmoid and a memory-only control share this memory mechanism. Any benefit shared by these controls cannot be attributed uniquely to the financial operator.

The detailed recurrence, exact-arithmetic state/SPD proof, positive-time-gap assumptions and finite-precision limitations are in DESIGN.md. The fixed ridge is 0.01 and key dimension is 16; neither was changed after test construction.

## Development and confirmation separation

Development used base 2690000 and one initialization. Its four fullHX/memory-only memory/retrieval runs used only train/validation and all reached 100% validation accuracy. The initial lazy-table JAX tracer error and source are preserved. Loading the table outside tracing fixed that implementation issue; no architectural changes followed the validation scores.

Sources and prospective protocols were frozen at 2026-10-30T03:06:06.391797+00:00. Confirmation used base 2700000, five seeds, 2048 training sequences at each of lengths 8/16/32, 600 Adam updates, batch 32 and learning rate 0.003. Every model used exactly 19200 sampled training examples. Checkpoints were selected by validation loss alone. Held-out sets have 1024 examples each.

The primary criteria are memory ≥95% and retrieval ≥90% for **every seed at every length 32/64/128**. Challenge base 2800000 was also declared before confirmation. It provides new 512-token, eight-association and noisy-filler data; challenge scores do not change checkpoint selection.

## Held-out accuracy

Entries are mean ± sample standard deviation across five seeds, in percent. These comparisons match data, optimizer updates and approximately 6200 trainable parameters; they do not match state capacity, operations or hardware cost.

### memory

| Model | L32 | L64 | L128 | Worst seed/length | Target in every seed/length |
|---|---:|---:|---:|---:|---|
| full_hx | 100.00 ± 0.00 | 100.00 ± 0.00 | 98.77 ± 2.75 | 93.85 | Fail |
| hcsn | 100.00 ± 0.00 | 100.00 ± 0.00 | 99.43 ± 1.27 | 97.17 | Pass |
| sigmoid | 100.00 ± 0.00 | 100.00 ± 0.00 | 98.57 ± 3.19 | 92.87 | Fail |
| ridge_memory_only | 100.00 ± 0.00 | 100.00 ± 0.00 | 77.25 ± 33.58 | 25.39 | Fail |
| gru | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| transformer | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| snn | 49.55 ± 0.61 | 49.92 ± 1.78 | 48.87 ± 1.15 | 47.75 | Fail |

### retrieval

| Model | L32 | L64 | L128 | Worst seed/length | Target in every seed/length |
|---|---:|---:|---:|---:|---|
| full_hx | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| hcsn | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| sigmoid | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| ridge_memory_only | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 ± 0.00 | 100.00 | Pass |
| gru | 50.57 ± 1.51 | 47.09 ± 1.77 | 39.34 ± 2.76 | 35.45 | Fail |
| transformer | 100.00 ± 0.00 | 99.98 ± 0.04 | 99.49 ± 0.92 | 97.85 | Pass |
| snn | 48.67 ± 2.10 | 41.60 ± 2.52 | 33.34 ± 2.41 | 30.18 | Fail |

### irregular

| Model | L32 | L64 | L128 | Worst seed/length | Target in every seed/length |
|---|---:|---:|---:|---:|---|
| full_hx | 84.77 ± 0.88 | 82.30 ± 0.55 | 81.66 ± 2.40 | 79.20 | Not declared |
| hcsn | 84.71 ± 1.12 | 81.54 ± 0.86 | 81.05 ± 2.47 | 78.32 | Not declared |
| sigmoid | 84.49 ± 0.97 | 81.43 ± 0.79 | 80.80 ± 2.20 | 77.93 | Not declared |
| ridge_memory_only | 52.73 ± 2.33 | 47.81 ± 0.94 | 45.61 ± 0.91 | 44.43 | Not declared |
| gru | 84.43 ± 1.32 | 85.35 ± 0.99 | 84.77 ± 1.75 | 82.62 | Not declared |
| transformer | 77.25 ± 1.43 | 37.64 ± 3.05 | 36.74 ± 2.57 | 33.01 | Not declared |
| snn | 72.09 ± 1.17 | 73.22 ± 1.88 | 71.80 ± 1.82 | 68.95 | Not declared |

### Noisy and missing irregular input

The corruption split uses noise 0.35 and missingness 0.5 at length 32. Its labels are computed from the available underlying observed events by the shared generator; this is a synthetic robustness test.

| Model | Accuracy, mean ± seed SD | Worst seed |
|---|---:|---:|
| full_hx | 74.41 ± 0.52 | 73.83 |
| hcsn | 74.59 ± 0.95 | 73.34 |
| sigmoid | 73.87 ± 1.01 | 72.56 |
| ridge_memory_only | 50.64 ± 1.60 | 48.73 |
| gru | 75.59 ± 1.33 | 74.41 |
| transformer | 70.92 ± 1.31 | 69.92 |
| snn | 64.73 ± 0.96 | 63.38 |

## Extrapolation and capacity challenges

These checkpoints were neither retrained nor reselected. No post hoc challenge pass threshold is imposed.

| Challenge | Model | Accuracy, mean ± seed SD | Worst seed |
|---|---|---:|---:|
| memory_512 | full_hx | 63.36 ± 37.88 | 23.83 |
| memory_512 | hcsn | 63.05 ± 37.84 | 23.83 |
| memory_512 | sigmoid | 63.44 ± 37.90 | 23.83 |
| memory_512 | ridge_memory_only | 41.41 ± 32.82 | 24.61 |
| memory_512 | gru | 75.94 ± 25.19 | 48.83 |
| memory_512 | transformer | 90.47 ± 20.45 | 53.91 |
| memory_512 | snn | 48.28 ± 2.85 | 44.53 |
| retrieval_8_items_128 | full_hx | 99.96 ± 0.09 | 99.80 |
| retrieval_8_items_128 | hcsn | 99.96 ± 0.09 | 99.80 |
| retrieval_8_items_128 | sigmoid | 99.96 ± 0.09 | 99.80 |
| retrieval_8_items_128 | ridge_memory_only | 100.00 ± 0.00 | 100.00 |
| retrieval_8_items_128 | gru | 36.88 ± 1.53 | 35.55 |
| retrieval_8_items_128 | transformer | 98.98 ± 1.36 | 96.68 |
| retrieval_8_items_128 | snn | 34.02 ± 0.84 | 33.40 |
| retrieval_noisy_128 | full_hx | 97.50 ± 1.28 | 95.51 |
| retrieval_noisy_128 | hcsn | 97.54 ± 1.11 | 95.90 |
| retrieval_noisy_128 | sigmoid | 97.54 ± 1.31 | 95.51 |
| retrieval_noisy_128 | ridge_memory_only | 96.84 ± 1.01 | 95.51 |
| retrieval_noisy_128 | gru | 32.11 ± 1.90 | 30.27 |
| retrieval_noisy_128 | transformer | 94.88 ± 4.00 | 89.65 |
| retrieval_noisy_128 | snn | 28.87 ± 2.15 | 26.37 |
| retrieval_8_items_512 | full_hx | 99.45 ± 0.45 | 98.83 |
| retrieval_8_items_512 | hcsn | 99.45 ± 0.45 | 98.83 |
| retrieval_8_items_512 | sigmoid | 99.45 ± 0.45 | 98.83 |
| retrieval_8_items_512 | ridge_memory_only | 98.36 ± 0.93 | 97.27 |
| retrieval_8_items_512 | gru | 27.58 ± 1.50 | 25.39 |
| retrieval_8_items_512 | transformer | 96.41 ± 5.44 | 86.72 |
| retrieval_8_items_512 | snn | 29.61 ± 1.45 | 27.73 |

## Operator-specific evidence

The following are paired FullHX minus control accuracy differences at L128, in percentage points. The approximate t intervals use five paired seeds, are descriptive and are not corrected for multiple comparisons. They do not establish universal equivalence or superiority.

| Task | Control | Mean difference | Approximate 95% interval |
|---|---|---:|---:|
| memory | hcsn | -0.664 | [-2.508, +1.180] |
| memory | sigmoid | +0.195 | [-0.347, +0.738] |
| memory | ridge_memory_only | +21.523 | [-21.586, +64.633] |
| retrieval | hcsn | +0.000 | [+0.000, +0.000] |
| retrieval | sigmoid | +0.000 | [+0.000, +0.000] |
| retrieval | ridge_memory_only | +0.000 | [+0.000, +0.000] |
| irregular | hcsn | +0.605 | [-0.134, +1.345] |
| irregular | sigmoid | +0.859 | [+0.022, +1.697] |
| irregular | ridge_memory_only | +36.055 | [+34.021, +38.088] |

The FullHX-versus-sigmoid irregular-L128 contrast is a limited positive signal: +0.859 percentage points with a nominal 95% interval [+0.022, +1.697]. It uses five paired seeds, has no multiple-comparison adjustment, and changes both the risk and Call shapes. It cannot isolate a Put-specific effect. FullHX's 81.660% mean is also below the GRU's 84.766% in this condition.

A ceiling score shared with ridge-memory-only is evidence that this memory mechanism solves the tested task, not evidence that the financial Call/risk shape is necessary. FullHX versus toy/sigmoid changes activation shapes under a shared dynamic graph; memory-only also reallocates the parameter budget and therefore is not an identical-width single-factor removal.

The memory-only prefix statistics commute under token/time-gap permutations with a fixed final query. They cannot represent every order-sensitive exponential-filter target in the irregular task. Adding temporal state can therefore matter substantially; the similar toy/sigmoid results and the GRU control are needed to distinguish this effect from a financial-shape effect.

## Resource accounting

Times are medians across runs of each run's measured median. Optimizer execution excludes AOT compilation, validation and discarded warmup updates (there are zero such updates). Inference is logits only, batch 32 at length 32. These are shared-CPU measurements, not an energy benchmark, GPU kernel comparison or quality-cost scaling curve.

| Model | Trainable parameters | Logical persistent state scalars/sequence | Fixed operator KiB | Optimizer update ms | Logits inference ms |
|---|---:|---:|---:|---:|---:|
| full_hx | 6217 | 1373 | 128.05 | 6.9009 | 4.1083 |
| hcsn | 6217 | 1373 | 0.00 | 5.3481 | 3.1954 |
| sigmoid | 6217 | 1373 | 0.00 | 5.4041 | 3.8413 |
| ridge_memory_only | 6250 | 1313 | 0.00 | 4.0124 | 1.9941 |
| gru | 6257 | 37 | 0.00 | 0.9275 | 0.8728 |
| transformer | 6166 | Sequence dependent | 0.00 | 1.6503 | 0.6987 |
| snn | 6260 | 204 | 0.00 | 1.1676 | 0.6939 |

The frozen results field `fixed_operator_bytes` is mislabeled: it records 262256 bytes of source float64 table arrays. The actual JAX runtime casts every table leaf to float32 and needs 131128 bytes (128.05 KiB). Raw results and runner remain unchanged. `resource_accounting.json` records the correction and per-array evidence; the table above uses runtime FP32 bytes.

The ridge state is much larger than a same-parameter GRU state. It performs outer products at every prefix token and a dense solve at the final query. Streaming state does not grow with sequence length, while training activations and repeated autoregressive queries add costs. The financial table is fixed and shared across units; it is not trainable capacity, but it is real storage.

## Numerical verification and independent replay

State/gradient validation passed: True. The separately declared zero/rank-one solve finite-difference stress passed: False. Independent replay of all 105 test32 checkpoints, data fingerprints, selection histories and budgets passed: True.

The solve stress preserved two FP32 finite-difference failures at step 2e-5: normalized errors 0.003610 and 0.004519 exceeded the declared 0.003 tolerance. FP64 checks passed and FP32 linear-system residuals were at most 4.71e-8. An independent NumPy float64 closed-form adjoint comparison then found maximum normalized FP32 gradient error 2.536e-6 (below its declared 2e-5 threshold). The complete difference-step sweep reduced errors to at most 2.15e-4 at step 2e-3 and reproduced the failures at 2e-5. This evidence supports small-step cancellation rather than an autodiff error, while the original failed test remains failed in its raw record.

The independent audit also verified that changing only the last query leaves Gram, cross-value and inverse-mass statistics bitwise unchanged, while fast/slow neuron states and logits may respond. Dataset hashes and exact input-overlap checks found no reuse of the confirmation/challenge datasets from v3 or development, and no evaluation input duplicates in any v3/development/v4 training set.

The separate-agent replay of 210 test64/test128 evaluations and 140 challenge evaluations passed: True. It uses independently implemented metric calculations and recomputes the per-seed acceptance failures. Passing an integrity replay does not turn a failed task target into a pass.

| Precision | Online-statistic error versus independent weighted sum | Exact closed-write retention | Maximum tested gradient absolute error |
|---|---:|---|---:|
| float32 | 7.896e-08 | True | 2.312e-05 |
| float64 | 2.984e-16 | True | 3.756e-10 |

The stress sequence contains 4096 updates. The dynamic stress multiplies random inputs by one million and positive time gaps by 100. Bounds are for recurrent state, not a proof of stable gradients at arbitrary length or arbitrary floating-point magnitude. The solve diagnostic includes rank-one statistics near the declared condition bound of 101.

## Remaining scope limits

This experiment meets the declared associative-retrieval criterion under its fixed conditions. The FullHX memory-retention criterion remains unmet, so the combined prerequisite for scaling is not satisfied. The results do not establish a novel optimal neuron model, biological spiking equivalence, a unique cross-task benefit from financial operators, improved energy consumption, a large-language-model scaling law, or readiness for language/multimodal backbone pretraining. The normalized statistics can dilute old rare events and finite key dimension still limits independent associations. Broader capacities, learned financial parameters, mixed precision beyond FP32, fused kernels and quality-cost scaling remain separate research questions.

## Evidence files

- `freeze.json`, `protocol.json`, `challenge_protocol.json`: prospective sources and evaluation conditions.
- `development_results.json`, `development_failures/`: all development successes and the implementation failure.
- `validation.json`, `stress_solve_results.json`: stated numerical standards and raw checks.
- `resource_accounting.json`: source-float64 versus runtime-FP32 table memory correction; original raw fields retained.
- `results.json`, `checkpoints/`: complete confirmation matrix, histories, source/data/checkpoint hashes and measured timings.
- `challenge_results.json`: duration, capacity and noisy-input evidence with frozen checkpoints.
- `audit_results.json`: independent replay and budget checks.
- `independent_audit.json`, `INDEPENDENT_AUDIT.md`: separate-agent mathematical, adjoint, data-isolation, resource and checkpoint review.
- `summary.json`: machine-readable acceptance and paired comparisons.
