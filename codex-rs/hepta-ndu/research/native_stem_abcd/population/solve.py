"""Same-objective optimizers and reduced population-adjoint equation solvers."""
import time
import numpy as np
from scipy.optimize import least_squares
import torch
from torch.func import jacfwd, grad
from problem import AttentionStem, MatrixStem, initial_states, initial_moments, objective, policy_value, stationarity


def vector(model):
    return np.concatenate([p.detach().numpy().reshape(-1) for p in model.parameters()])


def assign(model,values):
    offset=0
    with torch.no_grad():
        for p in model.parameters():
            p.copy_(torch.as_tensor(values[offset:offset+p.numel()].reshape(p.shape),dtype=p.dtype))
            offset+=p.numel()
    if offset!=len(values): raise ValueError('weight length')


class CapReached(Exception):
    pass


def fit(model,problem,method,seconds):
    if not np.isfinite(seconds) or seconds<=0: raise ValueError('positive finite CPU cap')
    start=time.process_time();wall=time.perf_counter();selected=vector(model)
    counts=dict(objective_calls=0,stationarity_calls=0,jacobian_calls=0,updates=0,
                forward_ad_lanes=0,reverse_gradient_calls=0)
    history=[];status='cpu_cap'
    def check():
        if time.process_time()-start>=seconds: raise CapReached()
    if method in ('adam','lbfgs'):
        opt=(torch.optim.Adam(model.parameters(),lr=.003 if isinstance(model,AttentionStem) else .02)
             if method=='adam' else torch.optim.LBFGS(model.parameters(),lr=1.,max_iter=1,
                 line_search_fn='strong_wolfe',tolerance_grad=1e-11,tolerance_change=1e-15,history_size=30))
        def closure():
            check();opt.zero_grad(set_to_none=True)
            loss=objective(model,problem,initial_states())
            counts['objective_calls']+=1
            if not torch.isfinite(loss): raise FloatingPointError('nonfinite cost')
            loss.backward();counts['reverse_gradient_calls']+=1
            return loss
        try:
            for _ in range(100000):
                check()
                if method=='adam':
                    loss=closure();opt.step()
                else: loss=opt.step(closure)
                selected=vector(model);counts['updates']+=1
                if counts['updates']%25==0:
                    history.append([time.process_time()-start,float(loss.detach())])
        except CapReached:
            assign(model,selected)
    elif method in ('adjoint','gradient_root'):
        if not isinstance(model,MatrixStem):raise ValueError('matrix family required')
        shape=model.weights.shape;w=problem.tensors();M=initial_moments(initial_states())
        def cost_tensor(t):
            P,c,_=policy_value(model.gains(t.reshape(shape)),w,problem.gamma,3)
            return (P[0]*M).sum()+c[0].mean()
        gradient=grad(cost_tensor)
        def eq(t):
            if method=='gradient_root' or model.family!='matrix': return gradient(t)
            return stationarity(model,problem,t.reshape(shape))
        def fun(x):
            check();counts['stationarity_calls']+=1
            if method=='gradient_root' or model.family!='matrix': counts['reverse_gradient_calls']+=1
            a=eq(torch.tensor(x,dtype=torch.float64)).detach().numpy()
            if not np.isfinite(a).all():raise FloatingPointError('nonfinite stationarity')
            return a
        def jac(x):
            check();counts['jacobian_calls']+=1;counts['forward_ad_lanes']+=len(x)
            return jacfwd(eq)(torch.tensor(x,dtype=torch.float64)).detach().numpy()
        def accepted(intermediate_result):
            nonlocal selected
            selected=intermediate_result.x.copy();counts['updates']+=1
            history.append([time.process_time()-start,float(2*intermediate_result.cost)])
        try:
            r=least_squares(fun,selected,jac=jac,method='trf',max_nfev=10000,
                            ftol=1e-12,gtol=1e-12,xtol=1e-12,callback=accepted)
            selected=r.x.copy();status=f'converged_status_{r.status}'
        except CapReached:pass
        assign(model,selected)
    else:raise ValueError('unknown optimizer')
    return dict(method=method,status=status,cpu_cap=seconds,cpu_seconds=time.process_time()-start,
                wall_seconds=time.perf_counter()-wall,counts=counts,history=history,
                cap_semantics='check before operation; overshoot visible; no dummy equalizing work',
                history_metric='objective before update' if method in ('adam','lbfgs') else 'equation squared residual')
