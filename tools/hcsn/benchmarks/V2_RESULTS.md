# HCSN v2: one fixed repair, fresh-data evaluation

The v1 memory and retrieval failures motivated one new architecture. The design and training protocol were recorded in `v2_protocol.json` before its training. No v2 hyperparameter search or test-guided redesign was performed. All v1 source and results remain unchanged.

## Fixed architecture

V2 retains the bounded Call/Put fast and slow states. It adds an input-dependent boundary and residual memory. With boundary score s, the write gate is q(s) times normalized_call(-s). It is exactly zero for s<=0 and has zero first derivative there. The memory update is m_next = m + write_gate*(bounded_candidate-m), so stored memory is preserved when the gate closes. Readout uses q(s)*old_memory plus bounded fast/slow residuals, before writing the current token.

This is a new engineered recurrent architecture. The boundary is learned and does not solve a task-specific optimal-stopping problem. The exponential fast/slow update still freezes nonlinear gates and is not an exact nonlinear ODE flow.

## Fresh-data results

All figures are percentages across five seeds. Training uses 32 positions; OOD uses 64. The new data seed base is 900000; no v1 test examples are reused. Checkpoint selection uses only validation loss.

| Task | Model | Parameters | Persistent state scalars | ID mean ± SD | 64-step mean ± SD |
|---|---|---:|---:|---:|---:|
| memory | hcsn | 6258 | 159 | 100.00 ± 0.00 | 42.34 ± 46.78 |
| memory | sigmoid | 6258 | 159 | 100.00 ± 0.00 | 26.21 ± 29.90 |
| memory | gru | 6257 | 37 | 24.96 ± 2.36 | 24.10 ± 1.40 |
| memory | transformer | 6166 | Full-sequence reference | 100.00 ± 0.00 | 99.77 ± 0.52 |
| retrieval | hcsn | 6258 | 159 | 53.12 ± 1.32 | 51.84 ± 3.78 |
| retrieval | sigmoid | 6258 | 159 | 52.46 ± 0.94 | 51.68 ± 2.39 |
| retrieval | gru | 6257 | 37 | 49.02 ± 1.66 | 44.96 ± 2.42 |
| retrieval | transformer | 6166 | Full-sequence reference | 100.00 ± 0.00 | 98.91 ± 2.12 |

## Repair attribution: unchanged v1 on the same new data

This additional diagnostic reference was declared after early v2 scores were observed. It changes no v1 settings and performs no model selection using test scores. It prevents comparison of v1/v2 means from different datasets.

| Task | Split | v1 HCSN mean | v2 HCSN mean | Paired improvement |
|---|---|---:|---:|---:|
| memory | test | 97.81 | 100.00 | +2.19 pp |
| memory | long | 19.96 | 42.34 | +22.38 pp |
| retrieval | test | 34.80 | 53.12 | +18.32 pp |
| retrieval | long | 27.23 | 51.84 | +24.61 pp |

## Put-specific increment

Paired HCSN-minus-sigmoid differences in percentage points; nominal 95% t intervals are exploratory and unadjusted for multiple comparisons.

| Task | Split | Mean difference | Nominal 95% interval |
|---|---|---:|---:|
| memory | test | +0.000 | [+0.000, +0.000] |
| memory | long | +16.133 | [-66.026, +98.292] |
| retrieval | test | +0.664 | [-0.856, +2.184] |
| retrieval | long | +0.156 | [-2.253, +2.566] |

## Validation and compute

The v2 float64 finite-difference gradient check has maximum absolute error 3.53e-10. The zero-write region and its zero derivative are explicitly checked. Inputs scaled by one million and time gaps by one hundred yield finite outputs in the tested case.

| Model | Legacy training-time diagnostic seconds per run | Median batch-32 CPU evaluation (ms), averaged across runs |
|---|---:|---:|
| hcsn | 1.7602 | 1.0579 |
| sigmoid | 1.6635 | 1.8046 |
| gru | 0.4645 | 0.9324 |
| transformer | 0.8564 | 0.7185 |

These are shared-CPU reference diagnostics. The legacy `warm_training_seconds` field removes only the first update; a later audit found that weakly typed scalar parameters can cause a second JIT compilation for a new signature. Cache reuse means this does not affect every seed identically. Training-time fields must not be treated as pure warm timings or used to conclude a speed or energy advantage. Evaluation latency includes loss, accuracy and Brier score; it cannot be compared directly with logits-only latency in the encoder experiment. Encoder execution is excluded. No energy or GPU result is claimed. The original code and raw receipts remain unchanged so their recorded source hashes remain meaningful.

## Gate decision

**Not sufficient for full-backbone promotion.** The repair improves associative retrieval and average memory extrapolation against unchanged v1 on the same data, but performance remains far below the Transformer on these tasks. Memory extrapolation has large seed dependence. Put-specific gains over the same v2 system with sigmoid are not reliably established by this five-seed experiment. This result supports further targeted research, not an architecture-wide superiority claim.

## Reproduction

Run `python run_v2.py`, `python validate_v2.py`, and `python run_v2_reference.py`. The original fixed-budget v1 protocol and limitations in README.md continue to apply. Raw results are in sequence_v2_results.json, gradient_v2_validation.json and v2_reference_results.json.
