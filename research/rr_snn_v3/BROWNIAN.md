# Brownian interval operator

This stage extends the finite continuation reference in PR #4233 with the
constant-coefficient Brownian first-passage and killed-transition operators.
It is a mathematical research module, without production installation or
an architecture performance claim.

## Defined process

The state is distance from an absorbing threshold:

\[
X_t=x+\mu t+\sigma W_t,\qquad x>0,\quad \sigma>0,\qquad
\tau=\inf\{t:X_t\leq0\}.
\]

Positive distance drift moves away from the threshold. For evidence
\(Y_t=y+a t+\sigma W_t\) with fixed threshold \(h\), use \(x=h-y,\mu=-a\).
The analytic first-passage density and killed density are

\[
f(t)=\frac{x}{\sigma\sqrt{2\pi t^3}}
\exp[-(x+\mu t)^2/(2\sigma^2t)],
\]

\[
K_t(z|x)=\frac{\phi((z-x-\mu t)/s)}{s}
[1-\exp(-2xz/(\sigma^2t))],\qquad s=\sigma\sqrt{t}.
\]

The equivalent image-density difference uses expm1 and log probabilities
to reduce cancellation. Its mass is survival:

\[
S(t)=\Phi((x+\mu t)/s)
-\exp(-2\mu x/\sigma^2)\Phi((-x+\mu t)/s).
\]

For positive mu, eventual hitting probability is exp(-2*mu*x/sigma^2)<1.
The sampler retains non-hitting mass.

These interval formulas are standard absorbing Brownian results. The
research question concerns continuation values, maturity obligations and
resource costs controlling neural operators; it does not concern inventing
the Brownian first-passage distribution.

Primary context:
- He and Xiong, *Rollover Risk and Credit Risk*:
  https://www.princeton.edu/~wxiong/papers/rollover.pdf
- Molini, Talkner, Katul, and Porporato, *First passage time statistics of
  Brownian motion with purely time dependent drift and diffusion*:
  https://arxiv.org/abs/1009.0557

Image solutions do not extend to arbitrary time-varying coefficients.
Here coefficients and boundary are constant within each interval.

## Surviving input changes

When an input arrives at D, a neuron that has not fired has distribution

\[
X_D\mid\tau>D\sim K_D(\cdot|x)/S(D).
\]

An unconditional Gaussian endpoint reintroduces paths that crossed the
threshold. After a parameter switch, use the actual conditional endpoint.

The interval function uses an inverse hitting CDF for a hit before the
horizon, otherwise a numerical inverse of K/S. A null hitting quantile
means no hit before that horizon. Uniform variates must lie inside (0,1).
Equality at the horizon belongs to the no-earlier-hit branch.

This module does not implement pathwise runUntil replay. Adding random
conditional endpoints may change a coupled sample while preserving its law.
Full replay and scheduling belong to the marked-event runtime.

## Gradients and censoring

The exported scores differentiate log first-passage density, log survival,
and log killed endpoint density with respect to x, mu and sigma.

For an interval observed only as "no spike before D", likelihood is log S(D).
If the physical endpoint is also part of the complete path, the joint
contribution is log K_D(z|x). Equivalently log S + log(K/S) = log K.
Survival must not be charged twice. A hit contributes log f(t).
Each reset, later spike and final censored interval needs its own term.
These derivatives alone do not establish a full-network gradient estimator.

## Numerical scope

Probability formulas are analytic; normal CDF evaluation, CDF inversion and
continuation quadrature are numerical floating-point computations.
No moving-boundary closed form is asserted.

Parameters must be finite with x,sigma>0 and t>=0. Explicit work/magnitude
caps reject unsupported values. Unresolved positive image subtraction
rejects rather than silently returning an invalid law. Survivor inversion
requires S>=1e-12; derivative overflow rejects. Inverse-CDF work caps
also check the final probability residual, rejecting a poorly resolved root.

Validation quadrature truncates beyond 12 Gaussian standard deviations.
Reported error is fixture agreement, not a universal certified bound.
The 120 mass cases cover x={.001,.01,.1,1,4,10}, mu={-4,-1,0,1,4},
sigma=1 and t={.01,.1,1,10}; extreme cancellation explicitly rejects.

## Actual validation

There are 20 checks: independent normal-density quadrature, probability
mass, CDF/density agreement, killed Chapman-Kolmogorov composition, 36
hit/censored/endpoint derivative components, inverse CDF residuals,
non-hitting mass, twelve rejection cases and the restricted policy example.

A fixed-seed diagnostic uses 4,096 conditional endpoints and a subsequent
parameter switch, compared with independent killed-density integrals.
This is calibration, not a selected architecture holdout.

For x=.8, mu=.1, sigma=.7, D=1, conditional endpoint mean is 1.1329118839;
unconditional mean is .9. Switching mu to -.6 for .75 time units gives
conditional next-interval survival .6986966673. The sampler mean was
1.1257044935 (SE .0087011049), survival .6943359375 (SE .0071691279).

## Restricted continuation example

One cohort starts with evidence .8, evidence drift -.1, sigma .3, budget 2.
Output and renewal debit one each. Output ends the cohort. At D=1 choose
drop, output, or renewal to D+1 with drift +.7 and terminal positive-evidence
output. Only renewal incurs utility fee L.

Before D choose immediate output or fixed threshold h in {.85,1,1.2,1.5,2}:

\[
V_h=h\,P(\tau_h<D)+
\int_0^\infty K_D(z|h-.8)
\max\{0,h-z,E[(h-z+.7+.3Z)^+]-L\}\,dz.
\]

At L=0, best listed h=2 gives 1.4000430694. At L=.8, immediate output
is best at .8. This establishes the direction only within this policy set.
It is not a global free-boundary solution or universal pulse-count theorem.

## Reproduce

    node research/rr_snn_v3/validate_brownian.cjs

Exact CommonJS text was executed in the conversation JavaScript V8 runtime;
raw numerical output is in brownian_results.json. Shell initialization
failed, so Node CLI, just fmt, target-host measurements and production
execution were not run.


## Independent numerical-domain review

An independent reviewer executed the supplied mathematical function bodies
(comments and whitespace elided), rather than auditing complete-file byte identity.
The review found loss of relative accuracy for survival at distances 1e-12 and
1e-16 with mu=sigma=t=1. The implementation now requires a log-difference gap
above 1e-6 in both survival and endpoint CDF calculations. This is a conservative
conditioning guard, not a universal error certificate. Nonempty Gaussian intervals
whose log mass cannot be resolved and positive endpoints whose reflection scale
underflows are also rejected. Empty intervals and the absorbing endpoint still
have valid zero mass.

The complete validator now passes 20 grouped checks, including 16 rejected invalid
or unresolved inputs and the original 4096 surviving-path switch sample.
Independent direct-density quadrature, Richardson derivatives and inverse-CDF
checks are recorded in brownian_independent_audit.json. Final complete source bytes
are verified separately by the Node execution receipt.
