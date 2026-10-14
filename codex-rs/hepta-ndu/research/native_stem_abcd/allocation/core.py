"""R9: unchanged quality predicate, same-node Gaussian rule, exact lazy checks."""
from pathlib import Path
import sys
import time
import resource
import numpy as np
import torch
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scaling'))
from engine import Graph, EndFit, TARGET, TOLERANCE, CADENCE, CAP, qualifies
from wide import WidePolicy, rule, make_problem, evaluate, SCALE

METHODS = ('adam', 'lbfgs', 'adjoint_ncg', 'ad_ncg')


def training_rule(name):
    if name == 'cc5':
        return rule(name)
    if name != 'gl5':
        raise ValueError('unknown training rule')
    x, w = np.polynomial.legendre.leggauss(5)
    s = np.stack(np.meshgrid(*([x] * 4), indexing='ij'), -1).reshape(-1, 4) * SCALE
    weights = np.prod(np.stack(np.meshgrid(*([w / 2] * 4), indexing='ij'), -1), -1).reshape(-1)
    if not np.isfinite(s).all() or (weights <= 0).any() or abs(weights.sum() - 1) > 1e-13:
        raise ValueError('invalid quadrature')
    return s, weights / weights.sum()


def gate(evaluator, monitor):
    """Return exact predicate; skipped fine cost stays None, never fabricated."""
    if monitor not in ('full', 'lazy'):
        raise ValueError('unknown monitor')
    c5 = float(evaluator('cc5'))
    if not np.isfinite(c5):
        raise FloatingPointError('nonfinite coarse cost')
    if monitor == 'lazy' and c5 > TARGET:
        return c5, None, False
    c9 = float(evaluator('cc9'))
    if not np.isfinite(c9):
        raise FloatingPointError('nonfinite fine cost')
    return c5, c9, qualifies(c5, c9)


def fit(width, seed, method, train, monitor, cap=CAP):
    if method not in METHODS or monitor not in ('full', 'lazy') or train not in ('cc5', 'gl5'):
        raise ValueError('invalid method/rule/monitor')
    if not np.isfinite(cap) or cap <= 0:
        raise ValueError('invalid cap')
    started, cpu = time.perf_counter(), time.process_time()
    elapsed = lambda: time.perf_counter() - started
    policy = WidePolicy(width, seed)
    selected = policy.initial.copy()
    laws = {name: rule(name) for name in ('cc5', 'cc9')}
    states, weights = training_rule(train)
    problem = make_problem()
    counts = dict(graphs=0, hvp=0, full_hessians=0, objectives=0, cache_hits=0,
                  callbacks=0, updates=0, fine_calls=0, coarse_calls=0, skipped_fine=0)
    logs, checkpoints = [], []
    last_check, monitor_cpu, monitor_wall = -CADENCE, 0., 0.
    success, observed, status = False, None, 'wall_cap'

    def budget():
        if elapsed() >= cap:
            raise EndFit()

    def check(force=False, terminal=False):
        nonlocal last_check, monitor_cpu, monitor_wall, success, observed, status
        if not force and elapsed() - last_check < CADENCE:
            return
        start, cstart = elapsed(), time.process_time()
        tensor = torch.tensor(selected)

        def cost(name):
            counts['coarse_calls' if name == 'cc5' else 'fine_calls'] += 1
            s, w = laws[name]
            return float(w @ evaluate(policy, tensor, problem, s, chunk=256).mean(1))

        c5, c9, good = gate(cost, 'full' if terminal else monitor)
        counts['skipped_fine'] += int(c9 is None)
        checkpoints.append(selected.copy())
        end = elapsed()
        logs.append(dict(index=len(logs), start=start, end=end, cpu_end=time.process_time()-cpu,
                         cc5=c5, cc9=c9, predicate=good, within_cap=end <= cap,
                         terminal=terminal, updates=counts['updates']))
        monitor_cpu += time.process_time() - cstart
        monitor_wall += end - start
        last_check = end
        if good and end <= cap:
            success, observed, status = True, end, 'quality_reached'
            raise EndFit()

    try:
        check(True)
        graph = Graph(policy, states, weights, method == 'adjoint_ncg', budget, counts)
        if method == 'adam':
            theta = torch.tensor(selected, requires_grad=True)
            opt = torch.optim.Adam([theta], lr=.015)
            for _ in range(100000):
                budget()
                opt.zero_grad(set_to_none=True)
                value = policy.value(theta, problem, states, weights)
                if not torch.isfinite(value):
                    raise FloatingPointError('nonfinite Adam value')
                value.backward()
                opt.step()
                selected = theta.detach().numpy().copy()
                counts['objectives'] += 1
                counts['updates'] += 1
                check()
        else:
            def callback(intermediate_result):
                nonlocal selected
                new = intermediate_result.x.copy()
                counts['callbacks'] += 1
                counts['updates'] += int(not np.array_equal(new, selected))
                selected = new
                check()

            kwargs = dict(jac=graph.jac, callback=callback)
            options = dict(gtol=1e-9, maxiter=100000)
            if method == 'lbfgs':
                kwargs['method'] = 'L-BFGS-B'
                options.update(ftol=1e-14, maxls=40)
            else:
                kwargs.update(method='trust-ncg', hessp=graph.hvp)
                options.update(initial_trust_radius=1., max_trust_radius=1000., eta=.15)
            result = minimize(graph.fun, selected, options=options, **kwargs)
            selected = result.x.copy()
            status = str(result.message)
    except EndFit:
        pass
    if not success:
        try:
            check(True, terminal=True)
        except EndFit:
            pass
    if not np.isfinite(selected).all():
        raise FloatingPointError('nonfinite selected weights')
    info = dict(success=success, observed_wall=observed, status=status, checks=logs, counts=counts,
                wall=elapsed(), cpu=time.process_time()-cpu, monitor_wall=monitor_wall,
                monitor_cpu=monitor_cpu, fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024)
    return selected, np.asarray(checkpoints), info
