"""R7 matrix-free/cached adjoints; all methods optimize the R6 population target."""
import sys
import time
from pathlib import Path

import numpy as np
import torch
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'continuous'))
from domain import Policy, adjoint, check_law, make_problem, rule


class Limit(Exception):
    pass


class Promote(Exception):
    pass


class Derivatives:
    """Cache one gradient graph; vector products do NOT form a parameter Hessian.

    Reverse differentiation computes (Dg)^T v. g is the exact smooth scalar
    gradient, so this is H v. Dense symmetry, finite differences and forward
    JVP comparisons are independently tested. Every cache build is paid.
    """
    def __init__(self, policy, problem, states, weights, explicit, counts, check):
        self.policy, self.problem = policy, problem
        self.states, self.weights = states, weights
        self.explicit, self.counts, self.check = explicit, counts, check
        self.key = self.z = self.g = self.f = None

    def scalar(self, z):
        return self.policy.value(z, self.problem, self.states, self.weights)

    def gradient_function(self, z):
        if self.explicit:
            return adjoint(z, self.problem, self.states, self.weights)[1]
        return torch.func.grad(self.scalar)(z)

    def build(self, x):
        self.check()
        if self.key is not None and np.array_equal(x, self.key):
            self.counts['cache_hits'] += 1
            return
        self.key = None
        self.z = torch.tensor(np.asarray(x), dtype=torch.float64, requires_grad=True)
        if self.explicit:
            self.f, self.g = adjoint(self.z, self.problem, self.states, self.weights)
        else:
            self.f = self.scalar(self.z)
            self.g = torch.autograd.grad(self.f, self.z, create_graph=True)[0]
        if not torch.isfinite(self.g).all() or not torch.isfinite(self.f):
            raise FloatingPointError('nonfinite derivative graph')
        self.counts['gradient_graphs'] += 1
        self.counts['graph_state_points'] += len(self.states)
        self.key = np.asarray(x).copy()

    def value(self, x):
        self.check()
        self.counts['value_requests'] += 1
        if self.key is not None and np.array_equal(x, self.key):
            self.counts['cache_hits'] += 1
            return float(self.f.detach())
        with torch.no_grad():
            val = float(self.scalar(torch.tensor(x, dtype=torch.float64)))
        self.counts['value_evaluations'] += 1
        if not np.isfinite(val):
            raise FloatingPointError('nonfinite objective')
        return val

    def gradient(self, x):
        self.counts['gradient_requests'] += 1
        self.build(x)
        return self.g.detach().numpy().copy()

    def hvp(self, x, v):
        self.build(x)
        self.counts['hvp'] += 1
        tangent = torch.as_tensor(np.asarray(v), dtype=torch.float64)
        result = torch.autograd.grad(self.g, self.z, grad_outputs=tangent,
                                     retain_graph=True)[0].detach().numpy()
        if not np.isfinite(result).all():
            raise FloatingPointError('nonfinite Hessian-vector product')
        return result

    def dense(self, x):
        self.check()
        self.counts['full_hessians'] += 1
        self.counts['forward_tangent_lanes'] += len(x)
        H = torch.func.jacfwd(self.gradient_function)(torch.tensor(x)).detach().numpy()
        if not np.isfinite(H).all():
            raise FloatingPointError('nonfinite full Hessian')
        return (H + H.T) / 2


def empty_counts():
    return dict(value_requests=0, value_evaluations=0, gradient_requests=0,
                gradient_graphs=0, graph_state_points=0, hvp=0, full_hessians=0,
                forward_tangent_lanes=0, cache_hits=0, callbacks=0, updates=0,
                promotion_gradient_evaluations=0)


