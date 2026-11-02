# Independent mathematical review

Reviewed2026-11-02 by the independent equivalence/audit agent. This review
concerns the exact synthetic two-mode reflected-diffusion task and the ideal
finite-difference map stated in this directory. No new numerical owner world,
boundary-location result, or convergence experiment was opened for this review.

The stated arguments are sound within their declared assumptions. They supply
a comparison/uniqueness construction and a qualitative ideal-value convergence
argument for this task. They do not close general continuous free-boundary
regularity, continuum parameter-gradient, or actual production qualifications.

## Exact problem and causal recursion

The distinction between active WAIT carry and the fixed recovery charge is
correct. Every reset consumes strictly positive `ρ`; this bounds the number of
resets and makes the delayed operator strictly causal. The successor is the
full value at remaining time `t−ρ` after drawing the next observed mode. It is
not the immediate STOP payoff.

The `G_k/W_k` recursion keeps the previous slab's right initial value and its
separate upper left trace. The compatibility condition `G_k≥h_k(0)` follows
from its definition. At an admission the maximum of the preceding left value
and the new reset value is necessary: any positive initial wait loses the newly
available exact-count reset opportunity. This is a property of the declared
deadline/equality convention, not a numerical smoothing choice.

The stopping-slab proof now specifies relative dyadic partitions. Their nested
Bermudan values are continuous jointly in horizon and state; the established
continuous limit and compactness permit Dini's theorem to give uniform
approximation. A fixed sufficiently fine partition supplies a Borel jointly
selected ε-optimal policy for the finite reset-stage concatenation. This
clarifies a selection detail raised during independent review.

## Reflection and viscosity comparison

The fold to a circle of circumference16 is exact for constant-coefficient
Brownian reflection on `[−4,4]`. Semigroup intertwining passes through finite
max/heat stopping recursions. The limiting value therefore gains no extra
control information from observing a fold phase. Continuous lifted payoffs may
have cusps; classical Neumann compatibility of the immediate STOP payoff is
not imposed.

The scalar comparison argument uses the canonical folded-circle problem.
At a positive subsolution/supersolution gap, the ordered obstacle cannot be
active for the subsolution. The parabolic maximum lemma then compares the heat
inequalities. With `X≤Y`, `D(Y−X)≥0`, while strictification forces the same
quantity to be at most `−η`: the displayed contradiction has the correct sign.
The lower affine localization explains use with semicontinuous half-relaxed
limits. The draft does not claim comparison for every unspecified weak
interval boundary interpretation.

Nonnegative stochastic `M` and the endpoint maximum preserve order. Finite
slab induction yields comparison and uniqueness in the stated trace class.
Each closed trace slab is continuous; the assembled value is right-continuous
with uniform spatial left limits. Global time continuity is neither needed
nor true in general.

## Exact task certificates checked independently

For E1, the exponential lower bounds give `sigmoid(.78)>2/3` and
`sigmoid(−1.95)<1/7`. With the actual mode1 row and charge,
`B1(.2)>.421`. The mode1 payoff has Lipschitz constant at most `.13`.
The triangular fold is1-Lipschitz and Doob/Jensen gives
`E sup|W|≤2√.2<.9`; omitting nonnegative WAIT cost gives
`U1(.2−,−1.5)<11/70+.13·1.3·.9=.309242857…`.
The true continuum jump is consequently greater than `.11175714` for the
registered `σ≤1.3`. No grid measurement is used.

For F1, the cubic exponential bound produces
`sigmoid(39/50)>540823/790823`. Independently evaluating the three-stage
reset-until-mode0 strategy gives exactly
`R3>12720913317/25306336000=.502677010…>1/2`.
At `t≥.6`, immediate mode1 RESET exceeds every possible mode1 STOP payoff.
Waiting preserves mode1, reaches only smaller remaining times, and adds
nonnegative carry. Horizon monotonicity therefore bounds every later first
action by the current reset value. The all-state mode1 RESET conclusion is
valid for every `σ>0` in this task.

