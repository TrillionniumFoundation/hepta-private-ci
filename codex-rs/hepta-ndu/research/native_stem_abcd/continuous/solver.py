"""Same population objective, different numerical methods; complete call accounting."""
import time
import numpy as np
import torch
from scipy.optimize import minimize, least_squares
from domain import Policy, adjoint, check_law


class Budget(Exception):
    pass


def fit(policy, p, states, weights, method, seconds=8., ridge=0.):
    check_law(states, weights)
    if not np.isfinite(seconds) or seconds <= 0 or not np.isfinite(ridge) or ridge < 0:
        raise ValueError('invalid budget/regularizer')
    t, wall = time.process_time(), time.perf_counter(); selected = policy.initial.copy()
    history = []; counts = dict(values=0, gradients=0, hessians=0, tangent_lanes=0, callbacks=0, updates=0)
    def check():
        if time.process_time() - t >= seconds:
            raise Budget()
    def value(x):
        check(); counts['values'] += 1
        with torch.no_grad():
            f = float(policy.value(torch.tensor(x), p, states, weights, ridge))
        if not np.isfinite(f): raise FloatingPointError('nonfinite objective')
        return f
    fn = lambda z: policy.value(z, p, states, weights, ridge)
    gfn = (lambda z: adjoint(z, p, states, weights, policy.family, ridge)[1]) if method == 'adjoint' else torch.func.grad(fn)
    def grad(x):
        check(); counts['gradients'] += 1
        a = gfn(torch.tensor(x)).detach().numpy()
        if not np.isfinite(a).all(): raise FloatingPointError('nonfinite gradient')
        return a
    def hess(x):
        check(); counts['hessians'] += 1; counts['tangent_lanes'] += len(x)
        H = torch.func.jacfwd(gfn)(torch.tensor(x)).detach().numpy()
        if not np.isfinite(H).all(): raise FloatingPointError('nonfinite Hessian')
        return (H + H.T) / 2
    def callback(intermediate_result):
        nonlocal selected
        x = intermediate_result.x.copy(); counts['callbacks'] += 1
        counts['updates'] += int(not np.array_equal(x, selected)); selected = x
        f = np.asarray(intermediate_result.fun)
        history.append(dict(cpu=time.process_time()-t, metric=float(f) if f.ndim == 0 else float(np.linalg.norm(f)),
                            metric_type='gradient_norm' if method == 'root' else 'objective', **counts))
    status = 'cpu_cap'
    if method == 'none':
        status = 'untrained'
    else:
        try:
            if method == 'adam':
                z = torch.tensor(selected, requires_grad=True); opt = torch.optim.Adam([z], lr=.015)
                for i in range(100000):
                    check(); opt.zero_grad(set_to_none=True); loss = fn(z)
                    counts['values'] += 1; counts['gradients'] += 1
                    if not torch.isfinite(loss): raise FloatingPointError('nonfinite Adam')
                    loss.backward(); opt.step(); selected = z.detach().numpy().copy(); counts['updates'] += 1
                    if i % 25 == 0:
                        history.append(dict(cpu=time.process_time()-t, metric=float(loss.detach()), metric_type='pre_update_objective', **counts))
            elif method in ('adjoint', 'adtrust', 'lbfgs'):
                kw = dict(method='L-BFGS-B' if method == 'lbfgs' else 'trust-exact', jac=grad, callback=callback)
                options = dict(maxiter=10000, gtol=1e-9)
                if method == 'lbfgs': options.update(ftol=1e-14, maxls=40)
                else: kw['hess'] = hess
                r = minimize(value, selected, options=options, **kw); selected = r.x.copy(); status = str(r.message)
            elif method == 'root':
                r = least_squares(grad, selected, jac=hess, callback=callback, ftol=1e-12, xtol=1e-12, gtol=1e-10, max_nfev=10000)
                selected = r.x.copy(); status = str(r.message)
            else:
                raise ValueError('unknown method')
        except Budget:
            pass
    return selected, dict(cpu=time.process_time()-t, wall=time.perf_counter()-wall, status=status, counts=counts,
                          history=history, nominal_cap=seconds, overshoot=max(0.,time.process_time()-t-seconds),
                          state_count=len(states), finite_leaf_count=len(states)*2*2**p.horizon)