def fit(seed, method, schedule='cc5', seconds=8.):
    """Fixed CC3/CC5 or training-only error-triggered one-way CC3->CC5.

    Adaptive checks happen every five distinct changes. Promote if
    ||g5-g3||inf > .25 ||g3||inf, ||g3||inf <1e-3, or half the CPU cap
    is consumed. Restart the optimizer at accepted theta; do not carry stale
    quasi-Newton/Adam state across objectives. Check work is fully metered.
    """
    allowed = ('adam', 'dense', 'adjoint_ncg', 'ad_ncg', 'lbfgs', 'none')
    if method not in allowed or schedule not in ('cc3', 'cc5', 'adaptive'):
        raise ValueError('unsupported method/schedule')
    if not np.isfinite(seconds) or seconds <= 0 or seed < 0:
        raise ValueError('invalid seed/budget')
    policy = Policy('nonlinear', seed)
    selected = policy.initial.copy()
    problem = make_problem()
    counts, history, checks, stages = empty_counts(), [], [], []
    start, wall = time.process_time(), time.perf_counter()
    current = 'cc3' if schedule == 'adaptive' else schedule
    final_status, switch_reason = 'cpu_cap', None

    def clock():
        return time.process_time() - start

    def check():
        elapsed = clock()
        if elapsed >= seconds:
            raise Limit()
        if schedule == 'adaptive' and current == 'cc3' and elapsed >= seconds / 2:
            raise Promote('half_cap')

    def diagnostic():
        # Only training rules. No CC9/17, reference or evaluation probe enters fit.
        if schedule != 'adaptive' or current != 'cc3':
            return
        gradients = []
        for name in ('cc3', 'cc5'):
            if clock() >= seconds:
                raise Limit()
            st, wt = rule(name)
            with torch.no_grad():
                gg = adjoint(torch.tensor(selected), problem, st, wt)[1].numpy()
            counts['promotion_gradient_evaluations'] += 1
            gradients.append(gg)
        norm = float(np.max(np.abs(gradients[0])))
        delta = float(np.max(np.abs(gradients[1] - gradients[0])))
        promote = delta > .25 * norm or norm < 1e-3
        checks.append(dict(cpu=clock(), gradient3=norm, gradient_delta=delta,
                           promote=bool(promote), rule='cc3_cc5_training_only'))
        if promote:
            raise Promote('gradient_discrepancy_or_small_gradient')

    try:
        while method != 'none':
            st, wt = rule(current)
            check_law(st, wt)
            stage_start, count_start = clock(), counts['updates']
            explicit = method in ('dense', 'adjoint_ncg')
            engine = Derivatives(policy, problem, st, wt, explicit, counts, check)
            last_diag = counts['updates']
            scipy_status = None

            def callback(intermediate_result):
                nonlocal selected, last_diag
                candidate = intermediate_result.x.copy()
                changed = not np.array_equal(candidate, selected)
                counts['callbacks'] += 1
                counts['updates'] += int(changed)
                selected = candidate
                history.append(dict(cpu=clock(), rule=current,
                                    objective=float(intermediate_result.fun),
                                    updates=counts['updates'], hvp=counts['hvp'],
                                    full_hessians=counts['full_hessians']))
                if counts['updates'] - last_diag >= 5:
                    last_diag = counts['updates']
                    diagnostic()

            try:
                if method == 'adam':
                    z = torch.tensor(selected, requires_grad=True)
                    opt = torch.optim.Adam([z], lr=.015)
                    for _ in range(100000):
                        check()
                        opt.zero_grad(set_to_none=True)
                        loss = policy.value(z, problem, st, wt)
                        if not torch.isfinite(loss):
                            raise FloatingPointError('nonfinite Adam objective')
                        loss.backward()
                        counts['value_evaluations'] += 1
                        counts['gradient_requests'] += 1
                        opt.step()
                        selected = z.detach().numpy().copy()
                        counts['updates'] += 1
                        if counts['updates'] % 5 == 0:
                            history.append(dict(cpu=clock(), rule=current,
                                                objective=float(loss.detach()),
                                                metric_timing='pre_update',
                                                updates=counts['updates']))
                            diagnostic()
                else:
                    kwargs = dict(jac=engine.gradient, callback=callback)
                    if method == 'dense':
                        kwargs.update(method='trust-exact', hess=engine.dense)
                    elif method in ('ad_ncg', 'adjoint_ncg'):
                        kwargs.update(method='trust-ncg', hessp=engine.hvp)
                    else:
                        kwargs['method'] = 'L-BFGS-B'
                    options = dict(maxiter=10000, gtol=1e-9)
                    if method == 'lbfgs':
                        options.update(ftol=1e-14, maxls=40)
                    result = minimize(engine.value, selected, options=options, **kwargs)
                    selected = result.x.copy()
                    scipy_status = str(result.message)
                if schedule == 'adaptive' and current == 'cc3':
                    raise Promote('coarse_optimizer_terminated')
                final_status = scipy_status or 'iteration_limit'
                stages.append(dict(rule=current, cpu=clock()-stage_start,
                                   updates=counts['updates']-count_start,
                                   status=final_status))
                break
            except Promote as exc:
                stages.append(dict(rule=current, cpu=clock()-stage_start,
                                   updates=counts['updates']-count_start, status='promoted'))
                current, switch_reason = 'cc5', str(exc)
                # cached graphs from a former rule MUST NOT survive promotion.
                del engine
            except Limit:
                stages.append(dict(rule=current, cpu=clock()-stage_start,
                                   updates=counts['updates']-count_start, status='cpu_cap'))
                raise
    except Limit:
        pass
    if method == 'none':
        final_status = 'untrained'
    return selected, dict(cpu=clock(), wall=time.perf_counter()-wall,
                          cap=seconds, status=final_status, counts=counts,
                          stages=stages, promotion_checks=checks,
                          promotion_reason=switch_reason, final_rule=current,
                          history=history, overshoot=max(0., clock()-seconds),
                          matrix_free=method in ('adjoint_ncg', 'ad_ncg'))
