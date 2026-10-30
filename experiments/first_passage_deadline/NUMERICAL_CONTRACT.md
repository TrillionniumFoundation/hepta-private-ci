# Finite-deadline natural firing: scalar contract

This is a new, independently versioned numerical extension. It imports the
previously frozen first-hit/killed kernels and stationary scalar verifier without
changing their source. It neither retrains a model nor reuses confirmation data.
`PROTOCOL.json` fixes four cases, three grids, independent policy evaluation and
acceptance thresholds before implementation or evaluation.

## State, reward and terminal convention

While active, (dX_t=\mu\,dt+\sigma\,dW_t), with constant coefficients and
\(\sigma>0\). A chosen firing pays \(X_t-c\), resets to the fixed \(r\le c\),
and holds the state at \(r\) for a mandatory \(a>0\). Discounting uses actual
elapsed time at rate \(q>0\). Holding earns zero. The state includes remaining
refractory time \(\eta\in[0,a]\); a refractory state must equal \(r\).

At the deadline, an active state pays \(g(x)=(x-c)^+\) once. This is terminal
liquidation, recorded separately from ordinary spikes. A refractory state pays
zero, consistent with \(g(r)=0\). A spike immediately before the deadline receives
its spike reward and leaves zero terminal payoff. These rules prevent duplicate
terminal rewards. A policy can refrain from firing, so the value is nonnegative.

Let \(h\) be time remaining. The refractory value is exactly

\[
V_R(h,r,\eta)=\begin{cases}
0,&h\le\eta,\\
e^{-q\eta}V(h-\eta,r),&h>\eta.
\end{cases}
\]

Define \(D(h)=0\) for \(h\le a\), and
\(D(h)=e^{-qa}V(h-a,r)\) for \(h>a\). At \(h=a\), this agrees with
\(e^{-qa}g(r)=0\). The immediate firing obstacle is
\(M(h,x)=x-c+D(h)\).

## Dynamic programming and boundary scope

With \(\mathcal L=\mu\partial_x+\tfrac12\sigma^2\partial_{xx}\), the active
value satisfies

\[
\min\{\partial_h V-\mathcal LV+qV,\ V-M\}=0,
\qquad V(0,x)=g(x).
\]

The first-event dynamic program is a scalar stopping problem with future reward
\(D(h-\tau)\). For a fixed stopping time on a common Brownian filtration, its
payoff is nondecreasing, convex and 1-Lipschitz in the initial state; the terminal
positive part has the same properties. The supremum preserves those properties.
Consequently \(V(h,x)-M(h,x)\) is nonincreasing in \(x\). A nonempty stopping
set is an upper ray. The numerical solver checks this property rather than
forcing a disconnected computed stopping set into a threshold.

Horizon monotonicity follows by running any shorter-horizon policy and converting
its positive terminal liquidation into an actual spike at that earlier deadline;
any later continuation is nonnegative. Thus \(D\) is nondecreasing. Let
\(\lambda>0\) solve
\(\tfrac12\sigma^2\lambda^2+\mu\lambda-q=0\). For the perpetual single-stop
problem, the threshold is \(b_{\rm single}=c+1/\lambda\). The first-event
representation gives

\[
V(h,x)\le V_{\rm single,\infty}(x)+D(h).
\]

For \(x\ge b_{\rm single}\), the right side equals \(M(h,x)\), while immediate
firing supplies the reverse inequality. Hence this region is exactly a firing
region at every positive horizon. The finite spatial upper endpoint can be
placed above \(b_{\rm single}\), with the exact obstacle as its boundary value.
This argument does not assume that the deadline boundary is monotone in \(h\).
Recycling starts only when enough time remains, so that monotonicity must not be
imposed without an additional proof.

The terminal boundary is \(c\). In the single-stop interval \(0<h\le a\), the
short-time limit from positive horizons is
\(c+\max(\mu,0)/q\): away from the payoff kink,
\((\mathcal L-q)(x-c)=\mu-q(x-c)\). A positive generator makes immediate
exercise suboptimal for arbitrarily short positive time; a strictly negative
generator away from the kink dominates the vanishing short-time crossing tail.
In particular, positive drift produces a terminal boundary jump. Smooth fit and
boundary continuity are not imposed across \(h=0\). Possible time regularity
changes at multiples of \(a\), especially when \(r=c\), also need refinement.

Fixed positive refractory time bounds the number of spikes on every finite
horizon, avoiding accumulation of events. By induction over intervals of length
\(a\), the delayed obstacle is already known from earlier horizons. This reduces
the model to a succession of ordinary obstacle problems. This is the route to
comparison and a limiting optimal-stopping solution in the scalar model; a small
finite-grid residual is not itself a proof of a continuous optimality gap.

