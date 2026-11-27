"""Research-only asynchronous multi-stage Erlang refractory CTMC/QVI.

An additive finite-state model building on asynchronous_qvi, NOT a direct
He-Xiong equation. For each cell, the refractory duration is the sum of k
independent exponential(k/tau) stages. Mean=tau, variance=tau^2/k, and
E(exp(-rho T))=(1+rho*tau/k)^(-k) -> exp(-rho*tau). The second active cell
continues to evolve and fire throughout each of the other cell's stages.

The k=1 model coincides exactly with asynchronous_qvi (exponential delay).
The k->infinity limit approximates deterministic independent refractory;
this finite-grid result is NOT a global timed-SDE convergence theorem.

Model and state machine details, numerical evidence, and DENY_ALL policy are
in ERLANG_ASYNC_QVI_GATE.md. No product authority or native runtime changes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from .coupled_qvi import Rectangle, TwoCell, _axis_rates


@dataclass(frozen=True)
class ErlangResult:
    x1: np.ndarray
    x2: np.ndarray
    phases: tuple[int,int]
    values: np.ndarray
    policy: np.ndarray
    iterations: int
    bellman_residual: float
    qvi_residual: float
    stage_rates: tuple[float,float]

    def at_active(self,a:float,b:float)->float:
        if not all(math.isfinite(z) for z in (a,b)) or not (
            self.x1[0]<=a<=self.x1[-1] and self.x2[0]<=b<=self.x2[-1]):
            raise ValueError("Invalid active query")
        i=min(int(np.searchsorted(self.x1,a,side='right')-1),len(self.x1)-2)
        j=min(int(np.searchsorted(self.x2,b,side='right')-1),len(self.x2)-2)
        s=(a-self.x1[i])/(self.x1[i+1]-self.x1[i]); t=(b-self.x2[j])/(self.x2[j+1]-self.x2[j])
        v=self.values
        return float((1-s)*(1-t)*v[i,j]+s*(1-t)*v[i+1,j]+(1-s)*t*v[i,j+1]+s*t*v[i+1,j+1])


@dataclass(frozen=True)
class _Grid:
    x1:np.ndarray
    x2:np.ndarray
    qm1:np.ndarray
    qp1:np.ndarray
    qm2:np.ndarray
    qp2:np.ndarray
    r1:tuple
    r2:tuple
    k1:int
    k2:int
    lam1:float
    lam2:float
    rho:float
    rate:np.ndarray


def _prepare(cells:TwoCell,rect:Rectangle,phases:tuple[int,int])->_Grid:
    if not isinstance(cells,TwoCell) or not isinstance(rect,Rectangle):
        raise TypeError("Requires TwoCell, Rectangle")
    if not (type(phases) is tuple and len(phases)==2 and
            all(type(k) is int and 1<=k<=32 for k in phases)):
        raise ValueError("Refractory phase counts must be tuple of integers in [1,32]")
    cells.validate(rect)
    k1,k2=phases
    if (rect.n1+k1)*(rect.n2+k2)>6400:
        raise ValueError("Finite-state budget exceeded")
    x1,qm1,qp1,r1=_axis_rates(cells.first,rect.x1min,rect.x1max,rect.n1)
    x2,qm2,qp2,r2=_axis_rates(cells.second,rect.x2min,rect.x2max,rect.n2)
    lam1=k1/cells.first.refractory
    lam2=k2/cells.second.refractory
    if not all(math.isfinite(z) and z>0. for z in (lam1,lam2)):
        raise ArithmeticError("Unrepresentable Erlang rate")
    rho=cells.first.discount
    q1=np.concatenate((qm1+qp1,np.full(k1,lam1)))
    q2=np.concatenate((qm2+qp2,np.full(k2,lam2)))
    total=q1[:,None]+q2[None,:]
    rate=rho+total
    if not np.all(np.isfinite(rate)) or not np.all(rate>total):
        raise ArithmeticError("Nonfinite CTMC rate or loss of discount in fp64")
    return _Grid(x1,x2,qm1,qp1,qm2,qp2,r1,r2,k1,k2,lam1,lam2,rho,rate)


def _wait(v:np.ndarray,g:_Grid)->np.ndarray:
    n1,n2=len(g.x1),len(g.x2)
    flow=np.zeros_like(v)
    flow[1:n1,:]+=g.qm1[1:,None]*v[:n1-1,:]
    flow[:n1-1,:]+=g.qp1[:n1-1,None]*v[1:n1,:]
    flow[n1,:]+=g.lam1*sum(w*v[i,:] for i,w in g.r1)
    for stage in range(1,g.k1):
        flow[n1+stage,:]+=g.lam1*v[n1+stage-1,:]
    flow[:,1:n2]+=g.qm2[None,1:]*v[:,:n2-1]
    flow[:,:n2-1]+=g.qp2[None,:n2-1]*v[:,1:n2]
    flow[:,n2]+=g.lam2*sum(w*v[:,j] for j,w in g.r2)
    for stage in range(1,g.k2):
        flow[:,n2+stage]+=g.lam2*v[:,n2+stage-1]
    return flow/g.rate


def _actions(v:np.ndarray,cells:TwoCell,g:_Grid)->tuple[np.ndarray,np.ndarray]:
    n1,n2=len(g.x1),len(g.x2)
    a=np.full_like(v,-math.inf)
    b=np.full_like(v,-math.inf)
    a[:n1,:]=g.x1[:,None]-cells.first.cost+v[n1+g.k1-1,:][None,:]
    b[:,:n2]=g.x2[None,:]-cells.second.cost+v[:,n2+g.k2-1][:,None]
    return a,b


def _qvi(v,cells,g):
    q0=_wait(v,g);q1,q2=_actions(v,cells,g)
    return (float(np.max(np.abs(v-np.maximum.reduce((q0,q1,q2))))),
            float(np.max(np.abs(np.maximum.reduce((g.rate*(q0-v),q1-v,q2-v))))))


def _result(v,p,it,cells,g)->ErlangResult:
    if not np.all(np.isfinite(v)) or float(np.min(v))<-1e-8*max(1.,float(np.max(v))):
        raise ArithmeticError("Nonfinite or negative discounted option value")
    br,qr=_qvi(v,cells,g)
    return ErlangResult(g.x1,g.x2,(g.k1,g.k2),v,p,it,br,qr,(g.lam1,g.lam2))


def _edges(i:int,j:int,g:_Grid):
    n1,n2=len(g.x1),len(g.x2)
    if i<n1:
        if i>0:yield i-1,j,float(g.qm1[i])
        if i<n1-1:yield i+1,j,float(g.qp1[i])
    elif i==n1:
        for kk,w in g.r1:yield kk,j,g.lam1*w
    else:
        yield i-1,j,g.lam1
    if j<n2:
        if j>0:yield i,j-1,float(g.qm2[j])
        if j<n2-1:yield i,j+1,float(g.qp2[j])
    elif j==n2:
        for kk,w in g.r2:yield i,kk,g.lam2*w
    else:
        yield i,j-1,g.lam2


def solve_erlang_policy(cells:TwoCell,rect:Rectangle,phases:tuple[int,int]=(2,2),*,
                        max_iterations:int=160,decision_tolerance:float=1e-11)->ErlangResult:
    if not (type(max_iterations) is int and 1<=max_iterations<=1000 and
            math.isfinite(decision_tolerance) and 0<=decision_tolerance<=1e-7):
        raise ValueError("Invalid policy budget/tolerance")
    g=_prepare(cells,rect,phases)
    n1,n2=len(g.x1),len(g.x2); sz1=n1+g.k1;sz2=n2+g.k2
    policy=np.zeros((sz1,sz2),dtype=np.int8)
    for iteration in range(1,max_iterations+1):
        mat=lil_matrix((sz1*sz2,sz1*sz2),dtype=np.float64)
        b=np.zeros(sz1*sz2)
        for i in range(sz1):
            for j in range(sz2):
                row=i*sz2+j
                act=int(policy[i,j])
                if act==0:
                    mat[row,row]=g.rate[i,j]
                    for ii,jj,rate in _edges(i,j,g):
                        mat[row,ii*sz2+jj]-=rate
                elif act==1 and i<n1:
                    mat[row,row]=1.
                    mat[row,(n1+g.k1-1)*sz2+j]=-1.
                    b[row]=g.x1[i]-cells.first.cost
                elif act==2 and j<n2:
                    mat[row,row]=1.
                    mat[row,i*sz2+(n2+g.k2-1)]=-1.
                    b[row]=g.x2[j]-cells.second.cost
                else:
                    raise ArithmeticError("Ineligible FIRE")
        v=np.asarray(spsolve(mat.tocsc(),b),dtype=float).reshape((sz1,sz2))
        if not np.all(np.isfinite(v)):
            raise ArithmeticError("Policy system nonfinite")
        q0=_wait(v,g);q1,q2=_actions(v,cells,g)
        current=np.choose(policy,[q0,q1,q2]);best=np.maximum.reduce((q0,q1,q2))
        propose=np.argmax(np.stack((q0,q1,q2)),axis=0).astype(np.int8)
        propose=np.where(best>current+decision_tolerance,propose,policy).astype(np.int8)
        if np.array_equal(propose,policy):
            out=_result(v,policy,iteration,cells,g)
            scale=max(1.,float(np.max(v)))
            if out.bellman_residual>max(3*decision_tolerance,1e-9)*scale or out.qvi_residual>1e-7*scale:
                raise ArithmeticError("Policy QVI is not satisfied")
            return out
        policy=propose
    raise RuntimeError("Erlang policy-iteration budget exhausted")


def solve_erlang_jacobi(cells:TwoCell,rect:Rectangle,phases:tuple[int,int]=(2,2),*,
                        tolerance:float=2e-10,max_iterations:int=100000)->ErlangResult:
    if not (math.isfinite(tolerance) and 0<tolerance<1e-3 and
            type(max_iterations) is int and 1<=max_iterations<=500000):
        raise ValueError("Invalid Jacobi budget/tolerance")
    g=_prepare(cells,rect,phases)
    v=np.zeros((len(g.x1)+g.k1,len(g.x2)+g.k2))
    for iteration in range(1,max_iterations+1):
        q0=_wait(v,g);q1,q2=_actions(v,cells,g)
        nxt=np.maximum.reduce((q0,q1,q2))
        error=float(np.max(np.abs(nxt-v)))
        v=nxt
        if error<tolerance:
            q0=_wait(v,g);q1,q2=_actions(v,cells,g)
            policy=np.argmax(np.stack((q0,q1,q2)),axis=0).astype(np.int8)
            out=_result(v,policy,iteration,cells,g)
            if out.bellman_residual>max(3*tolerance,1e-8):
                raise ArithmeticError("Jacobi residual exceeds tolerance")
            return out
    raise RuntimeError("Erlang Jacobi budget exhausted")


def erlang_discount(discount:float,mean:float,phases:int)->float:
    """Exact closed-form Laplace transform of k-stage Erlang recovery time."""
    if not (math.isfinite(discount) and discount>0. and
            math.isfinite(mean) and mean>0. and
            type(phases) is int and 1<=phases<=1_000_000):
        raise ValueError("Invalid Laplace transform parameter")
    z=discount*mean/phases
    if not math.isfinite(z):
        return 0.
    return math.exp(-phases*math.log1p(z))
