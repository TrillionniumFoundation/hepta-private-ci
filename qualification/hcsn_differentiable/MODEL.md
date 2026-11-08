# Differentiable HCSN candidate: declared model and evidence boundary

This is a **new FP64 numerical and training candidate**. It does not amend,
unfreeze, or inherit the source, plan, budgets, or pass gates of S81 or S25.
The default 16 active / 1 tail / 8 remaining-time coefficients are a small
mechanism fixture, not a previously qualified architecture. A separate 64 / 1 /
16 fixture exercises 81-state construction and physical-parameter gradients;
that also earns no old S81 pass credit.

## 1. Continuum process being approximated

Let `B = log_boundary = log(b)` be constant throughout an episode. The physical
log state is `Y = log(V)` and the active relative coordinate is

\[
x=Y-B>0,\qquad dX_t=\mu\,dt+\sigma\,dW_t,
\qquad \mathcal L=\mu\partial_x+\tfrac12\sigma^2\partial_{xx}.
\]

`mu` is a **log-state drift**, not the multiplicative drift of `V`. A hit at
zero emits an event and starts a deterministic delay `d = grid.refractory`.
At the end of that delay, the continuum process restarts at

\[
x_r=\log(V_r)-B,\qquad V_r=\texttt{absolute_reset}>0.
\]

`V_r` and `B` are independent physical parameters. In particular the reset is
not defined as `exp(B + fixed_margin)`. The core propagator accepts
`log_boundary`, `mu`, `sigma`, `absolute_reset`, and `discount` as scalar FP64
tensors on one device. The network may keep `discount` fixed while training
the other four. No generator tensor or transition matrix is detached.

The fixed physical domain accepted by this implementation is `abs(mu)<=2`,
`0.05<=sigma<=2`, `0.001<=discount<=4`, and `1e-4<=x_r<=8`. Initial log-median
margins must lie in `(0,8]`. These are **input limits, not a proof of accurate
arithmetic throughout the box**. Actual qualification consists of the recorded
fixtures; unresolved positivity, finite arithmetic, or mass checks raise an
error. FP32, arbitrary parameter-conditioned moving boundaries, zero
diffusion, zero discount, and higher derivatives have no qualification here.

## 2. Frozen basis with an explicit returning tail

The state has `K = active_cells + 1 + phase_cells` coefficients in this order:

1. Uniform active densities on fixed cells covering `[0,L)` in relative `x`.
2. One active tail density `L + Exp(tail_rate)`, covering the whole half-line
   above `L`. It can return to finite cells and hit the boundary.
3. Uniform densities over remaining refractory time cells covering `[0,d]`.

The tail is **not** absorbing overflow or discarded probability. Its shape is
reconstructed after every propagation; this is a basis approximation even
though it retains all tail mass. Its mean `L + 1/tail_rate` is used in the
reported margin proxy. Refractory coefficients have zero active margin.

If `R` reconstructs densities from coefficients and `Q` integrates a density
back into the fixed cells/tail, one interval has the numerical structure
`Q P_dt R`. The implemented integrals use fixed positive Gauss rules. Row
orientation is used in code: `p_next = p @ matrix`.

The matrix is built from analytic killed-process probabilities, fixed
quadrature over source densities, and deterministic remaining-time transport.
It is **not** a finite-state CTMC matrix exponential, and in general

\[
P^{\mathrm{basis}}_{t+s}\ne
P^{\mathrm{basis}}_tP^{\mathrm{basis}}_s.
\]

Repeating the projection changes the approximation. Tests report this
discrepancy and spatial/phase/quadrature refinement separately. There is no
per-step renormalization, hidden mass correction, or probability clipping.
Quadrature weights integrate a constant exactly; that normalization is fixed
numerical rule construction, not repair of a transition row.

## 3. Analytic one-cycle laws and interval construction

For `x>0`, `T>0`, the first-hit distribution is

\[
F(T,x)=\Phi\!\left(\frac{-x-\mu T}{\sigma\sqrt T}\right)
 +e^{-2\mu x/\sigma^2}
  \Phi\!\left(\frac{-x+\mu T}{\sigma\sqrt T}\right).
\]

With `kappa = sqrt(mu**2 + 2*q*sigma**2)`, the discounted first-hit mass is

\[
G_q(T,x)=
e^{(-\mu+\kappa)x/\sigma^2}
 \Phi\!\left(\frac{-x-\kappa T}{\sigma\sqrt T}\right)
+e^{(-\mu-\kappa)x/\sigma^2}
 \Phi\!\left(\frac{-x+\kappa T}{\sigma\sqrt T}\right).
\]

