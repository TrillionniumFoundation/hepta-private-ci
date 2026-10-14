"""R16 fresh-process solver controls; certified global optimum never used in fitting."""
from __future__ import annotations
import time
import resource
import numpy as np
from scipy.optimize import minimize
from problem import objective,derivative

INITIALS=((0.,0.),(.1,.1),(-.1,-.1),(1.,1.),(-1.,-1.),(2.,-2.),(1.,-1.),(2.,2.))
METHODS=('adam','bfgs','lbfgs','trust-exact')
CPU_CAP=.75
class Budget(Exception):pass


def fit(init,method,cap=CPU_CAP):
    if method not in METHODS or not cap>0:raise ValueError('method/cap')
    start_cpu=time.process_time();start_wall=time.perf_counter()
    checkpoints=[]
    theta=np.array(init,dtype=np.float64).copy()
    count={'fun':0,'grad':0,'hess':0,'accepted_changes':0}
    def elapsed():return time.process_time()-start_cpu
    def record(z):
        z=np.array(z,dtype=np.float64).copy()
        checkpoints.append({'theta':[float(v) for v in z],
                            'cpu':elapsed(),'cost':float(objective(z))})
    record(theta)
    def check():
        if elapsed()>=cap:raise Budget()
    status='cpu_cap'
    try:
        if method=='adam':
            m=np.zeros_like(theta);v=np.zeros_like(theta)
            for k in range(1,1001):
                check()
                g=derivative(theta)[0];count['grad']+=1
                if not np.isfinite(g).all():raise FloatingPointError('adam nonfinite gradient')
                m=.9*m+.1*g;v=.999*v+.001*(g*g)
                step=.03*m/(1-.9**k)/(np.sqrt(v/(1-.999**k))+1e-8)
                new=theta-step
                if not np.isfinite(new).all():raise FloatingPointError('adam nonfinite parameter')
                count['accepted_changes']+=int(not np.array_equal(theta,new))
                theta=new;record(theta)
            status='iteration_cap'
        else:
            def fun(x):check();count['fun']+=1;return objective(x)
            def jac(x):check();count['grad']+=1;return derivative(x)[0]
            def hess(x):check();count['hess']+=1;return derivative(x)[1]
            def callback(x):
                nonlocal theta
                new=np.array(x,dtype=np.float64)
                count['accepted_changes']+=int(not np.array_equal(theta,new))
                theta=new.copy();record(theta)
            args=dict(method={'bfgs':'BFGS','lbfgs':'L-BFGS-B','trust-exact':'trust-exact'}[method],jac=jac,callback=callback,options={'maxiter':1000,'gtol':1e-12})
            if method=='trust-exact':args['hess']=hess
            elif method=='lbfgs':args['options'].update(ftol=1e-15,maxls=30)
            opt=minimize(fun,theta,**args)
            # If solver exits normally, final proposed accepted iterate is opt.x.
            if not np.array_equal(theta,opt.x):
                theta=opt.x.copy();count['accepted_changes']+=1;record(theta)
            status=str(opt.message)
    except Budget:
        status='cpu_censored'
    elapsed_cpu=elapsed();elapsed_wall=time.perf_counter()-start_wall
    return dict(theta=theta,checkpoints=checkpoints,counts=count,status=status,
                cpu=elapsed_cpu,wall=elapsed_wall,
                rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
