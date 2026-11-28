"""Stationary switching-equilibrium candidate for recurrent regime-dependent credit."""
from dataclasses import dataclass
from pathlib import Path
import sys
import numpy as np
from scipy.linalg import expm
from scipy.optimize import root
from scipy.sparse import coo_matrix, eye, diags
from scipy.sparse.linalg import splu, spsolve

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"hcsn_sustained_20261128"/"resolvent"))
from closed_form import Contract


@dataclass
class Policy:
    barriers: np.ndarray
    levels: np.ndarray
    equity: np.ndarray
    debt: np.ndarray
    loss: np.ndarray
    first_hit: np.ndarray
    smooth_fit: np.ndarray
    stop_residual: np.ndarray


class Economy:
    def __init__(self,*,rates=(.7,.35),premia=(.01,.05),n=256,substeps=160,length=3.5,p=Contract()):
        self.rates=np.array(rates,dtype=float)
        self.premia=np.array(premia,dtype=float)
        self.n=n
        self.m=substeps
        self.length=length
        self.p=p
        self.dx=length/n
        self.mu=p.r-p.payout-.5*p.sigma**2
        self.diff=p.sigma**2/2
        self.liabs=np.array([[-rates[0],rates[0]],[rates[1],-rates[1]]])
        self.q=p.r+self.premia
        self.c=p.coupon/p.maturity
        self.par=p.principal/p.maturity
        self.safe=self.safe_prices(np.linspace(0,p.maturity,2*substeps+1))
        self.equity_top=np.linalg.solve(p.r*np.eye(2)-self.liabs,
                                        self.safe[-1]-self.par-(1-p.tax)*p.coupon)

    def safe_prices(self,times):
        M=self.liabs-np.diag(self.q)
        # Stable 2x2 forcing with the nonsingular discounted generator.
        steady=-np.linalg.solve(M,np.full(2,self.c))
        if len(times)>1 and np.allclose(np.diff(times),times[1]-times[0]):
            step=expm(M*(times[1]-times[0]))
            z=expm(M*times[0])@(np.full(2,self.par)-steady)
            rows=[]
            for _ in times:
                rows.append(steady+z)
                z=step@z
            return np.array(rows)
        return np.array([steady+expm(M*t)@(np.full(2,self.par)-steady) for t in times])

    def operator(self,wall):
        n=self.n; nint=n-1; size=2*nint; dx=self.dx
        points=wall[:,None]*np.exp(np.arange(n+1)[None,:]*dx)
        left=self.diff/dx**2-self.mu/(2*dx)
        right=self.diff/dx**2+self.mu/(2*dx)
        rr=[];cc=[];vv=[]
        # For a row whose stencil exits either continuation interval, store its
        # boundary source exactly; the recovery amount depends on actual V.
        low=np.zeros((size,2)); up=np.zeros((size,2))
        low_assets=np.zeros(size); up_assets=np.zeros(size)
        def boundary(row,state,coef,V,bottom):
            (low if bottom else up)[row,state]+=coef
            (low_assets if bottom else up_assets)[row]+=coef*V
        for s in (0,1):
            other=1-s
            for i in range(1,n):
                row=s*nint+i-1
                def append(col,w):
                    rr.append(row);cc.append(col);vv.append(w)
                append(row,-left-right-self.rates[s])
                if i>1:append(row-1,left)
                else:boundary(row,s,left,points[s,0],True)
                if i<n-1:append(row+1,right)
                else:boundary(row,s,right,points[s,-1],False)
                at=i+np.log(wall[s]/wall[other])/dx
                coef=self.rates[s]; V=points[s,i]
                if at<=0:
                    boundary(row,other,coef,V,True)
                elif at>=n:
                    boundary(row,other,coef,V,False)
                else:
                    j=int(np.floor(at)); weight=at-j
                    for idx,w in ((j,1-weight),(j+1,weight)):
                        if idx==0:boundary(row,other,coef*w,points[other,0],True)
                        elif idx==n:boundary(row,other,coef*w,points[other,-1],False)
                        else:append(other*nint+idx-1,coef*w)
        A=coo_matrix((vv,(rr,cc)),shape=(size,size)).tocsc()
        return points,A,low,up,low_assets,up_assets

    def parabolic(self,A,initial,constant,top_weights,top_values):
        m=self.m; dt=self.p.maturity/m; I=eye(A.shape[0],format="csc")
        # Two fully implicit half steps smooth out the corner at maturity before CN.
        factor=splu(I-A*(dt/2))
        z=initial.copy()
        src=lambda j:constant+top_weights@top_values[j]
        for j in (1,2): z=factor.solve(z+dt/2*src(j))
        right=I+A*(dt/2)
        for j in range(2,m+1):
            z=factor.solve(right@z+dt/2*(src(2*j-2)+src(2*j)))
        return z

    def policy(self,wall,with_risk=True):
        p=self.p
        grid,A,low,up,vl,vu=self.operator(wall)
        nint=self.n-1
        assets=grid[:,1:-1].ravel()
        q=np.repeat(self.q,nint)
        cost=p.recovery/p.maturity
        bond_op=A-diags(q,format="csc")
        bond=self.parabolic(bond_op,np.full(len(assets),self.par),self.c+cost*vl,up,self.safe)
        eq_rhs=p.payout*assets-(1-p.tax)*p.coupon+bond-self.par+vu+up@self.equity_top
        eq=spsolve(p.r*eye(len(assets),format="csc")-A,eq_rhs)
        equity=np.c_[np.zeros(2),eq.reshape(2,-1),grid[:,-1]+self.equity_top]
        bond=np.c_[cost*wall,bond.reshape(2,-1),self.safe[-1]]
        risk=None
        if with_risk:
            hit=self.parabolic(A,np.zeros(len(assets)),low.sum(1),np.zeros_like(up),
                               np.zeros((2*self.m+1,2)))
            risk=np.c_[np.ones(2),hit.reshape(2,-1),np.zeros(2)]
        slopes=(4*equity[:,1]-equity[:,2])/(2*self.dx)
        stop=[]
        for s in (0,1):
            probes=np.geomspace(1e-3,wall[s],1001)
            next_eq=np.interp(np.log(probes),np.log(grid[1-s]),equity[1-s],left=0.)
            gain=(p.payout*probes-(1-p.tax)*p.coupon+cost*probes-self.par
                  +self.rates[s]*next_eq)
            stop.append(np.max(gain))
        return Policy(wall.copy(),grid,equity,bond,self.safe[-1,:,None]-bond,risk,slopes,np.array(stop))

    def equilibrium(self,start=(72.,75.)):
        def fit(w):
            return self.policy(np.exp(w),with_risk=False).smooth_fit
        out=root(fit,np.log(start),method="hybr",options={"xtol":1e-10})
        result=self.policy(np.exp(out.x))
        if not out.success or abs(result.smooth_fit).max()>5e-7:
            raise RuntimeError((out.message,result.smooth_fit))
        return result


def probe(policy,attr,V):
    return np.stack([np.interp(np.log(V),np.log(grid),a)
                     for grid,a in zip(policy.levels,getattr(policy,attr))])
