"""P0 research reference: *regenerative neuron* one-dimensional optimal stopping.

This is not the coupled He--Xiong (2012) debt/equity model.  It is an
independent, declared-domain QVI for a Brownian state, affine firing reward,
fixed reset, and deterministic refractory time.  Mathematical verification is
restricted to the stated scalar constant-coefficient real-arithmetic domain;
binary64 output and the independent finite-domain grid are diagnostics, not
certified enclosures.

With L=mu*d/dx + sigma**2/2*d²/dx², rho>0, r<K and refractory tau>=0,
    M J(x) = x-K + exp(-rho*tau)*J(r)
    max(L J-rho*J, M J-J) = 0.

Let kappa>0 solve sigma²*kappa²/2 + mu*kappa-rho=0.  Let
q0=exp(-rho*tau-kappa*(K-r)), z be the unique root in (0,1) of
    psi(z)=z-1+q0*exp(-z)=0.
Then b=K+z/kappa, q=q0*exp(-z)=1-z, and
    J(x)=exp(kappa*(x-b))/kappa    for x<b,
         x-K+q/kappa               for x>=b.

Exact proof: in continuation (L-rho)J=0 by characteristic equation,
J-MJ=(exp(y)-1-y)/kappa>=0 with y=kappa*(x-b)<0.  In stopping,
MJ-J=0 and (L-rho)J=mu-rho*J<=mu-rho/kappa=-sigma²*kappa/2<0.
Matching, smooth fit, growth/transversality and the strict root monotonicity
psi'(z)=1-q0*exp(-z)>0 verify the scalar QVI.  This does NOT establish
whole-network optimality, HX self-consistent equilibrium, or low-precision
correctness; firing at the boundary remains a discrete action.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import math

import numpy as np
from scipy.optimize import brentq
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve


class UnresolvedQVI(ValueError):
    """Parameter, arithmetic or independently checked policy is not admissible."""


@dataclass(frozen=True)
class RegenerativeNeuron:
    drift: float
    sigma: float
    discount: float
    cost: float
    reset: float
    refractory: float

    def __post_init__(self):
        for name, value in vars(self).items():
            if type(value) not in (int, float) or not math.isfinite(value):
                raise UnresolvedQVI(f'{name}: finite numeric input required')
        if not (self.sigma>0 and self.discount>0 and self.reset<self.cost
                and self.refractory>=0):
            raise UnresolvedQVI('require sigma,rho>0; reset<K; tau>=0')

    @property
    def kappa(self) -> float:
        root=math.hypot(self.drift, self.sigma*math.sqrt(2*self.discount))
        if self.drift>=0:
            k=2*self.discount/(root+self.drift)
        else:
            k=(root-self.drift)/(self.sigma*self.sigma)
        if not math.isfinite(k) or k<=0:
            raise UnresolvedQVI('positive characteristic root unresolved')
        residual=math.fsum((.5*self.sigma**2*k*k,self.drift*k,-self.discount))
        if abs(residual)>1e-10*max(1.,self.discount):
            raise UnresolvedQVI('characteristic residual above f64 reference tolerance')
        return k

    @property
    def solution(self) -> 'Solution':
        k=self.kappa
        logq=-self.discount*self.refractory-k*(self.cost-self.reset)
        if not math.isfinite(logq) or logq>=0 or logq < -30:
            raise UnresolvedQVI('q0 is singular or too small for a distinct f64 root')
        # expm1 avoids 1-exp(-epsilon) catastrophic cancellation.
        def rootfn(z: float) -> float:
            return z+math.expm1(logq-z)
        if rootfn(0.)>=0 or rootfn(1.)<=0:
            raise UnresolvedQVI('expected root bracket lost in f64')
        z=brentq(rootfn,0.,1.,xtol=5e-16,rtol=9e-16)
        if not 1e-10<z<1 or abs(rootfn(z))>2e-13*z:
            raise UnresolvedQVI('ill-conditioned root, or insufficient residual')
        b=self.cost+z/k
        if not math.isfinite(b) or b<=self.cost or b<=self.reset:
            raise UnresolvedQVI('boundary not represented strictly beyond cost/reset')
        q=math.exp(logq-z)
        if abs((q+z)-1)>2e-13:
            raise UnresolvedQVI('regenerative discount consistency failed')
        return Solution(kappa=k, boundary=b, q=q, root=z, root_residual=rootfn(z))

    def value(self, x: float) -> float:
        if type(x) not in (int,float) or not math.isfinite(x):
            raise UnresolvedQVI('state must be finite')
        s=self.solution
        if x>=s.boundary:
            v=math.fsum((x,-self.cost,s.q/s.kappa))
        else:
            exponent=s.kappa*(x-s.boundary)
            if exponent < -700:
                raise UnresolvedQVI('continuation value below supported f64 range')
            v=math.exp(exponent)/s.kappa
        if not math.isfinite(v) or v<=0:
            raise UnresolvedQVI('value not strictly positive in reference domain')
        return v

    def qvi(self, x: float) -> 'QVIProbe':
        if not isinstance(x,(float,int)) or isinstance(x,bool) or not math.isfinite(x):
            raise UnresolvedQVI('state must be finite')
        s=self.solution
        exercise=math.fsum((x,-self.cost,s.q/s.kappa))
        if x>=s.boundary:
            value=exercise
            residual_generator=self.drift-self.discount*value
            residual_obstacle=0.
            regime='FIRE'
        else:
            y=s.kappa*(x-s.boundary)
            if y < -700:
                raise UnresolvedQVI('continuation value too small')
            value=math.exp(y)/s.kappa
            # exp(y)-1-y >= 0 exactly.  Avoid numerical sign reversal
            # near the free boundary by an explicit positive series.
            if abs(y)<.05:
                factor=1+y/3+y*y/12+y**3/60+y**4/360+y**5/2520
                gap=.5*y*y*factor/s.kappa
            else:
                gap=(math.expm1(y)-y)/s.kappa
            if gap<0 or not math.isfinite(gap):
                raise UnresolvedQVI('QVI obstacle gap unresolved')
            residual_generator=0.  # characteristic identity, not FD residual
            residual_obstacle=-gap
            regime='CONTINUE'
        if not math.isfinite(value) or value<=0 or residual_generator>1e-12:
            raise UnresolvedQVI('QVI reference outside declared finite domain')
        return QVIProbe(regime, value, exercise, residual_generator,
                        residual_obstacle, max(residual_generator,residual_obstacle))

    def boundary_sensitivities(self) -> dict[str,float]:
        s=self.solution
        k,b,q,z=s.kappa,s.boundary,s.q,s.root
        D=math.hypot(self.drift,self.sigma*math.sqrt(2*self.discount))
        if D<=0 or k*z<=1e-14:
            raise UnresolvedQVI('implicit boundary sensitivity singular')
        projection=(b-self.cost)-q*(b-self.reset)
        dk_mu=-k/D
        dk_sigma=-self.sigma*k*k/D
        dk_discount=1/D
        factor=-1/(k*z)
        out={
            'drift':factor*(dk_mu*projection),
            'sigma':factor*(dk_sigma*projection),
            'discount':factor*(dk_discount*projection-q*self.refractory),
            'cost':1/z,
            'reset':-q/z,
            'refractory':q*self.discount/(k*z),
        }
        if not all(math.isfinite(v) for v in out.values()):
            raise UnresolvedQVI('implicit sensitivities non-finite')
        return out


@dataclass(frozen=True)
class Solution:
    kappa: float
    boundary: float
    q: float
    root: float
    root_residual: float


@dataclass(frozen=True)
class QVIProbe:
    regime: str
    value: float
    immediate_fire_value: float
    generator_residual: float
    obstacle_residual: float
    max_qvi_residual: float


@dataclass(frozen=True)
class GridOracle:
    xs: np.ndarray
    values: np.ndarray
    stop: np.ndarray
    grid_boundary: float
    max_complementarity_residual: float
    iterations: int
    lower_boundary_value: float


def independent_grid_oracle(p: RegenerativeNeuron, *, n:int=257,
                            width_below:float=12., width_above:float=6.) -> GridOracle:
    """Independent finite-state regenerative-policy iteration (no analytic b in optimizer).

    Analytic boundary is used ONLY to center a finite comparison domain. The
    lower endpoint is Dirichlet zero (a truncation approximation), and the
    upper endpoint is forced FIRE.  Runtime QVI can differ from continuous
    oracle due to mesh, truncation and reset interpolation; this is expected.
    """
    if type(n) is not int or n<31 or n>4097 or n%2!=1:
        raise UnresolvedQVI('odd grid size within [31,4097] required')
    if not (all(math.isfinite(v) for v in (width_below,width_above))
            and width_below>4 and width_above>2):
        raise UnresolvedQVI('invalid finite-grid domain widths')
    s=p.solution
    xmin=min(s.boundary-width_below/s.kappa,p.reset-1./s.kappa)
    xmax=s.boundary+width_above/s.kappa
    if not all(math.isfinite(v) for v in (xmin,xmax)) or not xmin<p.reset<xmax:
        raise UnresolvedQVI('reset not interior to reference grid')
    xs=np.linspace(xmin,xmax,n)
    h=(xmax-xmin)/(n-1)
    a=.5*p.sigma**2/h**2
    lc=a-p.drift/(2*h)
    rc=a+p.drift/(2*h)
    if min(lc,rc)<0:
        lc=a+max(-p.drift,0)/h
        rc=a+max(p.drift,0)/h
    if not all(math.isfinite(v) for v in (a,lc,rc)) or min(lc,rc)<0:
        raise UnresolvedQVI('grid operator not monotone')
    denom=p.discount+lc+rc
    idx=int(np.searchsorted(xs,p.reset,side='right'))
    if idx<=0 or idx>=n:
        raise UnresolvedQVI('reset interpolation outside grid')
    w=(p.reset-xs[idx-1])/h
    discount=math.exp(-p.discount*p.refractory)
    stop=np.asarray(xs>p.cost,dtype=bool)
    stop[0]=False
    stop[-1]=True
    values=np.zeros(n)
    for it in range(1,151):
        A=lil_matrix((n,n),dtype=float)
        rhs=np.zeros(n)
        A[0,0]=1.
        for i in range(1,n):
            if stop[i]:
                A[i,i]=1.
                A[i,idx-1]-=discount*(1-w)
                A[i,idx]-=discount*w
                rhs[i]=xs[i]-p.cost
            else:
                A[i,i]=denom
                A[i,i-1]=-lc
                if i+1<n:
                    A[i,i+1]=-rc
        values=np.asarray(spsolve(A.tocsr(),rhs))
        if not np.isfinite(values).all():
            raise UnresolvedQVI('finite-grid value solve nonfinite')
        resetv=(1-w)*values[idx-1]+w*values[idx]
        cont=(lc*values[:-2]+rc*values[2:])/denom
        exercise=xs[1:-1]-p.cost+discount*resetv
        better=np.asarray(exercise >= cont)
        candidate=stop.copy()
        candidate[1:-1]=better
        if np.array_equal(candidate,stop):
            break
        stop=candidate
    else:
        raise UnresolvedQVI('independent regenerative policy iteration not converged')
    resetv=(1-w)*values[idx-1]+w*values[idx]
    cont_res=lc*values[:-2]+rc*values[2:]-denom*values[1:-1]
    obs_res=xs[1:-1]-p.cost+discount*resetv-values[1:-1]
    res=float(np.max(np.abs(np.maximum(cont_res,obs_res))))
    if res>1e-7*max(1.,p.cost) or not np.isfinite(res):
        raise UnresolvedQVI(f'discrete Bellman residual {res} too large')
    stopinds=np.flatnonzero(stop[1:-1])+1
    if len(stopinds)<1:
        raise UnresolvedQVI('finite-grid contains no interior FIRE region')
    return GridOracle(xs,values,stop,float(xs[stopinds[0]]),res,it,float(values[0]))
