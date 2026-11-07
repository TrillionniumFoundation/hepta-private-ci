# One killed generator, single-cycle E and regenerative U

## Scope and identity

This package is a **new scalar FP64 research reference**. It imports the existing
HCSN first-passage and bin-integrated killed kernels, but does not modify the
frozen `qualification/hcsn` source, its experiment identity, trained weights,
170-run comparison, deployment inventory or training budget.

The reference covers constant drift/volatility, a fixed absorbing boundary,
a fixed strictly positive reset distance and a physical refractory duration.
Existing architecture A uses a chosen recurrent vector field; existing B adds
leak, input and recovery to its drift and resets at step ends. Their original
behavior is unchanged. The identities below do **not** establish that those
architectures already have the same generator or task value. State-dependent
coefficients, controlled boundaries and learned reset mechanisms require a new
backward/forward problem and a corresponding implementation.

## A single process and its killed successor

For distance x>0, define

    dX_t = mu dt + sigma dW_t,  sigma>0,
    tau_x = inf{t>=0: X_t<=0},
    L = mu partial_x + (sigma^2/2) partial_xx.

`KilledDiffusion(mu, sigma, discount=q)` supplies risk F(x,T), survival S(x,T),
discounted first hit G(x,T;q), regular density f_x(t), and the killed successor
kernel. All use the same mu and sigma; q discounts elapsed physical time.
For y>0 and t>0, the kernel is

    K_t(x,y) = exp(-(y-x-mu*t)^2/(2*sigma^2*t))
               * (1-exp(-2*x*y/(sigma^2*t))) / (sigma*sqrt(2*pi*t)).

It satisfies F(x,t)+integral K_t(x,y)dy=1 and S=integral K. The implementation
returns unconditional survivor mass in each half-open bin, lower-boundary hit
mass, and a separate upper tail. It never renormalizes surviving bins. When the
last edge is infinity, the preceding finite-edge tail becomes the final bin.
The zero-time successor is a Dirac mass at x, including deterministic bin-edge
ownership. At x=0, tau_0=0: F=G=1, S=0 even at T=0. The regular density is zero
there and does not represent the boundary atom.

For beta>=0, the first-hit Laplace transform is

    L_beta(x) = exp(-lambda(beta)*x),
    lambda(beta) = (sqrt(mu^2+2*beta*sigma^2)+mu)/sigma^2.

The negative-drift branch is rationalized to avoid cancellation. At beta=0,
L_0=1 for nonpositive drift, whereas positive drift permits permanent survival.
The characteristic identity `(sigma^2/2)*lambda^2-mu*lambda=beta` ties this
transform to precisely the same generator.

## Rewards, reset, remaining time and finite-horizon values

`ResetRule(margin=a, refractory=d, hit_reward=k)` pays k at the hit, waits d>=0,
and restarts at a>0. Refractory states receive zero running/terminal reward.
Active states earn constant running reward c and terminal reward h. Both may
be signed. There is no hidden reward at release. A release exactly at the
horizon is active and may earn h. A strictly positive a excludes an immediate
infinite sequence of boundary resets.

Single-cycle E ends at the first hit. Regenerative U permits repeated hits:

    E(x,T) = c integral_0^T exp(-q*t) S(x,t)dt
             + k G(x,T;q) + h exp(-q*T) S(x,T),

    U(x,T) = E(x,T)
             + integral_[0,T-d] exp(-q*(s+d)) U(a,T-s-d) dF_x(s).

The continuation integral is absent when T<d. Its Stieltjes measure includes
any x=0 atom. The deadline is never restarted with a full observation interval;
only T-s-d remains after a hit at s and refractory wait d. At the boundary,

    E(0,T)=k,
    U(0,T)=k + 1{T>=d} exp(-q*d) U(a,T-d).

For x>0, E(x,0)=U(x,0)=h. When d=0 and x=T=0, E=k while U=k+h: the immediate
initial hit and immediate release precede terminal evaluation. This explicit
corner convention prevents a lost boundary reward or a double counted reset.
In the interior, both values obey

    partial_T V = L V - q V + c.

Their boundary conditions differ. Equality of interior generators does not
make the single-cycle value equal to the regenerative value.

### Executable renewal series

