"""Stationary physical feedback branches and stability on the mass simplex."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq,minimize_scalar
import torch
from allen import gaussian
from population import BoundaryPopulation

DRIVES=(-.9,-.6,-.3,0.,.3,.6,.9)
RESTORE=(0.,.25,.65,1.5)
PANIC=(0.,.25,.65,1.5,3.,6.,12.)


class Fixed:
    def __init__(self,n,edge=1.30,samples=4097):
        self.m=BoundaryPopulation(1,1,n)
        if edge!=1.30:
            grid=torch.linspace(.015,edge,n,dtype=torch.float64)
            self.m.grid=grid
            self.m.cuts=.5*(grid[:-1]+grid[1:])
            j=int(torch.searchsorted(grid,.30))
            self.m.reset_weights.zero_()
            self.m.reset_weights[j]=(.30-grid[j-1])/(grid[j]-grid[j-1])
            self.m.reset_weights[j-1]=1.-self.m.reset_weights[j]
        self.grid=self.m.grid.numpy()
        self.rho=self.m.reset_weights.numpy()
        self.eye=np.eye(n)
        self.M=np.linspace(-15.,1.5,samples)
        self.mass=np.concatenate([self.stationary(m) for m in np.array_split(self.M,max(64,len(self.M)//12))])

    def stationary(self,mu):
        k=gaussian(self.m,np.asarray(mu))[:,:,:-1]
        lhs=self.eye-k.transpose(0,2,1)+self.rho[:,None]
        m=np.linalg.solve(lhs,np.broadcast_to(self.rho,(*lhs.shape[:1],len(self.rho)))[...,None])[:,:,0]
        if m.min() < -1e-10 or (1.-m.sum(1)).min() < -1e-10:raise ValueError("negative stationary mass")
        return m

    def steady_roots(self,v,ke,kl):
        base=self.m.prices.mu-.7*v
        P=self.m.prices.p.P0*(1+.28*v)
        with torch.no_grad():
            E,L=[a.numpy()/20 for a in self.m.priced_channels(torch.tensor(P,dtype=torch.float64))]
        def eff(m):
            avg=(m@self.grid)/m.sum(axis=-1)
            return base+ke*np.tanh(np.maximum(m@E,0))*(.30-avg)-kl*np.tanh(np.maximum(m@L,0))
        def at(mu):
            return mu-float(eff(self.stationary([mu])[0]))
        residual=self.M-eff(self.mass)
        if residual[0]>=0 or residual[-1]<=0:raise ValueError("physical drift range")
        roots=[]
        for j in np.flatnonzero(residual[:-1]*residual[1:]<=0):
            roots.append(brentq(at,self.M[j],self.M[j+1],xtol=1e-11))
        for j in np.flatnonzero((np.abs(residual[1:-1])<.02)&(np.abs(residual[1:-1])<=np.abs(residual[:-2]))&(np.abs(residual[1:-1])<=np.abs(residual[2:])) )+1:
            if residual[j-1]*residual[j+1]<=0:continue
            fit=minimize_scalar(lambda x:abs(at(x)),bounds=(self.M[j-1],self.M[j+1]),method="bounded",
                                options={"xatol":1e-12})
            if fit.fun<1e-9:roots.append(fit.x)
        unique=[]
        for r in sorted(roots):
            if not unique or r-unique[-1]>1e-6:unique.append(r)
        found=[]
        for r in unique:
            m=self.stationary([r])[0]
            delta=2e-5
            kern=gaussian(self.m,np.array([r-delta,r,r+delta]))
            k=kern[1,:,:-1];h=kern[1,:,-1]
            dk=(kern[2,:,:-1]-kern[0,:,:-1])/(2*delta)
            avg=m@self.grid/m.sum()
            eq=m@E;loss=m@L
            e=np.tanh(max(eq,0));l=np.tanh(max(loss,0))
            grad=(ke*((1-e**2)*E*(eq>0)*(.3-avg)-e*(self.grid-avg)/m.sum())
                  -kl*(1-l*l)*L*(loss>0))
            jac=k.T-self.rho[:,None]+np.outer(m@dk,grad)
            eig=np.linalg.eigvals(jac);z=eig[np.argmax(abs(eig))]
            flux=m@h
            me=np.max(abs(m@k+(1-m.sum())*self.rho-m))
            if max(me,abs(1-m.sum()-flux),abs(at(r)))>2e-9:raise ValueError("fixed-point verification")
            found.append(dict(mu=r,flux=flux,mean_distance=avg,equity=eq,loss=loss,radius=abs(z),
                              leading_eigenvalue=[z.real,z.imag],fixed_error=me))
        return dict(drive=v,equity_gain=ke,loss_gain=kl,roots=found)

    def trajectories(self,row):
        v=row["drive"];ke=row["equity_gain"];kl=row["loss_gain"]
        P=self.m.prices.p.P0*(1+.28*v)
        with torch.no_grad():E,L=[a.numpy()/20 for a in self.m.priced_channels(torch.tensor(P,dtype=torch.float64))]
        mass=np.stack([np.eye(len(self.grid))[0],self.rho,np.eye(len(self.grid))[-1]])
        report={}
        for t in range(8192):
            avg=mass@self.grid/mass.sum(-1)
            mu=self.m.prices.mu-.7*v+ke*np.tanh(np.maximum(mass@E,0))*(.3-avg)-kl*np.tanh(np.maximum(mass@L,0))
            kernel=gaussian(self.m,mu)
            out=np.einsum("di,dij->dj",mass,kernel)
            nxt=out[:,:-1]+(1-mass.sum(-1))[:,None]*self.rho
            err=abs(nxt-mass).max()
            if t+1 in (32,256,2048,8192):report[str(t+1)]=dict(flux=out[:,-1].tolist(),max_change=float(err))
            if err<2e-12:
                report["settled"]=dict(t=t+1,flux=out[:,-1].tolist());break
            mass=nxt
        return report


def main(dest):
    torch.set_num_threads(1)
    result={}
    for k in (12,24,48):
        model=Fixed(k);rs=[]
        for v in DRIVES:
            pairs=itertools.product(RESTORE,PANIC) if k==12 else [(0.,0.),(.25,.25),(.65,.65),(1.5,12.)]
            for ke,kl in pairs:
                row=model.steady_roots(v,ke,kl)
                if len(row["roots"])>1 or (v==0 and ke==kl==.65):
                    row["from_interior_reset_exterior"]=model.trajectories(row)
                rs.append(row)
        result[str(k)]=rs
        print(k,len(rs),sum(len(x["roots"]) for x in rs),max(len(x["roots"]) for x in rs),flush=True)
        tmp=dest.with_suffix(".tmp");tmp.write_text(json.dumps(result,indent=1,allow_nan=False)+"\n");tmp.replace(dest)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("dest",type=Path);a=p.parse_args();main(a.dest)
