# Round 8: continuous event laws and finite-model resolution

## Source and model identity

This directory is a new, independently implemented NumPy/SciPy research module.
The historical Round 7 baseline is commit
`1bbf9712140ec388f7fb7967fa7b22244386441d`; the native task baseline is
`e67a5e13ba82768a25858153452c15e76670b641`. Neither baseline is rewritten.

Round 7 `experiments/analytic_event_neuron/round7/dynamics.py` uses an upwind
finite OU chain and a per-tick refractory release law. The native
`tools/hcsn/value_boundary_v2_20261031/model.py` instead describes a finite
packet-evidence CTMDP, exponential task deadline and Erlang recovery. They are
different mathematical models. The present Brownian kernels do not certify
either old checkpoint as a continuous diffusion model.

The continuous contract here is scalar `dX=mu dt+sigma dW`, `sigma>0`, one
upper boundary, and strictly positive initial/reset distance. Constant or
affine boundary segments are supported. OU drift, arbitrary nonlinear moving
boundaries, correlated noise, interacting cells and learned input changes
inside an undeclared segment are outside this contract. Initial points on or
above the boundary require a caller-owned immediate event; this API rejects
them rather than hiding an atom in a density.

## Exact first-event objects

Let `d=b-x>0`, `tau=inf{t:X_t>=b}` and `s=sigma sqrt(t)`. The reflection
principle gives, with `Phi` the standard normal CDF,

\[
F_d(t)=\Phi((\mu t-d)/s)+e^{2\mu d/\sigma^2}\Phi((-\mu t-d)/s),\qquad
f_d(t)=\frac{d}{\sigma\sqrt{2\pi t^3}}
e^{-(d-\mu t)^2/(2\sigma^2t)}.
\]

The endpoint crossing probability is only the first summand. The reflected
term accounts for paths that cross and return. For `b(t)=b(0)+v t`, the gap
process gives the same formulas with `mu-v`; this is exact, not a frozen
approximation to a nonlinear boundary. The first-hit transform is

\[
G_q(t)=e^{(\mu-\sqrt{\mu^2+2q\sigma^2})d/\sigma^2}
F_d(t;\sqrt{\mu^2+2q\sigma^2},\sigma).
\]

`F` is a probability. `G` is a discounted event payoff weight. Neither is a
vanilla call/put price. The neural law uses its stated physical transition
measure, not a financial risk-neutral drift imported without justification.

The reflected/free Gaussian-density identity permits cancellation-free
evaluation of the killed density in the remaining-gap coordinate `y>0`:

\[
K_t(d,y)=\frac{e^{-(y-d+\mu t)^2/(2\sigma^2t)}}{\sigma\sqrt{2\pi t}}
\left(1-e^{-2dy/(\sigma^2t)}\right).
\]

Thus `K>=0` and its integral is `1-F`. Conditional continuation must propagate
this killed law. Multiplying independent tick-wise Bernoulli probabilities
without carrying the surviving state does not reproduce it.

The implementation uses `erfcx`, `log_ndtr` and `expm1` factorizations. It
retains `log_probability` and `log_survival` when ordinary probabilities round
to zero or one. It rejects nonfinite inputs, unrepresentable variance and
dimensionless distance/drift larger than `1e6`. Ill-conditioned survival
subtraction now uses the positive integral below, rejecting unresolved
quadrature. These guards are not a uniform float64 error proof.
Analytic CDF derivatives are derivatives of this distribution, not automatically
unbiased gradients of sampled hard-event trajectories. Underflowed derivative
values do not provide a log-gradient API.

### Near-boundary survival correction

The frozen direct log subtraction at `d=1e-15,mu=0,sigma=t=1` returned
`1.1102230246251546e-15`; the exact `erf(d/sqrt(2))` is
`7.978845608028654e-16`. Its sign check therefore admitted a 39.15% relative
error. A negative log-ratio alone does not establish retained significant
digits. This counterexample is preserved in `tail_regression.py` and its raw
evidence; it is not an admissible accuracy claim for the old source.

Write `a=d/(sigma*sqrt(t))`, `v=mu*sqrt(t)/sigma`, `c=v-a` and
`E(x)=(1-exp(-x))/x`, with `E(0)=1`. For `v>=0`, integrating the positive
killed density and substituting `y=ell*u`, `ell=1/max(1,c)`, gives

\[
S(a,v)=2a\,\phi(c)\ell^2\int_0^\infty
u\exp[-c\ell u-(\ell u)^2/2]E(2a\ell u)\,du.
\]

In the small-survival subtraction layer this integral stays on a resolved
scale even at large positive drift. For `v<0`, the alternative identity

\[
S(a,v)=a\phi(v)\int_{-1}^{1}e^{vau-a^2u^2/2}\,du
+(1-e^{2av})\Phi(-a-v)
\]

