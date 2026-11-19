# Fixed analytic release kernel and genuine zero-refractory candidate

This is a separate FP64 **construction** candidate. It does not change the
frozen V4 tensor source or extend V4's strictly positive-refractory domain.
Parameters and grids are fixed; parameter and boundary autodiff are not
qualified by this module. Its linear state tables can be consumed by a
separately tested tensor recurrence.

## One forward process

While active, `dX = mu dt + sigma dW`, with absorption at zero. On every hit,
restart immediately at the fixed positive distance `a`. Thus refractory time
is exactly zero, rather than a small tick or a limit silently substituted into
the positive-delay implementation. Brownian hitting times for consecutive
distances concatenate. The n-th hit has first-hit law `F(x+(n-1)*a,T)`.

The diffusion bounds are `abs(mu)<=2`, `.05<=sigma<=4`, `.01<=q<=4`,
`0<=T<=8`, finite `x>=0`, and fixed `0<a<=8`. Accepted configurations must
also resolve all explicit numerical guards and the fixed maximum term count.
These parameter bounds do not imply a global numerical certificate.

## Release convolution identity

Write `K(x;t,y)` for the killed transition density and `f_L` for the first-hit
density at distance L. The convolution following a release is

`C(L,a;t,y) = integral_0^t f_L(s) K(a;t-s,y) ds`.

For `L>=0`, including the first-hit atom at `L=0`, the exact identity is

* `C = K(a+L;t,y)` for `0<y<a`;
* `C = exp(-2*mu*L/sigma^2) K(a;t,y+L)` for `y>=a`.

The two expressions agree at a. A destination interval is split at a and
integrated using normal-CDF differences. Large exponential weights stay in
log space. If a difference is poorly resolved, an independently positive
killed-density integral is evaluated with a reported quadrature diagnostic.
Unresolved mass rejects; there is no clipping or row normalization.

One derivation uses the killed resolvent. With
`kappa=sqrt(mu^2+2*s*sigma^2)/sigma^2`, its Laplace transform is

`exp(mu*(y-a)/sigma^2) [exp(-kappa*abs(y-a))-exp(-kappa*(y+a))] / (sigma^2*kappa)`.

Multiplying by the first-hit transform `exp(-L*(mu/sigma^2+kappa))`
and inverting each Gaussian term gives the two cases above. The numerical
checks separately integrate the original positive time convolution, including
intervals crossing a and the infinite upper tail.

## Infinite renewal series and explicit omissions

The active law is `K(x;T,.) + sum_(n>=1) C(x+(n-1)*a,a;T,.)`.
Each release has mass `F(L,T)-F(L+a,T)`. After N releases the omitted active
mass is therefore exactly `F(x+N*a,T)` in the continuum formula. The returned
finite state remains a subprobability; the omitted mass is never reassigned.

The expected count of omitted hits is bounded using, for positive s,

`sum_(j>=0) F(D+j*a,T) <= exp(s*T-eta*D)/(1-exp(-eta*a))`,

where `eta=(mu+sqrt(mu^2+2*s*sigma^2))/sigma^2` and `D=x+N*a`.
The implementation chooses a fixed-data positive Chernoff parameter, records
the bound and requires it to meet the requested tolerance. This also bounds
omitted discounted hit rewards. The bound is evaluated in FP64, not outward
rounded interval arithmetic. Subnormal underflow is retained through the log
state-tail value; the count bound is floored at the smallest positive FP64
number rather than reported as an exact zero.

The value uses the same forward generator and horizon:

`U = c*(1-exp(-q*T))/q + h*exp(-q*T) + k*sum_(n>=1) G(x+(n-1)*a,T)`.

The active occupation is the entire physical horizon because zero-duration
refractory intervals have zero measure. The only truncated value term is the
hit sum; the reported absolute bound is `abs(k)` times the count-tail bound.
Value calls reject a forward receipt with a different generator or horizon.
At `x=0,T=0`, the initial hit and active reset atom are both handled explicitly.

## Bounded verification and usage

Run from the repository root:

```sh
python -m qualification.hcsn_regenerative.run_fixed_renewal_audit --output result.json
```

The independent checks cover 36 positive time-convolution cases, the initial
reset atom, spatial aggregation, a strong-drift case whose naive weight
overflows, explicit unresolved term counts, and small/underflowed tails.
A conservative upwind finite-volume PDE independently redirects boundary flux
to the reset target and tracks cumulative hits. Spatial refinement checks its
CDF and hit-count approach to the renewal law. That PDE's remote boundary is
reflecting and its check is restricted to the reported negligible-tail case.

V1 construction checks passed but review found that exponentiating a very
small positive tail printed zero. V2 retains the log state-tail and a positive
count bound. This is a reporting/underflow correction; it does not qualify
relative accuracy of arbitrary tails. Neither version is training evidence,
a parameter-gradient certificate, or an external-task benefit result.
