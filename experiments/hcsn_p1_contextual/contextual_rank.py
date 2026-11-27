"""Research-only P1 follow-up to #4527: recover rank without inventing information.

At fixed GBM parameters, the old (Call/K, Put/K, log(V/b)) observes only
V/K, rank <=1 in (log(V/K), log K, log T). Explicit log K and first-hit
Q(T) recover local rank 3, but Q is invertible in T on non-saturated
regions. It is NOT a new independent stochastic risk state or causal gain.
DENY_ALL / NO_GO. This is NOT coupled He--Xiong financial equity/debt.
"""
from dataclasses import dataclass
import math
from scipy.optimize import brentq
from scipy.special import log_ndtr, logsumexp

class Refuse(ValueError):
    pass

@dataclass(frozen=True)
class RankReceipt:
    probability: float
    log_time_derivative: float
    mathematical_rank_three: bool
    f64_conditioning_accepted: bool
    independent_risk_information: bool = False
    p1_causal_quality_gain: bool = False
    all_scientific_blockers_closed: bool = False
    production_activation: bool = False


def setup(r=.05,payout=.03,sigma=.2):
    if (not all(type(v) in (int,float) and math.isfinite(v) for v in (r,payout,sigma))
            or not (.001<=r<=.30 and .001<=payout<=.20 and .01<=sigma<=1.)):
        raise Refuse('unsupported bounded GBM parameters')
    drift=r-payout-.5*sigma*sigma
    disc=math.hypot(drift,math.sqrt(2*r*sigma*sigma))
    beta=2*r/(disc-drift) if drift<0 else (disc+drift)/(sigma*sigma)
    return drift,beta,beta/(1+beta)


def normalized_features(log_ratio, *,r=.05,payout=.03,sigma=.2):
    _,beta,ratio=setup(r,payout,sigma)
    if type(log_ratio) not in (int,float) or not math.isfinite(log_ratio) or abs(log_ratio)>10:
        raise Refuse('invalid log(V/K)')
    m=log_ratio-math.log(ratio)
    if m<=0:
        return (0.,1-math.exp(log_ratio),m)
    c=ratio*(math.expm1(m)+math.expm1(-beta*m)/beta)
    return (c,c-math.expm1(log_ratio),m)


def hit(log_ratio,T,*,r=.05,payout=.03,sigma=.2):
    nu,_,ratio=setup(r,payout,sigma)
    if (type(T) not in (int,float) or not math.isfinite(T)
            or not 0<T<=100):
        raise Refuse('invalid physical horizon')
    m=normalized_features(log_ratio,r=r,payout=payout,sigma=sigma)[2]
    if m<=0:
        return (1.,0.)
    root=sigma*math.sqrt(T)
    p=math.exp(float(logsumexp((log_ndtr((-m-nu*T)/root),
                                -2*nu*m/(sigma*sigma)+log_ndtr((-m+nu*T)/root)))))
    if not 0<=p<=1+1e-12:
        raise Refuse('invalid first-hit probability')
    logf=(math.log(m)-math.log(sigma)-math.log(2*math.pi)/2
          -1.5*math.log(T)-(m+nu*T)**2/(2*sigma*sigma*T))
    density=math.exp(logf) if logf>-745 else 0.
    return min(p,1.),density


def rank_receipt(log_ratio,log_k,log_T,*,r=.05,payout=.03,sigma=.2):
    if (not all(type(v) in (int,float) and math.isfinite(v)
                for v in (log_ratio,log_k,log_T))
            or abs(log_k)>10 or not -15<=log_T<=math.log(100)):
        raise Refuse('invalid independent coordinate')
    m=normalized_features(log_ratio,r=r,payout=payout,sigma=sigma)[2]
    T=min(100.,math.exp(log_T))  # clamp only exp(log(100)) representational overshoot
    p,f=hit(log_ratio,T,r=r,payout=payout,sigma=sigma)
    det=T*f   # triangular Jacobian of (m, logK, Q) vs (log(V/K),logK,logT)
    return RankReceipt(p,det,m>0 and T>0,
                       m>0 and 1e-8<p<1-1e-8 and det>1e-8)


def inverse_time(log_ratio,p,*,r=.05,payout=.03,sigma=.2):
    """Same information as a raw-horizon ordinary baseline, when invertible."""
    if type(p) not in (int,float) or not math.isfinite(p) or not 1e-10<p<1-1e-10:
        raise Refuse('saturated probability')
    low=hit(log_ratio,1e-5,r=r,payout=payout,sigma=sigma)[0]
    high=hit(log_ratio,100.,r=r,payout=payout,sigma=sigma)[0]
    if not low<p<high:
        raise Refuse('no unique resolvable horizon in interval')
    return brentq(lambda t:hit(log_ratio,t,r=r,payout=payout,sigma=sigma)[0]-p,
                  1e-5,100.,xtol=1e-12,rtol=1e-12)
