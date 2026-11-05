# What the TRAIN certificates can establish

All quantities in this note refer to the five frozen renewal checkpoints and
their original TRAIN full-state enumerations. They are not new validation or
test observations. A proof that one label system cannot be represented is not
a proof that no useful policy can be represented.

## 1. Fixed representation and the actual score path

The frozen deployed feature is a 49-vector `h`: 48 tanh hidden coordinates plus
a constant bias coordinate. The ordinary head has four affine outputs. The
first three are WAIT, READ and REPAIR scores. The fourth passes through the
fixed sigmoid decoder to give the complementary SUBMIT scores. STOP has score
zero. After applying the six-action legal mask, execution chooses the first
maximum.

The checked source returns the explicit binary64 product-and-sum result
`np.sum(theta * h[None, :], axis=1)`. Its BLAS product is an arithmetic audit,
not the score returned to the policy. All certificates bind the actual stored
binary64 feature values. They do not assert that the tanh operation itself was
evaluated in exact real arithmetic.

## 2. Exact feature aliases

Suppose two rows from the same fit have identical raw bytes for all 49 hidden
coordinates and the same complete legal mask. A deterministic fixed head and
decoder must return the same score vector and action on both. If the frozen J
program chooses different actions, no such head can reproduce both labels.
This conclusion permits arbitrary changes to all four output heads and does
not require a parameter budget.

The diagnostic keeps every conflict with the first row in the same feature
and mask class, and retains the first complete double-row witness. It does
not select a witness by its return or margin. The teacher's exact stored-Q
best-versus-runner-up gap is reported for both rows so that a near tie cannot
be mistaken for a demonstrated large value loss. The independent verifier
reconstructs both feature vectors and the corresponding own-law J tables.

This is a statement about copying this deterministic label map. An equally
good policy may choose another action at a tie. The two rows may be off-policy.
The statement supplies no lower bound on actual expected task-value loss.

## 3. A necessary continuation subsystem

Let `C` denote the three incumbent continuation rows, each of length 49, and
let `delta` be an arbitrary real displacement of their 147 stored coefficients.
The declared joint budget is

    ||delta||_F^2 <= R^2,       R^2 = sum(C_ij^2) / 4.

The squares and sum above use the exact dyadic values of stored C, not a
rounded norm. This ball contains every stored-F64 edit satisfying the original
declared budget; the earlier solver's inward numerical safety radius is not
substituted for it.

For every TRAIN row whose J action is a continuation, compare it with the
other legal continuation when one exists. Let `a` be J's action and `b` its
competitor. The corresponding row of A contains `+h` in block a and `-h` in
block b. In ideal affine arithmetic, a necessary weak ordering is

    A (C + delta) >= 0,       A delta >= b0,       b0 = -A C.

Every product in b0 is formed from the exact stored coefficients. A rounded
incumbent forward is not treated as an exact right-hand side.

If action b precedes a, actual first-max execution requires a strict win.
The diagnostic deliberately relaxes this to a weak win. It also omits all
terminal, STOP and Belief comparisons. Thus infeasibility is useful, but
feasibility of this relaxed subsystem does not establish J realizability.
No positive margin is imposed or searched in this experiment.

## 4. A sufficient, exact separation certificate

For any nonnegative vector y, put

    v = A^T y,       d = y^T b.

If a feasible delta existed, its constraints and Cauchy-Schwarz would give

    d <= y^T A delta = v^T delta <= R ||v||_2.

Consequently, the two exact tests

    d > 0,          d^2 > R^2 sum(v_i^2)

certify infeasibility. Requiring positive d before squaring is essential.
Equality is not a certificate. A zero multiplier never establishes a strict
separation. No approximate condition `A^T y = 0` is needed.

The search may supply any finite nonnegative binary64 y. Those supplied
numbers are interpreted as exact dyadic rationals. Both the producer and a
separately written verifier accumulate the vector and test the squared
inequality with `Fraction`. Optimizer termination, an infeasible status,
floating-point residuals or a negative numerical objective are not proofs.

The numerical search is the nonnegative smooth dual

    minimize 0.5 ||A^T y||_2^2 - b0^T y.

It is used only to find a witness direction. Its iteration and CPU budgets
are fixed. It is not rerun with a different margin when it finds no proof.

## 5. The stronger bound needed for binary64 execution

An exact-real affine impossibility alone need not exclude a rounded forward
near an action tie. The diagnostic also tests a more permissive necessary
system that accounts for dot-product error uniformly over the entire ball.

Let `u=2^-53`, `eta=2^-1074`, `Ru=ceil(sqrt(R^2))`, and

    gamma98 = 98 u / (1 - 98 u),
    S_j = sum_i |C_ji| + 49 Ru,
    E_j = gamma98 S_j + 98 eta / (1 - 98 u).

Every retained hidden coordinate is checked finite with absolute value at
most one. The displacement of any individual coefficient is at most R, so
S_j bounds the absolute product sum for each head. The source guard bounds
all possible partial sums below `2^1000`, far below overflow. The eta term
is deliberately larger than a half-subnormal rounding allowance.

Under binary64 round-to-nearest with gradual underflow, separately rounded
products and at most 48 additions for a 49-term dot, E_j bounds the absolute
score error regardless of the addition tree. Actual rounded weak ordering
therefore implies

    A delta >= b0 - E_a - E_b.

The same y is checked against this relaxed b using exact fractions. A passing
certificate excludes the specified action comparisons under these declared
floating-point semantics. If only the ideal-real certificate passes, the
report must retain that narrower result. The environment probes describe the
observed run and do not certify every possible hardware or library build.

## 6. A useful analytic feasibility check

Set every continuation row to the exact coordinate mean of the three C rows.
If the exact squared displacement fits in the actual Frobenius ball, all
continuation scores are equal in ideal affine arithmetic. Every weak pair
constraint is then satisfied, irrespective of h. The rounding-relaxed system
is also feasible.

This is a mathematical construction, not a saved or deployed model. It makes
searching for a separation certificate of that weak subsystem pointless, so
the fixed protocol skips that search. It says nothing about a correct
first-maximum READ or REPAIR choice: WAIT precedes them in the action order.

## 7. Remaining scope

The complete TRAIN enumeration contains off-policy states and charge aliases.
Neither type of certificate identifies an expected utility loss, an optimal
repair, or the smallest sufficient representation. These are fixed-representation
diagnostics. A representation change, more information in the decoder, a
different feasible policy, or a different objective may behave differently.
The already established structural J task benefit and the failed head edits
remain the only prior held-out science; this diagnostic adds no new efficacy
sample, Trader result or production authorization.
