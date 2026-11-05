# Native constrained-edit numerical contract

This document specifies the mathematical and representation boundaries of the
follow-up implementation. Execution outcomes, source identities, and measured
costs are recorded separately; this specification alone is not a test receipt.

## Fixed supervised subproblem

For each output j, let X be the feature matrix, W_j the nonnegative diagonal
sample-weight matrix, y_j the targets, and b0_j the source anchor. The optional
hard-budget problem is

    minimize sum_j [ ||sqrt(W_j)(X b_j-y_j)||_2^2
                     + lambda ||b_j-b0_j||_2^2 ]
    subject to sum_j ||b_j-b0_j||_2^2 <= r^2.

lambda is positive and finite. Each output may have different sample weights.
The radius is shared by all outputs; it is not independently available to each
row. There is no implicit sample-count normalization.

With delta_j=b_j-b0_j, H_j=X^T W_j X+lambda I and
c_j=X^T W_j(y_j-X b0_j), the real-arithmetic KKT equations are

    (H_j + mu I) delta_j = c_j,
    mu >= 0, ||delta||_2 <= r, mu (||delta||_2^2-r^2) = 0.

The positive-definite H_j makes the unconstrained real problem strictly convex.
If its solution is outside the ball, a common nonnegative multiplier is found
by a bounded bracket and bisection. Each shift requires an actual solve and
counts against the pre-admitted arithmetic budget. No gradient update is used.

r=0 is a singleton feasible set. Its answer is the anchor even when the usual
finite-multiplier stationarity equation cannot hold. A singleton result must
not report a fabricated finite KKT multiplier.

Floating-point stationarity and radius diagnostics qualify only the stated
numerical checks. They do not constitute an outward-error proof of exact-real
global optimality. A Frank-Wolfe diagnostic uses the same objective scaling:

    2 [ sum_j (H_j delta_j-c_j)^T delta_j
        + r ||concat_j(H_j delta_j-c_j)||_2 ].

## Actual F32 edit feasibility

Budget-mode anchors must be exactly representable finite F32 values. Source
authentication is still a separate guard responsibility.

Every finite F32 x can be represented exactly as I(x) * 2^-149, where I(x) is
a signed integer with magnitude less than 2^277. Consequently, for at most
1024 before/after pairs,

    S = sum_i [I(after_i)-I(before_i)]^2 < 2^566.

Nine 64-bit limbs, 576 bits total, suffice for S without rounding. If the
supplied finite F64 radius is m * 2^e, its exact squared value is
m^2 * 2^(2e), where m^2 needs at most 106 bits. The admission predicate is

    S * 2^-298 <= m^2 * 2^(2e).

This comparison does not square r in floating point, take a rounded square
root, or add a numerical tolerance. Subnormal numbers and exponent-extreme
radii are part of the contract.

The planner first lowers F64 coefficients toward their exactly represented
F32 anchors and then performs this independent exact comparison. It rejects
a proposal whose actual represented changes cannot satisfy the budget.
F32 feasibility and F32 optimization are distinct: this lowering does not
claim the optimum over all F32 parameter choices.

Positive and negative zero have numerical difference zero, although their
bytes can differ. A zero numerical norm does not by itself mean byte identity.

## Authentication and scope

The guard recomputes the budget from the exact expected/replacement F32 bytes.
The existing patch path separately authenticates the full source SHA, tensor
layout, distinct edit addresses, and old bytes before publication. Planner
claims alone cannot authenticate a checkpoint.

The optional bound applies to this one patch. It does not bound cumulative
drift across successive edits, externally supplied bias, a different model
component, or an unbound task environment. Acceptance still requires the
existing strict score condition gain > minimum_gain and all declared output
constraints.

An accepted finite-row score is not independent holdout qualification, full
policy value, a production activation, or a crash-recovery journal. Existing
negative and unknown outcome semantics remain explicit.

## Independent checks

Independent verification should compare represented-number budget decisions
with Python Fraction or another exact dyadic implementation, including
nextafter boundary cases, signed zero, finite exponent extremes and the
maximum admitted element count. The convex solution should also be compared
with an independently constructed reference using identical anchors, weights,
targets, lambda and a single shared radius.

A real Hepta fixture whose original head is F64 needs an explicitly identified
F32 derivative before invoking the budget-mode planner. Its results cannot
silently inherit the original F64 whole-policy qualification.

