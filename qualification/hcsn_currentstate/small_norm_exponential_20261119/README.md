# Restore small-norm exponential accuracy and differentiability

The retained scalar regenerative test at `rate=1.7`, `delay=1/5`, `T=61/100`
exposed a real error in the native Torch 2.8.0 CPU matrix exponential. The
original strict test remains unchanged. This change closes that failure for
the current complete-state operator and also repairs the larger FP32 region
affected by the same polynomial.

## Root cause and retained negative evidence

An independent 80-decimal matrix/reference diagnostic evaluated the exact
saved FP64 matrices. Four matrices of orders 6, 9 and 10 have one-norm `.034`.
Their native exponential has maximum absolute error `1.1433324330207104e-11`;
SciPy's result for the same matrix differs from the 80-decimal reference by
at most `8.94e-18`. Replacing only matrix-exponential values in the scalar
trajectory reduces its independent Gamma-reference error from
`6.68773624090388e-12` to `1.0708624812282554e-16`.

The upstream [Torch v2.8.0 `compute_T8` source](https://github.com/pytorch/pytorch/blob/v2.8.0/aten/src/ATen/native/LinearAlgebra.cpp)
is bound to Git blob `2d7c2ff067c69a813588a1bd0e072ea763de8ef0`.
The exact symbolic audit shows that its fifth through eighth polynomial
coefficients differ from Taylor's coefficients. With `x3=2/3`, the published
`x7` denominator is `5040*x3`; changing that denominator to `5040*x3*x3`
restores all coefficients through degree eight. The complete exact
`Q(sqrt(177))` calculation and original result are retained.

FP32 is also affected. For `diag(-.5,-.25)`, native matrix-exp differs from
the correctly rounded FP32 scalar exponential by **2.0623207092285156e-5**.
The repaired operator returns the same FP32 values as that scalar reference.
The initial FP64-only repair, its source commit, and all its successful
checks remain available as a separate development stage; the final profile
includes both dtypes.

## Implemented calculation

`Work.exponential` uses degree-12 Taylor evaluation in Horner form for:

| Tensor dtype | Computed matrix one-norm region | Exact-series remainder bound |
|---|---:|---:|
| FP64 | at most 0.1 | below 1.78e-23 |
| FP32 | at most 0.6 | below 3.83e-13 |

These are mathematical truncation bounds, `exp(r)*r^13/13!`. Floating-point
roundoff is assessed separately by the retained high-precision comparisons;
the bounds alone are not a floating-point error guarantee.

All Horner operations are Torch tensor operations and stay in the autograd
graph. The detached norm selects the numerical branch. Larger matrices in
norm continue to use native matrix-exp. Existing matrix-order, packet and
logical-action limits remain active. `Work` now exposes separate
`small_norm_exponentials` and `native_exponentials` counters alongside the
logical total, so twelve Horner products are not described as one native
matrix-exp call.

## Executed final-profile checks

The final kernel SHA-256 is
`e1731b349de811177dc402ee0ee70f08a25289bb844837b679cabef2d63bdfb6`.
`REQUEST_FP32.json` was frozen before the two final verification children.
All **35 core and network tests** pass, including the unchanged strict
`T=.61` values, first derivatives and second derivative; all eleven saved
high-precision problem matrices; branch-boundary controls for both dtypes;
complete network state, input/content/physics derivatives; reset snapshots;
and cold-state continuation. The CI workflow includes both added regression
modules on the published head.

| Original strict `T=.61` quantity, FP64 | Final absolute error |
|---|---:|
| Active/hit/waiting values | 4.440892098500626e-16 |
| Weighted rate gradient | 0 |
| Content gradient | 5.828670879282072e-16 |
| Weighted rate second derivative | 4.163336342344337e-17 |

The original tolerances remain `atol=3e-13`, `rtol=3e-12`. This trajectory
performs eleven logical actions: four Horner actions and seven native calls.

The changing-delay/reset/reward/discount study was rerun on the final kernel.
Its full-field error against the independent delayed ODE is
`3.3306690738754696e-16`, balance error `4.440892098500626e-16`, independent
ODE finite-difference gradient discrepancy `3.312292141954831e-10`, and
fresh-process cold-continuation discrepancy `1.1102230246251565e-16`.

A separate agent checked noncommuting 3-by-3 matrices with 80-decimal block
exponentials for values, first Fréchet derivatives and mixed/ordinary second
derivatives. Each review used four predeclared norms straddling its branch
boundary and 28 high-precision block exponentials, with no dataset or
optimizer calls. Every planned gate passed:

| Independent review stage | Maximum value error | Maximum gradient error | Maximum Hessian error |
|---|---:|---:|---:|
| FP64-only source snapshot, unchanged FP64 arithmetic | 3.33067e-16 | 1.38778e-17 | 1.30104e-18 |
| Final FP32+FP64 source, FP32 inputs | 9.40981e-8 | 1.30780e-8 | 7.92871e-10 |

The full 35-test and delayed-ODE results above are bound to the final source.
The first peer-review snapshot is kept under its original hash rather than
being relabeled as a new final-source execution.

## Complete costs and original artifacts

The final regression child used **12.718117 wall seconds / 12.664961 CPU
seconds**, with **295,076 KiB** peak RSS. The final changing-law child used
**9.873107 wall seconds / 9.744735 CPU seconds**, with **258,104 KiB** peak RSS.
Both exited zero within their CPU 7 / 4 GiB / 125 CPU-second / 150 wall-second
limits. The previous FP64-only verification and all diagnostic/peer-review
costs are retained separately; no failed or earlier work is refunded.

`diagnostic/`, `verification001/`, `verification002/`, `independent_fp64/`
and `independent_fp32/` retain the original commands, source hashes, snapshots,
raw matrices, states, reports, stdout/stderr and full child costs. The
upstream symbolic audit has zero model/matrix-exponential calls and reports
its own body time.

This qualification was executed on CPU with Torch 2.8.0+cpu. GPU execution
and TF32 arithmetic have not been qualified. The earlier 831-file task
training archive remains evidence for its original frozen implementation;
these numerical and integration checks do not turn it into a new training
run or establish task accuracy, throughput or energy improvements for this
repaired implementation.
