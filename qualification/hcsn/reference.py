"""FP64 He--Xiong reference and an independent killed-resolvent equity oracle.

The bond, hitting kernels and free boundary are closed form. ``hx_equity_closed``
rewrites published Eq. A7 through a normal-tail divided difference. ``hx_equity``
uses independent one-dimensional quadrature of the same stationary equation to
avoid cancellation at x=0 and q=r, and to validate tensor implementations.

The first-passage density is the regular density, not a resetting-neuron rate.
At x=0 there is an atom at t=0, represented by F=G=1, not by f.

These scalar functions are also mathematical oracles for formally admissible
ODE coefficients. Positive primitive parameters do not ensure economic equity
admissibility. Use ``parameter_feasibility`` before interpreting the resulting
smooth-pasting solution as a limited-liability equity value.
"""

from dataclasses import dataclass
from functools import lru_cache
import math

import numpy as np
from scipy.integrate import quad
from scipy.special import log_ndtr, ndtr, pbdv

_LOG_2PI = math.log(2.0 * math.pi)


def _finite(name, value):
    values = np.asarray(value, dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} must be finite")
    return values


def _map_scalar(function, *values):
    arrays = np.broadcast_arrays(*(np.asarray(v, dtype=np.float64) for v in values))
    if arrays[0].ndim == 0:
        return float(function(*(float(v) for v in arrays)))
    return np.vectorize(function, otypes=[float])(*arrays)


def _validate_hit(x, time, mu, sigma):
    if np.any(_finite("x", x) < 0) or np.any(_finite("time", time) < 0):
        raise ValueError("x and time must be nonnegative")
    _finite("mu", mu)
    if np.any(_finite("sigma", sigma) <= 0):
        raise ValueError("sigma must be positive")


def first_passage_cdf(x, horizon, mu, sigma):
    """P(tau<=T), including the atom at zero for x=0."""
    _validate_hit(x, horizon, mu, sigma)

    def one(xx, tt, drift, vol):
        if xx == 0:
            return 1.0
        if tt == 0:
            return 0.0
        scale = vol * math.sqrt(tt)
        l1 = log_ndtr((-xx - drift * tt) / scale)
        l2 = -2.0 * drift * xx / vol**2 + log_ndtr((-xx + drift * tt) / scale)
        return math.exp(np.logaddexp(l1, l2))

    return _map_scalar(one, x, horizon, mu, sigma)


def first_passage_survival(x, horizon, mu, sigma):
    """P(tau>T), using a log difference rather than subtracting rounded F."""
    _validate_hit(x, horizon, mu, sigma)

    def one(xx, tt, drift, vol):
        if xx == 0:
            return 0.0
        if tt == 0:
            return 1.0
        scale = vol * math.sqrt(tt)
        la = log_ndtr((xx + drift * tt) / scale)
        lb = -2.0 * drift * xx / vol**2 + log_ndtr((-xx + drift * tt) / scale)
        difference = lb - la
        if difference >= 0:
            # Very small x can round the two log probabilities to the same value.
            # The integral of the positive spatial density avoids a fake clamp.
            return quad(lambda y: math.exp(-0.5*((y-xx-drift*tt)/scale)**2-_LOG_2PI/2)
                        / scale * (-math.expm1(-2*xx*y/scale**2)),
                        0, np.inf, epsabs=1e-14)[0]
        return math.exp(la) * (-math.expm1(difference))

    return _map_scalar(one, x, horizon, mu, sigma)


def discounted_first_passage(x, horizon, mu, sigma, discount):
    """E[exp(-q*tau) 1(tau<=T)], with q>=0 and the x=0 atom."""
    _validate_hit(x, horizon, mu, sigma)
    if np.any(_finite("discount", discount) < 0):
        raise ValueError("discount must be nonnegative")

    def one(xx, tt, drift, vol, rate):
        if xx == 0:
            return 1.0
        if tt == 0:
            return 0.0
        chi = math.sqrt(drift**2 + 2*rate*vol**2)
        scale = vol * math.sqrt(tt)
        l1 = (chi-drift)*xx/vol**2 + log_ndtr((-xx-chi*tt)/scale)
        l2 = -(chi+drift)*xx/vol**2 + log_ndtr((-xx+chi*tt)/scale)
        return math.exp(np.logaddexp(l1, l2))

    return _map_scalar(one, x, horizon, mu, sigma, discount)


