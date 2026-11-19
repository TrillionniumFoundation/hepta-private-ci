"""R19 matched CPU-capped optimizers, no globally certified reference used in fits."""
from __future__ import annotations
import time,resource
import numpy as np
from scipy.optimize import minimize
from model import full,INITIALS,METHODS
CAP=.75
class Budget(Exception): pass

def fit(initial,method,eta,cap=CAP):
    if method not in METHODS or eta not in (0.,1/25) or not 0<cap<3600:
        raise ValueError('invalid method/eta/cap')
    start=time.process_time();wall=time.perf_counter()
    theta=np.asarray(initial,dtype='<f8').copy()
    history=[];count=dict(f=0,g=0,h=0,accepted=0,callbacks=0)
    def spent():return time.process_time()-start
    def check():
        if spent()>=cap:raise Budget()
    def record(): history.append((theta.copy(),spent(),full(theta,eta)[0]))
    record();status='cpu_censored'
    try:
        if method=='adam':
            m=np.zeros(2);v=np.zeros(2)
            for k in range(1,100001):
                check()
                grad=full(theta,eta)[1];count['g']+=1
                m=.9*m+.1*grad;v=.999*v+.001*(grad*grad)
                new=theta-.03*(m/(1-.9**k))/(np.sqrt(v/(1-.999**k))+1e-8)
                if not np.isfinite(new).all():raise FloatingPointError('divergence')
                count['accepted']+=int(not np.array_equal(theta,new))
                theta=new;record()
            status='iteration_limit'
        else:
            def obj(x):check();count['f']+=1;return full(x,eta)[0]
            def jac(x):check();count['g']+=1;return full(x,eta)[1]
            def hess(x):check();count['h']+=1;return full(x,eta)[2]
            def callback(x):
                nonlocal theta
                new=np.array(x,dtype='<f8')
                count['callbacks']+=1
                count['accepted']+=int(not np.array_equal(theta,new))
                theta=new;record()
            kw=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact'}[method],
                    jac=jac,callback=callback,options=dict(maxiter=100000,gtol=1e-12))
            if method=='trust-exact':kw['hess']=hess
            if method=='lbfgs':kw['options'].update(ftol=1e-15,maxls=30)
            result=minimize(obj,theta,**kw)
            if not np.array_equal(theta,result.x):
                theta=result.x.copy();count['accepted']+=1;record()
            status=str(result.message)
    except Budget:
        pass
    return dict(theta=theta,history=history,counts=count,status=status,
                fit_cpu=spent(),fit_wall=time.perf_counter()-wall,
                fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
