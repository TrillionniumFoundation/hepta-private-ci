"""Research-only two-cell competing-intervention, discounted regenerative QVI.

This is a NEW, precisely delimited *neural analogy* model, not the He-Xiong
corporate-finance equilibrium or a multivariate HX closed form.

Between events, two *independent* arithmetic-Brownian states evolve on a
finite rectangular domain with artificial reflecting/zero-flux boundaries.
At any state the controller either waits or fires exactly ONE cell. Firing
cell i pays x_i-cost_i; both coordinates are frozen for refractory_i units,
then the firing coordinate resets to reset_i and the other stays unchanged.
The global discount is rho, so action i has factor D_i=exp(-rho*tau_i).

The grid QVI is
  max{(L1_h+L2_h-rho)V,
      x1-cost1+D1*V(reset1,x2)-V,
      x2-cost2+D2*V(x1,reset2)-V} = 0.

We solve the discretized obstacle problem by (1) sparse Howard policy
iteration and (2) Jacobi Bellman value iteration. They are independent
algorithms for the SAME finite-grid model, NOT independent discretizations.
With rho>0, tau_i>0, finite positive Markov rates, each Bellman branch
is a sup-norm contraction. No claim of global continuum error bounds,
nonlocal asynchronous refractory behavior, actual spiking training gains,
low-precision certification, GPU runtime or production admission.

Research-only / DENY_ALL: no import in production execution/authority paths.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from .stopping import Stop


@dataclass(frozen=True)
class Rectangle:
    x1min: float
    x1max: float
    n1: int
    x2min: float
    x2max: float
    n2: int


@dataclass(frozen=True)
class TwoCell:
    first: Stop
    second: Stop

    def validate(self, rect: Rectangle) -> None:
        for c in (self.first, self.second):
            if not isinstance(c, Stop):
                raise TypeError("Both cells must be stopping.Stop")
            c.__post_init__()
        if self.first.discount != self.second.discount:
            raise ValueError("Both cells must have identical discount clocks")
        if not (self.first.refractory > 0 and self.second.refractory > 0):
            raise ValueError("Strictly positive refractory is required for a contractive QVI")
        for lo, hi, n, c in (
            (rect.x1min, rect.x1max, rect.n1, self.first),
            (rect.x2min, rect.x2max, rect.n2, self.second),
        ):
            if not (isinstance(n, int) and not isinstance(n, bool) and 9 <= n <= 97):
                raise ValueError("Grid axis node count must be an integer in [9,97]")
            if not all(math.isfinite(z) for z in (lo, hi)):
                raise ValueError("Grid limits must be finite")
            if not lo < c.reset < hi:
                raise ValueError("Reset must be strictly inside each grid interval")
            if not hi > lo or not math.isfinite((hi-lo)/(n-1)):
                raise ValueError("Grid interval/spacing invalid")
        if (rect.n1*rect.n2) > 6400:
            raise ValueError("Refuse oversized 2D direct solve; budget <= 6400 states")
        for c in (self.first, self.second):
            if c.delay_discount >= 1.:
                raise ValueError("Refractory discount rounded to one; contraction unproven")


@dataclass(frozen=True)
class CoupledResult:
    x1: np.ndarray
    x2: np.ndarray
    values: np.ndarray
    policy: np.ndarray  # 0 wait, 1 fire first, 2 fire second
    iterations: int
    bellman_residual: float
    generator_qvi_residual: float
    reset_interpolations: tuple[tuple[tuple[int,float], ...], ...]

    def at(self, a: float, b: float) -> float:
        if not all(math.isfinite(v) for v in (a,b)) or not (
            self.x1[0] <= a <= self.x1[-1] and self.x2[0] <= b <= self.x2[-1]
        ):
            raise ValueError("Query outside computed rectangle")
        i = min(int(np.searchsorted(self.x1, a, side='right')-1), len(self.x1)-2)
        j = min(int(np.searchsorted(self.x2, b, side='right')-1), len(self.x2)-2)
        t=(a-self.x1[i])/(self.x1[i+1]-self.x1[i])
        u=(b-self.x2[j])/(self.x2[j+1]-self.x2[j])
        v=self.values
        return float((1-t)*((1-u)*v[i,j]+u*v[i,j+1]) +
                      t*((1-u)*v[i+1,j]+u*v[i+1,j+1]))


@dataclass(frozen=True)
class _GridData:
    x1: np.ndarray
    x2: np.ndarray
    rate: np.ndarray
    qm1: np.ndarray
    qp1: np.ndarray
    qm2: np.ndarray
    qp2: np.ndarray
    reset1: tuple[tuple[int, float], ...]
    reset2: tuple[tuple[int, float], ...]
    delay1: float
    delay2: float
    discount: float


def _axis_rates(c: Stop, lo: float, hi: float, n: int):
    x=np.linspace(lo,hi,n,dtype=np.float64)
    h=float(x[1]-x[0])
    diffusion=.5*(c.diffusion/h)**2
    minus=diffusion-c.drift/(2*h)
    plus=diffusion+c.drift/(2*h)
    if min(minus,plus)<0:  # monotonicity trumps order of accuracy
        minus=diffusion+max(-c.drift,0.)/h
        plus=diffusion+max(c.drift,0.)/h
    if not all(math.isfinite(z) for z in (minus,plus)) or min(minus,plus)<0:
        raise ArithmeticError("Non-finite/non-Markov generator")
    # Finite-state reflected random walk: no outward jump across a wall.
    # This is a MODEL boundary, not the same truncation as the scalar solver.
    qm=np.full(n,minus,dtype=float)
    qp=np.full(n,plus,dtype=float)
    qm[0]=0.
    qp[-1]=0.
    i=min(int(np.searchsorted(x,c.reset,side='right')-1),n-2)
    w=float((c.reset-x[i])/(x[i+1]-x[i]))
    if not 0<=w<=1:
        raise ArithmeticError("Reset interpolation is not convex")
    return x,qm,qp,((i,1-w),(i+1,w))


def _prepare(cells: TwoCell, rect: Rectangle) -> _GridData:
    if not isinstance(cells,TwoCell) or not isinstance(rect,Rectangle):
        raise TypeError("Expected TwoCell, Rectangle")
    cells.validate(rect)
    x1,m1,p1,r1=_axis_rates(cells.first,rect.x1min,rect.x1max,rect.n1)
    x2,m2,p2,r2=_axis_rates(cells.second,rect.x2min,rect.x2max,rect.n2)
    rate=(cells.first.discount + (m1+p1)[:,None] + (m2+p2)[None,:])
    if not np.all(np.isfinite(rate)) or not np.all(rate>0):
        raise ArithmeticError("Total generator rate invalid")
    return _GridData(x1,x2,rate,m1,p1,m2,p2,r1,r2,
                     cells.first.delay_discount,cells.second.delay_discount,
                     cells.first.discount)


def _actions(v: np.ndarray,cells:TwoCell,g:_GridData):
    first_reset=sum(w*v[k,:] for k,w in g.reset1)
    second_reset=sum(w*v[:,k] for k,w in g.reset2)
    fire1=g.x1[:,None]-cells.first.cost+g.delay1*first_reset[None,:]
    fire2=g.x2[None,:]-cells.second.cost+g.delay2*second_reset[:,None]
    return fire1,fire2


def _continuation(v: np.ndarray,g:_GridData) -> np.ndarray:
    flow=np.zeros_like(v)
    flow[1:,:] +=g.qm1[1:,None]*v[:-1,:]
    flow[:-1,:]+=g.qp1[:-1,None]*v[1:,:]
    flow[:,1:] +=g.qm2[None,1:]*v[:,:-1]
    flow[:,:-1]+=g.qp2[None,:-1]*v[:,1:]
    return flow/g.rate


def _residual(v,cells,g):
    c=_continuation(v,g)
    a,b=_actions(v,cells,g)
    bell=float(np.max(np.abs(v-np.maximum(np.maximum(c,a),b))))
    # Generator-space residual checks the discrete QVI, not continuum error.
    obstacle1=a-v
    obstacle2=b-v
    generator=g.rate*(c-v)
    gen=float(np.max(np.abs(np.maximum(np.maximum(generator,obstacle1),obstacle2))))
    return bell,gen


def _result(v,policy,it,cells,g):
    if not np.all(np.isfinite(v)):
        raise ArithmeticError("Nonfinite QVI value")
    if float(np.min(v)) < -1e-8*max(1.,float(np.max(v))):
        raise ArithmeticError("Negative option value from inadmissible policy")
    bell,gen=_residual(v,cells,g)
    return CoupledResult(g.x1,g.x2,v,policy,it,bell,gen,(g.reset1,g.reset2))


def solve_coupled_policy(cells: TwoCell,rect: Rectangle, *,max_iterations:int=120,
                         decision_tolerance:float=1e-11) -> CoupledResult:
    """Sparse policy evaluation and strict Howard improvement; fail on budgets."""
    if not (isinstance(max_iterations,int) and not isinstance(max_iterations,bool)
            and 1<=max_iterations<=2000 and math.isfinite(decision_tolerance)
            and 0<=decision_tolerance<=1e-7):
        raise ValueError("Invalid policy solver budget/tolerance")
    g=_prepare(cells,rect)
    n1,n2=len(g.x1),len(g.x2)
    n=n1*n2
    policy=np.zeros((n1,n2),dtype=np.int8)
    # Always-start-wait is an admissible zero-reward stopping policy.
    for it in range(1,max_iterations+1):
        a=lil_matrix((n,n),dtype=np.float64)
        b=np.zeros(n)
        for i in range(n1):
            for j in range(n2):
                k=i*n2+j
                action=int(policy[i,j])
                if action==0:
                    a[k,k]=g.rate[i,j]
                    if i>0: a[k,k-n2]=-g.qm1[i]
                    if i<n1-1: a[k,k+n2]=-g.qp1[i]
                    if j>0: a[k,k-1]=-g.qm2[j]
                    if j<n2-1: a[k,k+1]=-g.qp2[j]
                elif action==1:
                    a[k,k]=1.
                    for ii,w in g.reset1:
                        a[k,ii*n2+j] -= g.delay1*w
                    b[k]=g.x1[i]-cells.first.cost
                elif action==2:
                    a[k,k]=1.
                    for jj,w in g.reset2:
                        a[k,i*n2+jj] -= g.delay2*w
                    b[k]=g.x2[j]-cells.second.cost
                else:
                    raise AssertionError('Invalid internal policy')
        v=np.asarray(spsolve(a.tocsc(),b),dtype=float).reshape((n1,n2))
        if not np.all(np.isfinite(v)):
            raise ArithmeticError("Non-finite sparse policy solve")
        q0=_continuation(v,g)
        q1,q2=_actions(v,cells,g)
        current=np.choose(policy,[q0,q1,q2])
        # Keep the old action unless a new one strictly improves its value.
        best=np.argmax(np.stack((q0,q1,q2),axis=0),axis=0).astype(np.int8)
        top=np.maximum(np.maximum(q0,q1),q2)
        proposal=np.where(top>current+decision_tolerance,best,policy).astype(np.int8)
        if np.array_equal(proposal,policy):
            output=_result(v,policy,it,cells,g)
            if output.bellman_residual>max(3*decision_tolerance,1e-9)*max(1.,float(np.max(v))):
                raise ArithmeticError("Policy fixed point has unacceptably high residual")
            if output.generator_qvi_residual>1e-7*max(1.,float(np.max(v))):
                raise ArithmeticError("Generator QVI residual too high")
            return output
        policy=proposal
    raise RuntimeError("Coupled policy iteration budget exhausted")


def solve_coupled_jacobi(cells: TwoCell,rect:Rectangle,*,
                         tolerance:float=2e-10,max_iterations:int=100000) -> CoupledResult:
    """Independent value iteration (no policy selection or sparse solve)."""
    if not (math.isfinite(tolerance) and 0<tolerance<1e-3 and
            isinstance(max_iterations,int) and not isinstance(max_iterations,bool)
            and 1<=max_iterations<=500000):
        raise ValueError("Invalid Jacobi solver budget/tolerance")
    g=_prepare(cells,rect)
    v=np.zeros((len(g.x1),len(g.x2)),dtype=float)
    for it in range(1,max_iterations+1):
        q0=_continuation(v,g)
        q1,q2=_actions(v,cells,g)
        nxt=np.maximum(np.maximum(q0,q1),q2)
        diff=float(np.max(np.abs(nxt-v)))
        v=nxt
        if diff<tolerance:
            # Determine optimal policy from converged output, not previous round.
            t0=_continuation(v,g)
            t1,t2=_actions(v,cells,g)
            pol=np.argmax(np.stack((t0,t1,t2),axis=0),axis=0).astype(np.int8)
            out=_result(v,pol,it,cells,g)
            if out.bellman_residual>max(2*tolerance,1e-8):
                raise ArithmeticError("Jacobi Bellman residual above tolerance")
            return out
    raise RuntimeError("Jacobi Bellman solver budget exhausted")