def first_passage_density(time, x, mu, sigma):
    """Regular dF/dt; returns zero at t=0 or x=0, excluding the boundary atom."""
    _validate_hit(x, time, mu, sigma)

    def one(tt, xx, drift, vol):
        if tt == 0 or xx == 0:
            return 0.0
        return math.exp(math.log(xx)-math.log(vol)-0.5*_LOG_2PI-1.5*math.log(tt)
                        -(xx+drift*tt)**2/(2*vol**2*tt))

    return _map_scalar(one, time, x, mu, sigma)


def discounted_boundary_claim(x, mu, sigma, discount):
    """Infinite-horizon discounted hitting probability, including q=0."""
    _validate_hit(x, 0.0, mu, sigma)
    if np.any(_finite("discount", discount) < 0):
        raise ValueError("discount must be nonnegative")

    def one(xx, drift, vol, rate):
        chi = math.sqrt(drift**2+2*rate*vol**2)
        if drift < 0:
            root = 2*rate/(chi-drift)
        else:
            root = (chi+drift)/vol**2
        return math.exp(-root*xx)

    return _map_scalar(one, x, mu, sigma, discount)


@dataclass(frozen=True)
class HXParams:
    r: float = 0.05
    delta: float = 0.02
    sigma: float = 0.20
    coupon: float = 5.0
    principal: float = 100.0
    maturity: float = 1.0
    tax: float = 0.25
    recovery: float = 0.60
    ell: float = 0.01

    def __post_init__(self):
        for name, value in self.__dict__.items():
            if not np.isscalar(value) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite scalar")
        if min(self.r, self.delta, self.sigma, self.principal, self.maturity) <= 0:
            raise ValueError("r, delta, sigma, principal and maturity must be positive")
        if self.coupon < 0 or self.ell < 0 or not 0 <= self.tax < 1 or not 0 <= self.recovery <= 1:
            raise ValueError("invalid coupon, ell, tax or recovery")

    @property
    def q(self):
        return self.r + self.ell

    @property
    def mu(self):
        return self.r - self.delta - self.sigma**2/2

    @property
    def c(self):
        return self.coupon/self.maturity

    @property
    def p(self):
        return self.principal/self.maturity

    def roots(self):
        a = self.mu/self.sigma**2
        z = math.hypot(a, math.sqrt(2*self.r)/self.sigma)
        zq = math.hypot(a, math.sqrt(2*self.q)/self.sigma)
        eta = 2*self.r/(self.sigma**2*(z+a)) if a >= 0 else z-a
        gamma = 2*self.r/(self.sigma**2*(z-a)) if a < 0 else z+a
        return a, z, zq, eta, gamma


def _positive_normal_moment(order, w):
    """E[(w+Z)_+**order], avoiding cancelling recurrence in negative tails."""
    if w < -1:
        return (math.factorial(order)/math.sqrt(2*math.pi)
                * math.exp(-w*w/4)*pbdv(-order-1, -w)[0])
    j0 = ndtr(w)
    if order == 0:
        return float(j0)
    j1 = w*j0 + math.exp(-w*w/2)/math.sqrt(2*math.pi)
    for k in range(2, order+1):
        j0, j1 = j1, w*j1 + (k-1)*j0
    return float(j1)


def normal_tail_integral(lam, u, s):
    """H=integral_0^inf exp(-lam*y) Phi(u*s-y/s) dy, valid for real lam.

    A six-term Taylor divided difference is used near lam=0, including its
    exact limit; no epsilon is added to the denominator.
    """
    if not all(math.isfinite(v) for v in (lam, u, s)) or s <= 0:
        raise ValueError("H arguments must be finite, with s>0")
    w = u*s
    if abs(lam)*s*(1+abs(w)) < 1e-3:
        return math.fsum((-lam)**n/math.factorial(n)*s**(n+1)
                         *_positive_normal_moment(n+1, w)/(n+1) for n in range(6))
    la = float(log_ndtr(w))
    lb = (0.5*lam*lam-lam*u)*s*s + float(log_ndtr((u-lam)*s))
    if lam > 0:
        return math.exp(la) * (-math.expm1(lb-la))/lam
    return math.exp(lb) * (-math.expm1(la-lb))/(-lam)


