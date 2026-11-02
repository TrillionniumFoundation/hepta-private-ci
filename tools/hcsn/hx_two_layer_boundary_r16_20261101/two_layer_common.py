"""Create-only two-layer records; this module does not change frozen finance."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from two_layer_model import BatchedAssetReadout, TwoLayerBoundaryCell, load_adapter

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path); raw = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    payload = gzip.compress(raw, mtime=0) if path.name.endswith('.gz') else raw
    with path.open('xb') as f: f.write(payload)
    return {'path': str(path), 'bytes': len(payload), 'sha256': sha(path)}


def verify(expected):
    if sha(ROOT/'TWO_LAYER_PROTOCOL.json') != expected:
        raise ValueError('Wrong two-layer protocol')
    p = json.loads((ROOT/'TWO_LAYER_PROTOCOL.json').read_text())
    for name, digest in p['source_sha256'].items():
        if sha(ROOT/name) != digest: raise ValueError('Two-layer source changed '+name)
    if sha(ROOT/'TWO_LAYER_INPUTS.json') != p['inputs_sha256']:
        raise ValueError('Two-layer inputs changed')
    return p


def setup(adapter_root, financial_root, expected):
    p = verify(expected); data = json.loads((ROOT/'TWO_LAYER_INPUTS.json').read_text())
    module = load_adapter(adapter_root); backend = module.FrozenBackend(financial_root)
    operator = module.HXOperator(financial_root, 'asset', backend)
    readout = BatchedAssetReadout(operator)
    model = TwoLayerBoundaryCell(readout, torch.tensor(data['base1'], dtype=torch.float32), torch.tensor(data['base2'], dtype=torch.float32), p['cell'])
    return p, data, backend, operator, readout, model


def tensor(values, requires_grad=False):
    return torch.tensor(values, dtype=torch.float32, requires_grad=requires_grad)


def array(value):
    return value.detach().to(torch.float64).cpu().numpy()


def pack_trace(trace, include_internal=True):
    """Call before optimizer.step: raw Parameter entries are live in trace."""
    def layer(rows, last, dynamic):
        all_rows = rows+[last]
        result = {'Q_R_x': array(torch.stack([r['readout'] for r in all_rows])).tolist(),
                  'boundary': array(torch.stack([r['boundary'] for r in all_rows])).tolist(),
                  'asset': array(torch.stack([r['represented_asset'] for r in all_rows])).tolist()}
        if dynamic:
            result['effective_theta'] = array(torch.stack([r['effective_theta'] for r in all_rows])).tolist()
        else:
            result['effective_theta'] = array(trace['theta1']).tolist()
        asset, b = np.asarray(result['asset']), np.asarray(result['boundary'])
        phase = np.sign(asset-b).astype(int)
        result['phase'] = phase.tolist()
        result['actual_default_count'] = int(np.count_nonzero(asset <= b))
        result['sampled_phase_changes'] = [
            {'step': t, 'sample': j, 'from': int(phase[t, j]), 'to': int(phase[t+1, j])}
            for t in range(len(phase)-1) for j in range(phase.shape[1]) if phase[t, j] != phase[t+1, j]]
        return result
    result = {'state_order': ['z1', 'a1', 'z2', 'a2'], 'state': array(torch.stack(trace['state'])).tolist(),
              'layer1': layer(trace['layer1'], trace['final_layer1'], False),
              'layer2': layer(trace['layer2'], trace['final_layer2'], True),
              'links': array(torch.stack(trace['links'])).tolist(),
              'used_drive2': array(torch.stack(trace['used_drive2'])).tolist(),
              'drift': array(torch.stack(trace['drifts'])).tolist(),
              'raw_theta1': array(trace['raw_theta1']).tolist(), 'raw_theta2': array(trace['raw_theta2']).tolist(),
              'gradient_mode': trace['gradient_mode']}
    if include_internal:
        result.update({'theta1_tanh': array(trace['theta1_tanh']).tolist(),
                       'theta2_preactivation': array(torch.stack(trace['theta2_preactivation'])).tolist(),
                       'theta2_tanh': array(torch.stack(trace['theta2_tanh'])).tolist()})
    return result


def trace_checks(record, p, inputs):
    T, B, g = p['cell']['steps'], p['experiment']['batch_size'], p['gates']
    state = np.asarray(record['state'], dtype=np.float64)
    checks = {'state_shape': state.shape == (T+1, B, 4), 'state_finite': bool(np.isfinite(state).all()),
              'fixed_initial_state': np.array_equal(state[0], np.asarray(inputs['initial_state'])),
              'bounded_z': bool(np.min(state[..., [0, 2]]) >= g['min_z'] and np.max(state[..., [0, 2]]) <= g['max_z']),
              'bounded_adaptation': bool(np.min(state[..., [1, 3]]) >= -g['range_tolerance'] and np.max(state[..., [1, 3]]) <= g['max_adaptation'])}
    for name in ('layer1', 'layer2'):
        row = record[name]; obs, b, v = np.asarray(row['Q_R_x']), np.asarray(row['boundary']), np.asarray(row['asset'])
        default = v <= b
        checks[name+'_shapes'] = bool(obs.shape == (T+1, B, 3) and b.shape == v.shape == (T+1, B))
        checks[name+'_finite_positive_b_V'] = bool(all(np.isfinite(a).all() for a in (obs, b, v)) and np.min(b) > 0. and np.min(v) > 0.)
        checks[name+'_actual_default_values'] = bool(np.all(obs[..., 0][default] == 0.) and np.all(obs[..., 1][default] == 1.))
        checks[name+'_Q_R_range'] = bool(np.min(obs[..., 0]) >= -g['range_tolerance'] and np.min(obs[..., 1]) >= -g['range_tolerance'] and np.max(obs[..., 1]) <= 1.+g['range_tolerance'])
    b1, b2 = np.asarray(record['layer1']['boundary']), np.asarray(record['layer2']['boundary'])
    checks['layer1_boundary_constant_within_rollout'] = bool(np.max(np.abs(b1-b1[0])) <= g['constant_boundary_atol'])
    checks['layer2_boundary_changes_within_used_steps'] = bool(np.max(np.ptp(b2[:T], axis=0)) > g['minimum_boundary2_range'])
    theta2 = np.asarray(record['layer2']['effective_theta'])
    checks['theta2_shape_and_bound'] = bool(theta2.shape == (T+1, B, 9) and np.isfinite(theta2).all() and np.max(np.abs(theta2/np.asarray(inputs['base2'])-1.)) <= p['cell']['fraction']+2e-7)
    return {name: bool(value) for name, value in checks.items()}


def comparison(observed, reference, p):
    observed, reference = np.asarray(observed, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    if observed.shape != reference.shape or not np.isfinite(observed).all() or not np.isfinite(reference).all():
        return {'passed': False, 'shape_or_finite_failure': True, 'observed': observed.tolist(), 'reference': reference.tolist()}
    error = np.abs(observed-reference); allowance = p['gates']['gradient_atol']+p['gates']['gradient_rtol']*np.abs(reference)
    return {'passed': bool(np.all(error <= allowance)), 'observed': observed.tolist(), 'reference': reference.tolist(),
            'max_absolute_error': float(error.max()), 'max_error_over_allowance': float((error/allowance).max())}