Independent Brownian increments and the additive first-hit Laplace exponent
give the nth hit time, in distribution,

    H_n = tau_[x+(n-1)*a] + (n-1)*d.

This remains valid for defective first-hit laws with positive drift: an
infinite first-hit time prevents all later hits. Consequently,

    N_q(x,T) = sum_(n>=1) exp(-q*(n-1)*d)
                G(x+(n-1)*a,T-(n-1)*d;q),

where terms with negative remaining time vanish. For d>0, active probability is

    A(x,T) = S(x,T) + sum_(n>=1) [
      F(x+(n-1)*a,T-n*d) - F(x+n*a,T-n*d)].

For d=0, A=1, including the immediate boundary-release convention. The function
`finite_horizon_value` evaluates

    U = c integral_0^T exp(-q*t) A(x,t)dt
        + k N_q(x,T) + h exp(-q*T) A(x,T).

This includes multiple hits within the same observation interval. Refractory
occupancy is 1-A; the implementation does not round d to a time grid. Active
occupation is integrated adaptively, with panels at physical release times.
The returned `active_time` is a **discounted** occupation integral, not a raw
wall-clock duration when q>0.

### Declared numerical remainder

For beta=1/T, let r=exp(-beta*d-lambda(beta)*a). After n retained hits,

    sum_(j>n) P(H_j<=T)
        <= exp(beta*T-lambda(beta)*x) r^n/(1-r).

This follows by applying Markov's inequality to exp(-beta*H_j) and summing a
geometric series. Because q>=0, it also bounds omitted discounted hit count.
The returned `value_tail_bound` multiplies this remainder by
`abs(k)+T*abs(c)+abs(h)`; it is conservative for zero refractory. Positive d
also provides an exact finite cutoff once n*d>=T. Unresolved tail tolerance
raises an exception instead of silently truncating at `max_terms`.

This is a renewal truncation bound in exact arithmetic, not an FP64 enclosure.
`quadrature_error` is the sum of adaptive occupation error estimates; it is not
a certified probability/value error bound and is not already scaled by abs(c).
Reported quadrature nonconvergence raises explicitly. Cancellation in inherited
CDF kernels, underflow, extreme scales and missed localized quadrature features
still require independent numerical audits. Passing the tests below is not a
claim of global numerical validity or exact analytic gradients.

## Existing HX cashflow: stationary E versus U

The existing HX single-cycle function solves `(r-L)E=g_HX`, killed at zero,
at the boundary documented in [the original derivation](../hcsn/MATH.md).
`stationary_hx_value(par, reset, x)` derives mu, sigma and discount r from the
same `HXParams` object; callers cannot supply a second mismatched risk process.
The debt discount r+ell remains part of g_HX; the outer equity time discount is r.
With L_r the same first-hit transform, define

    D = 1 - exp(-r*d) L_r(a),
    U(a) = [E(a)+L_r(a)*k] / D,
    U(x) = E(x)+L_r(x)*[k+exp(-r*d)*U(a)].

The implementation uses `-expm1(log_cycle)` for D and requires a resolved
contraction. It reports both E and U, the reset values, cycle factor and renewal
multiplier. It also preserves the existing local economic admissibility check.
Since `(r-L)L_r=0`, the new U has the same interior cashflow g_HX and a different
boundary value. The inherited smooth-pasting boundary optimizes the original
killed problem under its stated assumptions; it is **not claimed optimal** for
the new reset problem. No financial payoff is declared a measured neural task
reward by this construction.

## Validation and next integration gate

Run `python -m unittest qualification.hcsn_regenerative.tests.test_process -v`.
The tests independently integrate the first-hit density, check mass including
upper tails and boundary atoms, compare a two-hit window against time-domain
convolution, exercise an off-grid refractory and exact-deadline release, test
multiple hits, signed rewards and remainder receipts, approach a low-noise
limit, and check the stationary HX fixed point and interior differential
operator with finite differences. They do not merely compare two wrappers
around the same value function.

Before using this as a trainable cell, the common generator contract must be
extended to the actual controlled drift/boundary; its survivor evolution,
reset continuation, reward and derivatives must then pass independent time,
space and precision refinement. Original campaign identity, missing runs,
OOM/recompute cost and B audit remain separate mandatory gates. No training,
quality/latency/energy improvement or broad deployment claim follows here.