@lru_cache(maxsize=256)
def _components(par):
    a, z, zq, eta, gamma = par.roots()
    s = par.sigma*math.sqrt(par.maturity)
    i_f = normal_tail_integral(z+a, a, s)+normal_tail_integral(z-a, -a, s)
    # This rationalized difference remains exactly zero at ell=0.
    difference = -2*par.ell/(par.sigma**2*(z+zq))
    i_g = normal_tail_integral(z+zq, zq, s)+normal_tail_integral(difference, -zq, s)
    fixed = (1-par.tax)*par.coupon-math.expm1(-par.q*par.maturity)*(par.p-par.c/par.q)
    coefficient = math.exp(-par.q*par.maturity)*(par.p-par.c/par.q)
    return a, z, zq, eta, gamma, s, i_f, i_g, fixed, coefficient


def hx_boundary(par):
    """Eq.12's formal boundary; inspect parameter_feasibility for economics."""
    _, _, _, eta, _, _, i_f, i_g, fixed, coefficient = _components(par)
    numerator = fixed/eta+coefficient*i_f+par.c/par.q*i_g
    denominator = par.r/eta+par.sigma**2/2+par.recovery/par.maturity*i_g
    boundary = numerator/denominator
    if not math.isfinite(boundary) or boundary <= 0:
        raise ValueError("parameters do not produce a finite positive default boundary")
    return boundary


def parameter_feasibility(par):
    """Separate an algebraic smooth-pasting root from economic admissibility.

    At a smooth-pasting boundary, E_xx(0+)=-2*g(0)/sigma**2. Thus g(0)<=0
    is necessary for nonnegative continuation equity. A stronger, sufficient
    monotonic-cashflow condition is recovery*b/m <= min(p,c/q): then
    d-R=(p-R)*exp(-q*m)*S+(c-q*R)*integral(exp(-q*t)*S(t),dt)
    increases with the initial margin, and the running cashflow is increasing.
    The raw recovery formula in published Eq.6 is uncapped; recovery>face is
    reported separately, rather than represented as a theorem of the paper.
    Passing only the local condition is not a global admissibility proof.
    """
    boundary = hx_boundary(par)
    recovery_value = par.recovery*boundary/par.maturity
    g0 = par.delta*boundary-(1-par.tax)*par.coupon+recovery_value-par.p
    scale = max(1.0,abs(par.delta*boundary),abs((1-par.tax)*par.coupon),
                abs(recovery_value),abs(par.p),abs(par.c/par.q))
    tolerance = 64*np.finfo(np.float64).eps*scale
    local = bool(g0 <= tolerance)
    monotone = local and recovery_value <= min(par.p,par.c/par.q)+tolerance
    excess_recovery = bool(recovery_value > par.p+tolerance)
    warnings = []
    if not local:
        warnings.append("Positive boundary running cashflow forces negative equity immediately above the root.")
    elif not monotone:
        warnings.append("The local necessary condition passes; global nonnegativity and optimal stopping are not certified.")
    if excess_recovery:
        warnings.append("The uncapped recovery alpha*b exceeds aggregate face value P.")
    return {"status":"inadmissible_local" if not local else
            "sufficient_monotone_subdomain" if monotone else "necessary_screen_only",
            "boundary":boundary,"boundary_running_cashflow":g0,
            "equity_boundary_second_derivative":-2*g0/par.sigma**2,
            "local_admissible":local,"sufficient_monotone_subdomain":bool(monotone),
            "uncapped_recovery_exceeds_face":excess_recovery,
            "recovery_to_face_ratio":par.recovery*boundary/par.principal,
            "floating_point_tolerance":tolerance,"warnings":warnings}


def hx_debt(x, horizon, par, boundary=None):
    """Eq.8 per unit of the stationary maturity ladder (not total debt)."""
    b = hx_boundary(par) if boundary is None else float(boundary)
    if not math.isfinite(b) or b <= 0:
        raise ValueError("boundary must be finite and positive")
    survival = first_passage_survival(x, horizon, par.mu, par.sigma)
    g = discounted_first_passage(x, horizon, par.mu, par.sigma, par.q)
    value = par.c/par.q*(1-g)+np.exp(-par.q*np.asarray(horizon))*(par.p-par.c/par.q)*survival
    value += par.recovery*b/par.maturity*g
    return float(value) if np.ndim(value) == 0 else value


