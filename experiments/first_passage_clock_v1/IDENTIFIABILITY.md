# What observed clocks identify

This note separates structural identifiability, local statistical information,
and optimization convergence. It does not establish an advantage for a
multilayer SNN, a surrogate gradient, meta-learning, or a production controller.
The accompanying `identifiability.py` uses deterministic integration and does
not read training, development, confirmation, or OOD episodes.

## 1. Observation contract

Let the known, strictly positive barrier distance be `d`. Starting from zero,

\[
dX_t=\mu\,dt+\sigma\,dW_t,\qquad
\tau=\inf\{t\ge0:X_t=d\},\qquad \sigma>0.
\]

An independent hidden cancellation time is \(C\sim\operatorname{Exp}(\lambda)\),
with \(\lambda\ge0\). A known observation horizon is \(h>0\).

- `hit(t)` means \(\tau=t\le h\) and \(\tau<C\).
- `no_hit(h)` means no hit was observed by \(h\). It includes both surviving
  contracts and contracts canceled without notification. It is not the event
  \(\tau>h,C>h\).

The observation law is a density on \((0,h)\) plus a no-hit atom:

\[
g_\theta(t)=e^{-\lambda t}
\frac{d}{\sigma\sqrt{2\pi t^3}}
\exp\!\left[-\frac{(d-\mu t)^2}{2\sigma^2t}\right],
\qquad
H_\theta(h)=\int_0^h g_\theta(t)\,dt,
\]

\[
\mathbb P_\theta\{\texttt{no_hit}(h)\}=1-H_\theta(h).
\]

The number of initiated contracts and their horizons are retained. Discarding
failed/no-hit contracts changes this observation law and its identifiability.
The task's randomized training horizons are independent of the hidden class
conditional on the public sampling design. A different informative-censoring
mechanism would need to enter the likelihood explicitly.

Here \(\lambda\) is a physical cancellation intensity, not a resource dual
price or an arbitrary discount parameter.

## 2. Known-distance structural identifiability

Expand the log density:

\[
\log\{t^{3/2}g_\theta(t)\}=A-\frac Bt-Ct,
\]

\[
A=\log\frac{d}{\sigma\sqrt{2\pi}}+\frac{d\mu}{\sigma^2},
\qquad B=\frac{d^2}{2\sigma^2},
\qquad C=\frac{\mu^2}{2\sigma^2}+\lambda.
\]

**Proposition.** For fixed known \(d>0\) and \(h>0\), the unconditional
observation law on \((0,h)\cup\{\texttt{no_hit}\}\) identifies
\((\mu,\sigma,\lambda)\).

**Proof.** Equality of observation laws implies equality of their continuous
hit densities almost everywhere on \((0,h)\). These densities are continuous
and positive there, so their log-density difference is zero throughout that
interval. The functions \(1,1/t,t\) are linearly independent on any nonempty
open interval: multiplying a purported linear relation by \(t\) gives a
polynomial that vanishes on an interval. Thus \(A,B,C\) agree. The physical
parameters are recovered uniquely by

\[
\sigma=\frac d{\sqrt{2B}},\quad
\mu=\frac{\sigma^2}{d}
  \left(A-\log\frac d{\sigma\sqrt{2\pi}}\right),\quad
\lambda=C-\frac{\mu^2}{2\sigma^2}.
\]

The observed no-hit count supplies the absolute hit incidence; the proof does
not normalize the density conditional on a hit. This is structural
identifiability of the population observation law, not a claim that a small
sample estimates every parameter accurately. Multiple horizons improve the
experimental design but are not required for this population argument.

## 3. Conditioning on hit loses one physical degree of freedom

Define

\[
\kappa=\sqrt{\mu^2+2\lambda\sigma^2}.
\]

The unconditional density has the exact factorization

\[
g_{\mu,\sigma,\lambda}(t)
=\exp\!\left[\frac{(\mu-\kappa)d}{\sigma^2}\right]
 f_{\kappa,\sigma}(t),
\]

where \(f_{\kappa,\sigma}\) is the ordinary first-passage density with drift
\(\kappa\). Hence, conditional on a hit before a fixed horizon,

\[
\mathbb P_\theta\{\tau\in dt\mid\tau<C,\tau\le h\}
=\frac{f_{\kappa,\sigma}(t)}{F_{\kappa,\sigma}(h)}\,dt.
\]