These certificates also show why a continuation band and two spatial contacts
must not be presumed in every mode/time. Monotonicity gives a lower RESET
contact interval when it exists; it does not give a single STOP graph. The
lower reflecting endpoint's positive `√δ` exercise-payoff gain and the local
generator sign checks are correctly distinguished from global optimality.

The additional G2 certificate was also checked independently. At first
admission `t=.2`, mode1, `0<σ≤1.3`, the no-reset left value at `x=−1/4` is
strictly below `.4201`, whereas `B1>.421`. Indeed the cubic Taylor sum for
`exp(.325)` exceeds `29/21`, so `sigmoid(−.325)<.42`; the same Doob/Lipschitz
bound supplies the remaining `.1521`. Spatial continuity gives a right
neighborhood of this point in RESET contact. For the upper point, the Taylor
sum **through order5** for `exp(13/8)` exceeds5 (order4 alone does not).
Thus `g1(5/4)>13/30`. The geometric bound on the tail from order3 gives
`exp(.78)<2.1842<11/5`, hence
`B1=.096+.4875 sigmoid(.78)<13797/32000<13/30`.
Therefore the upper point and a neighborhood are outside RESET contact.
Together with the closed lower-interval structure this proves the genuine
coarse continuum bracket `b_RESET(.2)∈(−1/4,5/4)` for this mode and volatility
range. It is a first-admission analytic bracket of width1.5, not a general
boundary-location algorithm, fine numerical error bar, STOP boundary theorem,
or smooth-fit result.

## Ideal finite-difference convergence

The even periodic centered grid restricts exactly to the endpoint rate
`2D/h²` used by the reflected scheme. Its off-diagonal rates are nonnegative
and row sums vanish. `I−ΔQ_h` is an M-matrix. The positive-maximum comparison,
sup-norm data estimate, and equivalent contraction with row sum
`Δq/(1+Δq)<1` establish existence, uniqueness, order, and stability of the ideal
LCP map without assuming policy iteration always terminates.

The consistency/half-relaxed-limit signs are correct: at a grid maximum of
`v−φ`, the backward time difference is larger and `Q_h(v−φ)≤0`, yielding the
subsolution inequality when continuation is active. The reverse inequalities
and feasibility yield the supersolution inequality at a minimum. Smooth even
initial barriers handle compatible continuous initial data. Extending only
the old external obstacle past a slab endpoint is a legitimate proof device
for the left trace; it does not grant early access to the new physical reset.

Positive spatial interpolation at `x_r`, stochastic `M`, and the1-Lipschitz
admission maximum propagate uniform errors through finitely many slabs.
Alignment of every `kρ` and separate left/right reconstruction are essential
for uniform convergence to a discontinuous time value. No CFL-type coupling is
needed for this implicit finite-difference map. The different projected-hat
reference has its own projection/quadrature consistency conditions and is
properly excluded from this theorem.

The residual qualification is essential: exact arithmetic/exact LCP solves,
or uniformly vanishing residual in the **scaled** PDE/obstacle operator, are
assumptions. The sufficient condition `r_h/Δ→0` for the displayed unscaled
complementarity residual is consistent with those assumptions. A fixed FP64
termination tolerance and a finite residual table do not establish this limit.

## Qualification boundary

This is an independently checked proof argument using the stated primary
maximum/comparison and monotone-scheme framework; it is not a machine-checked
proof or a numerical rate certificate. No unresolved mathematical defect was
found in the stated ideal-task arguments. The ledger correctly retains these
separate open items:

- general STOP geometry, smooth fit and moving-boundary regularity;
- general or quantitatively narrow boundary brackets and value error rates
  beyond the stated first-admission coarse analytic G2 bracket;
- convergence of spatial derivatives, parameter gradients, or a varying delay;
- fixed finite-precision implementation as a whole asymptotic sequence;
- continuous first-hitting-time owner execution;
- full financial model, learned content gains, hardware and production adoption.

The R19 finite-grid15-coordinate gradient evidence remains a separate
qualification. The main failed large finite-difference steps and the separately
frozen locality followup remain intact. Neither this proof nor that followup
retroactively changes the original numerical acceptance record.
