"""Independent-refractory, two-cell continuous-time Markov regenerative QVI.

RESEARCH ONLY / DENY_ALL. This does NOT implement the He-Xiong corporate
finance equilibrium, true SDE strong solutions, an exact free-boundary
solution, a deterministic refractory, or a production spiking kernel.

The existing ``coupled_qvi`` freezes BOTH Brownian coordinates for a fixed
interval whenever EITHER neuron fires. This alternative finite-state model
allows the non-firing cell to evolve and to fire while the first is refractory.
Each refractory time is *exponential*, with mean Stop.refractory (NOT a
fixed delay). A fired cell stays at the reset coordinate while refractory;
on recovery it samples the two nearest active grid nodes using convex
weights. The other active cell moves under a reflected finite-state CTMC.

The discrete state is (i,j), where the last index on each axis means the
corresponding neuron is refractory. At most one instantaneous FIRE may be
selected at once; a refractory neuron cannot FIRE. Any chosen FIRE moves
immediately into its refractory state (no discount on that zero-time jump),
earns x_i - K_i, and leaves the OTHER neuron unchanged. WAIT advances
continuous time under the CTMC's generator, including independent recovery
clocks. The infinite-horizon discounted Bellman obstacle problem is

 max{(Q-rho I)V, x1-K1+V(R1,j)-V, x2-K2+V(i,R2)-V}=0

with ineligible FIRE branches absent. There are no instantaneous cycles:
each immediate FIRE increments the number of refractory cells; any return
to active status requires discounted positive-time WAIT. For rho>0, positive
recovery hazard and finite rates, policy solves are proper in exact arithmetic.
We also reject cases where roundoff erases the discount in a WAIT row.

Limits: artificial blocked-jump finite rectangle, off-grid reset
interpolation, no continuum error theorem, no exact deterministic hold,
no multi-cell scalability claim. All results remain research-only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from .coupled_qvi import Rectangle, TwoCell, _axis_rates


@dataclass(frozen=True)
class AsynchronousResult:
    x1: np.ndarray
    x2: np.ndarray
    values: np.ndarray   # (n1+1,n2+1), final index = refractory
    policy: np.ndarray   # 0 WAIT, 1 FIRE1, 2 FIRE2
    iterations: int
    bellman_residual: float
    qvi_residual: float
    recovery_rates: tuple[float, float]

    def at_active(self, a: float, b: float) -> float:
        """Piecewise-bilinear query *only* when both cells are active."""
        if not all(math.isfinite(z) for z in (a, b)) or not (
            self.x1[0] <= a <= self.x1[-1] and
            self.x2[0] <= b <= self.x2[-1]
        ):
            raise ValueError("Nonfinite or off-grid query")
        i = min(int(np.searchsorted(self.x1, a, side="right")-1), len(self.x1)-2)
        j = min(int(np.searchsorted(self.x2, b, side="right")-1), len(self.x2)-2)
        t = (a-self.x1[i])/(self.x1[i+1]-self.x1[i])
        u = (b-self.x2[j])/(self.x2[j+1]-self.x2[j])
        v = self.values
        return float((1-t)*(1-u)*v[i,j]+t*(1-u)*v[i+1,j]
                     +(1-t)*u*v[i,j+1]+t*u*v[i+1,j+1])


@dataclass(frozen=True)
class _Grid:
    x1: np.ndarray
    x2: np.ndarray
    qm1: np.ndarray
    qp1: np.ndarray
    qm2: np.ndarray
    qp2: np.ndarray
    r1: tuple[tuple[int,float], ...]
    r2: tuple[tuple[int,float], ...]
    lam1: float
    lam2: float
    rho: float
    denominators: np.ndarray


def _prepare(cells: TwoCell, rect: Rectangle) -> _Grid:
    if not isinstance(cells,TwoCell) or not isinstance(rect,Rectangle):
        raise TypeError("Expected TwoCell and Rectangle")
    cells.validate(rect)
    x1,qm1,qp1,r1 = _axis_rates(cells.first,rect.x1min,rect.x1max,rect.n1)
    x2,qm2,qp2,r2 = _axis_rates(cells.second,rect.x2min,rect.x2max,rect.n2)
    lam1 = 1. / cells.first.refractory
    lam2 = 1. / cells.second.refractory
    if not all(math.isfinite(q) and q>0. for q in (lam1,lam2)):
        raise ArithmeticError("Invalid exponential recovery hazard")
    rho = cells.first.discount
    q1 = np.append(qm1+qp1,lam1)
    q2 = np.append(qm2+qp2,lam2)
    total = q1[:,None]+q2[None,:]
    denom = rho+total
    if (not np.all(np.isfinite(denom)) or
        not np.all(denom > total) or
        not np.all(np.isfinite(total))):
        raise ArithmeticError("Roundoff erased discount or generator rate overflow")
    return _Grid(x1,x2,qm1,qp1,qm2,qp2,r1,r2,lam1,lam2,rho,denom)


def _wait(v: np.ndarray,g: _Grid) -> np.ndarray:
    """Jacobi WAIT branch (vectorized, independent of sparse policy assembly)."""
    n1,n2=len(g.x1),len(g.x2)
    flow=np.zeros_like(v)
    flow[1:n1,:]+=g.qm1[1:,None]*v[:n1-1,:]
    flow[:n1-1,:]+=g.qp1[:n1-1,None]*v[1:n1,:]
    flow[n1,:]+=g.lam1*sum(w*v[k,:] for k,w in g.r1)
    flow[:,1:n2]+=g.qm2[None,1:]*v[:,:n2-1]
    flow[:,:n2-1]+=g.qp2[None,:n2-1]*v[:,1:n2]
    flow[:,n2]+=g.lam2*sum(w*v[:,k] for k,w in g.r2)
    return flow/g.denominators


def _actions(v: np.ndarray,cells: TwoCell,g:_Grid) -> tuple[np.ndarray,np.ndarray]:
    n1,n2=len(g.x1),len(g.x2)
    a1=np.full_like(v,-math.inf)
    a2=np.full_like(v,-math.inf)
    a1[:n1,:]=g.x1[:,None]-cells.first.cost+v[n1,:][None,:]
    a2[:,:n2]=g.x2[None,:]-cells.second.cost+v[:,n2][:,None]
    return a1,a2


def _residual(v:np.ndarray,cells:TwoCell,g:_Grid) -> tuple[float,float]:
    c=_wait(v,g)
    f1,f2=_actions(v,cells,g)
    br=float(np.max(np.abs(v-np.maximum.reduce((c,f1,f2)))))
    generator=g.denominators*(c-v)
    qr=float(np.max(np.abs(np.maximum.reduce((generator,f1-v,f2-v)))))
    return br,qr


def _result(v:np.ndarray,policy:np.ndarray,iterations:int,cells:TwoCell,g:_Grid):
    if not np.all(np.isfinite(v)):
        raise ArithmeticError("Nonfinite asynchronous QVI value")
    if float(np.min(v))<-1e-8*max(1.,float(np.max(v))):
        raise ArithmeticError("Option value is negative despite wait-forever")
    br,qr=_residual(v,cells,g)
    return AsynchronousResult(g.x1,g.x2,v,policy,iterations,br,qr,(g.lam1,g.lam2))


def _wait_edges(i:int,j:int,g:_Grid):
    """Sparse policy evaluator's explicit CTMC generator jump list."""
    n1,n2=len(g.x1),len(g.x2)
    if i<n1:
        if i>0: yield (i-1,j,float(g.qm1[i]))
        if i<n1-1: yield (i+1,j,float(g.qp1[i]))
    else:
        for k,w in g.r1:
            yield (k,j,g.lam1*w)
    if j<n2:
        if j>0: yield (i,j-1,float(g.qm2[j]))
        if j<n2-1: yield (i,j+1,float(g.qp2[j]))
    else:
        for k,w in g.r2:
            yield (i,k,g.lam2*w)