## Spatial truncation

Let \(V_\infty\) be the already verified stationary regenerative value in the
frozen package. The finite value is bounded above by \(V_\infty\), since a
terminal liquidation can be implemented as an admissible final spike in the
infinite problem. Kill the finite problem at a lower level \(L<r\), paying zero
there. At the first lower exit, the discarded continuation is at most
\(V_\infty(L)\). Thus the loss from this continuous lower truncation is at most
\(V_\infty(L)\), uniformly over the starting horizon and policies. The solver
chooses \(L\) analytically to make this bound no larger than the protocol budget.

The independent operator evaluator truncates continuation below \(L\) at segment
endpoints instead of killing all intra-segment lower crossings. Its first such
discarded continuation has the same upper bound. This distinction is explicit;
neither evaluator silently renormalizes the probability lost below the cutoff.
The bound covers domain truncation, not finite-difference, interpolation or
quadrature errors.

## Monotone implicit LCP

The reference solver uses \(a=m\Delta\), \(\Delta<a\), and a uniform state grid
containing \(r\). Central drift differences are used only when both generator
rates remain nonnegative; otherwise monotone upwind rates are used. With this
discrete generator \(L_x\), each positive time layer solves

\[
u^n\ge M^n,\qquad
A u^n\ge u^{n-1},\qquad
\min(u^n-M^n,A u^n-u^{n-1})=0,
\quad A=I+\Delta(qI-L_x).
\]

The matrix has positive diagonal and nonpositive off-diagonal entries. The
delayed reset value comes from \(u^{n-m}(r)\), a previously completed layer.
Policy iteration solves tridiagonal systems. Complementarity, upper-ray shape,
the single-stop upper bound and refinement differences are recorded separately.

## Independent analytic-kernel policy evaluation

The evaluator freezes the extracted threshold \(b_n\) throughout each interval
\(((n-1)\Delta,n\Delta]\) of remaining time. It evaluates that same policy with
the Brownian upper-barrier first-hit law and killed transition kernel, converting
to the frozen lower-distance convention by \(d=b-x\) and drift \(-\mu\).
Since \(\Delta<a\), each segment has at most one spike, including starts with a
nonzero refractory clock.

For an active start below its threshold, a segment of duration \(\delta\le\Delta\)
has value

\[
e^{-q\delta}\int_{y<b}K_b(\delta;x,dy)\,W_{\rm next}(y)
+(b-c)H_q(b-x,\delta)
+e^{-qa}\int_0^\delta e^{-qt}f_{b-x}(t)R(h-a-t)\,dt.
\]

Here \(R(s)\) is the reset value on earlier time layers. Its explicitly declared
piecewise linear interpolation is \(R(h-a-t)=R_0-st\) on this interval, so the
last integral uses the analytic quantities \(R_0H_q-sM_q\), with
\(M_q=E[\tau e^{-q\tau};\tau\le\delta]=-\partial_qH_q\).
The killed integral uses positive Gaussian quadrature of piecewise linear state
interpolation. Its raw mass is compared with the independently computed killed
CDF, without row normalization. The 12-standard-deviation quadrature band omits
only a Gaussian tail bounded by the unrestricted transition law.

If the current state satisfies \(x\ge b\), the start has an immediate spike
atom: the reward is **\(x-c\)**, not \(b-c\), followed by the full refractory
period. This includes lowering the boundary at a segment junction. An initially
refractory state is held until its actual release time, then evaluated in the
appropriate remaining segment; boundary changes during the hold do not produce
events. Arbitrary off-grid release times use a partial segment with the same
declared interpolation error.

The protocol refines a fixed extracted policy by halving evaluation time/state
steps and repeating its existing threshold values. This measures evaluator
error without reoptimizing the policy. It also compares quadrature orders and
the independently obtained LCP values. These agreements are numerical evidence,
not a rigorous continuous global error certificate or a network-level result.

## Related primary research and limits

The general decision-lag dynamic-programming setting is established research:
Li and Yong, *A Finite Horizon Optimal Stochastic Impulse Control Problem with A
Decision Lag* (2021), https://arxiv.org/abs/2005.04555. Bruder and Pham study the
more general distinction between decision lag and execution delay in
https://arxiv.org/abs/math/0703769. Neither is asserted to contain this code's
particular terminal/reset contract. Azimzadeh's thesis explains why ordinary
local-scheme convergence results cannot simply be quoted unchanged for nonlocal
HJBQVIs: https://hdl.handle.net/10012/12676. The special positive fixed lag here
permits the simpler interval induction described above.

This extension makes no claim of universal novelty, multidimensional network
optimality, differentiability of a moving boundary through every parameter, or
cross-task advantage. Those would require different mathematical and empirical
contracts.
