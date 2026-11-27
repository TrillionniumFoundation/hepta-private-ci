"""Matched-family population objectives; explicit-adjoint vs generic AD controls."""
import time
import numpy as np
import torch
from scipy.optimize import minimize, least_squares
from problem import objective, adjoint, initial_weights

class Budget(Exception): pass


def fit(p,states,family,method,seed,seconds):
    start=time.process_time();wall=time.perf_counter();x0=initial_weights(seed,family)
    selected=x0.copy();history=[];counts=dict(objectives=0,gradients=0,hessians=0,ad_lanes=0,accepted=0)
    def check():
        if time.process_time()-start>=seconds:raise Budget()
    def value(x):
        check();counts['objectives']+=1
        with torch.no_grad():f=float(objective(torch.tensor(x),p,states,family))
        if not np.isfinite(f):raise FloatingPointError('nonfinite objective')
        return f
    def grad(x,explicit=False):
        check();counts['gradients']+=1;t=torch.tensor(x)
        g=adjoint(t,p,states,family)[1] if explicit else torch.func.grad(lambda z:objective(z,p,states,family))(t)
        a=g.detach().numpy()
        if not np.isfinite(a).all():raise FloatingPointError('nonfinite gradient')
        return a
    def hessian(x,explicit=False):
        check();counts['hessians']+=1;counts['ad_lanes']+=len(x)
        fn=(lambda z:adjoint(z,p,states,family)[1]) if explicit else torch.func.grad(lambda z:objective(z,p,states,family))
        H=torch.func.jacfwd(fn)(torch.tensor(x)).detach().numpy()
        return .5*(H+H.T)
    def callback(intermediate_result):
        nonlocal selected
        selected=intermediate_result.x.copy();counts['accepted']+=1
        history.append(dict(cpu=time.process_time()-start,objective=float(intermediate_result.fun),
                            iteration=counts['accepted']))
    status='cpu_cap'
    if method=='none':return selected,dict(status='untrained',cpu=0.,wall=0.,counts=counts,history=history)
    try:
        if method=='adam':
            theta=torch.tensor(x0,requires_grad=True);opt=torch.optim.Adam([theta],lr=.015)
            for i in range(100000):
                check();opt.zero_grad(set_to_none=True);loss=objective(theta,p,states,family)
                counts['objectives']+=1;counts['gradients']+=1
                if not torch.isfinite(loss):raise FloatingPointError('nonfinite Adam')
                loss.backward();opt.step();selected=theta.detach().numpy().copy();counts['accepted']+=1
                if i%25==0:history.append(dict(cpu=time.process_time()-start,objective=float(loss.detach()),
                                              iteration=i,objective_is_pre_update=True))
        elif method in ('adjoint','adtrust','lbfgs'):
            explicit=method=='adjoint'
            kwargs=dict(method='L-BFGS-B' if method=='lbfgs' else 'trust-exact',jac=lambda x:grad(x,explicit),
                        callback=callback)
            if method!='lbfgs':kwargs['hess']=lambda x:hessian(x,explicit)
            options=dict(maxiter=10000,gtol=1e-9)
            if method=='lbfgs':options.update(ftol=1e-14,maxls=40)
            r=minimize(value,x0,options=options,**kwargs);selected=r.x.copy();status=f'{method}:{r.status}:{r.message}'
        elif method=='root':
            def accepted(intermediate_result):
                nonlocal selected
                selected=intermediate_result.x.copy();counts['accepted']+=1
                history.append(dict(cpu=time.process_time()-start,gradient_norm=float(np.linalg.norm(intermediate_result.fun))))
            r=least_squares(lambda x:grad(x,False),x0,jac=lambda x:hessian(x,False),method='trf',
                            ftol=1e-12,xtol=1e-12,gtol=1e-10,max_nfev=10000,callback=accepted)
            selected=r.x.copy();status=f'root:{r.status}:{r.message}'
        else:raise ValueError('unknown method')
    except Budget:pass
    return selected,dict(status=status,cpu=time.process_time()-start,wall=time.perf_counter()-wall,
                         counts=counts,history=history,initial=x0.tolist(),
                         budget='one nonpreemptible evaluation can overshoot; all work paid')