def solve_asynchronous_policy(cells: TwoCell,rect:Rectangle,*,max_iterations:int=120,
                              decision_tolerance:float=1e-11)->AsynchronousResult:
    """Monotone Howard improvement with sparse exact policy evaluation."""
    if not (type(max_iterations) is int and 1<=max_iterations<=1000 and
            math.isfinite(decision_tolerance) and 0<=decision_tolerance<=1e-7):
        raise ValueError("Invalid policy budget or tolerance")
    g=_prepare(cells,rect)
    n1,n2=len(g.x1),len(g.x2)
    dims=(n1+1,n2+1); size=(n1+1)*(n2+1)
    policy=np.zeros(dims,dtype=np.int8)
    for iteration in range(1,max_iterations+1):
        mat=lil_matrix((size,size),dtype=np.float64)
        rewards=np.zeros(size,dtype=np.float64)
        for i in range(n1+1):
            for j in range(n2+1):
                k=i*(n2+1)+j
                action=int(policy[i,j])
                if action==0:
                    mat[k,k]=g.denominators[i,j]
                    for ii,jj,q in _wait_edges(i,j,g):
                        mat[k,ii*(n2+1)+jj] -= q
                elif action==1 and i<n1:
                    mat[k,k]=1.
                    mat[k,n1*(n2+1)+j]=-1.
                    rewards[k]=g.x1[i]-cells.first.cost
                elif action==2 and j<n2:
                    mat[k,k]=1.
                    mat[k,i*(n2+1)+n2]=-1.
                    rewards[k]=g.x2[j]-cells.second.cost
                else:
                    raise ArithmeticError("Ineligible FIRE in internal policy")
        v=np.asarray(spsolve(mat.tocsc(),rewards),dtype=np.float64).reshape(dims)
        if not np.all(np.isfinite(v)):
            raise ArithmeticError("Nonfinite sparse policy evaluation")
        q0=_wait(v,g)
        q1,q2=_actions(v,cells,g)
        old=np.choose(policy,[q0,q1,q2])
        proposal=np.argmax(np.stack((q0,q1,q2)),axis=0).astype(np.int8)
        best=np.maximum.reduce((q0,q1,q2))
        proposal=np.where(best>old+decision_tolerance,proposal,policy).astype(np.int8)
        if np.array_equal(proposal,policy):
            out=_result(v,policy,iteration,cells,g)
            scale=max(1.,float(np.max(v)))
            if out.bellman_residual>max(3*decision_tolerance,1e-9)*scale or out.qvi_residual>1e-7*scale:
                raise ArithmeticError("Policy stopped without satisfying QVI")
            return out
        policy=proposal
    raise RuntimeError("Asynchronous policy iteration budget exhausted")


