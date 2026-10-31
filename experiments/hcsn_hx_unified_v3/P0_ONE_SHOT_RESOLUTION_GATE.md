# P0 f64 one-shot threshold/value admission — isolated numerical research

**DRAFT / DENY_ALL.** `all_blockers_closed=false`, `production_activation_allowed=false`. This is an isolated scalar stopping domain guard, not a complete He–Xiong finance / globally optimal QVI / low precision certificate.

## Exact source and numerical witnesses

Immutable parent: #4436 HEAD `c73cf1412e2685530ff1b04f4a9e4cfe038c05dd`. Reconstructed and executed original `stopping.py` from GitHub, verified its exact blob `c322dd5b66ffe6ec8f9d095d0fa524473f31dd6c`.

The prior one-shot API computes `cost + 1/kappa` without checking the representable threshold. Three finite, legal scalar parameters demonstrate different failures even with finite `kappa`:

1. `Stop(1e308,1.,.1,0.,-1.,0.)`: `kappa=1e-309` is representable, but `one_shot_boundary` returns `inf`, `one_shot_value(0)` returns `nan`.
2. `Stop(0.,1.,.5,1e308,0.,0.)`: `kappa≈1`, but `cost+1/kappa == cost` (a strict boundary is erased by f64 rounding).
3. `Stop(1e307,1.,.1,1.4e308,1e308,0.)`: `1/kappa` is finite, but `cost + 1/kappa` overflows.
4. `Stop(1e292,1.,.1,-1e308,-1.2e308,0.)`: boundary remains finite and strictly larger than cost, but a finite firing state `x=1e308` produces infinite immediate reward.

## Change and evidence

Refuse thresholds with nonfinite `1/kappa` or nonfinite / non-increasing `cost+1/kappa`. Refuse nonfinite one-shot values for finite states. Keep the original characteristic root, HX finance and regenerative solver untouched; no clipping, no hidden fallback. This is a conservative representation limit, not proof that the mathematical optimum does not exist.

Locally executed Python 3.13.5 / SciPy 1.17.0, Linux CPU:

- New tests **before** fix: 6 methods, **4 failures**, nonzero exit.
- Patched: **29/29 PASS, zero skips** (23 inherited tests and 6 new tests). `compileall` for changed source and new test passes.
- Original test sources reproduced with matching Git blobs: `test_stop_branchpoint.py` `7a0ecf72658165d14d945784d1b193f0ef21ca53`; `test_stop_kappa_scale.py` `bcdf7637a3201d5f71fdf26345fb5ad5e57b4e46`; `test_qvi_finite_gate.py` `494d13f3508c72d117e488e0b446e3fe34e64000`; `test_qvi_negative_tail.py` `2486b5d227431080560ce8d5be6b90ce5064afd8`.
- New test includes 128 deterministic independent fixed-threshold comparisons against alternate firing thresholds and normal boundary/value preservation.
- Exact patched source Git blob `334e1dc91a8e7ae092bcc2ca58e2855d82b71c07`, new test blob `a6522edbde0009512cac221b2cc0b14c9704e669`: remote identities verified against locally executed bytes.
- Replay:
  `python -m unittest -v experiments.hcsn_hx_unified_v3.test_stop_branchpoint experiments.hcsn_hx_unified_v3.test_stop_kappa_scale experiments.hcsn_hx_unified_v3.test_qvi_finite_gate experiments.hcsn_hx_unified_v3.test_qvi_negative_tail experiments.hcsn_hx_unified_v3.test_one_shot_resolution`

**Not executed / not established:** complete HX finance integration suite; all-domain coupled financial obstacle and QVI; rigorous real-interval error; boundary gradients over the full admissible set; fp32/f16/GPU; real trained mechanisms or memory; 4-modal holdout; 64–4096 Cell native benchmark, energy or recovery; matched token/compute Backbone improvement. Previously negative HCSN comparisons and P1 0/4 remain binding. Do not merge as production admission.