Only \(\kappa\) and \(\sigma\) remain. For fixed \(\kappa,\sigma\), all
admissible pairs satisfying

\[
\lambda=\frac{\kappa^2-\mu^2}{2\sigma^2}\ge0
\]

give the same conditional timing law. Conversely, the coefficients of
\(1/t\) and \(t\) in its log density identify \(\sigma\) and \(\kappa^2\);
the convention \(\kappa\ge0\) identifies \(\kappa\).

For positive \(\mu,\lambda\), in log coordinates
\(z=(\log\mu,\log\sigma,\log\lambda)\), a null direction is

\[
v_{\rm conditional}\ \propto\ (\lambda\sigma^2,\ 0,\ -\mu^2).
\]

It keeps \(\sigma\) and \(\kappa\) unchanged to first order. The loss of
information is exact, not an optimizer failure.

If hit-only records retain known horizon labels, their relative horizon
frequencies also depend only on \(\kappa,\sigma\): the same multiplicative
amplitude cancels. Retaining the number of initiated but unsuccessful
contracts restores incidence information and is no longer a hit-only design.

## 4. Unknown voltage scale remains unidentifiable

For every \(c>0\), the transformation

\[
(d,\mu,\sigma,\lambda)
\longmapsto(cd,c\mu,c\sigma,\lambda)
\]

leaves \(g(t)\), \(H(h)\), and every observation probability unchanged.
Thus observing clocks does not identify an unknown voltage unit. Fixing `d`,
or independently calibrating voltage, is essential. Without it, the
identifiable combinations can be written as \(\mu/d,\sigma/d,\lambda\).

In coordinates \((\log d,\log\mu,\log\sigma,\log\lambda)\), the null
direction is \((1,1,1,0)\). The four-parameter Fisher matrix therefore has
rank at most three.

A separate time-scale transformation,

\[
(\mu,\sigma,\lambda)\longmapsto(c\mu,\sqrt c\sigma,c\lambda),
\]

preserves the eventual hit probability but changes the timing law according
to \(g_c(t)=c\,g(ct)\) and \(H_c(h)=H(ch)\). This is the reason the task's
two classes have equal eventual incidence but different finite-time evidence.

## 5. Fisher calculation and comparison units

For the fixed known `d` diagnostic, all reported matrices use dimensionless
log coordinates \(z=(\log\mu,\log\sigma,\log\lambda)\). This avoids a
rank/condition comparison driven by choosing seconds instead of milliseconds
or rescaling physical parameter units.

Let \(s(t)=\nabla_z\log g(t)\), \(u_h=\nabla_z H(h)\). The full Fisher
information per initiated contract is

\[
I_{\rm full}(h)
=\int_0^h g(t)s(t)s(t)^\top\,dt
 +\frac{u_hu_h^\top}{1-H(h)}.
\]

The binary hit/no-hit information, with exact hit time discarded, is

\[
I_{\rm binary}(h)=\frac{u_hu_h^\top}{H(h)[1-H(h)]}.
\]

Conditional timing information per observed hit at that horizon is

\[
I_{\rm cond}(h)
=\int_0^h\frac{g(t)}{H(h)}
 \left[s(t)-\frac{u_h}{H(h)}\right]
 \left[s(t)-\frac{u_h}{H(h)}\right]^\top dt.
\]

The information chain rule gives

\[
I_{\rm full}(h)=I_{\rm binary}(h)+H(h)I_{\rm cond}(h).
\]

The script integrates the density-weighted outer products directly, rather
than estimating a Hessian by differencing nearly equal likelihood values.
It averages full and binary information over equally likely horizons. It
reports equal-horizon conditional information per hit, a version weighted by
the horizons' probabilities among retained hits, and the joint information
when retained hit records also keep the randomized horizon label. The last
version adds the horizon-label information: the distribution of horizon
labels among successful contracts is parameter-dependent. All three lose the
same physical degree of freedom. Per-hit and per-attempt information have
different denominators; their raw eigenvalues should not be compared as
equal-cost evidence.

## 6. Deterministic numerical result

At \(d=1\), \((\mu,\sigma,\lambda)=(0.8,0.6,0.35)\), with equally
weighted horizons \(0.25,0.6,1.2,2.4\):

