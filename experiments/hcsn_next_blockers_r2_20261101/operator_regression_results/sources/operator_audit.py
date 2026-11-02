"""Independent finite-model audit; each invocation preserves a new attempt."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import time
import traceback

for thread_variable in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ[thread_variable] = '1'

import numpy as np
from scipy.integrate import quad, quad_vec
from scipy.linalg import expm, expm_frechet, solve
from scipy.special import gammaln
from scipy.stats import poisson
import torch

from . import marked_flow as marked


HERE = Path(__file__).resolve().parent


def independent_generator(case, parameters=None):
    """Independent row generator assembled from declared physical jumps."""
    mu, sigma, boundary, reset, tau = case['parameters'] if parameters is None else parameters[:5]
    n, m = case['cells'], case['phases']
    h = (boundary - case['lower']) / n
    centers = case['lower'] + (np.arange(n) + .5) * h
    weights = np.zeros(n)
    left = min(n - 2, max(0, int(np.floor((reset - centers[0]) / h))))
    weights[left + 1] = (reset - centers[left]) / h
    weights[left] = 1 - weights[left + 1]
    diffusion = sigma * sigma / 2
    up, down = diffusion / h**2 + max(mu, 0) / h, diffusion / h**2 + max(-mu, 0) / h
    firing = 2 * diffusion / h**2 + max(mu, 0) / h
    q, mark = np.zeros((n + m, n + m)), np.zeros((n + m, n + m))
    for i in range(n):
        if i > 0:
            q[i, i - 1] += down
            q[i, i] -= down
        if i + 1 < n:
            q[i, i + 1] += up
            q[i, i] -= up
        else:
            q[i, i] -= firing
            if m:
                mark[i, n] = firing
            else:
                mark[i, :n] = firing * weights
    for j in range(m):
        rate = m / tau
        q[n + j, n + j] -= rate
        if j + 1 < m:
            q[n + j, n + j + 1] += rate
        else:
            q[n + j, :n] += rate * weights
    return q + mark, mark, centers, weights


def flow_for(case, parameters=None):
    parameters = case['parameters'] if parameters is None else parameters[:5]
    grid = marked.inherited.Grid(cells=case['cells'], lower=case['lower'], refractory_stages=case['phases'])
    return marked.inherited.make_flow(*[torch.as_tensor(x, dtype=torch.float64) for x in parameters], grid=grid)


def array(value):
    return value.detach().cpu().numpy() if torch.is_tensor(value) else np.asarray(value)


class Recorder:
    def __init__(self, out, protocol):
        self.out, self.protocol, self.rows, self.raw = out, protocol, [], []

    def check(self, name, passed, **data):
        row = dict(name=name, passed=bool(passed), **data)
        self.rows.append(row)
        with (self.out / 'cases.jsonl').open('a') as stream:
            stream.write(json.dumps(row, allow_nan=False) + '\n')

    def close(self, name, actual, reference, atol=None):
        a, b = array(actual), array(reference)
        tolerance = self.protocol['gates']['matrix_atol'] if atol is None else atol
        error = float(np.max(np.abs(a - b)))
        self.check(name, bool(np.isfinite(a).all()) and error <= tolerance,
                   max_absolute_error=error, tolerance=tolerance)


def scalar_cases(rec):
    tol = rec.protocol['gates']['probability_tolerance']
    for case in rec.protocol['cases']:
        name, duration = case['name'], case['duration']
        flow = flow_for(case)
        op = marked.operators(flow, duration)
        q, r, centers, reset = independent_generator(case)
        q0, rate, size = q - r, r.sum(-1), len(q)
        t, k = expm(q * duration), expm(q0 * duration)
        e, quadrature_error = quad_vec(lambda s: expm(q * s) @ rate, 0., duration,
                                       epsabs=1e-12, epsrel=1e-12)
        v = solve(case['rho'] * np.eye(size) - q, (case['parameters'][2] - case['cost']) * rate)
        value = marked.values(flow, case['rho'], case['cost'])
        for key, reference in [('Q', q), ('R', r), ('Q0', q0), ('transition', t), ('killed', k), ('event_vector', e)]:
            rec.close(name + '/' + key, op[key], reference)
        rec.close(name + '/same_q_value', value['value_vector'], v)
        inherited_value = marked.inherited.policy_value_vectors(flow, case['rho'], case['cost'])
        rec.close(name + '/inherited_value', value['value_vector'], inherited_value['J'])
        rec.close(name + '/discounted_next', value['next_event_discount_vector'],
                  solve(case['rho'] * np.eye(size) - q0, rate))
        rec.check(name + '/probability_invariants', float(t.min()) >= -tol and float(k.min()) >= -tol
                  and np.max(np.abs(t.sum(-1) - 1)) <= tol and float((1 - k.sum(-1)).min()) >= -tol
                  and float((e - (1 - k.sum(-1))).min()) >= -tol,
                  generator_rank=int(np.linalg.matrix_rank(q)), states=size, quad_error=float(quadrature_error))
        zero = marked.operators(flow, 0.)
        rec.close(name + '/time_zero', zero['transition'], np.eye(size))
        rec.close(name + '/time_zero_killed', zero['killed'], np.eye(size))
        rec.close(name + '/time_zero_count', zero['event_vector'], np.zeros(size))
        one, two = [marked.operators(flow, duration * split) for split in rec.protocol['semigroup_split']]
        rec.close(name + '/resampling_full', op['transition'], one['transition'] @ two['transition'])
        rec.close(name + '/resampling_killed', op['killed'], one['killed'] @ two['killed'])
        rec.close(name + '/resampling_count', op['event_vector'],
                  one['event_vector'] + one['transition'] @ two['event_vector'])
        if case['phases']:
            n, m, phase_rate = case['cells'], case['phases'], case['phases'] / case['parameters'][4]
            expected, _ = quad(lambda s: math.exp(m * math.log(phase_rate) + (m - 1) * math.log(s)
                - phase_rate * s - gammaln(m)) * (1 - reset @ expm(q0[:n, :n] * (duration - s)) @ np.ones(n)),
                0., duration, epsabs=1e-12)
            rec.close(name + '/next_event_from_refractory', 1 - k[n].sum(), expected)
        if name == 'instant_self_reset':
            rec.check(name + '/marked_self_loop_retained', float(np.diag(r).sum()) > 0,
                      marked_diagonal=float(np.diag(r).sum()))
        if name == 'zero_event':
            rec.close(name + '/zero_mark', r, np.zeros_like(r))
            rec.close(name + '/zero_value', value['value_vector'], np.zeros(size))
        rec.raw.append(dict(case=case, Q=q.tolist(), R=r.tolist(), transition=array(op['transition']).tolist(),
                            killed=array(op['killed']).tolist(), count=array(op['event_vector']).tolist(), value=array(value['value_vector']).tolist()))


def remap_and_witness(rec):
    case = rec.protocol['cases'][0]
    flow, settings = flow_for(case), rec.protocol['moving_boundary']
    n, m = case['cells'], case['phases']
    size = n + m
    old_edges = np.linspace(case['lower'], settings['old'], n + 1)
    new_edges = np.linspace(case['lower'], settings['new'], n + 1)
    overlap = np.maximum(0, np.minimum(old_edges[1:, None], new_edges[None, 1:])
                          - np.maximum(old_edges[:-1, None], new_edges[None, :-1])) / np.diff(old_edges)[:, None]
    m0 = np.zeros((size, size)); m0[:n, :n] = overlap; m0[n:, n:] = np.eye(m)
    hit = np.r_[np.maximum(0, old_edges[1:] - np.maximum(old_edges[:-1], settings['new'])) / np.diff(old_edges), np.zeros(m)]
    destination = np.eye(size)[n]
    full = m0 + hit[:, None] * destination
    p = np.ones(size) / size
    for duration in (0., settings['duration']):
        state = marked.advance(p, settings['old'], flow, duration)
        op = marked.operators(flow, duration)
        label = 'boundary/' + str(duration)
        rec.close(label + '/full_remap', state['remap'], full)
        rec.close(label + '/no_event_remap', state['no_event_remap'], m0)
        rec.close(label + '/full_state', state['probability'], p @ full @ array(op['transition']))
        rec.close(label + '/first_event', state['first_event'], 1 - p @ m0 @ array(op['killed']) @ np.ones(size))
        rec.close(label + '/count', state['events'], p @ hit + p @ full @ array(op['event_vector']))
    q, r, centers, _ = independent_generator(case)
    spec = rec.protocol['same_mean_witness']
    a, b = np.zeros(size), np.zeros(size)
    a[spec['point_index']] = 1.; b[spec['mixture_indices']] = spec['weights']
    first = 1 - expm((q - r) * case['duration']).sum(-1)
    means = [float(law[:n] @ centers) for law in (a, b)]
    risks = [float(law @ first) for law in (a, b)]
    rec.close('distribution_witness/equal_active_mean', means[0], means[1])
    rec.check('distribution_witness/different_first_event', abs(risks[0] - risks[1]) >= spec['min_first_event_gap'],
              means=means, first_event_probabilities=risks, initial_laws=[a.tolist(), b.tolist()])


def marked_count_law(q0, mark, initial, duration, tolerance):
    """Independent marked uniformization, retaining each count coefficient."""
    rate = max(float((-np.diag(q0)).max()), 1.)
    mean = rate * duration
    terms = max(1, int(poisson.ppf(1 - tolerance, mean)))
    while poisson.sf(terms, mean) > tolerance:
        terms += 1
    no_event, event = np.eye(len(q0)) + q0 / rate, mark / rate
    coefficients = np.zeros((terms + 1, len(q0))); coefficients[0] = initial
    result = np.zeros_like(coefficients)
    weight = math.exp(-mean)
    for order in range(terms + 1):
        result += weight * coefficients
        updated = coefficients @ no_event
        updated[1:] += coefficients[:-1] @ event
        coefficients = updated
        weight *= mean / (order + 1)
    return result, float(poisson.sf(terms, mean))


def tilted_checks(rec):
    spec = rec.protocol['tilted']
    for case in (rec.protocol['cases'][0], rec.protocol['cases'][2]):
        flow = flow_for(case); q, r, _, _ = independent_generator(case)
        size, duration = len(q), case['duration']
        p, content = np.ones(size) / size, np.linspace(-.7, 1.1, size)
        law, tail = marked_count_law(q - r, r, p, duration, spec['uniformization_poisson_tail'])
        moments, _ = marked_count_law(q - r, r, p * content, duration, spec['uniformization_poisson_tail'])
        counts = np.arange(len(law))
        for eta in spec['eta']:
            op = marked.tilted(flow, duration, eta, spec['decay'])
            weights = eta ** counts * math.exp(-spec['decay'] * duration)
            label = case['name'] + '/tilted/' + str(eta)
            rec.close(label + '/pgf', p @ array(op['transition']), weights @ law)
            rec.close(label + '/content_first_moment', (p * content) @ array(op['transition']), weights @ moments)
        op = marked.operators(flow, duration)
        rec.close(case['name'] + '/eta0_killed', marked.tilted(flow, duration, 0.)['transition'], op['killed'])
        rec.close(case['name'] + '/eta1_full', marked.tilted(flow, duration, 1.)['transition'], op['transition'])
        derivative = expm_frechet(q * duration, r * duration, compute_expm=False).sum(-1)
        rec.close(case['name'] + '/pgf_derivative_counts', derivative, op['event_vector'])
        rec.close(case['name'] + '/count_law_mean', counts @ law @ np.ones(size), p @ array(op['event_vector']))
        rec.check(case['name'] + '/count_law_tail', tail <= spec['uniformization_poisson_tail'], tail=tail)


def gradient_checks(rec):
    case = rec.protocol['cases'][0]
    theta = np.array(case['parameters'] + [case['duration'], case['rho'], case['cost']])
    x = torch.tensor(theta, dtype=torch.float64, requires_grad=True)
    flow = flow_for(case, x)
    op, value = marked.operators(flow, x[5]), marked.values(flow, x[6], x[7])
    size = op['Q'].shape[-1]; p = np.ones(size) / size; weights = np.linspace(-.4, .8, size)
    pt, wt = torch.tensor(p), torch.tensor(weights)
    objective = pt @ op['transition'] @ wt + .3 * (pt @ op['first_event_vector']) + .2 * (pt @ op['event_vector']) + .1 * (pt @ value['value_vector'])
    actual = array(torch.autograd.grad(objective, x)[0])
    q, r, _, _ = independent_generator(case, theta)
    rate = r.sum(-1); q0 = q - r
    augmented = np.zeros((size + 1, size + 1)); augmented[:size, :size] = q; augmented[:size, size] = rate
    system = theta[6] * np.eye(size) - q
    v = solve(system, (theta[2] - theta[7]) * rate)
    references = []
    for step in rec.protocol['derivatives']['central_steps']:
        derivatives = []
        for i in range(len(theta)):
            plus, minus = theta.copy(), theta.copy(); plus[i] += step; minus[i] -= step
            qp, rp, _, _ = independent_generator(case, plus); qm, rm, _, _ = independent_generator(case, minus)
            dq, dr = (qp - qm) / (2 * step), (rp - rm) / (2 * step)
            drate = dr.sum(-1)
            da = np.zeros_like(augmented); da[:size, :size] = dq; da[:size, size] = drate
            de = expm_frechet(augmented * theta[5], da * theta[5] + augmented * (i == 5), compute_expm=False)
            dk = expm_frechet(q0 * theta[5], (dq - dr) * theta[5] + q0 * (i == 5), compute_expm=False)
            dg = (theta[2] - theta[7]) * drate + ((i == 2) - int(i == 7)) * rate
            dv = solve(system, dg - ((i == 6) * np.eye(size) - dq) @ v)
            derivatives.append(p @ de[:size, :size] @ weights - .3 * (p @ dk).sum() + .2 * (p @ de[:size, size]) + .1 * (p @ dv))
        references.append(np.array(derivatives))
    gates = rec.protocol['gates']
    for i, name in enumerate(rec.protocol['derivatives']['parameter_order']):
        tolerance = gates['gradient_atol'] + gates['gradient_rtol'] * abs(references[-1][i])
        rec.check('gradient/' + name, abs(actual[i] - references[-1][i]) <= tolerance
                  and abs(references[0][i] - references[1][i]) <= gates['step_stability_atol'],
                  actual=float(actual[i]), reference_steps=[float(a[i]) for a in references], tolerance=tolerance)


def batch_checks(rec):
    case = rec.protocol['cases'][0]
    parameters = [torch.full(tuple(rec.protocol['batch_shape_check']), v, dtype=torch.float64)
                  for v in case['parameters']]
    parameters[0] += torch.tensor([[0., -.11], [.04, .08]], dtype=torch.float64)
    grid = marked.inherited.Grid(cells=case['cells'], lower=case['lower'], refractory_stages=case['phases'])
    flow = marked.inherited.make_flow(*parameters, grid=grid)
    duration = torch.tensor([[.2, .7], [.3, 0.]], dtype=torch.float64)
    op, value = marked.operators(flow, duration), marked.values(flow, .43, .4)
    tilt = marked.tilted(flow, duration, .7, .11)
    for i in range(2):
        for j in range(2):
            scalar = marked.inherited.make_flow(*[v[i, j] for v in parameters], grid=grid)
            reference = marked.operators(scalar, duration[i, j])
            for key in ('Q', 'R', 'Q0', 'transition', 'killed', 'event_vector'):
                rec.close(f'batch/{i}/{j}/{key}', op[key][i, j], reference[key])
            rec.close(f'batch/{i}/{j}/value', value['value_vector'][i, j], marked.values(scalar, .43, .4)['value_vector'])
            rec.close(f'batch/{i}/{j}/tilted', tilt['transition'][i, j], marked.tilted(scalar, duration[i, j], .7, .11)['transition'])


def refusals(rec):
    flow = flow_for(rec.protocol['cases'][0])
    checks = [('negative_time', lambda: marked.operators(flow, -1.)),
              ('nonfinite_time', lambda: marked.operators(flow, float('inf'))),
              ('rate_time_cap', lambda: marked.operators(flow, 1e10)),
              ('zero_discount', lambda: marked.values(flow, 0., .4)),
              ('eta_outside', lambda: marked.tilted(flow, .1, 1.1)),
              ('negative_decay', lambda: marked.tilted(flow, .1, .5, -.1)),
              ('invalid_mass', lambda: marked.advance(torch.ones(10), .91, flow, .1))]
    for name, action in checks:
        try:
            action(); refused = False
        except (ValueError, ArithmeticError):
            refused = True
        rec.check('refusal/' + name, refused)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--out', required=True)
    parser.add_argument('--stage', choices=('development', 'formal'), default='development')
    parser.add_argument('--frozen-commit'); args = parser.parse_args()
    if args.stage == 'formal' and (not args.frozen_commit or len(args.frozen_commit) != 40):
        parser.error('Formal execution requires the pre-execution source commit')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    protocol = json.loads((HERE / 'OPERATOR_PROTOCOL.json').read_text())
    sources = [HERE / name for name in ('marked_flow.py', 'operator_audit.py', 'OPERATOR_PROTOCOL.json', 'OPERATOR_CONTRACT.md')]
    sources += [Path(marked.inherited.__file__)]
    snapshot = out / 'sources'; snapshot.mkdir()
    freeze = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for p in sources:
        shutil.copyfile(p, snapshot / p.name)
    (out / 'SOURCE_FREEZE.json').write_text(json.dumps(dict(stage=args.stage, commit=args.frozen_commit, files=freeze), indent=2))
    torch.set_num_threads(1); rec = Recorder(out, protocol); start, cpu = time.perf_counter(), time.process_time()
    rec.check('upstream_identity', freeze[str(sources[-1])] == protocol['upstream_kernel_sha256'])
    try:
        scalar_cases(rec); remap_and_witness(rec); tilted_checks(rec); gradient_checks(rec); batch_checks(rec); refusals(rec)
    except Exception as error:
        (out / 'EXCEPTION.txt').write_text(traceback.format_exc()); rec.check('execution_exception', False, error=str(error))
    rec.check('source_unchanged', all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in freeze.items()))
    failures = [row for row in rec.rows if not row['passed']]
    summary = dict(stage=args.stage, frozen_commit=args.frozen_commit, checks=len(rec.rows), failed=len(failures), success=not failures,
                   cpu_seconds=time.process_time() - cpu, wall_seconds=time.perf_counter() - start,
                   clock_scope='Audit phases after imports; use root process receipt for full cost', not_established=protocol['not_established'])
    for name, data in [('SUMMARY.json', summary), ('FAILURES.json', failures), ('RAW_OPERATORS.json', rec.raw)]:
        (out / name).write_text(json.dumps(data, indent=2, allow_nan=False))
    print(json.dumps(summary)); return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
