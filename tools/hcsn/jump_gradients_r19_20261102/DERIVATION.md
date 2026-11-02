# Derivative of the actual causal jump-aware finite-grid task

This is a derivative of the R18 finite-grid numerical task value, not a proof
about all continuous free boundaries or the full financial model. The public
quality x, two content modes, objective, reset fees, recovery and task law are
unchanged. The actual old `jump_solver.solve` is called. A scoped return-profile
callback observes its exact code object and copies its private left limits; it
does not replace the primal computation. The returned value-array identity,
left-limit shapes and first-left equality are checked, and the previous profiler
is restored even when the primal rejects an input. All inherited source hashes
are fixed separately. This is a research wrapper, not a production/native API.

## Chart and the 15 trainable coordinates

Risk, WAIT/recovery prices, both reset fees and reward slope have logarithmic
coordinates. Reset quality is a physical state coordinate. Each content-mode
row has two softmax logits, retaining the redundant row gauge explicitly. For
terminal reward, `b_j=sigmoid(beta_j)` and
`a_j=(1-b_j)sigmoid(share_j)` ensure interior probabilities without clipping.
The payoff is `g_j(x)=b_j+a_j sigmoid(s*x)`.

Both row-logit derivatives are tested; their sum must vanish. The chart requires
strictly representable positive costs and probabilities. Zero-cost, zero-support
limits are outside this chart, not silently replaced with floors.

The physical domain, space/time grids, horizon, deterministic recovery lag and
discrete mode are fixed. Off-lattice changes of horizon/recovery are rejected.
Changing an integer lag changes the numerical model/topology. It is not assigned
a zero ordinary gradient. This qualification therefore covers all **declared
trainable** coordinates, not every scalar appearing in the task specification.

## Causal left and right equations

Let `A=I-dt*Q`, with Q the reflected finite-difference diffusion generator. On a
regular continuation row of the left-limit obstacle solve,

`A V_n^- = V_(n-1)^+ - c_wait dt`.

At an ordinary STOP row `V_n^-=g`. At a RESET row, the correct delayed successor
is used. At a recovery-admission date, the left successor is
`V_((k-1)rho)^-`, while the newly admitted right obstacle uses
`V_((k-1)rho)^+`. At the first admission no reset is available on the left.
After solving the left limit,

`V_n^+ = max(V_n^-, B_n^+)`.

Thus the previously corrected recovery jump is not differentiated as if it
were a single smooth old four-coordinate solve.

Write Z for a parameter tangent. On a regular continuation row,

`A Z_n^- = Z_(n-1)^+ - dt dc_wait - (dA)V_n^-`.

For log_sigma, `dQ=2Q`; the reflected endpoint coefficients are differentiated
with their actual doubled boundary rates. STOP rows use the terminal reward
partial. For any delayed reset,

`dB = M C Z + (dM) C V + M (dC) V - dk - rho dc_rec`,

where C interpolates at reset quality. The moving interpolation weight term is
included. All matrix-row logits, terminal payoff parameters, both prices and
both fees enter this recursion. The ordinary right-jump derivative takes the
unique winning branch. A tied branch is not given a fabricated classical
Jacobian.

The forward engine solves these active banded equations with all15 RHS columns.
The independent reference instead assembles one sparse system containing all
time states and auxiliary left limits, including every delayed inter-mode
coupling. It derives the chart/physical RHS separately and does not import the
forward engine, its reset helper, its band matrices or reward partials. Agreement
of those systems is a derivative check conditional on the actual primal; it is
not a second independent proof of primal optimality.

## Non-smooth directions

At a biactive primal LCP row both contact and continuation residual vanish. The
one-sided directional derivative solves the critical-cone complementarity
problem

`min(z-dF, A z-drhs+dA*V)=0`.

Strict obstacle and strict continuation rows retain their corresponding linear
equations. If the obstacle itself is a tied STOP/RESET maximum, `dF=max(dg,dB)`.
At a tied right-admission max, use the maximum of the left and reset directional
tangents. This is a one-sided Hadamard directional derivative of the discrete
complementarity map; it is not a straight-through gradient of an action.

At reset interpolation knots, an ordinary derivative is rejected. A specified
inward direction chooses the genuine left or right slope, with the delayed
value tangent still included. For an external query x, ordinary derivatives
exist inside a fixed interpolation cell; at a knot the API exposes left/right
slopes and their Clarke interval instead of a unique derivative. At a physical
endpoint an outward direction is rejected. Admission-time left/right values are
reported as limits; no smooth recovery-delay/time derivative is fabricated.

## Positive ordinary-reference derivative

The actual positive Gaussian-image/hat reference is differentiated as well.
For log_sigma and z=distance/(sigma sqrt(dt)),

`d density = density*(z*z-1)`.

This expression is integrated with the actual operator's quadrature nodes,
including16-node primals when supplied. The value tangent includes propagation
of earlier tangents, the differentiated kernel, WAIT price and the complete
reset/terminal/chart terms. Raw coordinates must decode to the actual supplied
primal fields; mismatched models are rejected.

An independent Fourier heat/tangent ODE checks the density derivative. The
linear-hat interpolant has sinc-squared Fourier alias coefficients. Each alias
obeys `u'=-lambda*u`, `z'=-lambda*z-2lambda*u` for log_sigma, with
`lambda=sigma^2*omega^2/2`. Positive-time omitted alias decay is recorded. This
checks the heat component, not the whole task's continuous free-boundary
parameter derivative. All other reference coordinates are also checked against
centered differences of the actual unchanged reference.

## Actual parameter update, fixed data

A canonical teacher produces a fixed24-point value target table once. Physical
inputs and target bytes remain fixed across20 student updates. The actual
analytic Jacobian supplies the MSE gradient; each candidate update is reevaluated
by the actual canonical objective under a fixed line search. Updated parameters
may change active sets and boundary/action cells, which are measured after the
update. No derivative of a hard decision is taken. This is value-model
calibration and a gradient-to-boundary-update smoke test, not new neural quality,
semantic generalization, owner net gain or model adoption.