| Observation design | Eigenvalues, ascending | Numerical rank |
|---|---|---:|
| Full event time plus no-hit, per attempt | 0.0348410, 0.3497515, 1.3595543 | 3 |
| Finite-horizon binary hit/no-hit, per attempt | 0.00760162, 0.1506265, 0.6311457 | 3 |
| Hit-conditioned timing, equal horizon weights, per hit | approximately 0, 0.1793888, 2.9949245 | 2 |
| Eventual hit indicator alone, per attempt | approximately 0, approximately 0, 0.5197818 | 1 |
| Full observations, unknown distance and voltage scale | approximately 0, 0.0352155, 0.3623356, 3.8951412 | 3 of 4 |

The full known-distance condition number is approximately 39.02. The
finite-horizon binary design has condition number approximately 83.03.
**Therefore exact timestamps are not uniquely necessary for local
identification in this particular multi-horizon design.** The four binary
incidences already give rank three at this point; timestamps add positive
information. A study that attributes all improvement specifically to exact
timestamps would need a time-discarding ablation.

Maximum integration consistency residuals were:

- hit mass versus closed-form CDF: \(3.33\times10^{-16}\);
- integrated event score versus closed-form CDF derivative:
  \(1.39\times10^{-16}\);
- Fisher chain-rule residual: \(3.59\times10^{-16}\);
- conditional null-direction residual: \(1.49\times10^{-17}\).

For 256 independent contracts of one class under this horizon design,
\(\sqrt{\operatorname{diag}(I^{-1})/256}\) gives local asymptotic standard
errors in log parameters of approximately

\[
(0.1370,\ 0.0801,\ 0.3178).
\]

These are information-scale diagnostics, not calibrated confidence intervals
for the particular finite training dataset. They already indicate that
cancellation is substantially less precisely estimated than noise at this
sample size. Full structural rank does not mean a fitted cancellation rate
will be numerically close to its truth in every seed.

The script uses candidate kernels for its density and CDF derivatives. The
residual checks and information decomposition are useful internal
consistency diagnostics, **not an independent oracle**. `IDENTIFIABILITY.json`
records source hashes, runtime versions, matrices, per-horizon results and
the repository head. No random samples or held-out episodes enter this run.

Reproduce with:

```bash
python -m experiments.first_passage_clock_v1.identifiability
```

## 7. What convergence can be justified

Consider parameters in a compact domain with \(\sigma\ge\sigma_{\min}>0\),
finite bounded drift and cancellation, fixed known \(d>0\), and observed
horizons bounded away from zero and infinity. At a strictly interior truth,
the event law is smooth in physical parameters. The small-time Gaussian
factor controls polynomial score terms as \(t\downarrow0\); finite horizons
and compact nondegenerate parameters keep the no-hit probability positive.
These conditions support differentiation under the expectation and the
usual local likelihood regularity argument.

At the correctly specified truth, the expected negative-log-likelihood
Hessian equals the full Fisher matrix. Positive definiteness implies, by
continuity, a sufficiently small convex neighborhood with Hessian bounds

\[
mI\preceq\nabla^2\mathcal L\preceq LI,\qquad 0<m\le L<\infty.
\]

Exact gradient descent initialized in a suitable invariant neighborhood and
using \(0<\eta\le1/L\) then has local linear convergence. A sufficiently
large empirical sample may inherit such local curvature under appropriate
uniform convergence conditions; no finite-sample threshold is proved here.
Bounded iterates or a finite L-BFGS-B termination message alone do not prove
these hypotheses. The actual experiment therefore retains optimizer status,
multiple starts and numerical residuals separately from this argument.

This result does not establish global convexity in \((\mu,\sigma,\lambda)\),
global convergence from arbitrary initializations, convergence at parameter
boundaries, or convergence under a misspecified event model. The hit-only
three-parameter objective has an exact unidentifiable direction, so the
same positive-curvature argument cannot apply to all three physical
parameters there.

No part of this likelihood result transfers automatically to a hard-spike
backward hook, bilevel meta-SG, learned free boundaries, a coupled recurrent
SNN, or a nonstationary resource-price loop. Those introduce different
objectives, gradient estimators, event boundaries, and stability conditions.
