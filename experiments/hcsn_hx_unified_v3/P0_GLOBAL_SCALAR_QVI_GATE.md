# P0: analytic all-state scalar regenerative QVI argument (research only)

**DRAFT / DENY_ALL / all_blockers_closed=false / production_activation_allowed=false.**
This is only for the ideal constant-coefficient one-dimensional arithmetic
Brownian regenerative optimal stopping model. It is **not** a coupled He–Xiong
financial default equilibrium, global finance obstacle result, formal proof of
floating-point kernels, adaptive finite-grid network, trained HCSN, GPU or
production Hepta gate.

## Parent and scientific contracts

Source parent: #4446 `1fd3afb4d749679439ea3bfd416f5f19a6164cb5`,
which already has the independent tiny-loss smooth-fit root. This addition is
isolated to three new research Python files and this note. The existing
`stopping.py`, `hx.py`, frozen datasets, native runtime, gate config and
benchmark evidence must remain byte-identical.

Write `dX=mu dt+sigma dW`, discount `rho>0`, fire reward `X-K`, deterministic
dead time `T>=0` and reset `r<K`. There is no stimulus after reset. Define the
positive characteristic root `k` by `mu*k+sigma²*k²/2=rho`. The unique
`0<t<1` solves `-log(1-t)-t=h`, where `h=rho*T+k*(K-r)>0`. Set
`b=K+t/k`, `q=exp(-h-t)=1-t` and `R=q/k`. The candidate is

```
V(x) = exp(k*(x-b))/k    when x<b;
V(x) = x-K+R            when x>=b.
```

In the continuation region, `u=k*(b-x)>0`. The obstacle inequality is
**global**, because `V(x)-(x-K+R)=(exp(-u)-1+u)/k >=0` by convexity of the
exponential, not from a finite sample of x. The generator is exactly zero by
the characteristic equation. In the firing region, the obstacle is exactly
zero; the generator is at most `mu-rho/k=-sigma²*k/2<0`, globally, and decreases
with x. At b, both value and first derivative agree. The renewal ratio
`q<1` is contractive, and discounted linear-growth transversality holds
for the stated Brownian dynamics. Standard optimal-stopping verification
then establishes the scalar stationary QVI for the **ideal model**.

This proof does not establish existence, admissibility or value optimality
for finite HX debt/equity or a multidimensional learned physical state.
Do not transfer it to those models by analogy.

## Independent binary64-admission diagnostic

`global_scalar_qvi_gate.py` independently computes k in Decimal using a
stable quadratic and solves the **original exponential** smooth-fit root
with safeguarded Decimal Newton. It does not depend on Lambert-W or the
primary `stopping.py`. The result can compare an observed production-path
boundary with the independently derived reference. It refuses inputs outside
`1e-60 <= h <= 30`, an unresolved f64 renewal ratio, inadequate threshold
resolution, nonfinite characteristics, and thresholds outside both an eight-
ULP *and* normalized `1e-9` displacement tolerance. These thresholds are
heuristic admission checks, **not interval-certified rounding bounds**.
Mathematical ideal-model validity is separate from binary64 implementability.

## Reproduction and evidence boundary

```
python -m unittest -v experiments.hcsn_hx_unified_v3.test_global_scalar_qvi_gate
python -m unittest -v experiments.hcsn_hx_unified_v3.test_global_scalar_qvi_integration
```

The first module is standalone and requires only the Python standard library.
Locally executed in the authored subset with Python 3.13.5: **9/9 PASS**,
including tiny-loss and unrepresentable binary64 refusal, exact global
inequality examples, independently evaluated log-root residuals, and a seeded
100-case sweep (**99 accepted, 1 deliberately refused as outside scope**).
`compileall` passed. The second source-integrating module is intentionally
committed but **not run** in the limited local subset because `stopping.py`
was not checked out. It must execute in a real exact-SHA checkout before any
integration closure claim. New source/test code is not evidence that the
mainline `stopping.py` passed the full suite.

## Still open (P0–P5)

- P0: coupled HX obstacle and comprehensive parameter-domain/free-boundary
  proof, gradient accuracy with certified intervals, f32/f16/GPU semantics.
- P1: preregistered slope/parameter/training-matched Call/Risk/Margin gains.
- P2: actual repeated physical sampled firing, overwrite/MQAR/Selective Copy
  with long irregular clocks and independent checkpoint/replay.
- P3: real paired text/image/audio/video experiments and noise/OOD robustness.
- P4: native Rust/GPU HCSN kernel and measured 64/256/1024/4096-cell energy,
  throughput, p95/p99 latency, RSS/VRAM and recovery.
- P5: controlled matched-data/token/compute superiority over tuned baselines.

Remain **research-only** until independent production-scale evidence closes
all relevant gates; preserve all pre-existing negative outcomes unchanged.
