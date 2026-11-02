"""Continuous-time numerical Brownian first-passage/reset reference.

This is a new, bounded reference, not a replacement for the archived projected
cell or its trained parameters. It resolves hit times by inverse CDF, samples
surviving endpoints from the killed law, and consumes *actual remaining time*
after each hit/refractory/reset. Multiple hits in one external interval are
allowed. Finite image sums and root tolerances make it numerically approximate.
It has no autodiff or production qualification.
"""
from dataclasses import asdict, dataclass
from copy import deepcopy
import math
import numpy as np
from scipy.optimize import brentq
from scipy.special import log_ndtr, ndtr, ndtri

VERSION = "continuous-brownian-renewal-numerical-v1"
BASELINE_COMMIT = "012bcf3505cb9306d9cef094a1acc3ca34c978be"
MASS_TOL = 3e-10
ROOT_XTOL = 2e-11
IMAGE_TERMS = 12


@dataclass(frozen=True)
class Law:
    boundary: float = 0.8
    diffusion: float = 0.8
    drift: float = 0.0
    recovery_rate: float = 2.0
    reset_minus: float = 0.0
    reset_plus: float = 0.0
    reset_sd: float = 0.0

    def validate(self):
        a = asdict(self)
        if not all(math.isfinite(v) for v in a.values()):
            raise ValueError("finite physical parameters required")
        if not 0.8 <= self.boundary <= 1.2 or not 0.35 <= self.diffusion <= 0.8:
            raise ValueError("reference envelope: boundary [.8,1.2], diffusion [.35,.8]")
        if abs(self.drift) > 1.1 or not 0.25 <= self.recovery_rate <= 2:
            raise ValueError("reference envelope: |drift|<=1.1, recovery [.25,2]")
        if any(abs(x) > 0.6*self.boundary for x in (self.reset_minus,self.reset_plus)):
            raise ValueError("reset centers must be within .6*boundary")
        if not 0 <= self.reset_sd <= 0.12*self.boundary:
            raise ValueError("reset_sd must be in [0,.12*boundary]")


def _mass(v, name):
    v = float(v)
    if not math.isfinite(v) or v < -MASS_TOL or v > 1+MASS_TOL:
        raise ArithmeticError(f"invalid {name}: {v}")
    return min(1.0,max(0.0,v))


def _log_normal_interval(a, b):
    a,b=np.broadcast_arrays(np.asarray(a,dtype=float),np.asarray(b,dtype=float))
    right=a>=0
    lo,hi=np.where(right,-b,a),np.where(right,-a,b)
    small,big=log_ndtr(lo),log_ndtr(hi)
    with np.errstate(divide="ignore", invalid="ignore"):
        return big+np.log(-np.expm1(np.minimum(0,small-big)))


def _check_position(x, law):
    if not math.isfinite(x) or not -law.boundary < x < law.boundary:
        raise ValueError("active voltage must be strictly inside both boundaries")


def exit_cdf(x, t, law, terms=IMAGE_TERMS):
    """Unconditional competing lower/upper first-exit probabilities by t.

    Image law integrated in time; unlike endpoint thresholding, excursions
    crossing and returning within t are included. No row renormalization.
    """
    law.validate(); _check_position(x,law)
    if not isinstance(terms,int) or terms<1:raise ValueError("image terms must be a positive integer")
    if not math.isfinite(t) or not 0 <= t <= 2:
        raise ValueError("external/reference duration must be in [0,2]")
    if t==0:return np.zeros(2)
    b,s,mu=law.boundary,law.diffusion,law.drift
    k=np.arange(-terms,terms+1)
    def lower(y,m):
        a=y+4*b*k; d=np.abs(a)
        loghit=np.logaddexp(log_ndtr((-d-m*t)/(s*math.sqrt(t))),
            -2*m*d/s**2+log_ndtr((-d+m*t)/(s*math.sqrt(t))))
        return np.sum(np.sign(a)*np.exp(m*(d-y)/s**2+loghit))
    p=np.array([_mass(lower(x+b,mu),"lower exit"),_mass(lower(b-x,-mu),"upper exit")])
    if p.sum()>1+MASS_TOL:raise ArithmeticError("first-exit mass exceeds one")
    return p


