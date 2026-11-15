# Stable active-bin probabilities: independent repair and admission

## Result

The new candidate passed all 75 CPU qualification tests, the existing four-fixture
numerical budget, and the independently declared localization v2 budget. The
original 28-file source and failed v2 attempt 001 remain unchanged. Attempt 002
is a different 29-file source snapshot: three source paths changed or added.

This result admits only the exact frozen physical initialization, grid, gaps and
unconditioned schedules recorded in the v2 profile. It does not certify the
subsequent observation-conditioned neural process or trainable physics.

## Failure reproduced without changing the probability law

The old active-cell evaluator subtracted adjacent survivor probabilities.
At duration 0.0810876, with the default physical initialization and the
256-active-cell spatial refinement, two source quadrature points produced a
negative first-bin probability:

| Source margin x | Destination bin | Old FP64 result | Independent positive-density reference |
| --- | --- | --- | --- |
| 0.8222875841068623 | [0, 0.009375] | -1.1102230246251565e-16 | 1.11885857336992304804e-16 |
| 0.8226885933231197 | [0, 0.009375] | -1.1102230246251565e-16 | 1.08332343809721382823e-16 |

Both old results subtract the rounded survivor values
0.9999999999999996 and 0.9999999999999997. The complete 80-decimal-digit working
precision diagnosis preserves the exact binary FP64 source coordinates,
parameters, bin edges and both independently evaluated positive integrals in
attempt-002/negative-bin-diagnostic-extended.json. The earlier attempt's
original diagnosis is also retained.

For s = sigma sqrt(t), the killed transition density is

\[
p_t(x,y)=\frac{\phi((y-x-\mu t)/s)}s
-\exp(-2\mu x/\sigma^2)\frac{\phi((y+x-\mu t)/s)}s,\qquad y>0.
\]

The reflected/free density ratio is exp(-2xy/(sigma squared times t)).
This gives an independent positive integrand for verification:

\[
p_t(x,y)=\frac{\phi((y-x-\mu t)/s)}s
\left[-\operatorname{expm1}\!\left(-\frac{2xy}{\sigma^2t}\right)\right].
\]

The repair integrates the two Gaussian terms as direct interval masses and
subtracts their logarithms with expm1. For a Gaussian interval [a,b], the
right half-line uses the equivalent survival difference Phi(-a)-Phi(-b);
the other branch uses Phi(b)-Phi(a). Branch arguments are selected before
log-difference evaluation. An unused subtraction of two values near one
therefore cannot inject log(0) or NaN into the backward graph.

The tail coefficient remains the direct survivor at L. It is never reconstructed
as one minus the finite-bin sum. The strict nonnegative/mass checks remain.
There is no clipping, row renormalization, tolerance exemption, parameter change,
or relaxation of numerical admission thresholds.

## Focused regression evidence

The added tests check the original rare-bin trigger against the independent
80-digit reference and positive-density Simpson quadrature; CDF/SF extreme
tails and analytic endpoint derivatives; reflected-bin first-order physical
derivatives against finite differences; and the complete triggering
256-cell operator.

All four passed within the 75-test run. The repaired first trigger is
1.1188585733699357e-16, with relative error 1.1324274851176597e-14.
The full triggering table has minimum coefficient zero and maximum row
mass residual 2.220446049250313e-16. First-order AD remains the declared
derivative scope.

## Localization v2 measurements

All measured values below use the thresholds locked before attempt 001.
The repair did not alter the grid, physical initialization, tick conversion,
selection, refinement anchors or acceptance limits.

| Measurement | Maximum observed | Locked limit |
| --- | ---: | ---: |
| Common-prior perpetual value relative/scaled error | 0.0020855629019780526 | 0.01 |
| Space refinement delta | 0.0017234743105992492 | 0.005 |
| Phase refinement delta | 0.00002154699219006264 | 0.005 |
| Tail refinement delta | 0.00023339675335488845 | 0.005 |
| Time refinement delta | 0.002282949087289029 | 0.005 |
| Quadrature refinement delta | 2.468508649570437e-10 | 1e-5 |
| Rounded linear-solve residual error estimate | 6.585372225579775e-13 | 2e-10 |
| One-step row mass error, all 325 distinct gaps | 5.551115123125783e-15 | 5e-11 |
| Unconditioned sequence continuation error | 0.0008784401090655221 | 0.01 |
| Unconditioned sequence mass drift | 6.217248937900877e-15 | 2e-6 |

The 26 locked distinct gaps include zero; perpetual resolvents are evaluated
only at positive duration. Six predeclared refinement anchors completed.
The exact continuum common-prior reference is 4.833436710969065.
Initial representation error is 9.864191033370662e-6 on the same scale.

The largest rowwise perpetual discrepancy is 0.016974039199635815. This is a
diagnostic outside the common-prior gate, and prevents extending the admitted
initial-law result into a uniform all-state claim.

The full A01 128-event sequence continuation error is 0.0008784401090655221;
D01's 64-event prefix is 0.0005444433552169784. Four original 32-event A01
schedules range from 0.0002952796858358107 to 0.0003077034043827476.
All schedules accumulate discounted running/event rewards and pay the closing
continuation once. A01 windows 2–4 retain their original first gap, matching
the actual interface runner. Complete A01/D01 sequences begin with zero gap.

Refinement deltas are sensitivity measurements. Repeated QPR projection means
that halving a step can increase fixed-basis error; these deltas are neither
independent additive error components nor rigorous error bounds. Observation
filtering and learned content feedback may amplify transport differences.
This unconditioned qualification supplies no bound for that closed neural
feedback process.

## Retained receipts and provenance

Native job: 1a1bae6f182-12894-1e31, completed with exit code zero, no timeout,
complete durable logs, CUDA disabled, one CPU thread and 2-GiB memory limit.
The v2 budget took 82.18351104785688 seconds, with peak RSS 821989376 bytes.
The mathematical test stage took 30.685890448046848 seconds including process
startup; the original four-fixture budget took 20.412979716900736 seconds.

| Artifact | SHA-256 |
| --- | --- |
| Independent repaired source ZIP | cb49a5f1aa24e15e25f46dd9fc8722de8fba4fa471d69a52142d37e8d98c3a2a |
| New locked v2 profile | a6661067b366f386d96782687dee6ace5718ffcd8148b2def3bca286c7293600 |
| 29-file source manifest | a0e067b9c7403d0ba2a683307f82ed0d461f771200a84de63e5dd1426fdd3bc3 |
| Locked budget runner | f8f411e1e3c7a13c9f5a4c6d94b631201506c143e0c2232cce60d68ede11b05b |
| 75-test qualification JSON | 9610040fd99f9501ba4d1cfc047517101d0142bfa3994073a68b797d59c5df34 |
| Original four-fixture budget JSON | e9c4a749bb8740ee5ae662fef677983910d014f27de2019ffb09d3c635bed48f |
| Complete v2 result JSON | 1c31a015de53ad720bfa7ac3e952fdbe494a8251161f5741c49239b247a53ddc |
| Attempt 002 evidence ZIP | 0712c39e9ed2836a15ed191867f6d4777f49ae7bf62021dbc04bc1422ba02a30 |

The three source paths are operator.py, MODEL.md and the new
tests/test_probability_intervals.py. stable-intervals.patch is the small
reviewable implementation stage. Its original baseline remains in the frozen
candidate; repair-source is the separate measured candidate.

No training run or model-effect claim is included in these receipts.

