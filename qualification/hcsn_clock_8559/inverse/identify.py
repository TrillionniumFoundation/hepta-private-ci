"""Single active-state inverse from two finance-derived observables at known model coefficients."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import numpy as np
from scipy.special import ndtr
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from he_xiong import Published
LO=.005;HI=.65;P0=61.68

class Basis:
    def __init__(self):
        self.law=Published().double()
    def price_torch(self,x,s):
        law=self.law;p=law.p;P=P0*(1.+s);E=law.equity(x,P)/100.
        def h(v):
            st=p.sigma*math.sqrt(p.m);dr=v*law.var*p.m
            return torch.exp(-(law.a-v)*x)*torch.special.ndtr((-x-dr)/st)+torch.exp(-(law.a+v)*x)*torch.special.ndtr((-x+dr)/st)
        L=(law.disc*(P/p.m-law.c/law.q)*h(law.a)+(law.c/law.q-p.alpha*law.boundary(P)/p.m)*h(law.zb))/100.
        return E,L
    def coefficients(self,x):
        x=torch.as_tensor(np.asarray(x),dtype=torch.float64);z=torch.zeros_like(x)
        with torch.no_grad():
            a,b=self.price_torch(x,z);u,v=self.price_torch(x,z+1.)
        return np.stack([a.numpy(),b.numpy()],-1),np.stack([(u-a).numpy(),(v-b).numpy()],-1)
    def equity_loss(self,x,s):
        a,b=self.coefficients(x);return a+np.asarray(s)[...,None]*b
    def hit(self,x,T):
        l=self.law;sig=l.p.sigma*math.sqrt(T);mu=l.mu
        return ndtr((-x-mu*T)/sig)+np.exp(-2.*l.a*x)*ndtr((-x+mu*T)/sig)
    def from_equity_hit(self,e,f,T):
        f=np.asarray(f);valid=(f>0)&(f<1)
        lo=np.zeros_like(f);hi=np.full_like(f,1.5)
        for _ in range(58):
            m=(lo+hi)/2;left=self.hit(m,T)>f
            lo=np.where(left,m,lo);hi=np.where(left,hi,m)
        x=(lo+hi)/2;a,b=self.coefficients(x)
        good=valid&(np.abs(b[...,0])>1e-13)
        s=np.divide(e-a[...,0],b[...,0],out=np.full_like(e,np.nan),where=good)
        return x,s,good
    def from_two_prices(self,price,grid=2049):
        # Eliminate principal algebraically and bracket all sampled sign changes on the declared active domain.
        nodes=np.linspace(LO-1e-8,HI+1e-8,grid);a,b=self.coefficients(nodes)
        e=price[:,0,None];l=price[:,1,None]
        residual=(e-a[:,0])*b[:,1]-(l-a[:,1])*b[:,0]
        r,j=np.where(residual[:,:-1]*residual[:,1:]<=0.)
        left,right=nodes[j],nodes[j+1]
        fa=residual[r,j]
        for _ in range(43):
            mid=(left+right)/2;ap,bp=self.coefficients(mid)
            f=(price[r,0]-ap[:,0])*bp[:,1]-(price[r,1]-ap[:,1])*bp[:,0]
            choose=fa*f>0
            left=np.where(choose,mid,left);fa=np.where(choose,f,fa);right=np.where(choose,right,mid)
        x=(left+right)/2;ap,bp=self.coefficients(x);s=(price[r,0]-ap[:,0])/bp[:,0]
        ok=np.isfinite(s)&(s>=-.30-1e-8)&(s<=.30+1e-8)
        return r[ok],x[ok],s[ok]

def quantize(values,kind,minmax):
    if kind=='double':return values.copy()
    if kind=='float32':return values.astype(np.float32).astype(float)
    if kind=='bfloat16':return torch.as_tensor(values).bfloat16().double().numpy()
    low,high=minmax
    return low+np.rint(255.*np.clip((values-low)/(high-low),0.,1.))*(high-low)/255.
def quantiles(v):
    v=np.ravel(v);v=v[np.isfinite(v)]
    return np.quantile(v,[.5,.95,1.]).tolist() if len(v) else None
def run(output):
    torch.set_num_threads(1);np.seterr(over='warn')
    basis=Basis();rng=np.random.default_rng(290114);n=2048
    x=rng.uniform(LO,HI,n);s=rng.uniform(-.3,.3,n)
    actual=basis.equity_loss(x,s)
    grid=np.linspace(LO,HI,2049);ends=np.vstack([basis.equity_loss(grid,np.full(len(grid),r)) for r in (-.3,.3)])
    bounds=np.array([ends.min(0),ends.max(0)])
    def qprice(v,k,i):return quantize(v,k,(bounds[0,i],bounds[1,i]))
    panels=[];monetary=[]
    for T in (.05,.25,1.):
        f=basis.hit(x,T);a,b=basis.coefficients(x)
        dx=1e-5;pe=(basis.equity_loss(x+dx,s)-basis.equity_loss(x-dx,s))/(2*dx);dq=(basis.hit(x+dx,T)-basis.hit(x-dx,T))/(2*dx)
        J=np.zeros((n,2,2));J[:,0,0]=pe[:,0];J[:,0,1]=b[:,0];J[:,1,0]=dq
        cond=np.linalg.cond(J)
        for precision in ('double','float32','bfloat16','uniform8'):
            e=qprice(actual[:,0],precision,0);observed=quantize(f,precision,(0.,1.));xc,sc,ok=basis.from_equity_hit(e,observed,T)
            physically=ok&(xc>=LO-1e-10)&(xc<=HI+1e-10)&(sc>=-.3-1e-9)&(sc<=.3+1e-9)
            panels.append(dict(T=T,precision=precision,nondegenerate=int(ok.sum()),within_physical_box=int(physically.sum()),saturated_q=int(np.sum((observed==0)|(observed==1))),
                 log_margin_error=quantiles(abs(xc[ok]-x[ok])),principal_relative_to_nominal_error=quantiles(abs(sc[ok]-s[ok])),
                 scaled_condition_number=quantiles(cond),exact_channel_replay_error=quantiles(abs(basis.hit(xc[ok],T)-observed[ok]))))
    for precision in ('double','float32','bfloat16','uniform8'):
        price=np.stack([qprice(actual[:,i],precision,i) for i in (0,1)],-1)
        st=time.perf_counter();r,xc,sc=basis.from_two_prices(price)
        mult=np.bincount(r,minlength=n);unique=mult[r]==1
        monetary.append(dict(precision=precision,zero=int(sum(mult==0)),one=int(sum(mult==1)),multiple=int(sum(mult>1)),max_candidates=int(mult.max()),wall_s=time.perf_counter()-st,
                 unique_state_log_margin_error=quantiles(abs(xc[unique]-x[r[unique]])),unique_principal_relative_to_nominal_error=quantiles(abs(sc[unique]-s[r[unique]])),
                 interpretation='Counts include all sign-changing sampled brackets; isolated even-multiplicity roots could be missed.'))
    special=[]
    for xx in (1e-7,1e-5,1e-3,.005,.05,.1,.30,.65,.90,1.2):
        a,b=basis.coefficients(np.array([xx]))
        for T in (.05,.25,1.):
            q=basis.hit(np.array([xx]),T)
            published=float(basis.law.passage(torch.tensor(xx,dtype=torch.float64),T))
            special.append(dict(x=xx,T=T,E_per_unit_relative_principal=float(b[0,0]),stable_probability=float(q[0]),original_torch_probability=published))
    output.write_text(json.dumps(dict(points=n,equity_hit=panels,equity_monetary_loss=monetary,
        precision_bounds_E_L=bounds.tolist(),stress=special,quantiles=['median','95%','maximum']),indent=1)+'\n')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();run(a.out)
