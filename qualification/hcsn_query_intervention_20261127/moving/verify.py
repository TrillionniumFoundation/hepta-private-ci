"""Exact single-interval moving-wall first-passage probabilities in dimensionless coordinates."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.integrate import quad
from scipy.special import ndtr, log_ndtr

HORIZONS=np.array([.0625,.125,.25,.5,1.])
DISCOUNTS=(0.,.08,.4)
PAR=np.array([4.4,4.25,.03355,.09,np.log(.23)])


def passage(u,v,t):
    rt=np.sqrt(t);a=-u/rt-v*rt;c=-u/rt+v*rt
    image=np.exp(-2*u*v+log_ndtr(c))
    f=ndtr(a)+image
    du=-2*np.exp(-.5*a*a)/(np.sqrt(2*np.pi)*rt)-2*v*image
    dv=-2*u*image
    return f,du,dv


def observation(param,t,q=0.):
    a,b,mu,s,l_sigma=param;sigma=np.exp(l_sigma)
    u=(a-b)/sigma;v=(mu-s)/sigma
    if u<0:
        return 1.,np.zeros(5)
    if q:
        w=np.sqrt(v*v+2*q);factor=np.exp((w-v)*u)
        f,fu,fw=passage(u,w,t)
        gu=factor*((w-v)*f+fu);gv=factor*(u*(v/w-1)*f+fw*v/w)
        g=factor*f
    else:
        g,gu,gv=passage(u,v,t)
    return g,np.array([gu/sigma,-gu/sigma,gv/sigma,-gv/sigma,-u*gu-v*gv])


def measured(param):
    values=[];grads=[]
    for q in DISCOUNTS:
        for h in HORIZONS:
            z,g=observation(param,h,q);values.append(z);grads.append(g)
    return np.array(values),np.array(grads)


def finite(param):
    ds=[]
    for k in range(len(param)):
        step=np.eye(len(param))[k]*1e-5
        ds.append((measured(param+step)[0]-measured(param-step)[0])/(2e-5))
    return np.stack(ds,axis=1)


def check():
    value,grad=measured(PAR)
    a,b,mu,s,l=PAR
    equiv=[
        PAR+np.array([.91,.91,0.,0.,0.]),
        PAR+np.array([0.,0.,-.83,-.83,0.]),
        np.array([b+2.8*(a-b),b,s+2.8*(mu-s),s,l+np.log(2.8)])]
    abs_grad_error=float(abs(grad-finite(PAR)).max())
    ranks={}
    initial=np.array([1.,0.,0.,0.,0.])
    drift_obs=np.array([1.,0.,.5,0.,0.])
    variance_obs=np.array([0.,0.,0.,0.,2*np.exp(2*l)])
    for name,jac in [('events',grad),('plus_initial',np.vstack([grad,initial])),
                      ('plus_future_mean',np.vstack([grad,initial,drift_obs])),
                      ('plus_variance',np.vstack([grad,initial,drift_obs,variance_obs]))]:
        sv=np.linalg.svd(jac,compute_uv=False)
        ranks[name]={'singular_values':sv.tolist(),'rank_threshold_1e-9':int((sv>1e-9).sum())}
    for t in (0.125,1.):
        closed,_=observation(PAR,t,.4)
        x=a-b;sig=np.exp(l);nu=mu-s
        density=lambda h: x/(sig*np.sqrt(2*np.pi*h**3))*np.exp(-(x+nu*h)**2/(2*sig**2*h))
        check_discount=quad(lambda h:np.exp(-.4*h)*density(h),0,t,epsabs=1e-13)[0]
        assert abs(closed-check_discount)<1e-10
    rng=np.random.default_rng(855933);size=350000;rows=[];mass=[]
    for slope in (-.18,0.,.18):
        par=PAR.copy();par[3]=slope;a,b,mu,s,l=par;sigma=np.exp(l)
        for t in HORIZONS:
            x=a-b;nu=mu-s;end=x+nu*t+sigma*np.sqrt(t)*rng.standard_normal(size)
            bridge=np.where(end<=0.,1.,np.exp(-2*x*np.maximum(end,0.)/(sigma**2*t)))
            hit=rng.uniform(size=size)<bridge
            mean=float(hit.mean());se=float(hit.std(ddof=1)/np.sqrt(size))
            truth=float(observation(par,t)[0]);left=par.copy();left[3]=0.
            right=left.copy();right[1]=b+s*t
            lo=float(observation(left,t)[0]);hi=float(observation(right,t)[0])
            def killed(y):
                k1=np.exp(-(y-x-nu*t)**2/(2*sigma*sigma*t))
                k2=np.exp(-2*nu*x/(sigma*sigma) -(y+x-nu*t)**2/(2*sigma*sigma*t))
                return (k1-k2)/(sigma*np.sqrt(2*np.pi*t))
            survival=quad(killed,0.,np.inf,epsabs=3e-12)[0]
            mass.append(abs(survival+truth-1.))
            rows.append(dict(slope=s,t=float(t),exact=truth,frozen_initial=lo,frozen_final=hi,
                             monte_carlo=mean,se=se,z=(mean-truth)/se))
    par=PAR.copy();par[0]=par[1];h=1e-7
    g=observation(par,.25)[1][0];ii=np.eye(5)[0]*h
    left=(observation(par,.25)[0]-observation(par-ii,.25)[0])/h
    right=(observation(par+ii,.25)[0]-observation(par,.25)[0])/h
    return dict(parameters=PAR.tolist(),observations=value.tolist(),rows=rows,paths_per_setting=size,
                equiv=[dict(parameters=x.tolist(),max_observation_difference=float(np.max(abs(measured(x)[0]-value)))) for x in equiv],
                ranks=ranks,max_abs_derivative_difference=abs_grad_error,max_mass_error=max(mass),
                contact={'probability':observation(par,.25)[0],'left_dx':float(left),'right_dx':float(right),'analytic_continuation_right_dx':float(g)})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();r=check()
    a.out.write_text(json.dumps(r,indent=1,allow_nan=False)+'\n')
    print('grad',r['max_abs_derivative_difference'],'mass',r['max_mass_error'],'contact',r['contact'])
    print(r['ranks']);print('max_abs_z',max(abs(x['z']) for x in r['rows']))
