# HCSN P1 eight-arm matched mechanism pilot — 2026-10-31

**Research-only / DENY_ALL / NO_GO.** Stacked on #4499 exact parent `1d44dcd5fb0f7d2bf766298a58a8db71369ebe65`. This is a *bounded exploratory pilot*, NOT P1 acceptance, full HCSN, a financial neural optimality result, or a hardware benchmark.

## Frozen protocol and implementation

- Protocol was committed *before* the full 80-run measurement: `PILOT_PROTOCOL_20261031.json`, commit `8bae5b16051da0b951808a8b92f8507aa088284f`.
- All eight arms: ordinary, Call, Risk, Margin, Call+Risk, Call+Margin, Risk+Margin, all-three. Same frozen scalar Encoder, same data/labels, same 561-parameter 20-unit recurrent readout, and **three active trainable channel coefficients** per hidden unit.
- Call is a financial **equity readout**, not a literal European call price. Risk is first-hit default probability, Margin is bond rollover accounting margin. They are deterministic transformations of the *same* encoded scalar; neither adds information. A 101-point PCHIP grid normalizes each financial feature's value to 0 and signed derivative to +1 at the shared training-only anchor z=0. Three shifted ordinary tanh controls receive the same anchor treatment. The eight 3-column basis matrices pass an SVD rank guard; none is silently collapsed to fewer effective coefficients. This is **local** value/slope matching, not a function-family/global shape match.
- Two distinct sequence tasks: 12-to-28-step Selective Copy and **two-key last-write overwrite**, *not full MQAR*. Five paired seeds; 120 full updates, 48 examples/update, 512 training examples; 384 independent ID and 384 independent OOD examples per seed/task/arm. Same initial weights, batch indices and no early stopping. CPU single-thread PyTorch. Per-run precompute/training/inference CPU and wall times are recorded.
- Exact paired seed-sign-flip tests for 14 nonbaseline comparisons, Holm adjusted. No candidate search, no unreported selection. Five paired seeds cannot supply confirmatory power or reliable multi-run confidence intervals. Equal **updates**, not strictly equal measured CPU seconds; common financial lookup creation is not charged to each arm.

## Executed local evidence (not full checkout/CI)

- **80/80** nominally matched trainings and **5/5** focused contract tests passed, zero skips; source and test uploaded to GitHub and read back at exact bytes.
- Local Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, PyTorch 2.10.0+cpu. The local HX helper is a **reconstructed HX subset** with Green-resolvent equity, not a byte-identical full repository checkout. Results in an exact upstream checkout need a fresh replay; do not call the current numerical files repository-CI certified.
- Complete local 80-record JSON SHA-256: `892948ce8597dbe01d801d065c4f90c9c4fc8df57eedf4d4f50b43d132b9f463`. The full JSON remains attached separately to the research conversation; this report is a summary, NOT lossless raw evidence in GitHub. The checked-in script deterministically regenerates a fresh raw record.
- Python source Git blob `eb81a440d0cd583b9f296788742c3c5be120e965`; contract test `4a459da41dcbe765f7720835af251cdc3a7d3777`.

### Heldout OOD accuracy (five seeds; higher is better)

| Arm | Copy (T=28) | Copy delta vs ordinary (pp) | Last-write (T=28) | Last-write delta (pp) |
| --- | ---: | ---: | ---: | ---: |
| Ordinary | 83.80% | 0 | 86.25% | 0 |
| Call | 72.50% | -11.30 | 85.94% | -0.31 |
| Risk | 70.73% | -13.07 | 86.77% | +0.52 |
| Margin | 89.69% | +5.89 | 86.56% | +0.31 |
| Call+Risk | 82.86% | -0.94 | 86.93% | +0.68 |
| Call+Margin | 74.74% | -9.06 | 86.04% | -0.21 |
| Risk+Margin | 64.17% | -19.64 | 86.46% | +0.21 |
| All-three | 59.43% | -24.38 | 86.20% | -0.05 |

All 14 Holm-adjusted two-sided paired P values are **1.0**; *no measured contrast* establishes a positive Call/Risk/Margin causal advantage. The all-three Copy degradation is a serious **negative exploratory observation** but is itself not a confirmatory statistical claim. The slight Margin-only apparent improvement is not significant.

The sum of recorded per-run CPU across 80 jobs is about 16.79 s and is NOT a total platform energy/computational cost. The cold-start first process has a one-time initialization outlier; do not compare mean CPU as a strict equal-budget optimization benchmark. Full input calibration cost, subprocess scheduling and GPU/energy are unmeasured.

## Reproduce

```sh
python -m unittest -v experiments.hcsn_p1_mechanism.test_p1_factorial
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m experiments.hcsn_p1_mechanism.p1_factorial \
  --out /tmp/PILOT_RESULTS_20261031.json --updates 120 --seeds 5
sha256sum /tmp/PILOT_RESULTS_20261031.json
```

Results may differ from this local JSON SHA if the upstream full `hx.py` implementation, PyTorch kernels, CPU settings or process-time measurements differ; the SHA is **not** a global deterministic reproducibility guarantee. Check model outputs, per-seed paired deltas and error tolerances, not timing bitwise equality.

## Mandatory next P1 gate and P0/P2–P5 blockers

- **P1 OPEN:** fresh genuinely learned HX Call/Risk/Margin **dynamic** mechanisms versus optimized ordinary recurrent/SSM/Transformer gates; matched *global* information, local value/signed slope, active parameters, total CPU/GPU costs; external datasets, lengths, sufficient paired seeds, no negative transfer, and blinded confirmation. This proxy pilot is not that gate.
- **P0 OPEN:** globally admissible self-consistent financial obstacle, continuum error, certified interval/low-precision full HX and active-set gradients; upstream independent PDE and 101-node disagreement preserved.
- **P2 OPEN:** true jointly trained continuous event content, multi-FIRE/cold restart, Selective Copy and *standard* MQAR OOD, missing-time and overwrite semantics.
- **P3 OPEN:** genuine four-modal encoders, paired alignment, OOD noise.
- **P4 OPEN:** native Rust/GPU full execution, 64–4096 Cells, Joules, crash recoveries, p95/p99.
- **P5 BLOCKED:** full quality+compute matched Transformer/SSM/gates net improvement.

`production_activation=false`; `all_scientific_blockers_closed=false`. Preserve earlier failures, do not merge into production or disable checks.