def exit_density(x,t,law,terms=IMAGE_TERMS):
    """Competing boundary probability fluxes at positive time t."""
    law.validate();_check_position(x,law)
    if not math.isfinite(t) or not 0<t<=2:raise ValueError("density requires finite t in (0,2]")
    if not isinstance(terms,int) or terms<1:raise ValueError("image terms must be a positive integer")
    b,s,mu=law.boundary,law.diffusion,law.drift
    k=np.arange(-terms,terms+1)
    def lower(y,m):
        a=y+4*b*k
        v=np.sign(a)*np.exp(np.log(np.abs(a))-0.5*np.log(2*np.pi)-np.log(s)
            -1.5*np.log(t)-a*a/(2*s*s*t)-m*y/s**2-m*m*t/(2*s*s))
        total=float(v.sum())
        if not math.isfinite(total) or total < -1e-10:raise ArithmeticError("invalid boundary flux")
        return max(0,total)
    return np.array([lower(x+b,mu),lower(b-x,-mu)])


def killed_cdf(x,y,t,law,terms=IMAGE_TERMS):
    """P(no earlier exit and X_t<=y); unconditional, not normalized."""
    law.validate();_check_position(x,law)
    if not isinstance(terms,int) or terms<1:raise ValueError("image terms must be a positive integer")
    if not 0<t<=2 or not -law.boundary <= y <= law.boundary:
        raise ValueError("invalid killed CDF arguments")
    b,s,m=law.boundary,law.diffusion,law.drift
    if y==-b:return 0.0
    k=np.arange(-terms,terms+1);length=2*b;u=x+b
    a=0.;v=y+b;scale=s*math.sqrt(t)
    mean1=u-2*k*length+m*t;mean2=-u-2*k*length+m*t
    log1=-2*m*k*length/s**2+_log_normal_interval((a-mean1)/scale,(v-mean1)/scale)
    log2=-2*m*(u+k*length)/s**2+_log_normal_interval((a-mean2)/scale,(v-mean2)/scale)
    return _mass(np.sum(np.exp(log1)-np.exp(log2)),"killed cumulative mass")


def sample_segment(x,t,law,rng):
    """Return (hit time, side, voltage); side=0 means no exit before t.

    side -1/+1 is lower/upper, with voltage exactly at that boundary. The
    surviving endpoint is sampled conditionally on survival, using killed CDF.
    """
    law.validate();_check_position(x,law)
    if not math.isfinite(t) or not 0<=t<=2:raise ValueError("duration must be in [0,2]")
    if t==0:return 0.0,0,float(x)
    p=exit_cdf(x,t,law);u=float(rng.random())
    if u < p.sum():
        tau=brentq(lambda z: float(exit_cdf(x,z,law).sum())-u,0,t,
                   xtol=ROOT_XTOL,rtol=1e-13)
        if tau<=0:raise ArithmeticError("hit lies below supported time resolution")
        flux=exit_density(x,tau,law)
        if flux.sum()<=0:raise ArithmeticError("unresolved competing exit flux")
        side=-1 if rng.random()*flux.sum()<flux[0] else 1
        return float(tau),side,float(side*law.boundary)
    survival=1-float(p.sum())
    mass=killed_cdf(x,law.boundary,t,law)
    if abs(survival-mass)>MASS_TOL:raise ArithmeticError("exit/survival mass disagreement")
    if mass<=0:raise ArithmeticError("zero survival selected")
    target=float(rng.random())*mass
    y=brentq(lambda z:killed_cdf(x,z,t,law)-target,-law.boundary,law.boundary,
             xtol=ROOT_XTOL,rtol=1e-13)
    if abs(y)>=law.boundary:raise ArithmeticError("unresolved surviving endpoint")
    return float(t),0,float(y)


