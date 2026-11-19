# R3 completed: integral Stem, structural fidelity and solver comparison

## Executed result and source

All 50 frozen fresh-process runs completed, zero failures: 40 actual fits changed
weights, nine initial-model controls, and one direct reference. This is an actual
CPU/FP64 experiment in the assistant container, not a project-cloud or native
Neuron deployment. Core source commit b21692769c53d837b4bb68424898814a136c711a
is stacked on parent 50550e6b6625f18d809649c595d595a873ad97e0. The four new
Python files and protocol were refetched and their Git blobs matched the exact
executed bytes. Original nine top-level Python files remain unchanged.

64/64 source/math tests passed, zero skips. Four additional real-evidence tamper
tests passed after the sweep, including under python -O: incomplete census,
prediction bytes, a rehashed false metric, and rehashed interval metadata.
The post-seal audit reverified all plans, identities, selected/initial weights,
metrics and 11 freshly recomputed Decimal-50 references, plus an independent
matrix-power probability check. All 550 panels were replayed exactly, maximum
error 0.0 over 1,593,600 scalar predictions. There are 49 saved models including
untrained controls. Twelve B/C pairs have exact same initial bytes and 65 weights.
These repeated replays are not additional independent efficacy samples.

## Main outcome

Mean RMSE across seeds 11/23/47 at the nominal 8-second training CPU cap and
64 intervals. Scalar entries are single fixed-initialization controls. A has
665 parameters, B/C families each have 65, and scalar controls have one. Parameter
count equality across different families is NOT function-class equality.

| Family / optimizer | New composed | New uniform | Horizon 8 | 192-state world |
| --- | ---: | ---: | ---: | ---: |
| Transformer / Adam | 0.00913918 | 0.00742545 | 0.00547337 | 0.00666914 |
| Raw / Adam | 0.00779352 | 0.00563439 | 0.00524177 | 0.00550450 |
| Raw / TRF | 0.000621790 | 0.000394854 | 0.000309860 | 0.00293472 |
| Mixture / Adam | 0.000839668 | 0.000833293 | 0.000563056 | 0.000843890 |
| Mixture / TRF | 0.000848575 | 0.000842663 | 0.000569442 | 0.000867107 |
| Integral / Adam | 0.000188483 | 0.000137783 | 0.0000981368 | 0.000141206 |
| Integral / TRF | 0.0000327457 | 0.0000191316 | 0.0000135959 | 0.0000208322 |
| Integral / L-BFGS | 0.0000508907 | 0.0000381161 | 0.0000272182 | 0.0000327434 |
| Untrained integral | 0.0547912 | 0.0552506 | 0.0456727 | 0.0538128 |
| Scalar / Adam or TRF | 0.0000365428 | 0.0000403483 | 0.0000278127 | 0.0000327538 |

The frozen primary integral C/TRF versus B/Adam comparison is won in all three
paired initializations. New-composed B/C error ratios are 2.86944, 23.05131 and
7.00423; the ratio of means is 5.75595. C also has lower error than same-family
L-BFGS in all three seeds, but the seed11 margin is small. This is finite-law
operator recovery on known coefficients, not a general statistical superiority
or natural-language result. The same 32 functions are reused across seeds.

The new uniform/composed functions have zero identity overlap with R2. One of
32 independently generated indicator functions coincides with an R2 indicator;
this is disclosed and retained without replacement. Randomly generated seeds
are not independent application domains.

## The prior mixture's representation bottleneck is overcome

The old two-temperature mixture has an analytic relaxed full-objective lower
bound evaluated numerically at 4.460276410094337e-7 on the unchanged training
law. Integral C attains training MSEs 8.1419191294e-11, 5.1812297703e-11 and
2.4768872663e-11. This comparison concerns different function classes, not a
solver-only improvement. The formula and numerical lower bound are not
outward-rounded interval certificates or claims of global optimality.

A constructive, NONTRAINED witness sets F=1 and linearly interpolates the true
entropic derivative on the grid. On training terminals, max errors at
16/32/64/128 intervals are 0.00252446903 / 0.00063363137 / 0.00015922950 /
0.00003941689. No learned parameter count increases. For target derivative
q*(u)=sigmoid(logit(p)+u), |q*''|<=sqrt(3)/18. Within the grid, the one-step
witness value error is <=gamma*|a-b|*(sqrt(3)/18)*h^2/8, h=8/N.
Thus the old fixed-mixture floor does not apply as this class is refined.
This is an explicit entropic inductive prior, not an approximation theorem for
all recursive utilities or a discovery of a general representation.

Actual seed11 C fits at 16/64/128 intervals give new-composed RMSE
0.0006794555 / 0.00006307499 / 0.00002382566. These are separately fitted,
equal-cap resolution diagnostics, not fixed-weight refinement, not three-seed
confirmation and not a post-hoc choice of the primary grid.

## Single-coefficient transfer and structure

Mean RMSE at the same 8-second cap:

| Change | Raw C | Mixture C | Integral B | Integral C |
| --- | ---: | ---: | ---: | ---: |
| Cost zero only | 0.249228 | 0.000838824 | 0.000134929 | 0.0000190302 |
| Discount one only | 0.0933985 | 0.00100804 | 0.000166581 | 0.0000223995 |
| Indicator terminal only | 0.000335781 | 0.000727448 | 0.0000895466 | 0.00000768132 |
| Joint probability | 0.188223 | about 4e-17 | about 4e-17 | about 4e-17 |

The new cost/discount robustness is a useful measured result. Probability
correctness, however, holds for EVERY integral and scalar model even before
training: q(0,p)=p and the primitive's correction vanishes at rho=0. It is a
built-in invariant, not learned transfer. No prediction clipping is used.
All trained/untrained integral variants have zero raw out-of-range probability;
the maximum numerical invariant-probe discrepancy is 6.6613381478e-16.
These finite probes support, but do not replace, the real-arithmetic derivation.

## Important contrary evidence, not filtered

First, the scalar control is very strong. The one-parameter slope fitted with
TRF reaches new-composed RMSE 3.6542773081e-5 in 0.996264627 CPU seconds;
Adam reaches the same result in 8.004987151 seconds. It is close to the mean
65-parameter C result and beats one of those three C models. Both use the
same integral representation, not the exact target CE evaluation. This task is
largely solvable by entropic slope calibration; it cannot establish that 65
parameters or general feature learning are necessary.

Second, more solving does not uniformly improve transfer. C seed11 moves from
new-composed error 3.3879100773e-5 at two seconds to 6.3074986871e-5 at eight;
seed47 moves from 1.5901170510e-5 to 2.6551653740e-5. Training residual decreases
in both. Seed23 improves. These are two independently timed runs from identical
initial weights, not held-out checkpoint selection. We did not switch the
primary budget to two seconds after observing these outcomes.

Third, four-times-amplitude tail_spread remains difficult. About 3.9931% of the
integral C continuation evaluations fall outside the derivative grid. C's mean
RMSE rises to 0.00447888 versus 0.0119761 for integral Adam and 0.00324244 for
the scalar control. Constant tails preserve order/range, not accurate extrapolation.
Boundedness and in-distribution error are not a general OOD guarantee.

## Decisions and full work accounting

On the fixed exogenous price grid for new composed contracts, integral C and
both scalar controls have zero regret and 100% non-tie accuracy. Integral Adam
has mean regret 3.550566e-8 and accuracy 99.9762%; L-BFGS has 1.320001e-9 and
99.9898%. These are small, correlated numerical choices, not an independent
language-answer benchmark. All original unpriced and priced metrics remain.

The 50-run sweep took 542.253857365 seconds wall and 540.661884 whole-child CPU.
Fitting consumed 265.745493473 CPU seconds; oracle/scoring/save 114.893420134;
prediction/seal 2.515803791; diagnostics/replay 1.814324317. Whole-child totals
also include imports and remaining process overhead. The extra complete audit
used 6.895733920 CPU seconds; four tamper tests took 26.768 seconds wall. Multiple
development and frozen source tests, the initial smoke, source publication and
unmeasured tool/provider work are additional, not claimed free or fully metered.

Main integral B fits use 8.00036--8.00622 CPU seconds. C uses 8.03108--8.06371,
with 73--83 full Jacobians and 4,745--5,395 forward-AD tangent lanes. The largest
grid128 diagnostic uses 8.09925 CPU seconds. One-operation cap overshoot is
reported; no dummy equalizing work, exact-FLOP or exact-time matching is claimed.
Main integral C peak RSS is 383,254,528--388,763,648 bytes, versus integral B
363,765,760--365,113,344 bytes, including runtime allocation. Total FLOPs, GPU
peak and energy remain unknown rather than imputed.

## Interpretation and next target

This completes the richer structure-preserving numerical operator experiment:
learned coefficients beat the old mixture's bias, and full-equation solving
improves the matched-family primary metric while retaining structural guarantees.
The target still has a simple known entropic form. C remains reduced-space
collocation on a known forward law, not a jointly learned forward-state/preference
and backward adjoint system. No universal LLM/world-model conclusion follows.
The next substantive task is a non-scalar-reducible multi-task forward/backward
problem with trainable shared representation dynamics, independent solution
verification, the same-family B/C control and the scalar baseline retained.
That next task has not been executed in this record.

All source, raw arrays, individual weights, plans, logs and failed/contrary
outcomes are retained. The new CI is a separate required check; local success
is not full GitHub/Rust/Bazel or native-device acceptance. No main/CURRENT,
production model, native Q24/Q32 contract or deployment authority is changed.

Six primary B/C tensors are also published as exact little-endian hexadecimal
files in integral_primary_hex/. All six remote Git blob identities were reread
and match the locally decoded and replayed originals. A previous oversized
single-JSON transfer was truncated and rejected by its hash; that object is
not referenced by any published tree. The original local packet is unchanged.