def solve_asynchronous_jacobi(cells:TwoCell,rect:Rectangle,*,
                              tolerance:float=2e-10,max_iterations:int=100000)->AsynchronousResult:
    """Jacobi fixed point; no linear system, sparsity graph, or policy evaluation."""
    if not (math.isfinite(tolerance) and 0<tolerance<1e-3 and
            type(max_iterations) is int and 1<=max_iterations<=500000):
        raise ValueError("Invalid Jacobi budget or tolerance")
    g=_prepare(cells,rect)
    v=np.zeros((len(g.x1)+1,len(g.x2)+1),dtype=np.float64)
    for iteration in range(1,max_iterations+1):
        c=_wait(v,g)
        a,b=_actions(v,cells,g)
        nxt=np.maximum.reduce((c,a,b))
        delta=float(np.max(np.abs(nxt-v)))
        v=nxt
        if delta<tolerance:
            c=_wait(v,g)
            a,b=_actions(v,cells,g)
            p=np.argmax(np.stack((c,a,b)),axis=0).astype(np.int8)
            out=_result(v,p,iteration,cells,g)
            if out.bellman_residual>max(3*tolerance,1e-8):
                raise ArithmeticError("Jacobi iterate has excessive Bellman residual")
            return out
    raise RuntimeError("Asynchronous Jacobi iteration budget exhausted")
