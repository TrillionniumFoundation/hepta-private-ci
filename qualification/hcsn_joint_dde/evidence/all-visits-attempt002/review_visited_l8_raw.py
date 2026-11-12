"""Independent backward-value recheck of all retained uniform/tail posteriors.

The discrete candidate value is integrated as a piecewise linear backward
function on each SAME original uniform density. This is not a claim that the
old posterior was replayed by the DDE state transport or historical weights.
"""

import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.integrate import quad
from scipy.linalg import solve_banded


def identity(path):
    data = path.read_bytes()
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def mean_exp(rate, left, right):
    return math.exp(-rate * left) * -math.expm1(-rate * (right - left)) / (rate * (right - left))


def finite_phi(x, endpoint, mu, sigma, q):
    kappa = math.sqrt(mu * mu + 2 * q * sigma * sigma)
    alpha = 2 * q / (kappa - mu) if mu < 0 else (mu + kappa) / sigma**2
    beta = kappa / sigma**2
    return math.exp(-alpha * x) * -math.expm1(-2 * beta * (endpoint - x)) / -math.expm1(-2 * beta * endpoint)


def main(output):
    started, cpu = time.perf_counter(), time.process_time()
    root = Path('/workspace/scratch/c06d659c1e72/visited-originals/training-domain-original/run/audit')
    inputs = {str(p): identity(p) for p in sorted(root.glob('*.derived.jsonl'))}
    rows = []
    for path in map(Path, inputs):
        with path.open() as stream:
            for line in stream:
                item = json.loads(line)
                if item['kind'] == 'visit':
                    rows.append((path.name, item))
    if len(rows) != 14336 or len(inputs) != 12:
        raise ValueError('original full roster required')
    first = rows[0][1]
    g, params, op = first['grid'], first['parameters'], first['operator']
    originalL, L, mu, sigma, q = g['endpoint'], 8.0, params['mu'], params['sigma'], params['discount']
    d, a, h = g['refractory'], op['active_reward'], op['hit_reward']
    for _, row in rows:
        if row['grid'] != g or row['operator'] != op or any(row['parameters'][name] != params[name]
            for name in ('mu', 'sigma', 'discount', 'absolute_reset')):
            raise ValueError('this independent reference expects the verified fixed-physics roster')
    kappa = math.sqrt(mu * mu + 2 * q * sigma**2)
    alpha = 2 * q / (kappa - mu)
    eta, base = math.exp(-q * d), a / q
    active_edges = np.linspace(0, originalL, g['active_cells'] + 1)
    phase_edges = np.linspace(0, d, g['phase_cells'] + 1)
    half_means = np.array([mean_exp(alpha, l, r) for l, r in zip(active_edges, active_edges[1:])]
        + [math.exp(-alpha * originalL) * g['tail_rate'] / (g['tail_rate'] + alpha)])
    finite_means = np.array([quad(lambda x: finite_phi(x, L, mu, sigma, q), l, r,
                                  epsabs=1e-13, epsrel=1e-13)[0] / (r - l)
                            for l, r in zip(active_edges, active_edges[1:])] + [quad(lambda x: g['tail_rate'] * math.exp(-g['tail_rate'] * (x-originalL)) * finite_phi(x,L,mu,sigma,q),originalL,L,epsabs=1e-13,epsrel=1e-13)[0]])
    phase_means = np.array([mean_exp(q, l, r) for l, r in zip(phase_edges, phase_edges[1:])])
    panels = []
    all_values, filenames = [], []
    for n in (128, 256, 512):
        spacing = L / n
        down, up = sigma**2 / (2 * spacing**2) - mu / (2 * spacing), sigma**2 / (2 * spacing**2) + mu / (2 * spacing)
        if min(down, up) < 0:
            raise ValueError('inadmissible central rates')
        band = np.zeros((3, n - 1)); band[0, 1:] = -up; band[1] = q + down + up; band[2, :-1] = -down
        rhs = np.zeros(n - 1); rhs[0] = down
        phi = np.r_[1., solve_banded((1, 1), band, rhs), 0.]
        nodes = np.linspace(0, L, n + 1)
        candidate_list = []
        for left, right in zip(active_edges, active_edges[1:]):
            points=np.r_[left,nodes[(nodes>left)&(nodes<right)],right]
            heights=np.interp(points,nodes,phi)
            candidate_list.append(float(np.sum(np.diff(points)*(heights[:-1]+heights[1:])/2)/(right-left)))
        tail=0.
        points=np.r_[originalL,nodes[nodes>originalL]]
        heights=np.interp(points,nodes,phi)
        rate=g['tail_rate']
        for left,right,lo,hi in zip(points[:-1],points[1:],heights[:-1],heights[1:]):
            width=right-left
            zero=-math.expm1(-rate*width)
            first=zero/rate-width*math.exp(-rate*width)
            tail+=math.exp(-rate*(left-originalL))*(lo*zero+(hi-lo)/width*first)
        candidate_means=np.array(candidate_list+[tail])
        errors, spatial_errors, truncation_errors, original_values = [], [], [], []
        for file, row in rows:
            p = np.asarray(row['posterior'][0])
            reset = math.log(row['parameters']['absolute_reset']) - row['parameters']['log_boundary']
            def backward(means, reset_phi):
                reset_value = (base * (1-reset_phi) + h * reset_phi)/(1-eta*reset_phi)
                active_values = base + means * (h + eta * reset_value - base)
                return float(p[:len(means)] @ active_values + p[len(means):] @ (phase_means * reset_value))
            exact = backward(half_means, math.exp(-alpha * reset))
            finite = backward(finite_means, finite_phi(reset, L, mu, sigma, q))
            candidate = backward(candidate_means, np.interp(reset, nodes, phi))
            scale = max(1., abs(exact))
            errors.append(abs(candidate-exact)/scale)
            spatial_errors.append(abs(candidate-finite)/scale)
            truncation_errors.append(abs(finite-exact)/scale)
            original_values.append(exact)
            all_values.append((n,row['index'],candidate,exact,finite))
            filenames.append(file)
        errors, spatial_errors, truncation_errors = map(np.asarray, (errors, spatial_errors, truncation_errors))
        panels.append({'intervals':n, 'positions':len(rows), 'one_percent_failures':int(np.sum(errors > .01)),
            'separate_error_sum_failures': int(np.sum(spatial_errors + truncation_errors > .01)),
            'scaled_error_min_median_max': [float(np.min(errors)),float(np.median(errors)),float(np.max(errors))],
            'maximum_spatial_scaled_error':float(max(spatial_errors)),
            'maximum_truncation_scaled_error':float(max(truncation_errors)),
            'maximum_separate_error_sum':float(max(spatial_errors+truncation_errors)),
            'exact_value_range':[min(original_values),max(original_values)]})
    if inputs != {str(p): identity(p) for p in map(Path, inputs)}:
        raise ValueError('original sidecar bytes changed')
    artifact=Path(output).with_suffix('.npz')
    if artifact.exists(): raise ValueError('fresh artifact required')
    np.savez_compressed(artifact,rows=np.asarray(all_values),filenames=np.asarray(filenames))
    report = {'array':identity(artifact),'schema':'hcsn-independent-all-visit-backward-values-v1','inputs':inputs,
              'source':identity(Path(__file__)),'complete_original_positions':len(rows),
              'panels':panels,'physical_parameters':params,'grid':g,
              'limits':{'scaled_continuation_value_error':.01},
              'state_transport_qualified':False,'historical_weight_reconstruction':False,
              'candidate_endpoint':L,'scope':'same original uniform/tail posterior laws; candidate backward linear interpolation, not old state replay',
              'scientific_admission':'HOLD_NO_GO','wall_seconds':time.perf_counter()-started,'cpu_seconds':time.process_time()-cpu}
    with Path(output).open('x') as stream:
        json.dump(report,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
    print(json.dumps(report,sort_keys=True,allow_nan=False))


if __name__ == '__main__':
    import sys
    main(sys.argv[1])
