# Fixed-reset renewal contract and independent audit

## Scope and interpretation

This research operator describes a one-dimensional Brownian distance from an
absorbing boundary. It is not the full He–Xiong equity model, a proof of optimal
task control, or an exact expectation of a nonlinear recurrent content network.
The default parameters are `mu=-0.25, sigma=1, reset=0.8, refractory=0.15,
horizon=1`. A separate content experiment may use the expected count as a gate
feature. All claims below refer to the explicit local stochastic contract.

He and Xiong, *Rollover Risk and Credit Risk*, Journal of Finance 67 (2012),
391–430, provide the motivating endogenous boundary and first-passage valuation
setting: <https://www.princeton.edu/~wxiong/papers/rollover.pdf>.
The reset renewal identities and their implementation below are our derivations.
Absorbing flux and reset-source formulations also have established neural
population antecedents, e.g. *Neuronal Dynamics*, section 13.3:
<https://neuronaldynamics.epfl.ch/online/Ch13.S3.html>.

## 1. Pathwise contract

On each active period,

\[
 dX_t=\mu\,dt+\sigma\,dW_t,\qquad X_0=x\geq0,\qquad
 \tau_x=\inf\{t\geq0:X_t\leq0\}.
\]

An arrival at zero counts immediately. The cell is then inactive for a fixed
duration `d=refractory`, after which its distance is set to `r=reset>0`. A new
active first-passage period uses the same drift and diffusion coefficients and
independent Brownian increments. Drift, diffusion, reset, and refractory duration
are frozen throughout the requested horizon. Multiple hits in that horizon are
allowed. A positive drift permits a nonzero probability of never hitting again.

Inputs are finite, `x>=0`, `sigma>0`, `horizon>=0`, `reset>0`, `refractory>=0`.
Zero noise is deliberately outside this implementation's domain; deterministic
crossings require a separate nonsmooth contract. At `x=0` the first event is an
atom at time zero, including when the observation horizon is zero. At
`x=0,horizon=0` the spatial derivative is undefined and the API returns NaN.
For `x=0,horizon>0` the reported derivative is the right derivative.

The index of the last firing is not a substitute for the live distance or
refractory age when continuing a process across multiple calls. A globally
continuous renewal simulation must retain that state. Reinitializing `x` from
an encoder at every token defines a local gate feature, not an exact global
renewal trajectory.

## 2. First-passage kernels

For `t>0`, `x>0`, set `s=sigma*sqrt(t)` and

\[
 z_1=(-x-\mu t)/s,\qquad z_2=(-x+\mu t)/s.
\]

Then

\[
 F(t,x)=\Pr(\tau_x\leq t)
 =\Phi(z_1)+e^{-2\mu x/\sigma^2}\Phi(z_2),
\]

\[
 f(t,x)=\frac{x}{\sigma\sqrt{2\pi t^3}}
 \exp\left[-\frac{(x+\mu t)^2}{2\sigma^2t}\right],
\]

\[
 F_x(t,x)=-\frac{2\phi(z_1)}{s}
 -\frac{2\mu}{\sigma^2}e^{-2\mu x/\sigma^2}\Phi(z_2).
\]

For negative time, the internal count-tail calculation uses zero probability.
At positive distance and time zero it also uses zero. The density function
returns the continuous density only; it does not encode the `x=0` Dirac atom.

The CDF implementation evaluates the two terms in log space. For `z2<=0`, the
second term is evaluated as

\[
 B=\tfrac12 e^{-z_1^2/2}\operatorname{erfcx}(-z_2/\sqrt2),
\]

which avoids an overflowing prefactor multiplied by an underflowing CDF. For
`mu<0`, define `u=x/s`, `a=-z2`, `R(a)=Phi(-a)/phi(a)`. The gradient is computed as

\[
 F_x=-\frac{2\phi(z_1)}s\{[1-aR(a)]+uR(a)\}.
\]

The difference `1-a*R(a)` uses the alternating inverse-power expansion beginning
`a^-2-3a^-4+15a^-6-...` for `a>=20`; eleven terms are used. This prevents
catastrophic cancellation in strong negative drift. The moderate and extreme
domains below are audited; no claim is made that all finite IEEE-754 inputs can
produce representable derivatives without overflow.

The killed transition density has a stable nonnegative expression for `y>=0`:

\[
 K_t(x,y)=\frac1{\sigma\sqrt t}
 \phi\left(\frac{y-x-\mu t}{\sigma\sqrt t}\right)
 \left(1-e^{-2xy/(\sigma^2t)}\right).
\]