The killed survivor tail above `y>=0` is

\[
S_y(T,x)=
\Phi\!\left(\frac{x+\mu T-y}{\sigma\sqrt T}\right)
-e^{-2\mu x/\sigma^2}
 \Phi\!\left(\frac{-x+\mu T-y}{\sigma\sqrt T}\right).
\]

Cell probabilities are differences of adjacent tails. These expressions use
log-CDF sums, a stable exponential difference, and rationalized roots. The
normal log-CDF backward uses the Mills ratio with `erfcx`; it deliberately
supports first-order reverse AD only. Numerical stability is tested afresh.

Discounted active occupation is evaluated by a positive quadrature:

\[
A_q(T,x)=\int_0^T e^{-qt}\,[1-F(t,x)]\,dt.
\]

Each `advance` requires `0<=dt<=d`, so an initially active path can hit at
most once in this interval. If it hits at time `s`, its remaining refractory
time at the end is `d-dt+s`; phase-cell probabilities are differences of `F`
at the corresponding fixed deadlines. An initially refractory path with
remaining time `r<=dt` first waits `r`, then follows the killed law at the
**continuous reset point** `x_r` for `dt-r`. `G_q` and occupation rewards are
discounted by `exp(-q*r)`; ordinary event counts are not.

The release integral uses `h = h_min + span*u**2` to resolve the small active
horizon near release. There is no `argmin`, nearest-grid reset, or surrogate
gradient for reset coordinates. Source tail integration also uses a positive
change of variables. Gauss nodes and weights are built with Python's standard
library; the candidate runtime depends only on Python and Torch.

## 4. What “fixed deterministic delay” does and does not mean here

The underlying renewal law has a deterministic delay `d`. The finite state
retains **remaining-time densities**, not Erlang stages. A source refractory
cell is transported by `r -> r-dt` until release. For aligned cell/time steps,
this transport can be exact for the represented density.

Nevertheless, projecting a new or shifted refractory density back to uniform
phase cells can change its remaining delay by up to a phase-cell width per
projection in a natural coupling. Repeated projection can therefore release
some mass **earlier than the continuum process would**. The numerical chain
does not claim the exact per-path minimum inter-event interval. This differs
from adopting an Erlang delay: there is no exponential phase waiting time,
and `d` is not merely a phase-type mean.

Tests explicitly measure early release and its phase-grid refinement from a
common initial remaining-time distribution. Long-run rate is separately
compared with the negative-drift renewal reference

\[
\nu_\infty=\frac{1}{d+x_r/(-\mu)},\qquad\mu<0.
\]

The numerical chain can have a biased stationary rate even while preserving
probability. One successful conservation test cannot establish delay or
renewal accuracy.

## 5. Static learnable boundary, initialization, and episode identity

The initial physical prior is explicitly

\[
\log V\sim N(\log V_{\rm initial},s_0^2)\quad\text{conditioned on }V>b,
\qquad s_0=\texttt{grid.initial_log_std}.
\]

The prior's integrated probabilities are projected to the fixed relative
cells. They use smooth CDF integrals, not point-to-bin placement. It is a
continuous conditioned prior, **not** a Dirac initialization, and the tail is
subsequently reconstructed using the declared exponential tail basis.

At fixed physical `V`, `dx/dB=-1`; at fixed `V_r`, `dx_r/dB=-1` and
`dx_r/dV_r=1/V_r`. This candidate's boundary gradient enters through both the
initial prior and the unquantized absolute reset mapping. A simultaneous
translation of all physical log values and `B` is a coordinate invariance;
the boundary cannot be identified without an absolute input/initial/reset
convention. A trained static threshold is not automatically an optimal
free boundary of a stopping problem.

The network owns clocks and episode state. `PhysicalParameters.snapshot()`
returns detached **identity-check copies only**; forward computation must use
the original tensors. An episode must reject changing `B`, `mu`, `sigma`,
`V_r`, or `q` while continuing an old state. Optimizer updates require a new
episode. A state deliberately detached between chunks is truncated training,
not a claim that long-horizon gradients were preserved.

This API does not define a moving boundary. If `B(t)` were introduced, drift
would become `mu-dB/dt`; upward jumps would sweep crossing probability into
events/refractory mass. Neither transformation is implemented. Silently
feeding a new `B` into an existing relative-coordinate state is invalid.

