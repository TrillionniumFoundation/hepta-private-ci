# HCSN closure: mathematical contract and causal controls

## Source and scope

He and Xiong, “Rollover Risk and Credit Risk,” *Journal of Finance* 67(2), 391–430 (2012), derive equity, debt, and an endogenous default boundary using differential equations and Laplace transforms. Equity obeys value matching and smooth pasting; a default probability is not a second payoff with the same zero-value and zero-slope conditions. The original default event terminates the firm. A repeating neuron needs an added reset and refractory law. See the [author-hosted paper](https://www.princeton.edu/~wxiong/papers/rollover.pdf), especially equation (11), Proposition 1 and Appendix A, and its [DOI](https://doi.org/10.1111/j.1540-6261.2012.01721.x).

The models here are a regenerative extension inspired by that method. They are not the paper's financial model with names replaced. In particular, the implemented value and finite-horizon risk are two functionals of a common transition law. Reading them out does not make them two physical forces.

## Exact frozen-segment hitting and renewal kernels

For a point initial margin x>0 and a constant law X_t=x+μt+σW_t, let τ be the first hit of zero. Solving (σ²/2)H″+μH′−sH=0 with H(0)=1 and the decaying condition gives

\[
H_x(s)=\mathbb E_x[e^{-s\tau};\tau<\infty]
      =\exp\!\left[-x\frac{\mu+\sqrt{\mu^2+2s\sigma^2}}{\sigma^2}\right],\quad s>0.
\]

The finite-horizon probability and first-hit density are

\[
F_T(x)=\Phi\!\left(\frac{-x-\mu T}{\sigma\sqrt T}\right)
       +e^{-2\mu x/\sigma^2}\Phi\!\left(\frac{-x+\mu T}{\sigma\sqrt T}\right),
\qquad
f_t(x)=\frac{x}{\sigma\sqrt{2\pi t^3}}
          e^{-(x+\mu t)^2/(2\sigma^2t)}.
\]

These formulas solve the killed half-line law; they are not the finite reflecting-grid law used in the executable model. For σ>0, T>0 and x>0 they provide smooth distributional sensitivities. With x=y−b, fixed μ and fixed absolute y, ∂_b H=κH where κ=(μ+sqrt(μ²+2sσ²))/σ². The total derivative of an endogenous b also includes its implicit QVI sensitivity and any changes of μ or σ. A probability channel has H(0)=1 and nonzero slope −κ; it cannot inherit equity's zero-value/zero-slope boundary conditions. At x=0 a time-zero hit is an atom, requiring separate handling.

For fixed law, independent refractory delay D, and fixed reset margin a−b, the discounted event-intensity and expected-count transforms follow by summing renewal generations:

\[
\widehat j_x(s)=\frac{H_x(s)}{1-\mathbb E[e^{-sD}]H_{a-b}(s)},
\qquad
\mathcal L\{\mathbb E_x[N_t]\}(s)=\frac{\widehat j_x(s)}s.
\]

One channel is first-event probability; another is the expected count of every generation. They must not be substituted for one another. Point-state formulas extend linearly to an initial distribution, not by replacing it with its mean. Once input changes the boundary or coefficients, one global stationary convolution no longer describes the trajectory: propagate the complete surviving and refractory distribution between segments. Numerically, evaluate the Gaussian-tail product in a stable log-tail form when the exponential prefactor is large; an algebraic closed form does not itself guarantee stable FP32 arithmetic.

## One law for probability, signed content, risk, and value

Let G be the row generator of one finite-state population. Its active states approximate a diffusion above b; refractory phases release to the declared absolute reset a. The finite upper edge reflects. There is also an unused zero-mass bookkeeping state. Let p be row probability, q row signed content with componentwise |q| ≤ p, and e the nonnegative event intensity column. For a segment of duration Δ with fixed G:

\[
p^+=p e^{\Delta G},\qquad q^+=q e^{\Delta G},\qquad
J_p=p\int_0^\Delta e^{sG}e\,ds,\qquad
J_q=q\int_0^\Delta e^{sG}e\,ds.
\]

An input write modifies q before transport according to the declared write fraction. It does not collapse p to a point or to its mean. Matrix actions include every possible reset generation inside the segment. J_p is an expected count, not a probability, and can exceed one. J_q can cancel when opposite signed cohorts emit.

If r is the event-destination basis vector, K = G − e rᵀ removes the event transition while retaining its killing rate. The probability of at least one event in the interval is

\[
F_\Delta(p)=p\int_0^\Delta e^{sK}e\,ds.
\]

This permits a population that starts in refractory phases to release and then hit. The implementation separately accounts for immediate crossings caused by a moving-boundary remap, without counting them twice in F. Consequently 0 ≤ F ≤ 1 and F ≤ J_p. Its discounted value vector is

\[
c=(\rho I-G)^{-1}r_{\rm reward},\qquad
r_{\rm reward}=\text{active running reward}-K_{\rm release}e.
\]

Risk and value must use the same G, event rule, reset geometry, and refractory phases as probability transport. The upper-edge reflection and spatial projection are approximations; the half-line continuum QVI boundary below is a policy for that reference continuum, not an exact optimum of the truncated finite-state chain.

## Regenerative affine QVI and its derivative

For dY = μdt + σdW, running reward αY − ℓ, discount ρ > 0, cost K > 0, fixed absolute reset a, and independent refractory time D, write η = E[e^(−ρD)]. With R Erlang phases of total mean d,

\[
\eta=\left(\frac{R/d}{R/d+\rho}\right)^R\in(0,1).
\]

This is not a deterministic delay. A positive Erlang mean gives no positive lower bound on an individual wait; nonexplosion follows from the finite bounded transition rates, not from an invented minimum dead time.

Set s = α/ρ, i = αμ/ρ² − ℓ/ρ,

\[
k=\frac{\mu+\sqrt{\mu^2+2\rho\sigma^2}}{\sigma^2}>0,\qquad
A=s/k,\qquad
U(y)=sy+i+A e^{-k(y-b)}\quad(y>b).
\]

Use the stable equivalent k = 2ρ/(sqrt(μ²+2ρσ²)−μ) when μ < 0. Since reset is fixed in absolute coordinates, the intervention value −K+ηU(a) has zero derivative with respect to the pre-event state. Thus U′(b)=0 is the appropriate smooth-fit condition. Value matching gives

\[
R(b)=sb+i+A+K-\eta[sa+i+A e^{-k(a-b)}]=0.
\]

Within b<a:

\[
R'(b)=s[1-\eta e^{-k(a-b)}]>0,\qquad
R''(b)=-s\eta k e^{-k(a-b)}<0,\qquad
\partial_\theta b=-\frac{\partial_\theta R}{R'(b)}.
\]

Existence still requires a sign-changing admissible bracket; monotonicity alone does not put a root in the numerical/reset domain. The continuation solution is increasing above b, so it dominates its constant intervention value. Below b the affine running reward decreases, giving the appropriate intervention-region inequality. A full optimal-control statement also requires integrability, admissibility and transversality; a local frozen-law policy is not task-wide optimal control when future neural inputs change μ or K.

The stored custom backward is first order. Its existence does not promise a supported Hessian or global smoothness of the complete network: finite-grid deposition/remapping has declared piecewise derivatives, with a symmetric generalized derivative at exact knots. Differentiating a transition distribution or its matrix action is also distinct from differentiating the hitting time of one fixed Brownian sample path. The latter needs a separately justified pathwise construction; deterministic transversal-event derivative formulas do not by themselves establish it for nowhere-differentiable Brownian trajectories. This does not rule out other pathwise or distributional sensitivity estimators.

## Safeguarded Newton acceleration

Let l < b* < u < a, R(l)<0<R(u). For exact arithmetic, increasing concavity gives

\[
0=R(b^*)\le R(l)+R'(l)(b^*-l),
\qquad
l<N(l)=l-\frac{R(l)}{R'(l)}\le b^*.
\]

Repeated Newton updates starting at the lower bracket therefore increase monotonically to the root. On a compact bracket, R′ has a positive lower bound and |R″| a finite upper bound, yielding the usual local quadratic error bound. This justifies the starting side; it does not justify promising a universal number of iterations.

Floating-point implementations need a retained bracket, finite/positive derivative checks, a scaled residual tolerance, a boundary-location tolerance, and the reset-projection feasibility check. Roundoff can stall or violate exact monotonicity. Reject an inadmissible step or fall back to the bracketed method. Reuse the implicit backward at the accepted root; do not silently differentiate a truncated Newton algorithm instead. Report root error, complete-state error and scalar-loss VJP error separately. Near remap knots, a small boundary error can move between derivative branches.

## The slow-clock alias and its repair

The old control rule reads external input only at steps divisible by q=2. A cue present solely at odd step 5 changes the sender's signed content, but not its drift or boundary. In a boundary-only network, signed content has no outgoing path. Inductively, all future receiver states are independent of that cue. This is a structural alias, not evidence that all boundary communication is impossible.

The independent communication wrapper leaves the input writer on the raw observed frame. Only the input-drive branch receives one of these declared causal interfaces:

* Raw: the old instantaneous control input.
* Accumulate: sum impulse coordinates 0–3 since the preceding control update; retain the current clock and nuisance coordinates; consume the pending sum exactly once at an update.
* Hold: retain each cue's last observed value and observed flag until that cue is replaced. Arrival is read from an explicit binary flag, so a zero-valued cue is not confused with no cue.

Accumulate preserves pulse content up to a delay of at most q−1 observation steps. Hold supplies additional observation memory and must be described as such, rather than credited to the physical neuron. Neither computes A+B or sees a label. Both store pending/held tensors and the absolute clock in the returned state. Omitting these from a continuation silently changes the model.

The constructed-weight diagnostic reads receiver physical margin, not an immediate signed readout. For q=2, a sender update at t can affect receiver drift/boundary only at the next eligible receiver control step, because connections consume OLD messages. It observed:

| Cue arrival | Raw boundary path | Accumulate | Hold |
|---:|---|---|---|
| 4 | First receiver-margin effect at 6 | 6 | 6 |
| 5 | No effect in any of 12 steps | 8 | 8 |

Every earlier output difference was exactly zero. The six runtime checks also cover unchanged-core parity in raw mode, future-prefix invariance, odd-cut continuation, a nonzero buffered-input VJP against finite differences, and batch-independent unsigned transforms. These are causal/numerical diagnostics, not learned accuracies or a fresh-process serialization qualification.

## Unsigned-rate diagnostics

The reference unsigned event rate is obtained without data: solve πG₀=0, π1=1 on the nominal active-plus-refractory recurrent class and set j₀=πe. The unused absorbing bookkeeping state must be excluded, otherwise the stationary solution is not unique.

The diagnostic alternatives are j, j−j₀, and τ tanh((j−j₀)/τ), with fixed τ>0. They act only on the old unsigned recurrent message. Physical p, q, event counts and local value/risk keep their original semantics. At initial step zero there is no previous interval, so its empty message stays zero. No batch mean, current labels or future sample is used.

Centering removes one predetermined offset; it is not a proof that the actual nonstationary process has zero mean. Bounding changes the channel and attenuates its derivative by sech² ≤ 1. Saturation can lose practically usable information. With recurrent initialization proportional to 1/√N, a constant-rate row contribution does not automatically diverge with N; any optimization explanation needs measured channel contributions and preactivations.

The independent 21-fit campaign therefore compares signed-only against unsigned-plus-signed raw/centered/centered-bounded, with the boundary channel disabled in all four. Three further boundary-only arms compare raw/accumulate/hold. This isolates unsigned preprocessing within a fixed channel contract; it does not mix in a boundary channel and then attribute the whole change to unsigned flow.

## A coherent dual-force experiment

Two readout features do not satisfy the user's dual-force proposal. The implemented extension changes the next frozen segment's actual law using the previous complete population and previous interval's first-hit probability F. The normalized slope of the prior-law affine QVI solution is

\[
q(y)=\frac{U'(b+y)}{\alpha/\rho}=1-e^{-ky},\qquad
q_j=1-e^{-k x_j}\frac{1-e^{-kh}}{kh},
\]

where [x_j,x_j+h] is a finite-volume cell. Thus q_j is the exact average of the reference slope over that cell, rather than q evaluated at a mean population coordinate. Let q_target be its expectation under the same grid deposition of reference margin 0.7. The two feedback contributions are

\[
f_A=\gamma_A\sum_{j\in\mathrm{active}}p_j(q_{\rm target}-q_j),
\qquad f_B=-\gamma_B F,
\qquad
\mu_{k+1}=\mu_0+\Delta_\mu\tanh(d_{k+1}+f_A+f_B).
\]

For positive active mass m, f_A=γ_A m(q_target−E[q|active]). It is zero at the reference deposited distribution, positive for smaller slope moments, and negative for larger ones. All-refractory populations have f_A=0. This is a distributional restoring policy; the panic contribution is nonpositive. Both gains are fixed before holdout and the outer tanh preserves the existing drift bound. q_target and k are computed from the previous law, so this is a lagged family of reference potentials, not a single globally self-consistent optimal potential.

Recompute the new QVI boundary and transition generator with this actual μ, fixed absolute reset and the same delay law. Compute the next first-hit probability from that new generator. Keep cost controlled by the original unforced drive. The prior physical state already determines the call-gradient moment, so only the previous-risk tensor must be added to complete stream state. Four prespecified gain pairs (0,0), (0.5,0), (0,0.5), and (0.5,0.5) distinguish neither force, restoration alone, panic alone and both. The zero-gain implementation must reproduce the signed-only core exactly.

These terms now change transport rather than just the readout. Directional partial effects at a frozen prior state do not imply globally monotone event counts: the boundary, future population, refractory occupancy and feedback also change. A claim of faster learning or better representation still needs the separate matched training comparison; force direction tests alone do not establish it.

A stronger state-dependent potential-gradient version, such as μ(y)=μ₀+λ_C C′(y)+λ_P P′(y), generally leaves the constant-drift closed-form family. If C and P are claimed to describe that same changed law, they must be recomputed jointly with its generator/free boundary. Feeding old closed forms into a new drift while calling them the new law's exact solution is incoherent. Either declare them frozen reference potentials, or solve and differentiate the coupled control problem; neither shortcut is already proved by the financial paper.

## Prospective interpretation

The primary factorial fixes signed-only communication and compares fixed/learned/QVI boundary policies with value-risk/equal-dimensional tanh readout features. It uses 54 mixed-precision runs plus 9 separately registered native32 runs, new seeds, and new synthetic source identities. Equal 512-update comparisons are primary; the strict pre-180-training-CPU state is a separate, unselected budget snapshot. A 900-CPU interruption is censored, not a completed equal-update run.

Three seed means with fixed accuracy/Brier tolerances are engineering acceptance criteria, not a statistical noninferiority proof. New source identities from the same simulator are not new sensor modalities. Source, seed, cue parity and initial-state strata should remain visible. The fixed+tanh arm has structurally inactive cost parameters, and learned boundary has additional active parameters; equal feature dimension is not equal functional parameter count.

Readout coordinate sign/basis changes and within-group unit permutations can preserve a represented function when every corresponding tensor/state is transformed. Negating physical probability or a reset boundary is not such a symmetry. Input-affine edits for a buffered diagnostic must also transform the buffer's declared event-coordinate semantics; the old two-linear interface rewrite alone does not establish that equivalence.
