"""R21 matched analytic forward-sensitivity and independent Torch AD optimizers.

Never uses strict B&B certificates in any gradient, Hessian or optimizer stop.
"""
from __future__ import annotations
import time,resource
import numpy as np
from scipy.optimize import minimize
import torch
from model import full,INITIALS,METHODS
CAP=.75
torch.set_num_threads(1)
class Budget(Exception):pass

def torch_full(theta):
    import math
    n=int(theta.numel()); a,b=theta[0],theta[1]
    c=theta[2] if n>2 else theta.new_zeros(())
    d=theta[3] if n>3 else theta.new_zeros(())
    v=a-b
    shared=v*v/4+.04*a/(1+a*a)+.125*v/(1+v*v)
    ans=theta.new_zeros(())
    for x in (-1,1):
      for p0 in (0,1):
       branches=[]
       for e1 in (-1,1):
        p1=p0^(e1==1)
        h1=a*x+c
        base=b*h1+d*h1*h1/4+shared
        leaf=[]
        for e2 in (-1,1):
         p2=p1^(e2==1)
         r=base+e2/10-x-1
         leaf.append(r*r+p2/50)
        risk=.5 if p1==0 else 1.
        inside=torch.logsumexp(risk*torch.stack(leaf),0)/risk-math.log(2)/risk
        branches.append(p1/20+.9*inside)
       risk=.5 if p0==0 else 1.
       ans=ans+.9*(torch.logsumexp(risk*torch.stack(branches),0)-math.log(2))/risk/4
    return ans+(theta@theta)/4

def fit(initial,method,cap=CAP):
    if method not in METHODS or not 0<cap<=120:raise ValueError('method or cap')
    started=time.process_time();wall=time.perf_counter()
    theta=np.asarray(initial,dtype='<f8').copy();n=len(theta)
    history=[];counts=dict(f=0,g=0,h=0,callbacks=0,updates=0,ad_graphs=0)
    def elapsed():return time.process_time()-started
    def check():
        if elapsed()>=cap:raise Budget()
    def record():
        history.append((theta.copy(),elapsed(),full(theta)[0]))
    record();status='cpu_censored'
    try:
      if method=='adam':
        m=np.zeros(n);v=np.zeros(n)
        for k in range(1,100001):
            check();g=full(theta)[1];counts['g']+=1
            m=.9*m+.1*g;v=.999*v+.001*(g*g)
            new=theta-.03*m/(1-.9**k)/(np.sqrt(v/(1-.999**k))+1e-8)
            if not np.isfinite(new).all():raise FloatingPointError('nonfinite Adam weights')
            counts['updates']+=int(not np.array_equal(theta,new));theta=new;record()
        status='iteration_cap'
      else:
        def fun(x):
            check();counts['f']+=1
            if method=='ad-trust-exact':
                counts['ad_graphs']+=1
                return float(torch_full(torch.tensor(x,dtype=torch.float64)).detach())
            return full(x)[0]
        def jac(x):
            check();counts['g']+=1
            if method=='ad-trust-exact':
                z=torch.tensor(x,dtype=torch.float64,requires_grad=True)
                counts['ad_graphs']+=1
                return torch.autograd.grad(torch_full(z),z)[0].detach().numpy().copy()
            return full(x)[1]
        def hess(x):
            check();counts['h']+=1
            if method=='ad-trust-exact':
                z=torch.tensor(x,dtype=torch.float64,requires_grad=True)
                counts['ad_graphs']+=1
                return torch.autograd.functional.hessian(torch_full,z).detach().numpy().copy()
            return full(x)[2]
        def callback(x):
            nonlocal theta
            new=np.asarray(x,dtype='<f8').copy()
            counts['callbacks']+=1;counts['updates']+=int(not np.array_equal(theta,new))
            theta=new;record()
        kw=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact','ad-trust-exact':'trust-exact'}[method],jac=jac,callback=callback,
                options=dict(maxiter=100000,gtol=1e-12))
        if method in ('trust-exact','ad-trust-exact'):kw['hess']=hess
        if method=='lbfgs':kw['options'].update(ftol=1e-15,maxls=30)
        opt=minimize(fun,theta,**kw)
        if not np.array_equal(theta,opt.x):
            theta=np.asarray(opt.x,dtype='<f8').copy();counts['updates']+=1;record()
        status=str(opt.message)
    except Budget:pass
    if not np.isfinite(theta).all():raise FloatingPointError('nonfinite selected weights')
    return dict(theta=theta,history=history,counts=counts,status=status,
                fit_cpu=elapsed(),fit_wall=time.perf_counter()-wall,
                fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