## 6. Probability, marked content, risk, C, and U

The symbols name different mathematical objects; they are not interchangeable
network channels. Time units below are the physical units of the supplied
timestamps; a rate is in Hz only when those units are seconds.

| Symbol | Definition and semantics | Units | Status in this candidate |
| --- | --- | --- | --- |
| `E(V;V_b)` | Original He--Xiong equity value under the financial model's cash flows, debt rollover, and endogenous default boundary. Equity value matching and smooth pasting belong to that model's optimal boundary. | Currency, or a consistently normalized financial value | **Not implemented**; `call` is not this equity function. |
| `C_T(x)` | Killed single-cycle value: active running reward until first hit, plus terminal reward only on survival; the displayed definition below has zero payoff on absorption. | Reward units | Its constant-flow/terminal components are evaluated for one interval; risk and hit payoff are separate terms. |
| `U_T(x)` or `U(x)` | Total regenerative finite-horizon or perpetual value, including repeated events, delays, reset continuations, and terminal payoff paid once. | Reward units | **No global U solver** is implemented. Repeatedly summing `call` does not give U. |
| `F(T,x)` | `P_x(tau_0<=T)`, the first-hit CDF of one active killed cycle. | Dimensionless probability in `[0,1]` | Analytic primitive. The API's `risk` is the corresponding *one-interval* event probability integrated over its current active/refractory basis. |
| `M(t)` | `E[N_t]`, the expected cumulative number of boundary-hit events after episode start; it may exceed one. | Expected event count (dimensionless count) | Add interval `expected_events` for a fixed propagated law. With observation filtering these are successive conditional interval expectations, not a smoothed global first-hit probability. |
| `J(t)` | `dM(t)/dt`, the regenerative event-rate density; after resets it differs from the first-hit density `f(t,x)=dF/dt`. | Expected events per time unit | No continuous-time J solver is exposed. For `dt>0`, `expected_events/dt` is an **interval-average** conditional rate, not instantaneous J. |
| `G_q(T,x)` | `E_x[exp(-q*tau_0) 1_{tau_0<=T}]`, a discounted first-hit mass. | Dimensionless discounted count | Analytic primitive; `1-G_q` is not survival. |
| `call` | Declared finite-interval running/hit/terminal reward readout below. | Reward units, with `c_a` in reward/time, `c_h` in reward/event, and `c_T` in reward | Implemented engineering feature, not E or a global U. |

For an initially active point, the continuum renewal equation makes the
first-hit / repeated-event distinction explicit:

\[
f_x(t)=\frac{x}{\sigma\sqrt{2\pi t^3}}
       e^{-(x+\mu t)^2/(2\sigma^2t)},\qquad
k(t)=\mathbf1_{\{t>d\}}f_{x_r}(t-d),
\]

\[
J_x(t)=f_x(t)+(J_x*k)(t),\qquad
M_x(t)=\int_0^t J_x(s)\,ds.
\]

These are references for the underlying deterministic-delay continuum
process. The projected QPR chain approximates it and must not silently claim
that its numerical event curve solves this renewal equation exactly. The
4096-step fixed-operator test separately records accumulated M, probability
drift, and signed-content total drift; it is a numerical foundation test,
not evidence of neural-network long-context superiority.

Probability is `p[batch,K]`; content mass is `m[batch,K,content]`. They use the
same matrix:

\[
p'_j=\sum_i p_iP_{ij},\qquad
m'_{jc}=\sum_i m_{ic}P_{ij}.
\]

Reset currently preserves a path's content (identity reset). The operator
does not inject observations, reset content to a fresh learned value, or
renormalize state. An enclosing network may apply its explicitly declared
observation conditioning and content update after propagation.

`rewards[:,0:3]` are, respectively, interval expected event count, discounted
event count, and discounted active occupation. Because each represented
source path can hit at most once inside one `dt<=d` build, `risk` equals that
interval event probability/count. **Summing expected events across intervals
can exceed one** and is not a first-hit CDF. The discounted mass `G_q` is not
a probability complement; `1-G_q` is not survival when `q>0`.

For a killed single cycle, a value with zero payoff on absorption is

\[
C_T(x)=E_x\!\left[
\int_0^{T\wedge\tau}e^{-qt}g(X_t)\,dt
+e^{-qT}h(X_T)\mathbf1_{\{\tau>T\}}\right].
\]

At a fixed boundary, value matching need not imply smooth pasting. For
constant positive flow reward, `C_infinity = (c/q)*(1-psi_q)` has a nonzero
boundary slope. No risk-channel smooth-pasting claim is made here.