@dataclass(frozen=True)
class State:
    voltage: float = 0.0
    mode: int = 0  # active=0, lower/upper refractory=-1/+1
    refractory_remaining: float = 0.0

    def validate(self,law):
        if self.mode not in (-1,0,1) or not math.isfinite(self.refractory_remaining) or self.refractory_remaining<0:
            raise ValueError("invalid refractory state")
        if self.mode==0:
            _check_position(self.voltage,law)
            if self.refractory_remaining!=0:raise ValueError("active state has refractory time")
        elif self.voltage!=self.mode*law.boundary:
            raise ValueError("refractory voltage must identify hit boundary")


def _reset(law,side,rng):
    center=law.reset_minus if side==-1 else law.reset_plus
    if law.reset_sd==0:return float(center)
    a=ndtr((-law.boundary-center)/law.reset_sd)
    b=ndtr((law.boundary-center)/law.reset_sd)
    # Continuous *truncated* Gaussian, explicitly different from archived
    # finite folded-bin reset. No boundary atom may produce zero-time Zeno hits.
    p=a+(b-a)*rng.random()
    value=float(center+law.reset_sd*ndtri(p))
    if not -law.boundary<value<law.boundary:raise ArithmeticError("unresolved truncated reset")
    return value


def advance(state,dt,law,rng,max_events=1000):
    """Numerically sample one interval, allowing arbitrary hits up to a guard.

    Returns (new State, events). Each event has its actual local hit/release
    times. No event is moved to an interval boundary. A guard overflow raises
    rather than silently truncating, dropping residual time, or renormalizing.
    """
    law.validate();state.validate(law)
    if not math.isfinite(dt) or not 0<=dt<=2:raise ValueError("duration must be in [0,2]")
    if not isinstance(max_events,int) or max_events<1:raise ValueError("max_events must be positive")
    # Inputs are immutable and RNG is committed only after success.
    work=np.random.Generator(type(rng.bit_generator)())
    work.bit_generator.state=deepcopy(rng.bit_generator.state)
    x,mode,recovery=state.voltage,state.mode,state.refractory_remaining
    elapsed=0.;events=[]
    while elapsed<dt:
        remaining=dt-elapsed
        if mode:
            if recovery>remaining:
                recovery-=remaining;elapsed=dt;break
            elapsed+=recovery
            x=_reset(law,mode,work);mode=0;recovery=0.
            if elapsed>=dt:break
            continue
        tau,side,x=sample_segment(x,remaining,law,work)
        elapsed+=tau
        if side==0:break
        if len(events)>=max_events:raise OverflowError("event guard exceeded; no state/RNG committed")
        mode=side;recovery=float(work.exponential(1/law.recovery_rate))
        events.append(dict(time=float(elapsed),side=side,refractory_duration=recovery,
                           release_time=float(elapsed+recovery)))
    result=State(float(x),int(mode),float(recovery))
    result.validate(law)
    rng.bit_generator.state=deepcopy(work.bit_generator.state)
    return result,events


def checkpoint(state,rng,law):
    law.validate();state.validate(law)
    if type(rng.bit_generator).__name__!="PCG64":raise ValueError("checkpoint supports PCG64 only")
    return dict(schema=VERSION,law=asdict(law),state=asdict(state),
                rng_kind=type(rng.bit_generator).__name__,rng_state=deepcopy(rng.bit_generator.state))


def restore(payload):
    if payload.get("schema")!=VERSION or payload.get("rng_kind")!="PCG64":
        raise ValueError("unsupported checkpoint schema/RNG")
    law=Law(**payload["law"]);law.validate()
    state=State(**payload["state"]);state.validate(law)
    rng=np.random.Generator(np.random.PCG64());rng.bit_generator.state=payload["rng_state"]
    return state,rng,law
