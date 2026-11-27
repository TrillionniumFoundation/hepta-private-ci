"""Near-one-second expected count under the literal six-bin frozen-drifts regenerative core."""
import math
import numpy as np
from scipy.special import lambertw
from scipy.linalg import expm
from scipy.interpolate import RegularGridInterpolator
bins,stages=6,3;sig=.55;rho=.3;g=.8;maintenance=.25;cost=.15;absolute=1.2;tau=.2;extent=2.;h=extent/bins
edges=np.arange(bins+1)*h;centers=(edges[:-1]+edges[1:])/2
def bound(mu):
    root=math.sqrt(mu*mu+2*rho*sig**2)
    k=(mu+root)/sig**2 if mu>=0 else 2*rho/(root-mu)
    eta=(1+rho*tau/stages)**(-stages)
    d=(1-eta)*(absolute+mu/rho-maintenance/g)+cost*rho/g
    v=1+k*d;u=v+lambertw(-eta*math.exp(-v)).real
    return absolute-u/k
b0=bound(-.2)
def deposit(m):
    a=np.clip(1-np.abs(m-centers)/h,0,1)
    if abs(a.sum()-1)>1e-12:raise ValueError("reset outside interior")
    return a
def initialize(b):
    idx=np.arange(bins+1);cdf=np.clip((b-b0)/h+idx[None,:]-idx[:-1,None],0,1)
    old=deposit(absolute-b0);p=np.zeros(bins+stages);p[:bins]=old@(cdf[:,1:]-cdf[:,:-1]);p[bins-1]+=old@(1-cdf[:,-1])
    jump=old@cdf[:,0];p[bins]=jump
    assert abs(p.sum()-1)<1e-12
    return p,jump
def matrices(mu,mode):
    b=bound(mu) if mode=='qvi' else b0
    p,jump=initialize(b)
    df=sig**2/(2*h*h);left=np.full(bins,max(-mu,0)/h+df);right=np.full(bins,max(mu,0)/h+df)
    left[0]+=df;right[-1]+=df
    a=np.zeros((bins+stages,bins+stages));event=np.zeros(bins+stages);event[0]=left[0]
    for i in range(bins):
        if i>0:a[i,i-1]=left[i]
        if i<bins-1:a[i,i+1]=right[i]
    a[0,bins]=left[0]
    for k in range(stages-1):a[bins+k,bins+k+1]=stages/tau
    a[-1,:bins]=stages/tau*deposit(absolute-b);np.fill_diagonal(a,-a.sum(1));assert np.abs(a.sum(1)).max()<1e-12
    return a,event,p,jump
def direct(mu,t,mode):
    q,e,p,jump=matrices(mu,mode);aug=np.pad(q,((0,1),(0,1)));aug[:-1,-1]=e
    return jump+p@expm(aug*t)[:-1,-1]
def curve(mu,times,mode):
    q,e,p,jump=matrices(mu,mode);N=len(q)
    mat=q.T.copy();mat[-1]=1;rhs=np.zeros(N);rhs[-1]=1;pi=np.linalg.solve(mat,rhs);r=pi@e
    system=q.copy();system[-1]=pi;rhs=e-r;rhs[-1]=0;v=np.linalg.solve(system,rhs)
    eig,basis=np.linalg.eig(q);coeff=np.linalg.solve(basis,v)*(p@basis);transient=np.exp(np.outer(times,eig))@coeff
    assert abs(transient.imag).max()<1e-7
    return jump+r*times+transient.real-p@v
def build():
    mus=np.linspace(-.35,-.05,301);ts=np.geomspace(.095,506,601)
    grids={};validation={}
    for mode in ['qvi','fixed']:
        values=np.asarray([curve(mu,ts,mode) for mu in mus]);grids[mode]=RegularGridInterpolator((mus,ts),values,bounds_error=True)
        rng=np.random.default_rng(32779);err=[];native=[]
        for mu,t in zip(rng.uniform(-.35,-.05,160),np.exp(rng.uniform(np.log(.095),np.log(506),160))):
            y=direct(mu,t,mode);err.append(abs(float(grids[mode]([[mu,t]])[0])-y));native.append(abs(float(curve(mu,np.array([t]),mode)[0])-y))
        if max(err)>.04 or max(native)>1e-7:raise ValueError(('count-surface',mode,max(err),max(native)))
        validation[mode]={'offgrid_worst_abs_count':max(err),'eig_expm_worst':max(native),'min_rate':values.min(),'max_count':values.max()}
    return grids,validation
