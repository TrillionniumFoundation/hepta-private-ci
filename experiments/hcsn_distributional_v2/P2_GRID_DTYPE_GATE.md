# P2 finite-volume tensor dtype / grid geometry admission — research only

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.** This is a fail-closed source-domain guard for the finite CTMC's grid, not a physical continuous-time repeated-event proof, trained memory result or native GPU kernel.

## Exact parent and observed issues

Stacked on Draft PR #4439 HEAD `3cbe89d976cd398c5344ee7588dde6c88ef2984d`. Inspected original `distribution_kernel.py` Git blob: `be25116b29278978b4a34c91a1f1b19c0c541c58`.

A faithful standalone transcription of the original `make_flow` source, executed on Python 3.13.5 / PyTorch 2.10.0+cpu, gives two distinct invalid-but-unrejected outputs with default validation enabled:

1. `float32` lower `-2`, boundary `nextafter(-2,+inf)`, eight cells, reset `-2`: multiple nominal cell edges/centers collapse to the same binary32 coordinate while output and reset weights remain **finite**, e.g. five degenerate bins each receive ≈0.2 reset mass. The row labels are mathematically distinct but have the same represented location.
2. `float32`, lower `0`, boundary `1e-35`, reset `4e-36`, sigma `0.5`: centers can be distinct but the computed diffusion/upward rate is **infinity** due to the squared-spacing denominator. The old function returns it instead of refusing.

These can invalidate the meaning of a finite-volume state and cannot be counted as a correct f32 physical transition. This is not proof of an exploited GPU defect; native GPU execution was not available.

## Scope of minimal repair

With `Grid.validate=True`, check strictly ordered finite edges *and* centers, positive finite spacing, and finite computed diffusion/advective/exit/refractory rates and reset weights. Refuse the entire batch if any member fails, with explicit `ValueError` rather than clipping, reinterpreting degenerate cells or silently normalizing infinities. Valid scalar/array types, ordinary f32/f64 grids, sigma=0 and the existing numerical model remain unchanged. The intentionally unchecked `validate=False` mode retains its caller-responsibility contract.

## Verification and limitations

- 12 local **standalone faithfully transcribed** f32/f64 scenarios executed, all meeting expected accept/refuse outcomes (including NaN/Inf physical input): collapsed 2/8-cell boundaries, one bad batch member, nonfinite diffusion, tiny refractory overflow, f64 unrepresentable span, and 4 valid f32/f64 × zero/positive sigma cases.
- Added eight actual source-importing repository unittest methods, including preservation of the existing nonfinite-physical-parameter error in `test_grid_dtype_resolution.py`, but **the exact repository file and full kernel suite were not executed in this environment**. Do not describe the standalone verification as a source-exact full regression.
- Replay in a checkout:

```sh
python -m unittest -v \
  experiments.hcsn_distributional_v2.test_grid_dtype_resolution \
  experiments.hcsn_distributional_v2.test_probability_functional_shape \
  experiments.hcsn_distributional_v2.test_probability_functional_finite \
  experiments.hcsn_distributional_v2.test_probability_transition_batch \
  experiments.hcsn_distributional_v2.kernel_tests
```

## Outstanding scientific and production gates

P0 complete HX finance/QVI/interval/gradients remains open; P1 prior causal-gain gate remains failed; **P2 physical repeated sampled event paths, long selective copy, MQAR, overwrite and independent memory comparisons remain open**. P3 four-modality pairing, P4 measured native Rust/GPU throughput/energy/recovery over 64–4096 Cells, and P5 positive equal-total-cost scaling remain open. This testable numerical failure is a prerequisite for credible tensor hardware measurement, not a substitute for it. No production assets, permissions, Rust runtime, CI policy, checkpoints or frozen negative benchmark results changed.
