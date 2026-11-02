"""Tiny two-layer differentiation smoke; training-set behavior is not efficacy."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
import torch

from adapter_common import ROOT, verify, write
from hx_autograd import FrozenBackend, HXOperator


class ToyHXLayer(torch.nn.Module):
    def __init__(self, width, base, frozen_root, backend):
        super().__init__()
        self.projection = torch.nn.Linear(width, 1)
        self.raw_theta = torch.nn.Parameter(torch.zeros(9, dtype=torch.float32))
        self.register_buffer('base_theta', base.clone())
        self.operator = HXOperator(frozen_root, 'log_distance', backend)

    def forward(self, inputs):
        margin = .002+.05*torch.nn.functional.softplus(self.projection(inputs))
        theta = self.base_theta*(1.+.03*torch.tanh(self.raw_theta))
        packed = torch.cat((theta.expand(len(inputs), 9), margin), dim=-1)
        fields = self.operator.readout(packed)
        # Explicit float64 financial evaluation -> float32 neural feature path.
        return torch.stack((100.*fields[:, 0], 2.*fields[:, 1]-1., 10.*fields[:, 2]), dim=-1).to(torch.float32)


class TwoLayerSmoke(torch.nn.Module):
    def __init__(self, base, frozen_root, backend):
        super().__init__()
        self.first = ToyHXLayer(1, base, frozen_root, backend)
        self.second = ToyHXLayer(3, base, frozen_root, backend)
        self.head = torch.nn.Linear(3, 1)

    def forward(self, inputs):
        return self.head(self.second(self.first(inputs))).squeeze(-1)


def run(frozen_root, expected, output):
    protocol = verify(expected)
    config = protocol['training_smoke']
    fixtures = json.loads((ROOT/'ADAPTER_FIXTURES.json').read_text())
    torch.manual_seed(config['seed'])
    backend = FrozenBackend(frozen_root)
    model = TwoLayerSmoke(torch.tensor(fixtures['cases'][0]['packed'][:9], dtype=torch.float32), frozen_root, backend)
    inputs = torch.linspace(-1., 1., config['batch_size'], dtype=torch.float32).unsqueeze(-1)
    target = .5*torch.sin(3*inputs[:, 0])+.3*inputs[:, 0].square()
    optimizer = torch.optim.Adam(model.parameters(), lr=config['learning_rate'])
    initial = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    start, cpu = time.perf_counter(), time.process_time()
    with torch.no_grad():
        before_predictions = model(inputs)
        before_loss = float((before_predictions-target).square().mean())
    history = []
    for step in range(config['steps']):
        optimizer.zero_grad(set_to_none=True)
        predictions = model(inputs)
        loss = (predictions-target).square().mean()
        if not bool(torch.isfinite(loss)):
            raise ArithmeticError('Nonfinite toy loss')
        loss.backward()
        gradient_norms, gradients = {}, {}
        for name, parameter in model.named_parameters():
            if parameter.grad is None or not bool(torch.isfinite(parameter.grad).all()):
                raise ArithmeticError('Missing/nonfinite gradient: '+name)
            gradient_norms[name] = float(torch.linalg.vector_norm(parameter.grad.detach().to(torch.float64)))
            gradients[name] = parameter.grad.detach().tolist()
        optimizer.step()
        if not all(bool(torch.isfinite(p).all()) for p in model.parameters()):
            raise ArithmeticError('Nonfinite updated parameter')
        history.append({'step': step, 'training_loss_before_update': float(loss.detach()),
                        'gradient_norms': gradient_norms, 'gradients': gradients})
    with torch.no_grad():
        after_predictions = model(inputs)
        after_loss = float((after_predictions-target).square().mean())
    updates = {name: float(torch.linalg.vector_norm((parameter.detach()-initial[name]).to(torch.float64))) for name, parameter in model.named_parameters()}
    parameters = {name: {'initial': initial[name].tolist(), 'final': parameter.detach().tolist()} for name, parameter in model.named_parameters()}
    backend.verify(); verify(expected)
    changed = all(value > 0 for value in updates.values())
    passed = bool(changed and after_loss < before_loss and len(history) == config['steps'])
    result = {'schema': 'hcsn.hx-autograd-training-smoke.v1', 'smoke_passed': passed,
              'scope': 'Two financial-feature layers and a small linear head, fit and measured only on the same synthetic training grid. Demonstrates first-order BP/update, not spiking/reset closure, generalization or superiority.',
              'protocol_sha256': expected, 'binary_sha256': backend.protocol['binary_sha256'],
              'config': config, 'parameter_count': sum(p.numel() for p in model.parameters()),
              'inputs': inputs.tolist(), 'targets': target.tolist(),
              'initial_predictions': before_predictions.tolist(), 'final_predictions': after_predictions.tolist(),
              'initial_loss': before_loss, 'final_loss': after_loss, 'parameter_update_norms': updates,
              'parameters': parameters, 'history': history,
              'runtime': {'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available(),
                          'wall_seconds': time.perf_counter()-start, 'process_cpu_seconds': time.process_time()-cpu,
                          'financial_calls': backend.calls, 'financial_states': backend.states}}
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'smoke_passed': passed, 'initial_loss': before_loss,
                      'final_loss': after_loss, 'updates': updates, 'runtime': result['runtime']}, indent=2))
    return passed


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--frozen-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    try:
        passed = run(a.frozen_root, a.protocol_sha256, a.output)
    except Exception as error:
        if not a.output.exists():
            write(a.output, {'smoke_passed': False, 'protocol_sha256': a.protocol_sha256, 'error': repr(error)})
        print(json.dumps({'smoke_passed': False, 'error': repr(error)}))
        raise SystemExit(1)
    raise SystemExit(0 if passed else 1)