Its integral is `1-F(t,x)`. The implementation uses `-expm1` for the final factor.

## 3. Exact count tails, PMF, and spatial gradient

With independent active waiting times, the nth firing time is

\[
 T_n=\tau_x+\sum_{j=1}^{n-1}\tau_r^{(j)}+(n-1)d.
\]

First-passage times to successive levels of a Brownian motion with fixed drift
have independent increments in the level distance. Their defective Laplace
transform is

\[
 \mathbb E[e^{-q\tau_x};\tau_x<\infty]
 =\exp\left[-\frac{\mu+\sqrt{\mu^2+2q\sigma^2}}{\sigma^2}x\right].
\]

Multiplication of these transforms proves the convolution identity
`tau_x + tau_r + ...` equals in distribution `tau_(x+(n-1)*r)`, including the
defect at infinity when `mu>0`. Hence, for `n>=1`,

\[
 Q_n(H)=\Pr(N_H\geq n)
 =F\bigl(H-(n-1)d,\,x+(n-1)r\bigr).
\]

With `Q0=1`, `Pr(N_H=n)=Q_n-Q_(n+1)` and

\[
 \mathbb E[N_H]=\sum_{n\geq1}Q_n(H),\qquad
 \partial_x\mathbb E[N_H]=\sum_{n\geq1}
 F_x\bigl(H-(n-1)d,x+(n-1)r\bigr).
\]

The derivative is with respect to the *initial* distance only, holding all other
arguments fixed. If a model also learns drift, noise, reset or refractory time,
it needs those additional derivative terms.

For `d>0` the sum has finite support. All terms with a positive remaining horizon
are evaluated; zero-time subsequent hits have positive reset distance and zero
probability. For `d=0` the series is infinite and the code never calls a finite
truncation exact: it reports mathematical upper bounds on omitted mean and
absolute-gradient terms. These are real-arithmetic tail bounds, not a certified
interval enclosure of floating-point roundoff.

## 4. Controlled infinite sum when refractory time is zero

After summing `M` terms, let `a=x+M*r`, `s=sigma*sqrt(H)`,
`m=max(0,-mu)*H`, and `q=(a-m)/s`. For `q>0`, the Brownian supremum bound gives

\[
 F(H,a)\leq2\Phi(-q),\qquad
 \sum_{j\geq0}F(H,a+jr)
 \leq 2\Phi(-q)+\frac{2s}{r}[\phi(q)-q\Phi(-q)].
\]

The bracket is computed as `phi(q)*(1-q*R(q))`, avoiding tail cancellation.
For `q<=0` the implementation reports an infinite bound and continues summing.

For the derivative, put `z=(a+mu*H)/s`, which is positive whenever `q>0`, and

\[
 R_g=\exp\left[-\frac{2(a+\mu H)r+r^2}{2s^2}\right]<1.
\]

The Gaussian terms have successively smaller ratios. Since
`|Fx| <= 2*phi((x+mu*H)/s)/s + 2*max(mu,0)/sigma^2*F`, the omitted absolute-gradient
sum is bounded by

\[
 \frac{2\phi(z)}{s(1-R_g)}+
 \frac{2\max(\mu,0)}{\sigma^2}\,B_{\rm mean}.
\]

The stopping tolerances are `1e-13 + 2e-13*abs(accumulated sum)` separately for
mean and derivative. There is an explicit maximum of 10000 terms, after which
the call raises rather than silently returning an uncontrolled truncation.

## 5. Public interface and content gate interpretation

```python
expected_count(x, mu, sigma, horizon, reset, refractory) -> numpy.ndarray
expected_count_dx(x, mu, sigma, horizon, reset, refractory) -> numpy.ndarray
expected_count_details(...) -> dict
```

All arguments broadcast. For example, `x[B,W]` and `horizon[B,1]` produce `[B,W]`.
The details dictionary contains `mean`, `dx`, `summed_terms`,
`mean_remainder_bound`, and `dx_remainder_bound`. `summed_terms` is a shared loop
length for a broadcast batch. Scalar audits record it separately for every case.
`count_tail(n,...)` and `count_pmf(n,...)` evaluate requested nonnegative integer
indices without renormalizing a truncated table.

For a content feature `x=softplus(-a)+0.05`, `n=E[N]`, `g=1-exp(-n)`, the chain rule is

