"""R8 metered first-observed-quality stopping, without dense Hessians."""
import time
import resource
import numpy as np
import torch
from scipy.optimize import minimize
from wide import WidePolicy, rule, make_problem, evaluate

TARGET = .04850
TOLERANCE = 1e-6
CADENCE = .5
CAP = 12.


def qualifies(c5, c9):
    return bool(np.isfinite([c5, c9]).all() and max(c5, c9) <= TARGET and abs(c5-c9) <= TOLERANCE)


class EndFit(Exception):
    pass


class Graph:
    def __init__(self, policy, states, weights, explicit, check, counts):
        self.policy, self.states, self.weights = policy, states, weights
        self.explicit, self.check, self.counts = explicit, check, counts
        self.key = None
        self.p = make_problem()

    def scalar(self, z):
        return self.policy.value(z, self.p, self.states, self.weights)

    def build(self, x):
        self.check()
        if self.key is not None and np.array_equal(x, self.key):
            self.counts['cache_hits'] += 1
            return
        self.key = None
        self.z = torch.tensor(x, dtype=torch.float64, requires_grad=True)
        if self.explicit:
            self.f, self.g = self.policy.adjoint(self.z, self.p, self.states, self.weights)
        else:
            self.f = self.scalar(self.z)
            self.g = torch.autograd.grad(self.f, self.z, create_graph=True)[0]
        if not torch.isfinite(self.f) or not torch.isfinite(self.g).all():
            raise FloatingPointError('nonfinite gradient graph')
        self.key = x.copy()
        self.counts['graphs'] += 1

    def fun(self, x):
        self.check(); self.counts['objectives'] += 1
        if self.key is not None and np.array_equal(x, self.key):
            return float(self.f.detach())
        with torch.no_grad():
            value = float(self.scalar(torch.tensor(x)))
        if not np.isfinite(value):
            raise FloatingPointError('nonfinite cost')
        return value

    def jac(self, x):
        self.build(x)
        return self.g.detach().numpy().copy()

    def hvp(self, x, v):
        self.build(x); self.counts['hvp'] += 1
        a = torch.autograd.grad(self.g, self.z, torch.as_tensor(v), retain_graph=True)[0]
        if not torch.isfinite(a).all():
            raise FloatingPointError('nonfinite HVP')
        return a.detach().numpy().copy()


def fit(width, seed, method, cap=CAP):
    if method not in ('adam', 'lbfgs', 'adjoint_ncg', 'ad_ncg') or not np.isfinite(cap) or cap <= 0:
        raise ValueError('method/cap')
    start, cpu_start = time.perf_counter(), time.process_time()
    clock = lambda: time.perf_counter()-start
    policy = WidePolicy(width, seed); selected = policy.initial.copy()
    laws = {n: rule(n) for n in ('cc5', 'cc9')}; p = make_problem()
    counts = dict(graphs=0, hvp=0, full_hessians=0, objectives=0, cache_hits=0, callbacks=0, updates=0)
    checks, checkpoints = [], []
    last_check, monitor_cpu, monitor_wall = -CADENCE, 0., 0.
    success, status, observed = False, 'wall_cap', None

    def check():
        if clock() >= cap:
            raise EndFit()

    def monitor(force=False):
        nonlocal last_check, monitor_cpu, monitor_wall, success, observed, status
        if not force and clock()-last_check < CADENCE:
            return
        before, cpu = clock(), time.process_time()
        costs = {}
        z = torch.tensor(selected)
        for name in ('cc5', 'cc9'):
            s, w = laws[name]
            costs[name] = float(w@evaluate(policy, z, p, s, chunk=256).mean(1))
        cp = selected.copy(); checkpoints.append(cp)
        end = clock()
        good = qualifies(costs['cc5'], costs['cc9'])
        checks.append(dict(index=len(checks), wall_start=before, wall_end=end,
                           cpu_end=time.process_time()-cpu_start, **costs,
                           predicate=good, within_cap=end<=cap, updates=counts['updates']))
        monitor_cpu += time.process_time()-cpu; monitor_wall += end-before
        last_check = end
        if good and end <= cap:
            success, status, observed = True, 'quality_reached', end
            raise EndFit()

    try:
        monitor(True)
        s, w = laws['cc5']
        graph = Graph(policy, s, w, method=='adjoint_ncg', check, counts)
        if method == 'adam':
            z = torch.tensor(selected, requires_grad=True)
            opt = torch.optim.Adam([z], lr=.015)
            for _ in range(100000):
                check(); opt.zero_grad(set_to_none=True)
                f = policy.value(z, p, s, w)
                if not torch.isfinite(f):
                    raise FloatingPointError('nonfinite Adam cost')
                f.backward(); opt.step(); counts['objectives'] += 1
                selected = z.detach().numpy().copy(); counts['updates'] += 1
                monitor()
        else:
            def callback(intermediate_result):
                nonlocal selected
                new = intermediate_result.x.copy(); counts['callbacks'] += 1
                counts['updates'] += int(not np.array_equal(new, selected)); selected = new
                monitor()
            kwargs = dict(jac=graph.jac, callback=callback)
            options = dict(gtol=1e-9, maxiter=100000)
            if method == 'lbfgs':
                kwargs['method'] = 'L-BFGS-B'; options.update(ftol=1e-14, maxls=40)
            else:
                kwargs.update(method='trust-ncg', hessp=graph.hvp)
                options.update(initial_trust_radius=1., max_trust_radius=1000., eta=.15)
            result = minimize(graph.fun, selected, options=options, **kwargs)
            selected = result.x.copy(); status = str(result.message)
    except EndFit:
        pass
    if not success:
        try:
            monitor(True)
        except EndFit:
            pass
    report = dict(success=success, status=status, observed_wall=observed,
                  wall=clock(), cpu=time.process_time()-cpu_start,
                  monitor_wall=monitor_wall, monitor_cpu=monitor_cpu,
                  counts=counts, checks=checks, fit_peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                  timing='first observed completed qualifying monitor, includes monitoring; not exact first hitting time')
    return selected, np.array(checkpoints), report
