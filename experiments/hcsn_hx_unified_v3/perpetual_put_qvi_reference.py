"""Independent *simplified* perpetual-GBM optimal-stopping/QVI oracle.

IMPORTANT SCOPE: this is the standard perpetual American put with risk-neutral
GBM, NOT the full He--Xiong (2012) rollover equilibrium, bond pricing,
self-consistent default boundary, or a regenerative-neuron optimality claim.

Mathematical global QVI certificate under r>0, sigma>0, dividend>=0, K>0:

    L f=(r-dividend)*v*f_v + (sigma**2/2)*v*v*f_vv,
    g(v)=(K-v)+,    max{L U-r U, g-U}=0.

The negative root beta of
    (sigma**2/2)*beta*(beta-1)+(r-dividend)*beta-r=0
sets b=K*beta/(beta-1) in (0,K). Set U=K-v for v<=b and
U=(K-b)*(v/b)**beta otherwise.

Proof (exact real arithmetic): value and smooth fit hold at b; for v>b,
U''=beta*(beta-1)*U/v**2>0, hence U-(K-v)>=0 by tangency and
strict convexity until K, and U>0 beyond K. For v<=b,
(L-r)(K-v)=dividend*v-r*K <= dividend*b-r*K
= (sigma**2/2)*beta*K <0. In continuation (L-r)U=0 by the
characteristic equation. Together with U(v)->0 at infinity this is
a global QVI verification for this exact simplified problem.

This is a human-checkable analytic proof, not a machine-checked formal proof,
full-HX certificate, full finite-precision interval certificate, or GPU result.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.linalg import solve_banded


class ReferenceDomainError(ValueError):
    pass


@dataclass(frozen=True)
class GBMPut:
    rate: float
    dividend: float
    sigma: float
    strike: float

    def __post_init__(self):
        if any(type(z) not in (int, float) or not math.isfinite(z)
               for z in (self.rate, self.dividend, self.sigma, self.strike)):
            raise ReferenceDomainError('parameters must be finite real numbers')
        if not (self.rate > 0 and self.dividend >= 0 and
                self.sigma > 0 and self.strike > 0):
            raise ReferenceDomainError('require r>0, div>=0, sigma>0, K>0')

    @property
    def beta_minus(self) -> float:
        a = .5 * self.sigma**2
        b = self.rate - self.dividend - a
        discr = math.hypot(b, 2 * math.sqrt(a * self.rate))
        beta = (-2*self.rate/(discr-b)) if b < 0 else -(b+discr)/(2*a)
        if not math.isfinite(beta) or beta >= 0 or beta == 0 or beta == -1e308:
            raise ArithmeticError('negative exponent unresolved')
        residual = a*beta*(beta-1)+(self.rate-self.dividend)*beta-self.rate
        if not math.isfinite(residual) or abs(residual)>1e-9*max(self.rate,1e-12):
            raise ArithmeticError('characteristic equation unresolved')
        return beta

    @property
    def boundary(self) -> float:
        beta=self.beta_minus
        b=self.strike * beta/(beta-1)
        if not (math.isfinite(b) and 0 < b < self.strike and
                self.dividend*b-self.rate*self.strike < 0):
            raise ArithmeticError('boundary not resolvable in double precision')
        return b

    def value(self, v: float) -> float:
        if type(v) not in (int,float) or not math.isfinite(v) or v<=0:
            raise ReferenceDomainError('v must be finite and positive')
        b=self.boundary
        if v<=b:
            return self.strike-v
        return (self.strike-b)*math.exp(self.beta_minus*math.log(v/b))

    def qvi(self, v: float) -> tuple[float,float]:
        """Return (generator-minus-discount, obstacle-minus-value).

        Analytic branch identities avoid cancellation; they do not certify
        binary64 rounding near the zero-gradient or boundary itself.
        """
        u=self.value(v)
        g=max(self.strike-v,0.)
        if v<=self.boundary:
            generator=self.dividend*v-self.rate*self.strike
        else:
            generator=0.
        return generator,g-u

    def sensitivities(self) -> dict[str,float]:
        """Implicit derivatives of b w.r.t. r, dividend, sigma and strike."""
        beta=self.beta_minus
        f_beta=self.sigma**2*(beta-.5)+(self.rate-self.dividend)
        if not math.isfinite(f_beta) or f_beta>=0 or f_beta==0:
            raise ArithmeticError('boundary implicit derivative singular')
        db_d_beta=-self.strike/(beta-1)**2
        values={
            'rate':db_d_beta * (-(beta-1)/f_beta),
            'dividend':db_d_beta * (beta/f_beta),
            'sigma':db_d_beta * (-self.sigma*beta*(beta-1)/f_beta),
            'strike':beta/(beta-1),
        }
        if not all(map(math.isfinite,values.values())):
            raise ArithmeticError('unresolved boundary derivative')
        return values


def quantized_side_f32(v: float, b: float) -> str:
    """Refuse f32-aliased event sides; *not* an FP32 interval proof.

    Strict classification after ordinary float32 rounding is monotonic when
    the codes differ. A shared rounded code cannot establish which side of
    a real-valued boundary was intended, so returns AMBIGUOUS.
    """
    if any(type(t) not in (int,float) or not math.isfinite(t) or t<=0 for t in (v,b)):
        raise ReferenceDomainError('positive finite state and boundary required')
    vf,bf=np.float32(v),np.float32(b)
    if not (np.isfinite(vf) and np.isfinite(bf)) or vf==0 or bf==0:
        return 'AMBIGUOUS'
    if vf==bf:
        return 'AMBIGUOUS'
    return 'ABOVE' if vf>bf else 'BELOW'


@dataclass(frozen=True)
class DiscreteQVI:
    spots: np.ndarray
    values: np.ndarray
    stop: np.ndarray
    active_boundary: float
    max_complementarity_residual: float
    policy_iterations: int


def independent_grid_qvi(p: GBMPut, *, n: int=257,
                         x_min: float=-4.0, x_max: float=5.0) -> DiscreteQVI:
    """Independent obstacle-policy iteration on a log-price generator grid.

    Uniform log GBM grid, M-matrix tridiagonal generator with automatic upwind
    fallback, absorbing known lower payoff and zero large-value upper payoff.
    Thus finite-domain truncation errors persist: this solver is independent
    numerical evidence, NOT a mathematically certified full-domain solution.
    """
    if type(n) is not int or n<25 or n>8193 or n%2==0:
        raise ReferenceDomainError('odd n in [25,8193] required')
    if not all(math.isfinite(x) for x in (x_min,x_max)) or not x_min<x_max:
        raise ReferenceDomainError('invalid grid domain')
    h=(x_max-x_min)/(n-1)
    x=np.linspace(x_min,x_max,n)
    v=p.strike*np.exp(x)
    if not np.isfinite(v).all():
        raise ReferenceDomainError('grid overflows')
    payoff=np.maximum(p.strike-v,0.)
    log_drift=p.rate-p.dividend-.5*p.sigma**2
    a=.5*p.sigma**2/h**2
    lc=a-log_drift/(2*h)
    rc=a+log_drift/(2*h)
    if min(lc,rc)<0:
        lc=a+max(-log_drift,0)/h
        rc=a+max(log_drift,0)/h
    denom=p.rate+lc+rc
    stop=(payoff>0).copy()
    stop[0]=True; stop[-1]=True
    values=payoff.copy()
    for iteration in range(1,201):
        diag=np.full(n,denom,dtype=float)
        lo=np.full(n-1,-lc,dtype=float)
        up=np.full(n-1,-rc,dtype=float)
        rhs=np.zeros(n,dtype=float)
        idx=np.flatnonzero(stop)
        diag[idx]=1.
        rhs[idx]=payoff[idx]
        # Strip off-diagonal coefficients if the row belongs to a STOP state.
        lo[idx[idx>0]-1]=0.
        up[idx[idx<n-1]]=0.
        band=np.zeros((3,n),dtype=float)
        band[0,1:]=up
        band[1,:]=diag
        band[2,:-1]=lo
        values=solve_banded((1,1),band,rhs,overwrite_ab=False,overwrite_b=False,
                            check_finite=True)
        continuation=(lc*values[:-2]+rc*values[2:])/denom
        improve=np.zeros(n,dtype=bool)
        improve[1:-1]=payoff[1:-1]>=continuation
        improve[0]=improve[-1]=True
        if np.array_equal(improve,stop):
            break
        stop=improve
    else:
        raise ArithmeticError('policy iteration did not converge')
    action_res=(lc*values[:-2]+rc*values[2:]-denom*values[1:-1])
    # Bellman complementarity: max(g-u,L u-r u)=0.
    resid=np.maximum(payoff[1:-1]-values[1:-1],action_res)
    maxres=float(np.max(np.abs(resid)))
    if maxres>1e-6*max(1.,p.strike) or not np.isfinite(values).all():
        raise ArithmeticError('independent QVI complementarity violation')
    stop_indices=np.flatnonzero(stop[1:-1])+1
    # Last active stopping grid point below strike; upper boundary is a
    # separate truncation condition, not a stopping event.
    positive_stop=stop_indices[payoff[stop_indices]>0]
    if not len(positive_stop):
        raise ArithmeticError('no stopping region on grid')
    return DiscreteQVI(v,values,stop,v[max(positive_stop)],maxres,iteration)
