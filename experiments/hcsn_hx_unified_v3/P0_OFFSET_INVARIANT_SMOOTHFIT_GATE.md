# P0 offset-invariant independent renewal smooth-fit gate

**DRAFT / RESEARCH ONLY / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**

## Dependency and scope

- Parent PR #4446 HEAD `1fd3afb4d749679439ea3bfd416f5f19a6164cb5`, original stopping source blob `158d48e4c08bfa4537ff7624ab695eae6377d9e1`.
- Edits only `regenerative_boundary_independent` under `experiments/hcsn_hx_unified_v3/stopping.py` and adds tests / this note.
- This is a scalar regenerative Brownian reference, **not** the coupled financial HX system. No production Rust, GPU, permission, model-training, deployment or frozen-result change.

## Counterexamples to original f64 Brent coordinate

With `Stop(0., 1., .005, 1e14, 1e14-10., 0.)`, the regular-loss independent root search uses absolute `b` near `1e14`. Its `brentq(..., rtol=1e-13)` effective tolerance exceeds the whole displacement interval. A faithful transcription of the original branch returns `b-cost=10`, versus high-precision reward displacement around `8.41405660437` (about 18.85% relative discrepancy).

At `cost=1e8` with otherwise identical parameters, original displacement differs from independent 100-digit mpmath by `3.2259610627e-7`, over 20 ULPs. `b>cost` and finite residuals are not accuracy certificates. Small-loss Decimal solving also needs an explicit final float representability guard when cost is large.

## Repair

- For `h>1e-4`, use dimensionless `t=k*(b-cost) in (0,1)`, solve `t + expm1(-h-t)=0` with explicit strict brackets and narrow independent Brent tolerance; only then reconstruct `b=cost+t/k`.
- Keep the prior adaptive-precision Decimal equation for `0<h<=1e-4` unchanged, except tracking its displacement for a shared final guard.
- Both branches refuse unresolved `b`, nonpositive displacement or `ulp(b)>1e-8*displacement`. This constant is a numerical refusal policy, **not** a strict interval enclosure.
- Very large `h` can erase the positive interior right residual in f64; refusal stays refusal, not a fabricated root.

## Executed evidence, without overstating scope

- Local Python 3.13.5, SciPy 1.17.0, mpmath, Linux CPU.
- Locally reconstructed the relevant upstream scalar routines and imported the **byte-identical eight original tests** from PR #4446 (`test_independent_smoothfit_gate.py` Git blob `17755fe8defc6fb51d7f4bb3f12ad4b045ddaa92`). This was not a complete exact GitHub checkout of the 14 KB modified source or full CI.
- Added five test methods covering false cost-relative convergence, high-cost refusal, a small-h large-cost refusal, translation invariance and nominal regression.
- Old regular-loss branch + four initial tests: **three failures** (one includes the expected unresolved high-cost refusal). Patched relevant routines + original eight and new five: **13/13 PASS, zero skipped**; compileall PASS.
- Independent 90-digit mpmath diagnostic seed `2026103104`: 3,000 candidates, **1,484 accepted / 1,463 explicitly refused / 53 nonrepresentable reset inputs**; zero accepted candidates exceeded the declared `4*ulp(b)+1e-12*reward` diagnostic. Refusals do not count as passes or domain-wide certification.
- Published new test Git blob `fd22de7e1f6149b1d5b64bbb7e487c0f2ebdf899`, byte-equal to locally executed test file.

## Reproduce

```sh
python -m unittest -v experiments.hcsn_hx_unified_v3.test_independent_smoothfit_gate experiments.hcsn_hx_unified_v3.test_independent_offset_gate
python -m compileall -q experiments/hcsn_hx_unified_v3/stopping.py experiments/hcsn_hx_unified_v3/test_independent_offset_gate.py
```

## Open gates

The source-exact integrated repository suite, real joint He–Xiong obstacle/fixed-point verification, interval-certified all-domain error, complete boundary gradients/FP32/f16, P1 mechanism gain, P2 long memory, P3 four-modal alignment, P4 Rust/GPU 64–4096 Cell performance/energy/recovery, and P5 same-quality complete-budget scaling all remain **OPEN**. Research only; never promote or merge to production based on this note.