\[
 \frac{\partial g}{\partial a}
 =e^{-n}\frac{\partial n}{\partial x}[-\operatorname{sigmoid}(-a)].
\]

This `g` is a deterministic rate mapping. It is generally **not** `Pr(N>=1)`;
that probability is `F(H,x)`. Renewal counts are not generally Poisson. The gate
also is not an exact expectation of a nonlinear content state with sampled
spikes, resets or content-dependent coefficients. The exact object supplied by
this module is the scalar expected count under the frozen local contract.

## 6. Prespecified formal audit

The executable protocol is generated by `renewal_audit.py --stage protocol`.
Formal execution requires a frozen source commit identity:

```sh
python3 renewal_audit.py --stage formal --out evidence/renewal/formal_RUN \
  --frozen-commit FORTY_HEXADECIMAL_CHARACTERS
```

The script records the supplied identity; it does not independently contact
GitHub to verify that identity. The parent release workflow performs that check.
Every run records local source SHA-256 hashes and Python/NumPy/SciPy versions.
Output directories must be new, preventing accidental overwriting of failures.

### Parameter domains and counts

- Main finite-support domain: `mu=[-1,-.25,0,.25,1]`, `sigma=[.2,1,2]`,
  `x=[0,.05,.4,1.5,3]`, `H=[.1,1,3]`, `reset=[.4,.8,1.4]`,
  `refractory=[.15,.5]`: **1350 cases**.
- Zero-refractory diagnostic: the same first five axes with `d=0`: **675 cases**,
  with saved truncation orders and both remainder bounds.
- Independent integration: `mu=[-1,0,1]`, `sigma=[.7,1.5]`, `x=[.2,.8]`,
  `d=[0,.15]`, fixed `H=1.5,reset=.8`: **24 cases**. Each evaluates two- and
  three-waiting-time convolutions (**48 comparisons**), a killed-density mass,
  and active plus refractory mass (**24 mass comparisons**).
- Exact waiting-time Monte Carlo: `mu=[-1,0,1]`, `sigma=[.7,1.5]`, `d=[0,.15]`,
  fixed `x=.4,H=1.5,reset=.8`: **12 cases**, **50000 trajectories each**.
  Generator is NumPy PCG64 with seed `2026103100+case_index`, where Cartesian
  axes are ordered as written. All sampled counts are retained in NPZ files.
- Domain checks: **19 rejected-input cases**, four explicit boundary cases,
  and ten extreme CDF cases. Their exact values are in the executable source.

Negative-drift waiting times use an inverse Gaussian with mean `x/abs(mu)` and
shape `x^2/sigma^2`. Positive-drift waiting times use that conditional law plus
an independent hit/escape draw with hit probability `exp(-2*mu*x/sigma^2)`.
At zero drift, `tau=(x/(sigma*Z))^2` for standard normal `Z`. Thus the count
simulation has no time-grid missed-crossing bias.

The independent mass audit integrates each firing-time density over the
refractory interval and integrates its convolution with post-reset survival
over the active interval. It includes initial survival and compares the total
with one. The firing-distance semigroup is separately checked by direct
quadrature convolutions. This is not a full independent multi-cell simulator.

### Fixed tolerances

- CDF vs SciPy inverse-Gaussian/Lévy reference: `2e-11+2e-9*abs(reference)`.
- Central finite-difference gradient: `3e-8+3e-7*abs(analytic_dx)`, with
  `h=min(1e-5*max(1,x),x/4)`.
- At `x=0`, second-order right difference with `h=1e-6`:
  `2e-6+5e-6*abs(analytic_dx)`.
- Convolution: `2e-8+2e-7*abs(reference)`; mass conservation: `1e-8`.
- PMF minimum: `-2e-13`; PMF mass and tail-adjusted mean identities: `2e-11`.
- Monte Carlo mean: six empirical standard errors plus `3/N`; each PMF bin:
  `6*sqrt(p*(1-p)/N)+3/N`. These are prespecified diagnostics, not a proof of
  population equivalence or a calibrated simultaneous confidence procedure.
- Quadrature: absolute tolerance `2e-11`, relative tolerance `2e-9`, limit 200.

All cases go to `cases.jsonl`, all failures additionally to `failures.jsonl`.
Development runs are labeled as development, use fixed subsamples of the
domains and 5000 Monte Carlo trajectories, and do not substitute for the formal
run. A failed formal run must be retained if corrected source is frozen again.
