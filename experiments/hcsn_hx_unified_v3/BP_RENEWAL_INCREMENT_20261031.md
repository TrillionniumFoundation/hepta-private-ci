# HCSN P0/P1/P2: implicit BP + signed-slope control + nonstationary regenerative reference (2026-10-31)

**Status:** `RESEARCH_ONLY` / `DENY_ALL` / `NO_GO`. This is an additive research slice stacked on exact parent `f0ceb7c2d5384463b50271a9471a34c007ed76b2` (draft PR #4488), not a production integration or a replacement for the original He–Xiong coupled financial obstacle.

## Scope

- **P0 / BP:** `torch_stopping_bp_bridge.py` connects the repository's existing stationary scalar Brownian regenerative model (`Stop`, Brent boundary root, QVI) to PyTorch by first-order implicit differentiation. A signed safety margin, continuation-value advantage, and selected-policy value have genuine task gradient paths. Six parameter sensitivities are independently compared against finite differences; the primal value/obstacle are compared against the existing independent scalar reference. CPU / float64 / fixed boundary only. An active-set crossing, zero-`Psi_b`, ill-conditioned root, unsupported precision, or invalid domain is **refused**, not called smooth.
- **P1 / matched control:** `signed_anchor_calibration.py` matches an actual analytic feature and a conventional gate at a training-only anchor in both value and **signed input derivative**. Three incommensurate finite-difference stencils plus kink, flat-slope, nonfinite and excessive-gain refusals are tested. This is only local affine equalization; it does not claim matched information, equal effective trainable parameters, measured compute or heldout mechanism gain.
- **P2 / event reference:** `time_varying_refractory_reference.py` implements finite-grid positive-mass causal renewal for piecewise-constant input rates and exact deterministic refractory duration constrained to integer grid steps. It distinguishes probability of at least one first event from the expected count of all regenerated events; it supports a zero-refractory Poisson limit. It is a midpoint-cohort approximation, not a certified exact nonstationary Brownian hitting-time solution.
- **Unchanged:** historic HX Eq.(8)/(12)/(A7) kernels, original negative evidence, native Rust owner, read/write authority, model weights, production routing, CI workflows and earlier comparison thresholds.

## Locally executed evidence (not full repository CI)

Environment: Python 3.13.5; NumPy 2.3.5; SciPy 1.17.0; PyTorch 2.10.0+cpu. All three new source files and their tests were independently matched to the uploaded GitHub blob SHAs after publication.

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_torch_stopping_bp_bridge
python -m unittest -v experiments.hcsn_hx_unified_v3.test_signed_anchor_calibration
python -m unittest -v experiments.hcsn_distributional_v2.test_time_varying_refractory_reference_replay
```

- New targeted tests: **14/14 PASS**, 0 skipped. An initially invalid test grid exceeded the declared hazard-per-step admission limit and was repaired before committing; that error is not counted as scientific success.
- P0: three parameter sets compared to the existing Lambert-W boundary; 12 central differences for six physical parameters across two regimes; independent scalar QVI/obstacle comparison; task gradients of six parameters; fail-closed boundary/dtype/domain cases.
- P1: four tests of exact affine value/signed slope matching on three illustrative smooth functions and explicit refusal on a kink, constant/near-zero derivative, nonfinite feature and excessive gain. These are synthetic control checks, **not** a fresh registered Call/Risk/Margin mechanism experiment.
- P2: exact inhomogeneous Poisson zero-refractory limit; independent constant-rate Gamma renewal reference at 300/600/1200 steps; preserved prefix under different future rates; refractory suppression; invalid-input refusals.
- The local test harness reconstructed the **byte-identical upstream `stopping.py` Git blob** from exact parent `f0ceb7c2d5384463b50271a9471a34c007ed76b2` (blob `d165ed777990bbf8f3606b58e1b0991de59a1544`, 4,294 bytes), then reran **all 14/14 tests PASS**. Each of the six new source/test blobs likewise matches the locally executed files. This verifies the relevant exact parent source only; it is **not** a complete repository checkout, full CI, or HX financial-equilibrium integration.

## P0-P5 ledger (no inherited claims upgraded)

| Gate | Status | Unclosed proof |
|---|---|---|
| P0 HX/QVI/precision | **INCOMPLETE** | Original coupled HX bond/equity self-consistent obstacle, global admissible domain, strict numerical enclosure, low-precision native checks, active-set gradients |
| P1 Call/Risk/Margin | **INCOMPLETE** | Fresh preregistered same-information/slope/active-params/full-cost controlled causal positive effect; historic negative results retained |
| P2 events/memory | **INCOMPLETE** | Copy/MQAR overwrite/long-range retrieval; native repeated-event stream restore and numerical convergence/precision certificate |
| P3 four-modal | **INCOMPLETE** | Actual distinct text/image/audio/video encoders; paired retrieval/temporal OOD result |
| P4 Rust/GPU | **INCOMPLETE** | Native BP and GPU, actual joules, 64/256/1024/4096 Cells complete-queue/transfer/recovery benchmarks |
| P5 scaling | **BLOCKED_BY_P1-P4** | Quality-and-cost-matched Transformer/SSM/ordinary-gate superiority before expanding scale |

**Do not activate or merge as production-ready.** No missing metric may be treated as zero, no research PASS may be promoted to a scientific superiority claim, and no explicit refusal counts as a PASS.
