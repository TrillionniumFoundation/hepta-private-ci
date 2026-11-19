# HCSN P0: stable HX extreme asset/boundary log ratio

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

## Immutable dependency and narrow scope

Stacked on the research branch for Draft PR #4456 at exact parent commit `b07ece86fbfd8c718b184c53629d70105c7c389f`; not merged to main. Change only `experiments/hcsn_hx_unified_v3/hx.py` and a new dedicated regression, plus this note. No changes to authority, deployed neural inference, rust, GPU or finance trading services.

## Reproduced bug

With the default `HX()`, positive finite `asset=1e308` and `asset_boundary=1e-308`, existing `math.log(asset/asset_boundary)` produces `inf` because binary64 division overflows. In first-passage terms, the tail combination then computes `inf + (-inf)`, resulting in `NaN` for `default_probability`, `discounted_default_factor` and `bond_value`. The actual log ratio is finite (~1418.3924), so this was avoidable numeric invalidity for otherwise allowed finite inputs.

## Minimal correction

Use a shared `_log_asset_ratio`. Preserve the original quotient log bit-for-bit for finite quotients. Only when division overflows, use `log(asset)-log(asset_boundary)`; explicitly refuse a nonfinite result. Apply to financial first-passage F/G and finite-maturity bond; intentionally **do not** modify the independent resolvent, financial equity, global endogenous-boundary optimization or neural stopping oracle. Do not confuse numerical finiteness with financial model validity.

## Evidence scope

- Focused local Python 3.13.5 / SciPy 1.17.0 probe using extracted exact mathematical expressions (not a full-repo checkout): **3/3 tests PASS**. Before: F, G and bond return NaN in all three overflow-ratio probes. After: F/G are 0 in the far tail, bond equals independently computed risk-free asymptote within 2e-12; regular quotient ratios unchanged.
- New committed regression covers three extreme asset/boundary pairs across two maturities, normal branch stability, and zero-maturity/default semantics.
- **No source-exact full-module/local checkout or full CI result is claimed.** Run from a full checkout:

```sh
python3 -m unittest -q \\
  experiments.hcsn_hx_unified_v3.test_hx_log_ratio_overflow \\
  experiments.hcsn_hx_unified_v3.test_oracles
```

## Still OPEN

P0 global coupled HX obstacle/fixed-point and all legal finite/low-precision domains, certified first-passage F/G intervals, boundary gradients, and independent integration; P1 mechanism causality; P2 recurrent event/memory quality; P3 paired four-modal learning; P4 native Rust/GPU resource/recovery; P5 equal-budget verified backbone advantage. Keep the research-only admission and deny production activation.