has two nonnegative terms. Evaluate `E` with `exprel`, retain multiplicative
factors as logarithms, and use positive quadrature when the direct log-ratio
exceeds `-1e-3`. If forming `a` itself underflows, its logarithm is still
`log(d)-log(sigma*sqrt(t))`; the remaining integral admits its `a=0` limit.
The reported numerical quadrature estimate must meet the implementation's
relative gate. Neither this estimate nor the trigger is a universal rounding
certificate. Ninety-digit Decimal CDF subtraction and an independently scaled
first-hit *time-density* integral verify the frozen regression fixtures.

`two_segment_first_hit` composes killed propagation by positive quadrature.
At a downward boundary jump, all surviving mass beyond the new boundary is
counted immediately. Truncating the old gap integral at
`max(0,d-mu*t)+z*sigma*sqrt(t)` omits at most the chosen Gaussian tail mass,
since `K` is bounded by the free Gaussian density. Quadrature estimates and
floating-point error are distinct from that analytic truncation bound.

## Why changing the spatial stencil is insufficient

For interior spacing `h`, Round 7 upwind rates obey

\[
q_\pm=\frac{\sigma^2}{2h^2}+\frac{(\pm\mu)_+}{h},\quad
h(q_+-q_-)=\mu,\quad h^2(q_++q_-)=\sigma^2+|\mu|h.
\]

Scharfetter--Gummel rates use `D=sigma^2/2`, `Pe=mu*h/D` and
`B(z)=z/expm1(z)`: `q_+=D B(-Pe)/h^2`, `q_-=D B(Pe)/h^2`.
They preserve the constant-drift exponential ratio, but their local variance is

\[
\sigma_{\rm eff}^2=\mu h\coth(\mu h/\sigma^2)
=\sigma^2+\frac{\mu^2h^2}{3\sigma^2}+O(h^4).
\]

At fixed `h` as `sigma` tends to zero this still tends to `|mu|h`. Therefore
fitted rates improve the small-Peclet consistency order but cannot make a
coarse low-noise chain equal Brownian motion. `require_local_resolution`
rejects extra variance above 5% by default. Passing this necessary moment
check is explicitly not a first-passage accuracy certificate.

The inherited counterexample uses `mu=1,sigma=.05,b=1,t=.8`. The continuous
one-upper-barrier probability is `4.32182600673e-6`; the two-boundary lower-first
correction is bounded by `exp(-800)`. On grid 63, upwind gives approximately
`.13307838` and fitted rates still give `.12363090`. The audit preserves these
failures and routes the scalar Brownian reference through its independent
continuous kernel. It does not rename the failing chain as an exact cell.

## Physical recovery and repeated events

Recovery is `Erlang(m,lambda)`, with `lambda=m/mean_seconds`. Its phase-chain
transition is `exp(t Q_rec)`, so subdividing a physical second preserves the
same recovery law. A reference tick release `q` can calibrate a single-phase
hazard `-log(1-q)/reference_seconds`, but this does not recreate the historical
rule that freezes a newly fired path through its current and next tick.

For fixed coefficients and point reset gap `r>0`, strong Markov independence
and the first-hit Laplace transform imply that the sum of `n` active waiting
times has the law of a first hit at distance `d+(n-1)r`. The sum of the `n-1`
independent recovery periods is `Gamma(m(n-1),lambda)`. Consequently,

\[
E[N_t]=\sum_{n\ge1}P(N_t\ge n),\qquad
P(N_t\ge n)=\int_0^t F_{d+(n-1)r}(t-u)
\,\mathrm{Gamma}_{m(n-1),\lambda}(du).
\]

For `n=1` the recovery distribution is an atom at zero. This positive
quadrature admits multiple events within the same observation interval and
has no voltage or time mesh. `sample_counts` independently samples exact
Wald/Lévy waiting times and Gamma recoveries; it is not an Euler simulation.

For any tilt `s>0`, put
`k=(sqrt(mu^2+2*s*sigma^2)-mu)/sigma^2` and
`R=exp(-k*r)*(1+s*mean_seconds/m)^(-m)<1`. Chernoff's inequality gives the
count-tail bound after `M` terms:

\[
\sum_{n>M}P(N_t\ge n)\le
\frac{e^{st-kd}R^M}{1-R}.
\]

The implementation selects a finite sum meeting this bound or rejects the
request under its declared event budget. Analytic-integrand derivatives include
the recovery-mean score `(lambda*u-shape)/mean_seconds`. The count-tail bound
does not certify derivative-tail error. The registered test compares additional
terms and independent finite differences for its fixtures; no uniform neural
gradient certificate follows.

## Killed and regenerative Bellman stability

For bounded functions, positivity and `K_t 1<=1` give
`||K_t f-K_t g||_infinity<=||f-g||_infinity`. With a fixed positive decision
interval `Delta`, bounded rewards and discount `rho>0`, the Bellman map
`max_a[r_a+exp(-rho*Delta) P_a V]` contracts by at most `exp(-rho*Delta)`.

