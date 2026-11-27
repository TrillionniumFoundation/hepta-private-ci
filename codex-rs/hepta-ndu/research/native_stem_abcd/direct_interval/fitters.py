"""R20 genuine matched fit trajectories incl ordinary torch autograd trust-exact.

The full-population reference, B&B certificate and candidate are never used here.
"""
from __future__ import annotations
import time,resource
import numpy as np
from scipy.optimize import minimize
import torch
torch.set_num_threads(1)
from model import full, INITIALS, METHODS
CAP=.75
METHODS=METHODS+('ad-trust-exact',)
class Budget(Exception):pass


def ad_objective(theta,extra):
    import torch, math
    a,b=theta.unbind()
    delta=a-b
    t=a*b
    phi=delta*delta/4+(a/(1+a*a))/25+(delta/(1+delta*delta))/8*(1 if extra else 0)
    result=theta.new_zeros(())
    for x in (-1,1):
      for p0 in (0,1):
        steps=[]
        for e1 in (-1,1):
          p1=p0^(e1==1)
          vals=[]
          for e2 in (-1,1):
            p2=p1^(e2==1)
            r=x*(t-1)+phi-1+e2/10
            vals.append(r*r+p2/50)
          rho=.5 if p1==0 else 1.
          ce2=torch.logsumexp(rho*torch.stack(vals),0)/rho-math.log(2)/rho
          steps.append(p1/20+.9*ce2)
        rho=.5 if p0==0 else 1.
        ce1=torch.logsumexp(rho*torch.stack(steps),0)/rho-math.log(2)/rho
        result=result+.9*ce1/4
    return result+(a*a+b*b)/4


def fit(initial,method,extra,cap=CAP):
    if method not in METHODS or extra not in (True,False) or not 0<cap<3600:
        raise ValueError('method/extra/cap')
    start=time.process_time();wall=time.perf_counter()
    theta=np.asarray(initial,dtype='<f8').copy()
    history=[]
    counts=dict(f=0,g=0,h=0,updates=0,callbacks=0,ad_graphs=0)
    def elapsed():return time.process_time()-start
    def check():
        if elapsed()>=cap:raise Budget()
    def record():history.append((theta.copy(),elapsed(),full(theta,extra)[0]))
    record();status='cpu_censored'
    try:
        if method=='adam':
            m=np.zeros(2);v=np.zeros(2)
            for k in range(1,100001):
                check()
                g=full(theta,extra)[1];counts['g']+=1
                m=.9*m+.1*g;v=.999*v+.001*(g*g)
                new=theta-.03*(m/(1-.9**k))/(np.sqrt(v/(1-.999**k))+1e-8)
                if not np.isfinite(new).all():raise FloatingPointError('divergence')
                counts['updates']+=int(not np.array_equal(theta,new))
                theta=new;record()
            status='iteration_limit'
        else:
            def obj(x):
                check();counts['f']+=1
                if method=='ad-trust-exact':
                    z=torch.as_tensor(x,dtype=torch.float64)
                    counts['ad_graphs']+=1
                    return float(ad_objective(z,extra).detach())
                return full(x,extra)[0]
            def jac(x):
                check();counts['g']+=1
                if method=='ad-trust-exact':
                    z=torch.as_tensor(x,dtype=torch.float64).requires_grad_(True)
                    counts['ad_graphs']+=1
                    v=ad_objective(z,extra)
                    return torch.autograd.grad(v,z)[0].detach().numpy().copy()
                return full(x,extra)[1]
            def hess(x):
                check();counts['h']+=1
                if method=='ad-trust-exact':
                    z=torch.as_tensor(x,dtype=torch.float64).requires_grad_(True)
                    counts['ad_graphs']+=1
                    return torch.autograd.functional.hessian(lambda p:ad_objective(p,extra),z).detach().numpy().copy()
                return full(x,extra)[2]
            def callback(x):
                nonlocal theta
                new=np.array(x,dtype='<f8').copy()
                counts['callbacks']+=1
                counts['updates']+=int(not np.array_equal(theta,new))
                theta=new;record()
            kw=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact','ad-trust-exact':'trust-exact'}[method],
                    jac=jac,callback=callback,options=dict(maxiter=100000,gtol=1e-12))
            if method in ('trust-exact','ad-trust-exact'):kw['hess']=hess
            if method=='lbfgs':kw['options'].update(ftol=1e-15,maxls=30)
            opt=minimize(obj,theta,**kw)
            if not np.array_equal(theta,opt.x):
                theta=opt.x.copy();counts['updates']+=1;record()
            status=str(opt.message)
    except Budget:pass
    if not np.isfinite(theta).all():raise FloatingPointError('bad final weights')
    return dict(theta=theta,history=history,counts=counts,status=status,
                fit_cpu=elapsed(),fit_wall=time.perf_counter()-wall,
                fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
