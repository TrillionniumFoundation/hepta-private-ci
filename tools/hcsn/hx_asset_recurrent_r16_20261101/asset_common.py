"""Fixed-potential source seals, create-only receipts and complete traces."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from asset_model import FixedPotentialCell, FixedPotentialReadout, load_adapter

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    raw = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    payload = gzip.compress(raw, mtime=0) if path.name.endswith('.gz') else raw
    with path.open('xb') as f:
        f.write(payload)
    return {'path': str(path), 'bytes': len(payload), 'sha256': sha(path)}


def verify(expected):
    if sha(ROOT/'ASSET_PROTOCOL.json') != expected:
        raise ValueError('Wrong fixed-potential protocol')
    p = json.loads((ROOT/'ASSET_PROTOCOL.json').read_text())
    for name, expected_sha in p['source_sha256'].items():
        if sha(ROOT/name) != expected_sha:
            raise ValueError('Fixed-potential source changed: '+name)
    if sha(ROOT/'ASSET_INPUTS.json') != p['inputs_sha256']:
        raise ValueError('Fixed-potential inputs changed')
    return p


def setup(adapter_root, financial_root, expected):
    p = verify(expected)
    module = load_adapter(adapter_root)
    backend = module.FrozenBackend(financial_root)
    operator = module.HXOperator(financial_root, 'asset', backend)
    readout = FixedPotentialReadout(operator)
    inputs = json.loads((ROOT/'ASSET_INPUTS.json').read_text())
    cell = FixedPotentialCell(readout, torch.tensor(inputs['base_theta'], dtype=torch.float32), p['cell'])
    return p, inputs, backend, operator, readout, cell


def tensor(values, requires_grad=False):
    return torch.tensor(values, dtype=torch.float32, requires_grad=requires_grad)


def array(value):
    return value.detach().to(torch.float64).cpu().numpy()


def pack_trace(trace):
    z = array(torch.stack(trace['z'])); a = array(torch.stack(trace['adaptation']))
    obs = array(torch.stack(trace['readouts'])); last = array(trace['final_readout'])
    assets = np.concatenate((array(torch.stack(trace['assets'])), array(trace['final_asset'])[None, :]), axis=0)
    margin = np.concatenate((obs[..., 2], last[None, :, 2]), axis=0)
    phases = np.sign(margin).astype(int)
    crossings = []
    for t in range(len(z)-1):
        for j in range(z.shape[1]):
            if phases[t, j] != phases[t+1, j]:
                crossings.append({'step': t, 'sample': j, 'from': int(phases[t, j]), 'to': int(phases[t+1, j]),
                                  'margin_before': float(margin[t, j]), 'margin_after': float(margin[t+1, j]),
                                  'z_before': float(z[t, j]), 'z_after': float(z[t+1, j]),
                                  'drive': float(trace['drive'][t, j].detach())})
    return {'z': z.tolist(), 'adaptation': a.tolist(), 'represented_asset': assets.tolist(),
            'readout_Q_R_x': obs.tolist(), 'final_diagnostic_readout_Q_R_x': last.tolist(),
            'margin': margin.tolist(), 'phase': phases.tolist(), 'crossings': crossings,
            'log_asset_minus_z': (np.log(assets)-z).tolist(),
            'drift_dz_da': array(torch.stack(trace['drifts'])).tolist(),
            'theta': array(trace['theta']).tolist(), 'fixed_z_rest': float(trace['fixed_z_rest']),
            'detach_state_negative_control': trace['detach_state_negative_control']}


def trace_checks(row, p):
    z, a, obs = np.asarray(row['z']), np.asarray(row['adaptation']), np.asarray(row['readout_Q_R_x'])
    assets, margin = np.asarray(row['represented_asset']), np.asarray(row['margin'])
    T, B, g = p['cell']['steps'], z.shape[1], p['gates']
    nonpositive = margin[:-1] <= 0.
    return {'complete_shapes': bool(z.shape == (T+1, B) and a.shape == z.shape and assets.shape == z.shape and margin.shape == z.shape and obs.shape == (T, B, 3)),
            'all_finite': bool(all(np.isfinite(v).all() for v in (z, a, obs, assets, margin))),
            'fixed_rest_reference': row['fixed_z_rest'] == p['cell']['z_rest'],
            'bounded_z': bool(np.min(z) >= g['min_z'] and np.max(z) <= g['max_z']),
            'bounded_adaptation': bool(np.min(a) >= -g['range_tolerance'] and np.max(a) <= g['max_adaptation']),
            'positive_represented_assets': bool(np.min(assets) > 0.),
            'risk_in_range': bool(np.min(obs[..., 1]) >= -g['range_tolerance'] and np.max(obs[..., 1]) <= 1.+g['range_tolerance']),
            'equity_nonnegative': bool(np.min(obs[..., 0]) >= -g['range_tolerance']),
            'true_asset_default_Q_R': bool(np.all(obs[..., 0][nonpositive] == 0.) and np.all(obs[..., 1][nonpositive] == 1.))}


def comparison(observed, reference, p):
    observed, reference = np.asarray(observed, dtype=np.float64), np.asarray(reference, dtype=np.float64)
    if observed.shape != reference.shape or not np.isfinite(observed).all() or not np.isfinite(reference).all():
        return {'passed': False, 'observed': observed.tolist(), 'reference': reference.tolist(), 'shape_or_finite_failure': True}
    error = np.abs(observed-reference); allowance = p['gates']['gradient_atol']+p['gates']['gradient_rtol']*np.abs(reference)
    return {'passed': bool(np.all(error <= allowance)), 'observed': observed.tolist(), 'reference': reference.tolist(),
            'absolute_error': error.tolist(), 'allowance': allowance.tolist(),
            'max_absolute_error': float(np.max(error)), 'max_error_over_allowance': float(np.max(error/allowance))}