An instantaneous FIRE branch generally has norm one. It is incorrect to claim
the same one-step contraction for a zero-time impulse QVI. At regenerative
cycle epochs, however, every repeated FIRE in the present contract must incur
its independent positive recovery. Its discounted continuation mass is at most
`D=(1+rho*mean_seconds/m)^(-m)<1`. The cycle Bellman operator is a sup-norm
contraction by at most `D`, giving a unique bounded value and residual/error
amplification at most `1/(1-D)`. This statement requires bounded rewards and
the specified mandatory recovery; it is not a theorem about arbitrary
unbounded affine payoffs, zero-delay reset, or a large coupled network.

More precisely, choose decision epochs and augment the state with every
variable needed by the next event, reset and recovery. For each admissible
action let `C` be the duration to the next epoch and define the *discounted*
substochastic kernel

\[
Q_a(x,A)=E_x[e^{-\rho C}1\{X_C\in A,\ C<\infty\}\mid a],\qquad
(TV)(x)=\sup_{a\in A(x)}[g_a(x)+Q_aV(x)].
\]

Require measurable kernels and action selection, bounded `g`, and
`sup_{x,a}Q_a(x,S)<=beta<1`. The elementary inequality
`|sup f-sup h|<=sup|f-h|` then proves
`||TV-TW||<=beta||V-W||`; Banach's theorem supplies the unique bounded fixed
point. The recovery bound applies only when **every nonterminal action** in
this epoch model must include the specified recovery. An arbitrary zero-time
WAIT or bypass action invalidates that uniform premise. Merely knowing that
each individual recovery has positive mean is also insufficient for a uniform
bound over learned actions. For Erlang laws with a common lower mean
`mean_seconds>=r0>0` and integer `m>=1`, one may use
`beta<=(1+rho*r0)^(-1)`; if the allowed mean tends to zero, this bound tends
to one. No contraction is asserted at `rho=0` without a separate uniform
termination/kill condition.

For a numerical candidate `Vhat`, measured residual `delta=||Vhat-That Vhat||`,
reward error at most `eta`, and discounted kernels whose cemetery-augmented
TV error is at most `epsilon`, the same argument yields

\[
\|V-\widehat V\|_\infty\le
\frac{\delta+\eta+2\epsilon\|\widehat V\|_\infty}{1-\beta}.
\]

Here TV uses `sup_A|P(A)-Q(A)|`; the cemetery value is zero. This bound requires
the same complete state and legal actions. It accounts for mass lost by kill
or discount; renormalizing surviving mass would change the operator. The
bound does not establish the regularity, viscosity comparison or consistency
conditions for an arbitrary continuous impulse QVI. Those remain separate
obligations. `HIGH_DIMENSIONAL.md` records product/coupling, reset and action-gap
limits rather than promoting this scalar result to a whole network theorem.

## Primary mathematical sources

- [MIT 6.265/15.070J, Lecture 7, Brownian motion (2013)](https://ocw.mit.edu/courses/15-070j-advanced-stochastic-processes-fall-2013/aca1518a09539a09ddd37428ab0d0268_MIT15_070JF13_Lec7.pdf):
  reflection principle, strong Markov decomposition and first-hit Laplace
  transform. The specific stable formulas above are derived from the stated
  scalar law; the lecture is not a numerical-error certificate.
- [D. P. Bertsekas, Abstract Dynamic Programming, overview](https://web.mit.edu/dimitrib/www/Abstract_DP.pdf),
  slides 10--15: semi-Markov state/action-dependent discount factors and the
  distinction between uniform contraction and semicontraction. The cycle
  hypotheses and error bound above are stated explicitly for this implementation.

## Reproduction and review stages

From the repository root:

```sh
python -m unittest tools.hcsn.round8_20261031.event_dynamics.test_event_dynamics -v
python -m tools.hcsn.round8_20261031.event_dynamics.validation --output tools/hcsn/round8_20261031/event_dynamics/evidence/event_audit_verified.json
```

The earlier preliminary, final-named and verified records preserve their
original source hashes. The continuation adds `event_audit_continuation.json`,
`spatial_resolution_continuation.json` and `tail_regression_continuation.json`
for the corrected source; old records are not substituted for these. The
tolerances are diagnostic numerical
qualification criteria, not preregistered
confirmatory performance claims. Evidence includes exact baseline identities,
runtime versions, source hashes, all finite-generator failures, raw Monte Carlo
histograms and every tested derivative. For review, the coherent stages are:
`event_kernel.py` (continuous events), `generator.py` plus `renewal.py`
(resolution/recovery/recurrence), and validation/tests/theory. Each source
module remains below 500 lines. No original source, learned checkpoint or
remote branch is modified by these modules.
