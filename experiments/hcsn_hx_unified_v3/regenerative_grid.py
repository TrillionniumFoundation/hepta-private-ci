"""Independent MONOTONE finite-difference QVI for the scalar HCSN renewal model.

This is a *separate numerical algorithm* from stopping.py's Lambert-W
closed form. This solver never uses the analytic threshold or its value.

X follows dX=drift*dt+diffusion*dW. Intervention rewards x-cost, waits
refractory units, and resumes at reset. Discount is exp(-discount*t).

Interior viscosity scheme: max{L_h V - rho V, x-cost+D V(reset)-V}=0.
Left: V(xmin)=0 (truncation, not an exact stochastic boundary).
Right: forced intervention V(xmax)=xmax-cost+D V(reset).
Reset values use monotone piecewise-linear interpolation. A positive
rho, positive diffusion and reset<cost imply a nonexplosive reference
when the truncated domain and boundary choices are appropriate. The
numerical residual is NOT a mathematical error bound in the continuum.

Research-only, no production / no native f32/GPU / no deployment authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from .stopping import Stop


@dataclass(frozen=True)
class Grid:
    xmin: float
    xmax: float
    nodes: int

    def validate(self, p: Stop) -> None:
        vals = (self.xmin, self.xmax, p.reset, p.cost,
                p.drift, p.diffusion, p.discount, p.refractory)
        if not all(math.isfinite(v) for v in vals):
            raise ValueError('Finite inputs required')
        if not (isinstance(self.nodes, int) and not isinstance(self.nodes, bool)
                and 17 <= self.nodes <= 32769):
            raise ValueError('nodes must be an integer in [17,32769]')
        if not (self.xmin < p.reset < p.cost < self.xmax):
            raise ValueError('Domain must strictly contain reset and exercise cost')
        h = (self.xmax-self.xmin)/(self.nodes-1)
        if not math.isfinite(h) or h <= 0:
            raise ValueError('Unresolvable grid spacing')
        if not math.isfinite(p.discount + p.diffusion**2/h**2
                             + abs(p.drift)/h):
            raise ValueError('Grid generator overflows finite precision')


@dataclass(frozen=True)
class Result:
    x: np.ndarray
    values: np.ndarray
    fire: np.ndarray
    iterations: int
    residual: float
    boundary_low: float
    boundary_high: float
    interpolation_weights: tuple[tuple[int,float], ...]

    def at(self, location: float) -> float:
        if not math.isfinite(location) or not self.x[0] <= location <= self.x[-1]:
            raise ValueError('Position outside computed domain')
        return float(np.interp(location,self.x,self.values))


def _setup(p: Stop, grid: Grid):
    if not isinstance(p,Stop):
        raise TypeError('Expected independent stopping.Stop model')
    p.__post_init__()
    grid.validate(p)
    x = np.linspace(grid.xmin,grid.xmax,grid.nodes)
    h = float(x[1]-x[0])
    diffusion = .5*(p.diffusion/h)**2
    ql = diffusion + max(-p.drift,0.)/h
    qr = diffusion + max(p.drift,0.)/h
    # Centered discretization is less diffusive when its off-diagonal
    # generator rates are positive; otherwise monotone upwind is mandatory.
    center_left=diffusion-p.drift/(2*h)
    center_right=diffusion+p.drift/(2*h)
    if min(center_left,center_right)>=0:
        ql,qr=center_left,center_right
    rate=p.discount+ql+qr
    if not all(math.isfinite(v) for v in (rate,ql,qr)) or rate<=0:
        raise ArithmeticError('Invalid finite Markov generator')
    j=int(np.searchsorted(x,p.reset,side='right')-1)
    j=min(j,len(x)-2)
    w=float((p.reset-x[j])/(x[j+1]-x[j]))
    if not 0 <= w <= 1:
        raise ArithmeticError('Reset interpolation outside convex grid weights')
    reset=((j,1-w),(j+1,w))
    delay=math.exp(-p.discount*p.refractory)
    return x,ql,qr,rate,reset,delay


def _reset_value(v: np.ndarray, reset) -> float:
    return math.fsum(weight*float(v[j]) for j,weight in reset)


def _residual(v,active,x,p,ql,qr,rate,reset,delay):
    rhs=x-p.cost+delay*_reset_value(v,reset)
    cont=(ql*v[:-2]+qr*v[2:])/rate
    # Normalized Bellman residual in VALUE units, not the generator residual.
    bellman=float(np.max(np.abs(v[1:-1]-np.maximum(cont,rhs[1:-1]))))
    top=abs(v[-1]-rhs[-1]);left=abs(v[0])
    return max(bellman,top,left)


def _result(v,active,its,x,p,ql,qr,rate,reset,delay):
    residual=_residual(v,active,x,p,ql,qr,rate,reset,delay)
    if not np.all(np.isfinite(v)):
        raise ArithmeticError('Nonfinite finite-grid value')
    if np.min(v) < -1e-8*max(1.,float(np.max(v))):
        raise ArithmeticError('Negative value: invalid policy/mesh')
    i=int(np.flatnonzero(active)[0])
    if i==0 or i>=len(v)-1:
        # Domain does not bracket the interior optimal trigger.
        raise ArithmeticError('Exercise trigger not bracketed in mesh')
    if not np.all(active[i:]):
        raise ArithmeticError('Disconnected exercise region: reject calibration')
    return Result(x=x,values=v,fire=active,iterations=its,
                  residual=residual,boundary_low=float(x[i-1]),
                  boundary_high=float(x[i]),interpolation_weights=reset)


def solve_policy(p: Stop, grid: Grid, *, max_iterations: int=200,
                 decision_tolerance: float=1e-12) -> Result:
    """Howard policy iteration, sparse linear evaluation and policy improvement.

    Starting policy is finite-horizon stopping (fire only where x>cost),
    not an oracle-derived threshold. Local residual rejects nonconvergence.
    """
    if not 1<=max_iterations<=10000 or not (0<=decision_tolerance<=1e-7):
        raise ValueError('Invalid solver budget or tolerance')
    x,ql,qr,rate,reset,delay=_setup(p,grid)
    n=len(x)
    active=x>p.cost
    active[0]=False
    active[-1]=True
    for it in range(1,max_iterations+1):
        A=lil_matrix((n,n),dtype=np.float64)
        b=np.zeros(n,dtype=np.float64)
        A[0,0]=1.
        for i in range(1,n):
            if active[i]:
                A[i,i]=1.
                for j,w in reset:
                    A[i,j] -= delay*w
                b[i]=x[i]-p.cost
            else:
                A[i,i]=rate
                A[i,i-1]=-ql
                A[i,i+1]=-qr
        v=np.asarray(spsolve(A.tocsc(),b),dtype=float)
        if not np.all(np.isfinite(v)):
            raise ArithmeticError('Singular or nonfinite policy value')
        fire=x-p.cost+delay*_reset_value(v,reset)
        cont=(ql*v[:-2]+qr*v[2:])/rate
        proposal=active.copy()
        proposal[1:-1]=fire[1:-1]>cont+decision_tolerance
        if np.array_equal(active,proposal):
            out=_result(v,active,it,x,p,ql,qr,rate,reset,delay)
            if out.residual>max(3*decision_tolerance,1e-9)*max(1.,float(np.max(v))):
                raise ArithmeticError('Bellman residual above precision gate')
            return out
        active=proposal
    raise RuntimeError('Regenerative policy iteration failed to converge')


def solve_value_iteration(p: Stop, grid: Grid, *, tolerance: float=2e-11,
                          max_iterations: int=250000) -> Result:
    """Independent Jacobi Bellman fixed point (no sparse solver, no policy)."""
    if not 0<tolerance<1e-3 or not 1<=max_iterations<=1000000:
        raise ValueError('Invalid value iteration stopping rule')
    x,ql,qr,rate,reset,delay=_setup(p,grid)
    v=np.zeros(len(x),dtype=np.float64)
    for it in range(1,max_iterations+1):
        fire=x-p.cost+delay*_reset_value(v,reset)
        cont=(ql*v[:-2]+qr*v[2:])/rate
        nxt=np.empty_like(v)
        nxt[0]=0.
        nxt[1:-1]=np.maximum(cont,fire[1:-1])
        nxt[-1]=fire[-1]
        change=float(np.max(np.abs(nxt-v)))
        v=nxt
        if change<tolerance:
            active=np.zeros(len(x),dtype=bool)
            active[1:-1]=fire[1:-1]>cont
            active[-1]=True
            out=_result(v,active,it,x,p,ql,qr,rate,reset,delay)
            if out.residual>tolerance*1.1:
                raise ArithmeticError('Jacobi returned without Bellman consistency')
            return out
    raise RuntimeError('Regenerative Bellman iteration failed to converge')
