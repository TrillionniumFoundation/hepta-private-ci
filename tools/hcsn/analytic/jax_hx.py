"""Pure JAX He--Xiong Eq.(12), Eq.(A7) and Eq.(9), controlled domain.

No custom JVP/VJP or surrogate gradients are used. The boundary-local
fourth-order Taylor evaluation is derived from the original equity ODE.
Use float64 for scientific validation. Enable x64 in the calling program.
Existing NumPy/mpmath implementations remain the wider-domain reference.
"""

import math
import numpy as np
import jax.numpy as jnp
from jax.scipy.special import ndtr, log_ndtr

if __package__:
    from .hx_model import HXModel
else:
    from hx_model import HXModel


NAMES = ("r", "delta", "sigma", "alpha", "tax", "liquidity", "maturity", "coupon", "principal")
LOWER = (.04, .01, .08, 0., 0., 1e-4, .01, .5, 20.)
UPPER = (.15, .2, .8, 1., .6, .1, 20., 10., 100.)
_GAUSS_NODES, _GAUSS_WEIGHTS = np.polynomial.legendre.leggauss(8)
_GAUSS_NODES, _GAUSS_WEIGHTS = (_GAUSS_NODES+1)/2, _GAUSS_WEIGHTS/2


def validate_parameters(parameters):
    """Check the numeric box and necessary local boundary admissibility."""
    values = np.asarray([getattr(parameters, k) for k in NAMES], dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values < LOWER) or np.any(values > UPPER):
        raise ValueError("Outside the controlled JAX domain; use the NumPy/mpmath reference")
    HXModel(parameters)
    return values


def domain_mask(theta):
    return jnp.all(jnp.isfinite(theta) & (theta >= jnp.asarray(LOWER, theta.dtype))
                   & (theta <= jnp.asarray(UPPER, theta.dtype)))


def parameters_from_raw(raw):
    """Map into the numeric box; boundary admissibility remains a separate check.

    Some combinations in this box fail the stopping inequality. The boundary
    and equity functions return NaN for those combinations, without clipping.
    """
    lo, hi = jnp.asarray(LOWER, raw.dtype), jnp.asarray(UPPER, raw.dtype)
    return lo+(hi-lo)*(.5+.5*jnp.tanh(raw/2))


def exp_cdf(exponent, argument):
    return jnp.exp(exponent+log_ndtr(argument))


def exp_phi(exponent, argument):
    return jnp.exp(exponent-.5*argument**2)/math.sqrt(2*math.pi)


def exp_cdf_interval(exponent, lo, hi):
    log_big = jnp.where(lo > 0, log_ndtr(-lo), log_ndtr(hi))
    log_small = jnp.where(lo > 0, log_ndtr(-hi), log_ndtr(lo))
    return jnp.exp(exponent+log_big)*(-jnp.expm1(log_small-log_big))


def constants(theta):
    r, delta, sigma, alpha, tax, liquidity, m, C, P = theta
    s2, R = sigma*sigma, r+liquidity
    a = (r-delta-s2/2)/s2
    z, zt = jnp.sqrt(a*a+2*r/s2), jnp.sqrt(a*a+2*R/s2)
    eta = jnp.where(a >= 0, 2*r/(s2*(z+a)), z-a)
    gamma = 2*r/(s2*eta)
    s, c, p = sigma*jnp.sqrt(m), C/m, P/m
    q, discount = p-c/R, jnp.exp(-R*m)
    cost = (1-tax)*C-jnp.expm1(-R*m)*q
    return s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost


def boundary_candidate(theta):
    """Original positive Eq.(12) candidate, before the stopping inequality."""
    r, delta, sigma, alpha, tax, liquidity, m, C, P = theta
    s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost = constants(theta)
    def B(y):
        denominator = z+y
        near = jnp.abs(denominator) < 1e-3*(1+z)
        at = -z+jnp.asarray(_GAUSS_NODES, theta.dtype)*denominator
        exponent = .5*(z-at)*(z+at)*s*s
        derivative = s*exp_phi(0., at*s)+at*s*s*exp_cdf(exponent, -z*s)
        integrated = jnp.sum(jnp.asarray(_GAUSS_WEIGHTS, theta.dtype)*derivative)
        direct = (ndtr(y*s)-exp_cdf(.5*(z-y)*(z+y)*s*s, -z*s))
        direct /= jnp.where(near, 1., denominator)
        return jnp.where(near, integrated, direct)
    bs = B(-zt)+B(zt)
    value = (cost/eta+q*discount*(B(-a)+B(a))+(c/R)*bs)
    value /= .5*s2*(gamma+1)+alpha/m*bs
    return jnp.where(domain_mask(theta) & (value > 0), value, jnp.nan)