The implemented `call` is a **specified one-interval engineering value**:

\[
\texttt{call}=c_a A_q+c_h G_q
+c_T e^{-q\,dt}\,P(\text{active at interval end}),
\]

integrated over the source basis, including any initial refractory wait.
Defaults are `(c_a,c_h,c_T)=(0.4,1,0.2)`. The terminal payoff is paid once at
the end of this queried interval. At `dt=0`, events and occupation vanish,
but the terminal payoff is still `c_T` on active states. A padding caller
must mask its readout if that interval is not an observation. **Adding these
call values over steps would repeatedly pay terminal rewards and would not
compute a total episode value.**

A full regenerative value `U` includes repeated events and continuation
through resets. For example, a perpetual zero-refractory-flow value would
satisfy

\[
U(x)=C(x)+\psi_q(x)[r_{\rm sp}+e^{-qd}U(x_r)],\qquad
\psi_q(x)=
\exp\!\left[-\frac{\mu+\sqrt{\mu^2+2q\sigma^2}}{\sigma^2}x\right].
\]

That global `U` solver is **not implemented** in this candidate. Its reset
boundary condition differs from permanently killed equity value matching.
The module is not the full He--Xiong debt/equity model, a put/call replication,
a QVI solver, or a proof that a network learned an optimal free boundary.

## 7. Explicit no-reset control

`DifferentiableDistributionOperator(..., reset_enabled=False)` uses the same
state dimension but sends every new hit to the first phase slot as a permanent
absorbing state. Other phase slots are unreachable from the supported initial
law and remain identities. This mode has **different declared phase semantics**.
It never restarts from `absolute_reset`; therefore a reset gradient is not
expected in that control. The network must not manufacture its own no-reset
mode by cutting a matrix row or dropping hit mass.

## 8. API, cost, and tests

`forward(log_boundary, mu, sigma, absolute_reset, dt, discount)` returns one
`OperatorTable`. Its `matrix` is `[K,K]`; `rewards` is `[K,3]`; `call`, `risk`,
`margin`, and `active_probability` are `[K]`. `advance(p,m,dt,params)` accepts
a fixed scalar duration or `[batch]` durations and returns a `FlowReceipt`.
Duration tensors cannot require gradients. It builds each distinct duration
once within that call. There is no cross-call cache with stale physics.
When storing a table within a single forward graph, a caller may reuse it for
identical parameters and durations. It must discard that graph/cache after
the optimization step. This implementation prioritizes explicit correctness
over a performance qualification; repeated construction can be expensive.

The numerical tests include:

- Independent Python-math reflection and density-integral references for
  first hit, discounted first hit, and occupation.
- Conservation, nonnegativity, returning tail, common content propagation,
  exact identity at zero duration, and no-reset absorption.
- All four physical parameter AD/central-FD comparisons, with actual AD/FD,
  absolute errors, relative errors, and steps, on both 25-state and 81-state
  fixtures. Reset is off-grid and the fixture exercises release paths.
- Spatial-grid first-hit error against a continuous conditioned-prior
  reference, quadrature order differences, remaining-time early-release
  refinement, and stationary rate against the negative-drift renewal mean.
- 4096 fixed-operator steps with probability and signed content transported
  together, recording probability drift, signed-content conservation, and
  accumulated expected event count M greater than one.
- Episode snapshot rejection and explicit evidence that finite-basis
  one-step/two-step propagation is not an exact semigroup.

Tests put numerical values in `test.numerical_evidence` and print the same
values as `HCSN_NUMERICAL_EVIDENCE` JSON lines. The qualification runner should
preserve these records alongside source hashes and test outcomes. A missing
Torch runtime is a blocked run, not a successful skip. A failed numerical
fixture is evidence of an unresolved candidate, not authorization to weaken
an old study's thresholds. No cloud job, large training run, financial market
calibration, or real-sensor formal fit is started by these files.

## 9. Motivating financial reference

Zhiguo He and Wei Xiong, **Rollover Risk and Credit Risk**, *The Journal of
Finance* (2012), [author-hosted paper](https://www.princeton.edu/~wxiong/papers/rollover.pdf).
The boundary-value and endogenous-default perspective motivates this research.
The probability/reset/content model defined above is a separately specified
neural candidate, not an implementation of that paper's complete debt/equity
valuation system or a claim that financial smooth pasting applies to every
neural risk readout.
