# Independent mathematical review: fixed-mesh directional obstacle derivative

This is a new one-sided derivative contract. A finite central perturbation can
cross an action boundary while the base point still has a perfectly correct
ordinary local derivative. The twelve R19 failures and the one failed smaller
step therefore remain failed finite-perturbation checks; they alone do not prove
that R19's selected-branch algebra is wrong at a smooth base point.

## Directional complementarity system

For one implicit stage write `y=v-o`, `q=Av-b` and
`min(y,q)=0`, componentwise. The matrix has positive diagonal, nonpositive
off-diagonal entries and strictly positive row sums. On the reflected R18 mesh
the row sum is one. It is a nonsingular M-matrix.

For a one-sided parameter direction, put `r=db-dA v`. Partition nodes using the
exact primal solution:

* `y>0`: continuation is strict and `A z=r`.
* `q>0`: obstacle contact is strict and `z=do`.
* `y=q=0`: the derivative satisfies `min(z-do, A z-r)=0`.

This last equation is essential. Selecting an arbitrary one of the two zero
branches does not give the directional derivative at a tie. The derivative is
positively homogeneous in its direction; it need not be odd or additive.
Consequently there is generally no single Jacobian valid across tied actions.

Eliminate strict obstacle rows, then strict continuation rows. Principal
submatrices and the resulting Schur complements remain nonsingular M-matrices.
The remaining biactive obstacle LCP therefore has a unique solution. Equivalently
its policy matrices choose identity or M-matrix rows and stay invertible. Local
finite active-set representations are smooth on their pieces and agree in value
where pieces meet. Their one-sided selection yields the unique directional
solution above. Smooth coefficient maps and a fixed interpolation cell preserve
this finite-dimensional directional differentiability. This is a statement
about a fixed finite mesh, not a continuum free-boundary derivative theorem.

## Maxima, reset and admission dates

For `max(a,b)`, the directional derivative uses the slope of the strictly larger
value. If `a=b`, it is `max(da,db)`. Apply this first to the STOP versus RESET
obstacle and separately to the post-admission maximum between left value and
new right RESET. One cannot use a single preselected derivative at a tie.

Since the reset lag is a positive integer, all reset successors are already
computed. At `k*rho`, the left obstacle and its derivative use saved
`(k-1)*rho-` values; the right RESET uses `(k-1)*rho` right values. Differentiate
the left stage first, then the right maximum. The recursion is causal and
inherits directional differentiability from its previously computed stages.
This does not differentiate the moving lag or an admission date.

## Numerical tie classification is a separate qualification

Near a tie is not the same as exactly tied. A tolerance that converts every
small positive slack into zero can change the derivative of the original
finite problem. Report numerical ambiguity or the explicit numerical tie
contract rather than silently asserting exact mathematical ties.

A residual bound is available for this matrix class. Let
`delta=||min(v-o,Av-b)||_inf` and
`m=min(1,min_i(A 1)_i)>0`. The comparison principle and translations
`v +/- (delta/m)1` give `||v-v_exact||_inf <= delta/m` for the real-arithmetic
LCP with the given coefficients. Thus contact slack error is at most `E=delta/m`
and continuation slack error is at most `||A||_inf E`. Positive slacks above
these error envelopes can certify strict branches; unresolved nodes require
an exact tie construction or an explicit ambiguity qualification. Floating
evaluation of the residual itself must also be bounded to turn this into a
machine-verified certificate. No interval-arithmetic certificate is claimed
by ordinary floating residual statistics alone.

## Independent exact controls

1. Scalar `A=1`, `o=b=v=0`: for directions `(do,db)=(0,1)` and `(0,-1)` the
   answers are respectively `1` and `0`. A single selected obstacle derivative
   would return zero in both directions and fail the first control.
2. Two coupled ties, `A=[[2,-1],[-1,2]]`, `o=b=v=0`: RHS directions `[1,-1]`,
   `[-1,1]`, `[1,1]`, `[-1,-1]` give `[.5,0]`, `[0,.5]`, `[1,1]`, `[0,0]`.
   These cases test coupling, not just scalar max selection.
3. With the same matrix and `do=[1,0]`, RHS direction zero gives `[1,.5]`.
   Holding the second tied node at zero would violate its continuation inequality.
4. A strict-contact/strict-continuation mixture can be manufactured by choosing
   any nonnegative contact and continuation slack vectors with disjoint support,
   setting `o=v-y` and `b=Av-q`, and solving the corresponding linear directional
   equations. Include biactive nodes in the same system to test elimination.
5. A post-admission exact tie with left/right values equal and slopes `-1,+2`
   has directional slope `+2`; reversed direction slopes `+1,-2` give `+1`.
   Arbitrary left-only or right-only selection fails one of these directions.

One-sided finite-difference checks should use a fixed prospective step roster
and retain every attempted error. Exact piecewise-linear controls need no limit
argument: the stated derivatives equal their one-sided quotients for every
positive step that leaves strict branches unchanged. Fresh nonlinear task
directions require separately declared finite numerical tolerances and no
claim that shrinking steps retrospectively repairs R19's failed gate.

An exact whole-task tie profile is also available: equal constant reward bases,
zero reward amplitudes, zero WAIT/recovery costs and zero reset fees. For any
positive diffusion and stochastic mode transition, `V` is that same constant
at every time, mode and spatial node. WAIT, STOP and admitted RESET tie exactly.
The caller can supply that mathematically known biactive classification instead
of inferring it from small floating slacks. For fixed propagation/transition and
reward slope, perturbing reward bases/amplitudes and costs in a feasible
direction makes every primitive positively homogeneous around this constant.
Then the finite problem's one-sided quotient equals its directional solution
for every sufficiently small positive step preserving reward probabilities.
Joint perturbation of propagation parameters instead leaves higher-order terms;
its quotient generally has a first-order-in-step truncation error.

For the inherited transition matrix `[[.9,.1],[.25,.75]]`, an exact actual-task
admission control uses base-reward direction `[+.1,-.1]`, with all other
direction entries zero. Before the first reset, the directional values are
that pair. At the first admission, STOP versus RESET gives `[+.1,-.05]`.
For the reversed direction it gives `[-.08,+.1]`. Their sum is therefore
`[.02,.05]`, separately constant across spatial nodes, not a uniform `.05` in
both modes. This explicit nonzero sum disproves a single odd linear gradient
at these tied actions and tests actual delayed admission rather than only a
standalone scalar max.

At a zero fee, amplitude or cost, the declared task accepts only feasible
one-sided directions. A negative direction there differentiates an extended
coefficient map outside the task's domain. It must be rejected or explicitly
identified as outside the task contract. The same feasibility restriction
applies to stochastic-transition and reward-probability endpoints.

The current source has the correct critical-LCP sign, left/right reset
recursion, current-left-value diffusion source and max-of-slopes tie rule.
Generic unresolved numerical rows remain expressly unqualified. Exact-state
masks are caller-supplied mathematical assertions, not certificates inferred
from a tolerance. The independent primitive controls supply those masks only
for their explicitly known exact base solutions.

## Remaining open scope

Moving recovery time, horizon, domain and mesh, interpolation-knot derivatives,
continuum gradients, complete financial/neural differentiation, utility gain,
GPU/energy and production admission are not established by this directional
finite-dimensional result. A selected one-sided derivative is not a full
ordinary gradient through all action switches.
