"""Nonfinancial checker controls; never load a candidate model or native kernel.

The deliberately invented readouts below test represented-record consistency,
not H-X mathematics, learned performance, or the forthcoming frozen experiment.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np


def load(path):
    spec = importlib.util.spec_from_file_location('_checker_under_review', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_trace():
    T, B = 16, 8
    config = dict(steps=T, dt=.05, leak=.5, k_equity=.15, k_risk=.04,
                  tau=.4, fraction=.03, coupling_gain=.2, conditioning_gain=.5,
                  z_rest1=4., z_rest2=4.)
    g = dict(gradient_atol=2e-9, gradient_rtol=2e-5,
             fp32_transcendental_ulps=4, min_z=3.5, max_z=4.7,
             max_adaptation=.08, range_tolerance=1e-10,
             constant_boundary_atol=1e-10, minimum_boundary2_range=1e-10,
             minimum_conditioning_vjp=1e-12, minimum_direct_boundary_vjp=1e-12,
             nonzero_gradient_floor=1e-12)
    p = {'cell': config, 'gates': g, 'experiment': {'batch_size': B}}
    c = {k: np.float32(v) for k, v in config.items()}
    data = dict(base1=np.ones(9, dtype=np.float32), base2=np.ones(9, dtype=np.float32),
                initial_state=np.stack((np.linspace(3.98, 4.02, B, dtype=np.float32),
                                        np.full(B, .01, dtype=np.float32),
                                        np.full(B, 4., dtype=np.float32),
                                        np.full(B, .01, dtype=np.float32)), axis=-1),
                drive1=np.full((T, B), .1, dtype=np.float32),
                drive2=np.full((T, B), .09, dtype=np.float32))
    state = [data['initial_state']]
    layers = [[], []]
    links, drives, drifts, preactivations, tanhs, theta2s = [], [], [], [], [], []
    for t in range(T+1):
        old = state[-1]
        v1, v2 = np.exp(old[:, 0]), np.exp(old[:, 2])
        b1 = np.full(B, 40.)
        x1 = np.log(v1.astype(np.float64)/b1)
        link = x1.astype(np.float32)
        pre = np.zeros(9, dtype=np.float32)+c['conditioning_gain']*link[:, None]
        tanh = np.tanh(pre)
        theta2 = data['base2']*(np.float32(1.)+c['fraction']*tanh)
        b2 = 39.5+.5*theta2[:, 0].astype(np.float64)
        qrx1 = np.stack((np.full(B, .1), np.full(B, .2), x1), axis=-1)
        qrx2 = np.stack((np.full(B, .12), np.full(B, .3), np.log(v2.astype(np.float64)/b2)), axis=-1)
        layers[0].append((qrx1, b1, v1)); layers[1].append((qrx2, b2, v2))
        theta2s.append(theta2)
        if t == T:
            break
        used = data['drive2'][t]+c['coupling_gain']*link
        fields = []
        for coordinate, readout, drive in ((0, qrx1, data['drive1'][t]), (2, qrx2, used)):
            z, a = old[:, coordinate], old[:, coordinate+1]
            q, r = readout[:, 0].astype(np.float32), readout[:, 1].astype(np.float32)
            fields.extend((drive-c['leak']*(z-c['z_rest1'])-c['k_equity']*q-c['k_risk']*r+a,
                           (c['k_risk']*r-a)/c['tau']))
        drift = np.stack(fields, axis=-1)
        state.append(old+c['dt']*drift)
        links.append(link); drives.append(used); drifts.append(drift)
        preactivations.append(pre); tanhs.append(tanh)
    record = dict(state_order=['z1', 'a1', 'z2', 'a2'], state=np.asarray(state),
                  gradient_mode='full', raw_theta1=np.zeros(9), raw_theta2=np.zeros(9),
                  links=np.asarray(links), used_drive2=np.asarray(drives), drift=np.asarray(drifts),
                  theta1_tanh=np.zeros(9), theta2_preactivation=np.asarray(preactivations),
                  theta2_tanh=np.asarray(tanhs))
    for i, rows in enumerate(layers):
        qrx, boundary, asset = [np.stack([row[k] for row in rows]) for k in range(3)]
        phase = np.sign(asset-boundary).astype(int)
        record['layer'+str(i+1)] = dict(Q_R_x=qrx, boundary=boundary, asset=asset,
            phase=phase, actual_default_count=int(np.count_nonzero(asset <= boundary)),
            sampled_phase_changes=[], effective_theta=data['base1'] if i == 0 else np.asarray(theta2s))
    return record, data, p


def main(checker_path, output):
    checker = load(checker_path)
    rows = []
    def accept(name, fn):
        fn(); rows.append({'name': name, 'expected': 'accept', 'passed': True})
    def reject(name, fn, expected_message):
        try:
            fn()
        except (ValueError, KeyError, TypeError) as error:
            if expected_message not in str(error):
                raise AssertionError(name+' failed at unintended guard: '+str(error)) from error
            rows.append({'name': name, 'expected': 'reject', 'passed': True, 'error': str(error)})
        else:
            raise AssertionError(name+' was accepted')
    trace, data, p = synthetic_trace()
    check = lambda row: checker.check_trace(row, data, p, np.zeros(9), np.zeros(9), 'full', True)
    accept('invented nonfinancial FP32 trajectory', lambda: check(trace))
    def altered(path, fn):
        row = copy.deepcopy(trace); target = row
        for part in path[:-1]: target = target[part]
        target[path[-1]] = fn(target[path[-1]])
        return row
    mutations = [
        ('missing final state', ['state'], lambda a: a[:-1], 'Wrong shape'),
        ('changed Euler state', ['state'], lambda a: a+np.eye(17, 8, dtype=np.float32)[:, :, None]*np.float32(1e-3), 'Initial physical state'),
        ('wrong represented drift', ['drift'], lambda a: a+np.float32(.01), 'FP32 drift'),
        ('wrong continuous drive', ['used_drive2'], lambda a: a+np.float32(.01), 'Linear drive'),
        ('wrong link', ['links'], lambda a: a+np.float32(.01), 'Interlayer margin'),
        ('wrong preactivation', ['theta2_preactivation'], lambda a: np.nextafter(a, np.float32(np.inf)), 'preactivation'),
        ('wrong tanh', ['theta2_tanh'], lambda a: a+np.float32(.01), 'nonlinear record'),
        ('wrong downstream theta', ['layer2', 'effective_theta'], lambda a: a+np.float32(.01), 'Theta2/recorded'),
        ('wrong actual branch', ['layer2', 'phase'], lambda a: -a, 'branch record'),
        ('boolean phase cannot impersonate integer one', ['layer2', 'phase'], lambda a: a.astype(bool), 'branch record'),
        ('wrong default count', ['layer2', 'actual_default_count'], lambda a: a+1, 'Default count'),
        ('missing financial readout row', ['layer2', 'Q_R_x'], lambda a: a[:-1], 'Wrong shape'),
        ('wrong physical margin', ['layer2', 'Q_R_x'], lambda a: a+np.array([0., 0., .1]), 'margin'),
    ]
    for name, path, fn, error in mutations:
        reject(name, lambda path=path, fn=fn: check(altered(path, fn)), error)
    reject('nonfinite JSON', lambda: checker.finite_json({'x': float('nan')}), 'Nonfinite')
    reject('duplicate JSON object key', lambda: checker.unique_object([('x', 1), ('x', 2)]), 'Duplicate')
    reject('nonword actual gradient', lambda: checker.words([.1], (1,)), 'FP32 words')
    reject('missing trace flags', lambda: checker.flags({}, checker.TRACE_CHECKS, 'test'), 'Missing')
    comparison = dict(passed=True, observed=[1.], reference=[1.], max_absolute_error=1., max_error_over_allowance=0.)
    reject('forged comparison summary', lambda: checker.comparison(comparison, [1.], [1.], p['gates'], 'test'), 'summary mismatch')
    modes = {name: {'actual': {'raw1': np.zeros(9), 'raw2': np.ones(9)}} for name in checker.MODES}
    modes['full']['actual']['raw1'] = np.ones(9)
    modes['drive_only']['actual']['raw1'] = np.ones(9)
    identity = {'passed': True, 'checks': {name: True for name in checker.IDENTIFICATION_CHECKS}}
    reject('full gradient cannot hide dead conditioning', lambda: checker.check_identification({'identification': identity}, modes, p), 'Dead conditioning route')
    default_audit = {'modes': {name: {} for name in checker.MODES}, 'financial_reference': []}
    layer = {'boundary': np.full((16, 8), 40.), 'asset': np.full((16, 8), 30.),
             'Q_R_x': np.broadcast_to([0., 1., np.log(.75)], (16, 8, 3)).copy()}
    default_audit['modes']['full']['trajectory'] = {'layer1': layer, 'layer2': layer}
    for t in range(16):
        raw = np.broadcast_to([40., 0., 1., 1., 10.], (8, 5)).copy()
        default_audit['financial_reference'].append(dict(step=t, raw1=raw.copy(), raw2=raw.copy(),
            jac1=np.zeros((8, 5, 10)), jac2=np.zeros((8, 5, 10))))
    reject('valid invented default fields reach later missing-mode sentinel',
           lambda: checker.check_modes(default_audit, data, p, None), 'passed')
    corrupted = copy.deepcopy(default_audit)
    corrupted['financial_reference'][0]['jac2'][0, 1, 0] = .1
    reject('default-side equity derivative cannot create conditioning',
           lambda: checker.check_modes(corrupted, data, p, None), 'default E/F/G')
    corrupted = copy.deepcopy(default_audit)
    corrupted['financial_reference'][0]['raw2'][0, 3] = .5
    reject('default-side archived G must remain one',
           lambda: checker.check_modes(corrupted, data, p, None), 'default E/F/G')
    digest = hashlib.sha256(Path(checker_path).read_bytes()).hexdigest()
    receipt = {'schema': 'hcsn.two-layer-checker-nonfinancial-tests.v1', 'passed': True,
               'checker_sha256': digest, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               'count': len(rows), 'results': rows, 'financial_kernel_calls': 0, 'candidate_model_calls': 0,
               'scope': 'Synthetic invented readouts and direct checker guard tests only. No frozen two-layer experiment, financial values or numerical-performance validation.'}
    with Path(output).open('x') as f: json.dump(receipt, f, indent=2); f.write('\n')
    print(json.dumps({'passed': True, 'count': len(rows), 'checker_sha256': digest, 'output': str(output)}, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
