"""R18 matched CPU-capped methods; no global certificate enters fitting."""
from __future__ import annotations
import time,resource
import numpy as np
from scipy.optimize import minimize
from problem import objective,INITIALS
METHODS=('adam','bfgs','lbfgs','trust-exact')
CAP=.75
class Budget(Exception):pass

def fit(initial,method,shift=1.,cap=CAP):
    if method not in METHODS or shift not in (0.,1.) or not 0<cap<3600:
        raise ValueError('invalid fit config')
    start=time.process_time();wall=time.perf_counter()
    theta=np.asarray(initial,dtype=np.float64).copy()
    history=[];cnt=dict(f=0,g=0,h=0,accepted=0,callbacks=0)
    def spent():return time.process_time()-start
    def check():
        if spent()>=cap:raise Budget()
    def record():
        history.append((theta.copy(),spent(),objective(theta,shift)[0]))
    record();status='censored'
    try:
        if method=='adam':
            avg=np.zeros(2);var=np.zeros(2)
            for k in range(1,100001):
                check()
                g=objective(theta,shift)[1];cnt['g']+=1
                avg=.9*avg+.1*g;var=.999*var+.001*(g*g)
                nxt=theta-.03*(avg/(1-.9**k))/(np.sqrt(var/(1-.999**k))+1e-8)
                if not np.isfinite(nxt).all():raise FloatingPointError('Adam divergence')
                cnt['accepted']+=int(not np.array_equal(nxt,theta));theta=nxt;record()
            status='iterations'
        else:
            def f(x):check();cnt['f']+=1;return objective(x,shift)[0]
            def g(x):check();cnt['g']+=1;return objective(x,shift)[1]
            def h(x):check();cnt['h']+=1;return objective(x,shift)[2]
            def callback(x):
                nonlocal theta
                nxt=np.asarray(x).copy();cnt['callbacks']+=1
                cnt['accepted']+=int(not np.array_equal(theta,nxt));theta=nxt;record()
            args=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact'}[method],jac=g,callback=callback,
                      options=dict(maxiter=100000,gtol=1e-12))
            if method=='trust-exact':args['hess']=h
            if method=='lbfgs':args['options'].update(ftol=1e-15,maxls=30)
            result=minimize(f,theta,**args)
            if not np.array_equal(result.x,theta):
                theta=result.x.copy();cnt['accepted']+=1;record()
            status=str(result.message)
    except Budget:
        pass
    return dict(theta=theta,history=history,counters=cnt,status=status,
                cpu=spent(),wall=time.perf_counter()-wall,
                fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