def hx_equity_closed(x, par, boundary=None):
    """Closed resolvent equivalent of A7; diagnostic at regular parameters.

    For near-boundary or extreme-maturity validation use hx_equity, whose
    quadrature does not subtract individually large H terms.
    """
    _validate_hit(x, 0.0, par.mu, par.sigma)
    b = hx_boundary(par) if boundary is None else float(boundary)
    a, z, zq, _, gamma, s, _, _, fixed, coefficient = _components(par)

    def one(xx):
        if xx == 0:
            return 0.0

        def resolvent(u):
            shifted = u-xx/s**2
            return (math.exp(-gamma*xx)*(normal_tail_integral(u-z,u,s)-normal_tail_integral(z+u,u,s))
                    +math.exp(-(a+u)*xx)*(normal_tail_integral(z+u,shifted,s)-normal_tail_integral(u-z,shifted,s))
                    )/(par.sigma**2*z)

        rf = resolvent(a)+resolvent(-a)
        rg = resolvent(zq)+resolvent(-zq)
        return (b*(math.expm1(xx)-math.expm1(-gamma*xx))
                + fixed*math.expm1(-gamma*xx)/par.r - coefficient*rf
                +(par.recovery*b/par.maturity-par.c/par.q)*rg)

    return _map_scalar(one, x)


def hx_equity(x, par, boundary=None):
    """FP64 equity oracle from the stationary killed-resolvent equation.

    Uses positive-scale quadrature and a local initial-value representation at
    the optimal boundary. This is a numerical oracle, not a tensor fast path.
    """
    _validate_hit(x, 0.0, par.mu, par.sigma)
    b = hx_boundary(par) if boundary is None else float(boundary)
    if not math.isfinite(b) or b <= 0:
        raise ValueError("boundary must be finite and positive")
    _, z, _, eta, gamma, _, i_f, i_g, fixed, coefficient = _components(par)
    recovery_coefficient = par.recovery*b/par.maturity-par.c/par.q

    def bounded_running(y):
        return (-fixed-coefficient*first_passage_cdf(y,par.maturity,par.mu,par.sigma)
                +recovery_coefficient*discounted_first_passage(y,par.maturity,par.mu,par.sigma,par.q))

    def one(xx):
        if xx == 0:
            return 0.0
        if xx <= 0.25:
            slope = 0.0 if boundary is None else 2/par.sigma**2*(
                b*(par.r/eta+par.sigma**2/2)-fixed/eta-coefficient*i_f+recovery_coefficient*i_g)
            kernel = lambda distance: math.exp(eta*distance)*(-math.expm1(-2*z*distance))
            integral = quad(lambda y: kernel(xx-y)*(par.delta*b*math.exp(y)+bounded_running(y)),
                            0, xx, epsabs=2e-12, epsrel=2e-12)[0]
            return slope*kernel(xx)/(2*z)-integral/(par.sigma**2*z)
        left = quad(lambda y: math.exp(-gamma*(xx-y))*(-math.expm1(-2*z*y))*bounded_running(y),
                    0, xx, epsabs=2e-11, epsrel=2e-12)[0]
        right = quad(lambda distance: math.exp(-eta*distance)*bounded_running(xx+distance),
                     0, np.inf, epsabs=2e-11, epsrel=2e-12)[0]
        return b*(math.expm1(xx)-math.expm1(-gamma*xx))+(left-math.expm1(-2*z*xx)*right)/(par.sigma**2*z)

    return _map_scalar(one, x)


def simple_equity_ratio(x, gamma):
    """E/V for a separately defined constant-carry model with no rollover."""
    if np.any(_finite("x", x) < 0) or gamma <= 0:
        raise ValueError("x>=0 and gamma>0 required")
    return -(1+1/gamma)*np.expm1(-np.asarray(x))+np.expm1(-(gamma+1)*np.asarray(x))/gamma


def evaluate(V, params, T):
    """Map (V,theta,T) to b,E,F,G,f; requires surviving V>=b.

    E is a monetary value, F/G dimensionless, and f an inverse-time density.
    The extra first_passage_atom reports the omitted x=0 delta atom explicitly.
    """
    boundary = hx_boundary(params)
    values = _finite("V", V)
    if np.any(values < boundary):
        raise ValueError("V must be at or above the stationary boundary")
    x = np.log1p((values-boundary)/boundary)
    return {"b":boundary,"E":hx_equity(x,params),
            "F":first_passage_cdf(x,T,params.mu,params.sigma),
            "G":discounted_first_passage(x,T,params.mu,params.sigma,params.q),
            "f":first_passage_density(T,x,params.mu,params.sigma),
            "first_passage_atom":np.asarray(x == 0,dtype=float).tolist()}
