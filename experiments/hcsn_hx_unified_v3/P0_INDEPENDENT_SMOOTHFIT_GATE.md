# P0 independent scalar smooth-fit tiny-loss gate — research only

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.** This is an independent *scalar stopped-renewal diagnostic*, not a full He–Xiong coupled equilibrium, global obstacle/QVI certificate, neuron-training result, native kernel, or production admission.

## Exact dependency and negative witnesses

Parent: Draft PR #4441 HEAD `55f39c8c68271a721054e097045f1f0a1852d3df`. Target `stopping.py` parent blob `334e1dc91a8e7ae092bcc2ca58e2855d82b71c07`.

The old independent numerical function used `k*(b-cost)+D*exp(-k*(b-reset))-1` as a binary64 Brent residual, with `xtol=1e-13`. Although the genuine optimum has `b>cost`, this residual is an almost-double root near `cost` and loses the `O(h)` difference to direct subtraction.

- Legal `Stop(0,1,.5,0,-1e-20,0)`: near the left endpoint `exp(-h)-1` is rounded to zero and the legacy independent oracle rejects its bracket. The primary analytic solver has a real positive threshold of approximately `1.4142135623e-10`.
- Legal `Stop(0,1,.5,0,-1e-16,0)`: the legacy Brent result in an isolated faithful transcription is about `3.5e-13` instead of the reference `1.41421356e-8`. This false numerical agreement/disagreement cannot be counted as an independent smooth-fit validation.

## Narrow repair

For `0<h<=1e-4`, independently solve the *original exponential smooth-fit equation* `t + exp(-h-t) - 1 = 0` using Decimal arithmetic, adaptive precision `max(90, floor(-log10(h))+85)`, 20 bounded Newton steps, explicit residual, proper positive-root and finite distinguishable-boundary checks. The main Lambert-W/series implementation is **not reused**. The historical float64 Brent path remains for ordinary `h>1e-4` cases with finite-bracket and positive-boundary guards.

The reference still uses the finite f64 `p.kappa`; a distinct high-precision characteristic-root oracle is in the pre-existing tests. No interval-certified enclosure or global-in-parameter guarantee is claimed. Very large renewal-loss, f32/f16, finance HX fixed-point and global optimality domains remain unresolved.

## Executed and non-executed evidence

- Python 3.13.5 / SciPy 1.17.0, local CPU. A **standalone faithful transcription of the old root and proposed new root**, using the same source equations, reproduced both legacy counterexamples and passed **6/6 focused tests**, including eight extreme Decimal smooth-fit values, an independent refractory case, four ordinary positive controls and erased-cost refusal.
- This isolated probe was **not a byte-exact repository checkout**. Do **not** describe 6/6 as executing the full GitHub source/test tree.
- Added **eight repository test methods** in `test_independent_smoothfit_gate.py`, importing the existing independent 320-digit `high_precision_boundary` and the actual research `stopping.py`. These repository tests are committed for replay but have **not** been executed here.
- Replay when a source checkout is available:

```sh
python -m unittest -v \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale \
  experiments.hcsn_hx_unified_v3.test_qvi_finite_gate \
  experiments.hcsn_hx_unified_v3.test_qvi_negative_tail \
  experiments.hcsn_hx_unified_v3.test_one_shot_resolution \
  experiments.hcsn_hx_unified_v3.test_independent_smoothfit_gate
```

## Other open gates, unchanged

**P0**: full finite-input parameter map, coupled HX financial equilibrium and global obstacle, rigorous interval/roundoff/gradient controls, low-precision tensor semantics. **P1**: prior mechanism-gain gate remains failed; no confirmatory same-information/slope/active-parameter/budget Call/Risk/Margin ablation. **P2**: real repeated sampled events, memory/overwrite/long-sequence tests still missing. **P3**: genuinely paired text/image/audio/video unseen multimodal validation missing. **P4**: actual Rust/GPU kernels, energy, 64/256/1024/4096-Cell recovery and tail measurements missing. **P5**: no positive net-cost matched-data/token/compute scaling comparison. Preserve original negative evidence. Do not merge or activate as production-ready.
