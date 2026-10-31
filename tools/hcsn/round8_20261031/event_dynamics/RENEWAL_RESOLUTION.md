# Repeated-event resolution audit and preserved refinement failure

This continuation closes a specific numerical-coverage gap: the earlier
spatial audit tested the first event, while repeated-event checks compared
renewal quadrature with exact event-time Monte Carlo. The new audit also
refines a complete finite reset/recovery generator against that independent
continuous renewal oracle. It is a qualification experiment at one fixed
regular parameter group, not a general neural-network efficacy result.

## Matched continuous and finite contracts

The active process is scalar Brownian motion with drift `mu=0.4`, noise
`sigma=0.6`, upper boundary `b=1`, start `x=0`, and observation horizon `T=3`
physical seconds. Every upper hit records one event, then waits an independent
two-phase Erlang recovery with mean `0.5` seconds before resetting to `x=0`.
Thus both the initial gap and every reset gap equal `b`. Recovery rates remain
`2/0.5=4` per second at **every** spatial resolution. Recovery can complete
inside an observation interval, and any number of later hits is retained.

The finite chain has active nodes on `(-8*b,b)`, exactly aligned with `x=0`;
upper flux enters the first recovery phase, the final recovery phase returns
to the same zero node, and lower flux enters a cemetery state. The 72, 144,
288 and 576 intervals give spacings `0.125`, `0.0625`, `0.03125` and `0.015625`.
Both upwind and fitted rates use the same state/reset/recovery construction.

If `Q_h` is this row-source generator and `r_h` is its upper firing-rate
vector, the count mean is

\[
m_h(T)=\int_0^T e_{x=0}^{\mathsf T}e^{sQ_h}r_h\,ds.
\]

A matrix exponential with an accumulated-count coordinate evaluates this
integral. Block exponentials evaluate the exact derivatives of the finite
matrix problem, including the derivative of the firing-rate vector. Four
sensitivities are tested: drift, noise, the common initial/reset boundary
distance, and mean recovery time. Changing `b` also rescales the numerical
lower boundary; the continuous reference derivative is
`d(initial_gap)+d(reset_gap)`. Finite differences independently check all
four block derivatives at 144 intervals.

The continuous count oracle is the positive renewal formula in `THEORY.md`.
Its value is `0.9621804632864597`; its derivatives are:

| Parameter | Continuous derivative |
| --- | ---: |
| Drift | 1.692902267698641 |
| Noise | 0.8078266451826001 |
| Common boundary/reset distance | -1.1618568941890164 |
| Mean recovery seconds | -0.21755676667069765 |

## Fixed criteria and observed results

`renewal_resolution.py` writes its protocol before propagating a finite grid.
The fixed final error bounds were `0.005` for upwind and `0.0002` for fitted
rates, on **all five** value/gradient metrics. Minimum last-pair orders were
0.85 and 1.8 respectively. These thresholds were not changed after execution.

| Intervals | Upwind count error | Fitted count error | Upwind noise-gradient error | Fitted noise-gradient error |
| ---: | ---: | ---: | ---: | ---: |
| 72 | 0.0332016756 | 0.00195383483 | 0.0405900271 | 0.00697807221 |
| 144 | 0.0167108587 | 0.000488851363 | 0.0208281206 | 0.00175027657 |
| 288 | 0.00838458318 | 0.000122236694 | 0.0105523455 | 0.000437911999 |
| 576 | 0.00419979069 | 0.0000305606530 | **0.00531113793** | 0.000109499155 |
| 1152, later extension | 0.00210179651 | Not run | 0.00266433857 | Not run |

All five fitted errors decreased on every refinement; their last observed
orders ranged from 1.999696 to 2.000082. Its largest final absolute error was
`1.09499155e-4`, passing the original `2e-4` criterion. The upwind errors also
decreased and approached first order, but the **original** 576-interval
noise-gradient error exceeded `0.005`. Therefore the original record remains
`passed=false`, with 8 of its 9 gates passing.

The extension declares a single further upwind doubling to 1152 intervals,
checks the original protocol and source hashes, and retains the same `0.005`
criterion. Its maximum error is `0.00266433857`, and its last-pair orders range
from 0.993085 to 0.998811. All three extension gates pass. This improves the
resolution; it does not relabel the earlier failure as a pass or replace its
evidence. CPU times were 1.886 seconds for the original audit and 3.694 seconds
for the extension in this executor. These are audit CPU costs, not production
throughput measurements.

The finite-matrix derivative checks have maximum absolute disagreement
`8.1032e-10`. Adding four more renewal terms changed the reported oracle
gradients by zero at the stored precision; this is a fixture check, not a
uniform derivative-tail guarantee.

## Lower-domain count bound and its scope

Let `p_L` be the probability that one active Brownian excursion reaches the
artificial lower level `-8*b` by `T` without imposing the upper boundary.
This dominates lower absorption during any shorter actual excursion.
For the fixed parameters, `p_L=9.99379344e-19`. Couple the finite-domain
continuous reset law and the unrestricted continuous law up to the first
lower crossing. On paths with at most `M` events, there are at most `M+1`
excursions, so a union bound gives count loss at most `M*(M+1)*p_L` in
expectation. If `B_M=sum_{n>M}P(N_T>=n)` is the renewal tail bound, then

\[
E[N_T1\{N_T>M\}]\le(M+1)B_M,
\qquad
0\le E[N_T]-E[N_T^{\rm lower\ killed}]
\le M(M+1)p_L+(M+1)B_M.
\]

At `M=23` the resulting count bound is `1.415184e-11`. This bounds the
**continuous lower-domain count error**, not the finite-grid discretization
error. It also does not bound derivatives merely because the count error is
small. Total gradient errors are measured directly against the unrestricted
renewal oracle; no certified uniform lower-domain gradient estimate is claimed.

The audit does not cover low-noise limits, OU drift, coupled cells, nonlinear
moving boundaries, arbitrary reset maps, or changed recovery distributions.
The earlier low-noise coarse-grid failures and 5% local variance gate remain
unchanged. Finite numerical exponentials and quadrature carry estimated
floating-point error, not interval certificates.

## Reproduce in a fresh output directory

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution --output /tmp/renewal-audit.json
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m tools.hcsn.round8_20261031.event_dynamics.renewal_resolution_extension --baseline /tmp/renewal-audit.json --output /tmp/renewal-extension.json
```

The first command intentionally exits nonzero while saving its full original
failure record. Run the second command separately; do not chain it with `&&`.
Outputs use exclusive creation so earlier attempts cannot be overwritten.
