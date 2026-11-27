"""Matched numerical optimizer controls; never import global certificate."""
from __future__ import annotations
import time,resource
import numpy as np
from scipy.optimize import minimize
from problem import objective
METHODS=('adam','bfgs','lbfgs','trust-exact')
INITIALS=((0.,0.),(.1,.1),(-.1,-.1),(1.,1.),(-1.,-1.),(2.,-2.),(1.,-1.),(2.,2.))
CPU_CAP=.75
class CapReached(Exception):pass

def fit(start,method,kappa=.25,cap=CPU_CAP):
    if method not in METHODS or not cap>0 or kappa not in (0.,.25):raise ValueError('method/cap/kappa')
    cpu=time.process_time();wall=time.perf_counter()
    theta=np.asarray(start,dtype=np.float64).copy()
    counts=dict(f=0,g=0,h=0,updates=0,callbacks=0)
    checkpoints=[]
    def elapsed():return time.process_time()-cpu
    def check():
        if elapsed()>=cap: raise CapReached()
    def record(v):
        v=np.asarray(v,dtype=np.float64)
        checkpoints.append((v.copy(),elapsed(),objective(v,kappa)[0]))
    record(theta);status='cpu_cap'
    try:
        if method=='adam':
            m=np.zeros(2);v=np.zeros(2)
            for i in range(1,100001):
                check()
                grad=objective(theta,kappa)[1];counts['g']+=1
                m=.9*m+.1*grad;v=.999*v+.001*(grad**2)
                upd=.03*(m/(1-.9**i))/(np.sqrt(v/(1-.999**i))+1e-8)
                new=theta-upd
                if not np.isfinite(new).all():raise FloatingPointError('adam diverged')
                counts['updates']+=int(not np.array_equal(new,theta))
                theta=new;record(theta)
            status='iteration_cap'
        else:
            def fun(x):check();counts['f']+=1;return objective(x,kappa)[0]
            def jac(x):check();counts['g']+=1;return objective(x,kappa)[1]
            def hess(x):check();counts['h']+=1;return objective(x,kappa)[2]
            def cb(x):
                nonlocal theta
                y=np.asarray(x,dtype=float)
                counts['callbacks']+=1
                counts['updates']+=int(not np.array_equal(y,theta))
                theta=y.copy();record(theta)
            cfg=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact'}[method],jac=jac,callback=cb,options=dict(gtol=1e-12,maxiter=100000))
            if method=='trust-exact':cfg['hess']=hess
            if method=='lbfgs':cfg['options'].update(ftol=1e-15,maxls=30)
            result=minimize(fun,theta,**cfg)
            if not np.array_equal(theta,result.x):
                theta=result.x.copy();counts['updates']+=1;record(theta)
            status=str(result.message)
    except CapReached:
        status='cpu_censored'
    return dict(theta=theta,weights=np.array([c[0] for c in checkpoints]),
        checkpoint_cpu=np.array([c[1] for c in checkpoints]),
        checkpoint_cost=np.array([c[2] for c in checkpoints]),
        counts=counts,fit_cpu=elapsed(),fit_wall=time.perf_counter()-wall,
        peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,status=status)
