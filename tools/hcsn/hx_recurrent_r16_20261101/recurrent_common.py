"""Create-only receipts, immutable dependency seals and full trace records."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from recurrent import HXRecurrentCell, SignedC1Readout, load_adapter

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    encoded = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    payload = gzip.compress(encoded, mtime=0) if path.name.endswith('.gz') else encoded
    with path.open('xb') as f:
        f.write(payload)
    return {'path': str(path), 'bytes': len(payload), 'sha256': sha(path)}


def verify(expected):
    path = ROOT/'RECURRENT_PROTOCOL.json'
    if sha(path) != expected:
        raise ValueError('Wrong recurrent protocol')
    protocol = json.loads(path.read_text())
    for name, expected_sha in protocol['source_sha256'].items():
        if sha(ROOT/name) != expected_sha:
            raise ValueError('Recurrent source changed: '+name)
    if sha(ROOT/'RECURRENT_INPUTS.json') != protocol['inputs_sha256']:
        raise ValueError('Recurrent input manifest changed')
    return protocol


def setup(adapter_root, financial_root, expected):
    protocol = verify(expected)
    module = load_adapter(adapter_root)
    backend = module.FrozenBackend(financial_root)
    operator = module.HXOperator(financial_root, 'log_distance', backend)
    readout = SignedC1Readout(operator)
    inputs = json.loads((ROOT/'RECURRENT_INPUTS.json').read_text())
    cell = HXRecurrentCell(readout, torch.tensor(inputs['base_theta'], dtype=torch.float32), protocol['cell'])
    return protocol, inputs, backend, operator, readout, cell


def tensor(values, requires_grad=False):
    return torch.tensor(values, dtype=torch.float32, requires_grad=requires_grad)


def array(value):
    return value.detach().to(torch.float64).cpu().numpy()


def pack_trace(trace):
    xs = torch.stack(trace['x']).detach()
    adaptations = torch.stack(trace['adaptation']).detach()
    readouts = torch.stack(trace['readouts']).detach()
    drifts = torch.stack(trace['drifts']).detach()
    # Exact zero is its own recorded phase; crossing is sampled sign-category change.
    phase = torch.sign(xs).to(torch.int64)
    crossings = []
    for t in range(len(xs)-1):
        for j in range(xs.shape[1]):
            before, after = int(phase[t, j]), int(phase[t+1, j])
            if before != after:
                crossings.append({'step': t, 'sample': j, 'from': before, 'to': after,
                                  'x_before': float(xs[t, j]), 'x_after': float(xs[t+1, j]),
                                  'drive': float(trace['drive'][t, j].detach())})
    return {'x': xs.tolist(), 'adaptation': adaptations.tolist(), 'readout_Q_R_x': readouts.tolist(),
            'drift_dx_da': drifts.tolist(), 'theta': trace['theta'].detach().tolist(),
            'phase': phase.tolist(), 'crossings': crossings,
            'detach_state_negative_control': trace['detach_state_negative_control']}


def trace_checks(record, protocol):
    x = np.asarray(record['x'], dtype=np.float64)
    a = np.asarray(record['adaptation'], dtype=np.float64)
    obs = np.asarray(record['readout_Q_R_x'], dtype=np.float64)
    T, B = protocol['cell']['steps'], x.shape[1]
    return {'complete_shapes': bool(x.shape == (T+1, B) and a.shape == x.shape and obs.shape == (T, B, 3)),
            'all_finite': bool(np.isfinite(x).all() and np.isfinite(a).all() and np.isfinite(obs).all()),
            'bounded_x': bool(np.max(np.abs(x)) <= protocol['gates']['max_abs_x']),
            'bounded_adaptation': bool(np.min(a) >= -protocol['gates']['range_tolerance'] and np.max(a) <= protocol['gates']['max_adaptation']),
            'risk_in_range': bool(np.min(obs[..., 1]) >= -protocol['gates']['range_tolerance'] and np.max(obs[..., 1]) <= 1.+protocol['gates']['range_tolerance']),
            'equity_nonnegative': bool(np.min(obs[..., 0]) >= -protocol['gates']['range_tolerance'])}


def comparison(observed, reference, protocol):
    observed, reference = np.asarray(observed, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    if observed.shape != reference.shape or not np.isfinite(observed).all() or not np.isfinite(reference).all():
        return {'passed': False, 'observed': observed.tolist(), 'reference': reference.tolist(), 'shape_or_finite_failure': True}
    error = np.abs(observed-reference)
    allowance = protocol['gates']['gradient_atol']+protocol['gates']['gradient_rtol']*np.abs(reference)
    return {'passed': bool(np.all(error <= allowance)), 'observed': observed.tolist(), 'reference': reference.tolist(),
            'absolute_error': error.tolist(), 'allowance': allowance.tolist(),
            'max_absolute_error': float(np.max(error)), 'max_error_over_allowance': float(np.max(error/allowance))}
