# R22 independent mathematical diagnosis before new confirmation

This analysis reads the preserved R20 source and raw evidence. It does not
execute a new formal numerical campaign or alter R20 files.

## What the old failures do and do not imply

Both R20 generic campaigns completed all 78 signed-coordinate attempts and
passed 30. Every recorded `unresolved_rows` count was zero. Read-only replay of
all 39 paired positive/negative tangent arrays gives exactly zero oddness
error: `D(+e)+D(-e)=0` at every saved scalar. Thus the generic candidate behaved
as one selected linear local branch on these particular base configurations.
This fact does not independently prove that the branch was correct.

Several old one-sided errors have the expected first-order dependence on the
registered perturbation size. For example, profile 0 sigma minus has errors
`5.7315924e-6` and `1.7194515e-6` at `1e-4` and `3e-5`. Profile 0 reset-position
minus has `2.7781964e-5` and `8.3345873e-6`. Such ratios are consistent with a
smooth finite-step truncation term. Several large fee/cost errors disappear at
the second registered step, consistent with a crossed action boundary. These
are diagnoses to test, not proofs that every failed record has that cause.
The worst old record is profile 1, negative mode-1 reset fee: errors
`1.2711191808` and `.2737303130`. Its failure remains preserved.

With fixed diffusion, reset location, transition matrix and reward slope, the
finite map is piecewise affine in fees, time costs, reward bases and reward
amplitudes. Within one complete policy branch, its one-sided quotient therefore
equals its branch derivative up to numerical solve error. A substantial finite
step discrepancy in those coordinates must be distinguished between a crossed
policy boundary, a wrong branch/derivative, or an inadequately solved reference.
It is not explained by smooth within-branch curvature. Sigma, reset location,
transition probabilities and reward slope have genuine higher-order terms.

An independently evaluated derivative at the same base point can resolve this
question without shrinking finite steps. Agreement with that derivative does
not retroactively pass the old fixed-step `1e-6` gate. Report derivative fidelity
and fixed-step approximation error as separate contracts.

## Ordered dual semantics and its limits

An ordered dual pair `(v,dv)` represents the first-order right germ
`v+epsilon*dv` with `epsilon>0`. Addition and multiplication use the ordinary
dual rules; reciprocal has derivative `-dv/v^2`. Gaussian or tridiagonal
elimination over these pairs differentiates each selected linear policy.
Maximum/minimum compare primal values first. Only at a mathematically equal
primal value may derivative components break the tie. This reproduces the
critical complementarity directional system and the max-of-slopes rule.

Ninety-digit arithmetic is an independent numerical reference, not exact real
arithmetic. A spurious primal difference at its last digit must not override a
known exact tie's derivative. Conversely, treating every small primal difference
as an exact tie changes the original problem. Generic strict rows can report
high-precision residual/slack separation; outward-rounded bounds or exact
algebraic witnesses are needed for a mathematical classification certificate.
Increasing precision and comparing answers is useful numerical evidence but
does not itself supply that certificate.

The zero slack imposed by a particular identity/equation policy row is known
by its construction. That does not establish that its other small slack is
also exactly zero. A reference should preserve known equality metadata, use an
exact witness at structural ties, or expose unresolved classification.

## A nonconstant actual-task tie with an independent exact answer

Keep the original nonconstant logistic rewards with decimal-real parameters
`base=(1/5,1/10)`, `amplitude=(3/4,2/5)`, slope `13/10`; use sigma 1, space
step `1/5`, reset location zero, recovery cost zero and WAIT cost 10. Let the
mode-0 reset fee be `1/10` and the mode-1 fee be exactly `11/160`.

The reward Lipschitz constant is at most
`max(amplitude)*slope/4=39/160=.24375`. Every reflected discrete generator row
therefore satisfies `L_h g <= sigma^2*Lipschitz/dx=39/32=1.21875`. Before the
first admission, `g` is the unique obstacle solution because
`A g - (g-c*dt) >= dt*(10-39/32)>0`. STOP is strict, so every pre-admission left
value is exactly the nonconstant payoff. This proof uses a large positive
margin, not an inferred nearly-zero numerical residual.

At reset/target location zero, sigmoid is exactly one half:

`g_0(0)=23/40`, `g_1(0)=3/10`.

For the original mode-1 transition row `(1/4,3/4)`, the first-reset continuation
is `59/160`. Subtracting the fee `11/160` leaves `48/160=3/10`, exactly equal
to the strict left STOP value at that node. The rest of the spatial reward is
nonconstant. Thus this is an actual nonconstant delayed-task admission tie.

For a positive mode-1 fee direction, STOP slope zero beats RESET slope minus
one, so the directional value is zero at that target node. For the negative
fee direction, RESET slope plus one wins, so the directional value is one.
Their sum is one; no single odd linear Jacobian gives both answers. The answer
follows from the declared task law and exact fractions, independently of a
finite-difference step or high-precision policy solver.

These exact decimal/algebraic model constants must be explicit. The binary64
literal `.06875` is an approximation to `11/160`, and at an action tie input
rounding can change the derivative. Do not confuse a derivative of a binary
rounded coefficient problem with the intended exact algebraic control. The
candidate may receive rounded values together with a qualified exact-tie
witness, or reject unresolved ambiguity; a bare tolerance is not such a witness.
This control perturbs fees only and does not qualify reset-position derivatives
at the interpolation knot.

## Real possible R20 defects to examine

* Generic max comparisons use raw floating strict inequalities. A known
  nonconstant exact tie may be resolved incorrectly by input or arithmetic
  rounding unless the intended model and exact witness are represented.
* Generic critical-row classification is only a floating residual diagnostic.
  It can misclassify a very small nonzero slack as a tie, or the converse, if
  roundoff envelopes are insufficient. Its old scope already disclosed this.
* Fixed-policy tridiagonal differentiation must include `db-dA*v`, both reset
  successor time sides, direct reset interpolation slopes, transition-row
  derivatives and all terminal/obstacle payoff derivatives. An independent
  ordered-dual implementation should recompute these rather than import the
  candidate tangent recurrence.

The old policy-cycle termination defect was separately repaired in R20 V2.
Its preserved residual-based repair is not an explanation for generic V1/V2
results that are identical. No evidence here justifies modifying the old gates,
discarding failures or claiming moving-delay/domain, continuum or complete
financial/neural gradient qualification.
