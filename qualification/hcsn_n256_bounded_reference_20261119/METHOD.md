# An independent bounded reference for the retained N256 first step

This study evaluates all 69,728 coordinates of the retained `warm` state at
`t=1/1000`. Its inputs are the original exported binary64 nodes, probability,
four signed-content channels, eight constant-source packets and physics. It
does not rerun either archived matrix solver or the multistep experiment.

## Mathematical target

`inputs.py` decodes the JSON and the NPY payload independently and requires
identical input bytes. It assembles the original scalar operation order using
exact rational arithmetic and an integer implementation of binary64
round-to-nearest, ties-to-even. Each assembled entry is an exact binary64
rational. The two target operators are

`B = RN(A_fp * dt_fp)`, with orders 258 and 259 respectively. The target action
is the exact real `alpha_fp exp(B)`. The second operator includes discount,
first-hit and occupation accumulator coordinates. The initial permanent-upper
occupation is evaluated separately as
`u_fp (1 - exp(-RN(rho_fp * dt_fp))) / rho_fp`; this study requires `rho_fp>0`.

The complete target includes all active coordinates, permanent-upper state,
ordinary/discounted first hits, occupation, and every packet's generator,
initial coefficient and output vector. Known invariant source coefficients
remain exact point intervals after checking that the propagated enclosure
contains them. The static generator and source fields are independently
assembled before either archived output is read.

## Enclosure argument

For the row-vector action, choose integer `q >= max(-B_ii,0)` and set
`D=B+qI`. This is a nonnegative matrix. Then

`alpha exp(B) = exp(-q) sum_{k>=0} alpha D^k/k!`.

Each recurrence propagates signed lower and upper endpoints through the
nonnegative coefficients. Integer floor and ceiling at every multiplication
and division provide outward rounding. The finite sum is also accumulated
with exact integers. If `w` is an integer upper bound for the maximum row sum
of `D`, each omitted component is bounded in absolute value by

`||alpha||_1 sum_{k>K} w^k/k!`.

For `K+2>w`, successive omitted scalar terms have ratio at most `w/(K+2)`.
The geometric-tail bound includes the outward-rounded first omitted term.
The same positive series constructs an enclosure of `exp(q)`; taking its
positive rational reciprocal encloses `exp(-q)`. The four endpoint products
handle negative channels. The final dyadic output interval is rounded outward
once more. No floating-point numerical operation or transcendental routine
participates in this enclosure calculation.

For the independently assembled unscaled matrix, let
`E=A_fp*dt_fp`, `delta=||B-E||_infinity` and let `g` be the nonnegative maximum
of the row sums of `B` and `E`. The Metzler logarithmic norm bound and
Duhamel's identity give

`||alpha (exp(B)-exp(E))||_1 <= ||alpha||_1 delta exp(g)`.

This additional bound concerns entrywise time-scaling rounding. It does not
bound spatial discretization, the earlier scalar generator assembly, or the
unprojected continuous diffusion.

## Decisions fixed before execution

At each precision level, all coordinates receive intervals. The primary
reference gate is maximum interval width at most `2^-120`. Candidate absolute
errors are then bounded directly against these intervals, including signed
content. The separate new finite-matrix diagnostics require maximum absolute
error at most `1e-12` and total absolute error at most `1e-9`.

Unique binary64 rounding is reported separately. Endpoint rounding to the
same bit pattern proves that pattern for the exact coordinate, including
normal and subnormal cases. Intervals crossing zero may fail this test even
when their absolute width is tiny; no clipping is used. Exact rational zero
has the canonical positive-zero encoding, while archived negative-zero bits
are still compared as actual bytes. An unresolved rounding coordinate is
retained explicitly.

The fixed adaptive roster is 256, 512 and 768 fractional bits, two actions at
each level, and `K=2048`. It stops early only if both the width gate and all
69,728 unique-rounding checks succeed. Otherwise it exhausts this roster and
reports the width and rounding outcomes separately. It never retries an
authentic attempt. The original dense/sparse comparison remains RED with
1,291 mismatches; neither this reference nor the diagnostic absolute bounds
changes its zero-bit-mismatch requirement.

The result is one fully retained finite-generator first step. Continuum,
gradient, training, full-domain and production qualifications remain separate.
