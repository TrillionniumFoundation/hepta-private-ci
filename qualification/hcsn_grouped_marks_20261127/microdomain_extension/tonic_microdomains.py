"""Infinite-horizon joint-reset rates and dispersion, with the independent Brownian clock."""
import math
import numpy as np
from scipy.integrate import quad
from scipy.special import erf,log_ndtr


def zero_drift_dimensionless_moment(copies,order):
    if type(copies) is not int or type(order) is not int or min(copies,order)<1:
        raise ValueError('copy count and moment order must be positive integers')
    if copies<=2*order:return math.inf
    def order_density(y):
        log_probability=math.log(erf(y/math.sqrt(2)))
        return math.exp(math.log(copies)+.5*math.log(2/math.pi)+(copies-1)*log_probability-y*y/2-2*order*math.log(y))
    return quad(order_density,0.,1.,epsabs=2e-13,epsrel=2e-13)[0]+quad(order_density,1.,np.inf,epsabs=2e-13,epsrel=2e-13)[0]


def one_path_log_survival(t,d,mu,sigma):
    s=sigma*math.sqrt(t)
    # Written as a difference of the directly integrated absorbing heat kernel tails.
    a=log_ndtr((d+mu*t)/s)
    b=(-2*mu*d/sigma**2)+log_ndtr((mu*t-d)/s)
    if not b<a:
        raise FloatingPointError('unresolved survival-tail subtraction')
    return a+math.log(-math.expm1(b-a))


def stationary_rate(copies,reset,drift,volatility,refractory):
    if type(copies) is not int or copies<1 or min(reset,volatility)<=0 or refractory<0 or not all(
          math.isfinite(v) for v in (reset,drift,volatility,refractory)):
        raise ValueError('invalid count or physical coefficients')
    if drift>0:return 0.
    if drift==0:
        mean=(reset/volatility)**2*zero_drift_dimensionless_moment(copies,1)
    elif copies==1:
        mean=reset/(-drift)
    else:
        mean=quad(lambda t: math.exp(copies*one_path_log_survival(t,reset,drift,volatility)),
                  0.,np.inf,epsabs=1e-10,epsrel=1e-10,limit=250)[0]
    return 1/(refractory+mean)


def infinite_count_when_outward(copies,initial,reset,drift,volatility):
    if type(copies) is not int or copies<1 or min(reset,drift,volatility)<=0 or not all(
          math.isfinite(v) for v in (initial,reset,drift,volatility)):
        raise ValueError('use a positive outward drift, reset distance and volatility')
    def escape_distance(d):
        return (-math.expm1(-2*drift*max(0.,d)/volatility**2))**copies
    escape=escape_distance(reset)
    return {'reset_group_escape':escape,'expected_total_from_initial':(1-escape_distance(initial))/escape}