def boundary(theta):
    """Admit only a candidate with resolvably nonnegative local equity."""
    value = boundary_candidate(theta)
    r, delta, sigma, alpha, tax, liquidity, m, C, P = theta
    flow = delta*value-(1-tax)*C+(alpha*value-P)/m
    scale = jnp.abs(delta*value)+jnp.abs((1-tax)*C)+(jnp.abs(alpha*value)+jnp.abs(P))/m
    tolerance = 64*jnp.finfo(theta.dtype).eps*jnp.maximum(1., scale)
    admissible = jnp.isfinite(flow) & (flow < -tolerance)
    return jnp.where(admissible, value, jnp.nan)


def first_hit_x(x, horizon, theta):
    """Eq.(9), continuation x>=0 and horizon>0; invalid input returns NaN."""
    s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost = constants(theta)
    st = theta[2]*jnp.sqrt(horizon)
    f = ndtr(-x/st-a*st)+exp_cdf(-2*a*x, -x/st+a*st)
    g = exp_cdf((-a+zt)*x, -x/st-zt*st)+exp_cdf((-a-zt)*x, -x/st+zt*st)
    valid = domain_mask(theta) & (x >= 0) & (horizon > 0)
    return jnp.where(valid, f, jnp.nan), jnp.where(valid, g, jnp.nan)


def _A(x, y, values):
    s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost = values
    def numerator(u):
        exponent = .5*(z*z-u*u)*s*s
        common = -exp_cdf_interval(exponent-gamma*x, z*s-x/s, z*s)
        common += exp_cdf(exponent+eta*x, -x/s-z*s)
        return (jnp.exp(-gamma*x)*ndtr(u*s)+common
                -exp_cdf(-(a+u)*x, -x/s+u*s)
                -exp_cdf(-(a-u)*x, -x/s-u*s))
    return numerator(y)/(z-y)+numerator(-y)/(z+y)


def equity_raw_x(x, theta):
    """Complete A7; no clipping, epsilon denominator or pseudo-derivative."""
    b, values = boundary(theta), constants(theta)
    s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost = values
    result = b*jnp.exp(x)-theta[1]*b/(z*s2)*jnp.exp(-gamma*x)/(gamma+1)
    result -= cost/(z*s2)*(1/eta-jnp.expm1(-gamma*x)/gamma)
    result += (discount*q*_A(x, a, values)
               -(theta[3]*b/theta[6]-c/R)*_A(x, zt, values))/(z*s2)
    return jnp.where(x >= 0, result, jnp.nan)


def equity_taylor_x(x, theta):
    b, values = boundary(theta), constants(theta)
    s2, R, a, z, zt, eta, gamma, s, c, p, q, discount, cost = values
    r, delta, sigma, alpha, tax, liquidity, m, C, P = theta
    f1 = -2*exp_phi(0., a*s)/s-2*a*ndtr(a*s)
    g1 = (-a+zt)*ndtr(-zt*s)+(-a-zt)*ndtr(zt*s)-2*exp_phi(0., zt*s)/s
    f2, g2 = -2*a*f1, 2*R/s2-2*a*g1
    recovery = alpha*b/m-c/R
    flow0 = delta*b-(1-tax)*C+alpha*b/m-p
    flow1, flow2 = delta*b-discount*q*f1+recovery*g1, delta*b-discount*q*f2+recovery*g2
    e2 = -2*flow0/s2
    e3 = -2*a*e2-2*flow1/s2
    e4 = -2*a*e3+2*r/s2*e2-2*flow2/s2
    return x*x*(e2/2+x*(e3/6+x*e4/24))


def equity_x(x, theta):
    """Stable continuation A7; only its boundary-local evaluation is Taylor."""
    s = theta[2]*jnp.sqrt(theta[6])
    threshold = jnp.minimum(1e-4, 1e-3*s)
    result = jnp.where(x < threshold, equity_taylor_x(x, theta), equity_raw_x(x, theta))
    return jnp.where(x >= 0, result, jnp.nan)


def equity_asset(V, theta):
    """Financial limited-liability extension E=0 at and below the boundary."""
    x = jnp.log(V/boundary(theta))
    continuation = equity_x(jnp.maximum(x, 0.), theta)
    valid = (V > 0) & domain_mask(theta) & jnp.isfinite(x)
    return jnp.where(valid, jnp.where(x > 0, continuation, 0.), jnp.nan)


def risk_asset_constant_extension(V, horizon, theta):
    """Explicitly NOT C1: default-region F=G=1 has a derivative jump."""
    x = jnp.log(V/boundary(theta))
    f, g = first_hit_x(jnp.maximum(x, 0.), horizon, theta)
    valid = (V > 0) & (horizon > 0) & domain_mask(theta) & jnp.isfinite(x)
    return (jnp.where(valid, jnp.where(x > 0, f, 1.), jnp.nan),
            jnp.where(valid, jnp.where(x > 0, g, 1.), jnp.nan))
