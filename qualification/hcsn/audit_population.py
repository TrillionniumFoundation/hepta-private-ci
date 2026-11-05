"""Audit saved validation-selected B weights at their trained grid and refinements.

Inputs are held constant within each original interval when subdividing time.
The physical effective refractory duration is held at the trained value (.3 for
benchmark defaults), rather than silently changing it back to requested .24.
This reports sensitivity, not a convergence certificate or a new test selection.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch

from .baselines import make_encoder
from .benchmark import atomic_json, make_dataset
from .population_torch import TorchPopulation


def trace(encoder, readout, inputs, factor):
    original = encoder.population.config
    cfg = replace(original, bins=original.bins*factor, dt=original.dt/factor,
                  refractory=original.effective_refractory)
    population = TorchPopulation(cfg).to(inputs.device)
    state = population.initial_state((len(inputs), encoder.hidden_size))
    filtered = inputs.new_zeros(len(inputs), encoder.hidden_size)
    outputs = []
    mass_error = escape = 0.0
    minimum_mass = 1.0
    decay = math.exp(-cfg.dt/0.5)
    with torch.no_grad():
        for value in inputs.unbind(1):
            for _ in range(factor):
                drive = 6*torch.sigmoid(encoder.input(value)+encoder.recurrent(filtered))
                step = population(state, drive=drive)
                state = step.state
                filtered = decay*filtered+(1-decay)*step.rate
                mass_error = max(mass_error, float((state.total_mass()-1).abs().max()))
                escape = max(escape, float(state.escaped.max()))
                minimum_mass = min(minimum_mass, float(state.active.min()),
                                   float(state.refractory.min()), float(state.escaped.min()))
            outputs.append(filtered.clone())
        prediction = readout(filtered)
    return prediction, torch.stack(outputs, 1), dict(
        config=asdict(cfg), effective_refractory=cfg.effective_refractory,
        maximum_mass_error=mass_error, maximum_escape=escape, minimum_mass=minimum_mass)


def audit(report_path):
    report = json.loads(report_path.read_text())
    config = report['config']
    torch.set_num_threads(config['cpu_threads'])
    result = dict(benchmark=str(report_path), benchmark_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                  scope='validation-selected B; same held-out inputs; no retraining or checkpoint reselection',
                  device='cpu', records=[], limitations=['Smoke weights do not qualify full-budget B.',
                  'Joint refinement sensitivity is descriptive; no universal convergence threshold asserted.'])
    for run in report['runs']:
        if not run['model'].startswith('population_flux') or run['status'] != 'completed':
            continue
        path = Path(run['best_checkpoint'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != run['best_checkpoint_sha256']:
            raise ValueError('checkpoint hash mismatch')
        saved = torch.load(path, map_location='cpu', weights_only=True)
        encoder = make_encoder(run['model'], 2, config['hidden_size'], dt=config['dt'])
        encoder.load_state_dict({k.removeprefix('encoder.'): v for k, v in saved['state_dict'].items()
                                 if k.startswith('encoder.')})
        readout = torch.nn.Linear(config['hidden_size'], 1)
        readout.load_state_dict({k.removeprefix('readout.'): v for k, v in saved['state_dict'].items()
                                if k.startswith('readout.')})
        x, y = make_dataset(run['task'], config['test_count'], config['length'], config['data_seed']+2)
        row = dict(task=run['task'], model=run['model'], seed=run['seed'],
                   checkpoint_sha256=run['best_checkpoint_sha256'], resolutions=[])
        baseline_outputs = None
        for factor in (1, 2, 4):
            predictions, all_outputs, measurements = [], [], []
            for offset in range(0, len(x), config['batch_size']):
                prediction, outputs, values = trace(encoder, readout, torch.from_numpy(x[offset:offset+config['batch_size']]), factor)
                predictions.append(prediction)
                all_outputs.append(outputs)
                measurements.append(values)
            prediction, outputs = torch.cat(predictions), torch.cat(all_outputs)
            if baseline_outputs is None:
                baseline_outputs = outputs
            row['resolutions'].append(dict(
                factor=factor, config=measurements[0]['config'],
                effective_refractory=measurements[0]['effective_refractory'],
                maximum_mass_error=max(v['maximum_mass_error'] for v in measurements),
                maximum_escape=max(v['maximum_escape'] for v in measurements),
                minimum_mass=min(v['minimum_mass'] for v in measurements),
                test_mse=float((prediction-torch.from_numpy(y)).square().mean()),
                output_rms_change=float((outputs-baseline_outputs).square().mean().sqrt())))
        result['records'].append(row)
    result['source_files_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in Path(__file__).parent.glob('*.py')}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    atomic_json(args.output, audit(args.benchmark))


if __name__ == '__main__':
    main()
