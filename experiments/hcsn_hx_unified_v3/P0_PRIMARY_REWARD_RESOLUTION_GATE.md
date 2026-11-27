# HCSN P0: primary renewal firing-reward resolution gate

**RESEARCH ONLY / DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

## Exact dependency and failure

Stack strictly on #4454 HEAD `a86044733e0f03eb78f29c7e05b2ef26a71d6484`. Source blob before change: `84c652048ab7d75d835d48aeafe0285874c4bfa8`. No change to the independent root, HX finance formulas, trained model, ownership authority, Rust, GPU or CI.

The main `regenerative_boundary` previously admitted a boundary merely because it was finite and numerically greater than `cost`. With `Stop(0,1,.005,1e14,1e14-10,0)`, it returned `b-cost = 8.40625`; the independent 100-decimal oracle gives about `8.41405660437`. The existing independent oracle refuses that cost-scale accuracy. This is a false accept of a severely quantized reward, not a mathematical requirement for all parameters to be representable in binary64.

## Narrow correction

Retain all Lambert-W/series/Newton logic. Explicitly compute `displacement=t/kappa`, check finite positive displacement and finite `b>cost`. Then enforce the same *necessary numerical resolution policy* already declared by the independent oracle: `ulp(b) <= 1e-8*displacement`. A rejected input raises `ArithmeticError` and is **not** clamped or labeled a successful neural event. The `1e-8` resolution threshold is a declared engineering admission tolerance, **not** rigorous directed-rounding enclosure.

- Result source blob: `40cd1c47d56ae89d5740aabe45ef33a327856022`.
- New test blob: `1ea20f0a10d549f4883512eb8016464159aed0a1`.

## Actually executed local numerical evidence

Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, mpmath 1.3.0, selected relevant-source reconstruction:

- Unmodified parent + new four-method tests: **8 expected failing subtest assertions**, arising from accepted impossible-accuracy positive/negative large-cost values. Other valid-case assertions pass.
- Patched source, five inherited groups plus the new test: **34/34 unit test methods PASS, 0 skipped**; local wall 3.16 s, peak RSS 126092 KiB. `compileall` PASS.
- Seed `2026103109`, 700 randomized shifted-cost scalar instances: 436 admitted, 251 explicit refusals, 13 unrepresentable inputs; 0 admitted differences larger than `4*ulp(b) + 1e-12*reference_displacement` relative to the independently computed mpmath displacement. Largest *relative* admitted displacement discrepancy 3.5053e-9. These are diagnostic observations, **not** global accuracy proofs; refusals are not successful cases.
- The locally authored new test has Git blob hash **identical** to the committed remote test. The local `stopping.py` was reconstructed for relevant numerical tests, not a full byte-identical copy of the remote source. The remote patch and resulting blob were fetched and verified; no full-repository source-exact CI or production benchmark was run.

Reproduce the focused checks from an exact checkout of this draft branch:

```sh
python3 -m unittest -q \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale \
  experiments.hcsn_hx_unified_v3.test_independent_smoothfit_gate \
  experiments.hcsn_hx_unified_v3.test_independent_offset_gate \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint_wide_transition \
  experiments.hcsn_hx_unified_v3.test_primary_reward_resolution_gate
```

## Remaining unclosed stages

P0: no full-domain **coupled** He--Xiong fixed point and obstacle certification, certified F/G intervals or native precision proof; scalar renewal reset Jacobian diverges as loss -> 0. P1: unchanged negative pre-registered mechanistic gates; no new fresh same-information/slope/cost causal benefit. P2: repeated **actual** sampled events/long memory not proven. P3: paired text/image/audio/video training not established. P4: real Rust/GPU 64–4096 Cells, energy and recovery not run. P5: quality- and cost-matched backbone scaling not admitted. Keep no production activation or merge claim.
