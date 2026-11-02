"""Actual channel-isolated VJPs on already fixed integration fixtures."""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import torch

from adapter_common import ROOT, sha, verify, write
from hx_autograd import FrozenBackend, HXOperator


def run(frozen_root, expected, output):
    protocol = verify(expected)
    source_hash = sha(Path(__file__))
    fixtures = json.loads((ROOT/'ADAPTER_FIXTURES.json').read_text())
    backend = FrozenBackend(frozen_root)
    rows = []
    for case in fixtures['cases']:
        packed = torch.tensor(case['packed'], dtype=torch.float32, requires_grad=True)
        layer = HXOperator(frozen_root, case['coordinate'], backend)
        channels = layer.readout(packed)
        gradients = torch.stack([torch.autograd.grad(channels[i], packed, retain_graph=True)[0] for i in range(3)])
        gradient_array = gradients.detach().to(torch.float64).numpy()
        norms = np.linalg.norm(gradient_array[:, :9], axis=1)
        continuation = 'continuation' in case['id']
        passed = bool(torch.isfinite(channels).all() and torch.isfinite(gradients).all())
        if continuation:
            passed = passed and bool(norms[0] > 0 and norms[1] > 0)
        if case['coordinate'] == 'log_distance':
            passed = passed and bool(np.max(abs(gradient_array[2, :9])) == 0 and gradient_array[2, 9] == 1)
        rows.append({'case': case['id'], 'coordinate': case['coordinate'], 'packed': case['packed'],
                     'channel_order': ['E_over_b', 'R', 'x'], 'values': channels.detach().tolist(),
                     'actual_basis_vjp': gradient_array.tolist(), 'financial_theta_vjp_norms': norms.tolist(),
                     'state_vjp': gradient_array[:, 9].tolist(), 'continuation_nonzero_required': continuation,
                     'passed': passed})
    training_path = ROOT/'TRAINING_SMOKE_V2.json.gz'
    training = json.loads(gzip.decompress(training_path.read_bytes()))
    if training['protocol_sha256'] != expected:
        raise ValueError('Training evidence belongs to another protocol')
    base = torch.tensor(fixtures['cases'][0]['packed'][:9], dtype=torch.float32)
    theta = {}
    for name in ('first.raw_theta', 'second.raw_theta'):
        initial = torch.tensor(training['parameters'][name]['initial'], dtype=torch.float32)
        final = torch.tensor(training['parameters'][name]['final'], dtype=torch.float32)
        represented_initial = base*(1.+.03*torch.tanh(initial))
        represented_final = base*(1.+.03*torch.tanh(final))
        theta[name] = {'initial_theta': represented_initial.tolist(), 'final_theta': represented_final.tolist(),
                       'max_relative_change': float(torch.max(abs(represented_final-represented_initial)/represented_initial)),
                       'first_step_actual_raw_theta_gradient': training['history'][0]['gradients'][name],
                       'first_step_gradient_norm': training['history'][0]['gradient_norms'][name],
                       'raw_parameter_update_norm': training['parameter_update_norms'][name]}
    backend.verify(); verify(expected)
    if sha(Path(__file__)) != source_hash:
        raise ValueError('Readout evidence source changed')
    result = {'schema': 'hcsn.hx-autograd-channel-vjp.v1', 'passed': all(r['passed'] for r in rows),
              'protocol_sha256': expected, 'script_sha256': source_hash, 'fixture_sha256': protocol['fixture_sha256'],
              'training_receipt_sha256': sha(training_path), 'binary_sha256': backend.protocol['binary_sha256'],
              'scope': 'Actual first-order channel-isolated VJPs on the six already fixed functional cases. Nonzero gradients establish wiring, not task benefit or mechanism necessity. The trainable financial theta changes do not prove learning an optimal stopping boundary policy.',
              'financial_calls': backend.calls, 'financial_states': backend.states,
              'channel_rows': rows, 'training_effective_theta': theta,
              'bypass_limit': 'In the log-distance interface, x has exactly zero theta derivatives. x and the neural head can still explain training-loss improvement; there is no ablation or generalization evidence.'}
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'passed': result['passed'],
                      'continuation_channel_theta_norms': {r['case']: r['financial_theta_vjp_norms'] for r in rows if r['continuation_nonzero_required']},
                      'training_theta': theta}, indent=2))
    return result['passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--frozen-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    raise SystemExit(0 if run(a.frozen_root, a.protocol_sha256, a.output) else 1)
