# P0 scalar regenerative QVI far-left-tail stability gate

**Status:** RESEARCH ONLY / DRAFT / DENY_ALL / all_blockers_closed=false /
production_activation_allowed=false. This is a narrow scalar fixed-threshold
numerical regression, not a global He–Xiong equilibrium or a neural-model result.

## Exact source and negative witness

Parent: `#4432` head `a9117f926c9ffa104bab61dfde31b6735220cb5f`.
The byte-exact parent `stopping.py` Git blob is
`3ffe41cb633f69868c8ae96569cfb8dc9f932ac0`.

Run with `Stop(0., 1., .5, 1., 0., 0.)`, *arbitrary, nonoptimal*
fixed threshold `b=2`, and `x=-1000`. The parent evaluates
`val * expm1(1000)`, raising an overflow and `ArithmeticError`,
despite the finite exact fixed-policy result

```
V(x) = exp(x)/(exp(2)-1)       (x < 2)
obstacle(x) = x - 1 + (1-exp(x))/(exp(2)-1)
obstacle(-1000) ≈ -1000.8434823572503
```

The exact parent with the three initial new tests yielded **five subtest
errors** and nonzero process exit; no failures were hidden as skips.

## Scoped fix and numerical rationale

For `h=rho*tau + kappa*(x-reset) >= -36`, retain the original
`val * expm1(-h)`, important when reset continuation nearly equals
the value at the current state.

For `h < -36`, the assumptions `rho>0`, `tau>=0` and `kappa>0`
imply `x<reset`. Use `D*V(reset)-V(x)`, with `D=exp(-rho*tau)`.
The exact ratio `V(x)/(D*V(reset))=exp(h)<exp(-36)`; therefore the
direct subtraction cannot suffer the near-equality cancellation that the
original `expm1` branch avoids. This also removes the `0*infinity`
overflow when `V(x)` has underflowed. No clipping or changed action
semantics; invalid/nonfinite output remains rejected.

## Executed local evidence (not CI)

Environment: Python 3.13.5 / SciPy 1.17.0 on Linux CPU.
The original parent and three unchanged regression test modules were
verified using `git hash-object`:

- Parent `stopping.py`: `3ffe41cb633f69868c8ae96569cfb8dc9f932ac0`
- `test_qvi_finite_gate.py`: `494d13f3508c72d117e488e0b446e3fe34e64000`
- `test_stop_kappa_scale.py`: `bcdf7637a3201d5f71fdf26345fb5ad5e57b4e46`
- `test_stop_branchpoint.py`: `7a0ecf72658165d14d945784d1b193f0ef21ca53`

Ran from a local source-exact relevant-module package:

```sh
python -m unittest -q \
  experiments.hcsn_hx_unified_v3.test_qvi_finite_gate \
  experiments.hcsn_hx_unified_v3.test_stop_kappa_scale \
  experiments.hcsn_hx_unified_v3.test_stop_branchpoint \
  experiments.hcsn_hx_unified_v3.test_qvi_negative_tail
python -m compileall -q experiments/hcsn_hx_unified_v3
```

**23/23 tests passed, zero skipped**: 19 unchanged upstream P0
tests and 4 new tests. The latter include 100-digit independent Decimal
fixed-threshold algebra at negative states -36 to -4096, nonzero refractory,
transition around `h=-36`, and 128 deterministic varied-parameter
Decimal renewal comparisons (seed 2026103122, with the same resolved
binary64 kappa as the candidate). No genuine GPU, fp32/fp16 or interval
rounding certification is inferred.

**Tested and GitHub-matched Git blobs:**
- Patched `stopping.py`: `c322dd5b66ffe6ec8f9d095d0fa524473f31dd6c`
- New `test_qvi_negative_tail.py`: `2486b5d227431080560ce8d5be6b90ce5064afd8`

## Remaining P0–P5 gates are OPEN

- **P0:** Original He–Xiong global financial obstacle and positive-equity
  conditions, full parameter-domain interval certificates, coupled
  regenerative QVI, fp32/fp16 and native boundary-gradient correctness.
- **P1:** Frozen matched-capacity, local-slope, equal-data, equal-compute
  Call/Risk/Margin single/pair/triple ablations with held-out gains.
  Existing preregistered 0/4 mechanism finding is still negative.
- **P2:** Correct physical repeated events and long-memory Selective Copy,
  MQAR, overwrite, irregular-time, long retrieval and regeneration quality.
- **P3:** Aligned genuine text/image/audio/video encoder pairs, noisy
  held-out cross-modal generalization and negative controls.
- **P4:** Real Rust/GPU kernel plus 64/256/1024/4096 Cell throughput,
  CPU/GPU/RSS, p95/p99, joules, durable restart and failure recovery.
- **P5:** Hybrid backbone advantage over tuned baselines under identical
  data, tokens, total compute and inference cost.

No original `hx.py` finance-source integration, entire repository suite,
CI status, new trained tasks, target-machine or deployment claim is made.
Do not merge/promote this draft solely on these numerical tests.
