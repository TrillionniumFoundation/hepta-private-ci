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
from .attempts import resolve_weights
from .execution import execution_policy, implementation_record


def trace(encoder, readout, inputs, factor):
    original = encoder.population.config
    cfg = original if factor == 1 else replace(
        original, bins=original.bins*factor, dt=original.dt/factor,
        refractory=original.effective_refractory)
    population = encoder.population if factor == 1 else TorchPopulation(cfg).to(inputs.device)
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


def _audit_completed(run, report, report_path):
    config = report['config']
    path = (resolve_weights(report_path.with_suffix('.runs'), run)
            if run.get('best_checkpoint_relative') else Path(run['best_checkpoint']))
    if hashlib.sha256(path.read_bytes()).hexdigest() != run['best_checkpoint_sha256']:
        raise ValueError('checkpoint hash mismatch')
    saved = torch.load(path, map_location='cpu', weights_only=True)
    for field in ('task', 'model', 'seed'):
        if saved[field] != run[field]:
            raise ValueError(f'checkpoint {field} mismatch')
    if saved['config'] != config:
        raise ValueError('checkpoint config mismatch')
    if saved['best_validation_mse'] != run['best_validation_mse']:
        raise ValueError('checkpoint best_validation_mse mismatch')
    if saved['training_steps_completed'] != config['train_steps']:
        raise ValueError('checkpoint training budget mismatch')
    policy = execution_policy(config)
    encoder = make_encoder(run['model'], 2, config['hidden_size'], dt=config['dt'],
                           population_checkpoint_steps=policy['population_checkpoint_steps'])
    implementation = implementation_record(encoder)
    if run.get('encoder_class', implementation['encoder_class']) != implementation['encoder_class']:
        raise ValueError('encoder_class differs from declared execution policy')
    if run.get('implementation', implementation if not policy['population_checkpoint_steps'] else None) != implementation:
        raise ValueError('implementation differs from declared execution policy')
    encoder.load_state_dict({k.removeprefix('encoder.'): v for k, v in saved['state_dict'].items()
                             if k.startswith('encoder.')})
    expected_grid = dict(asdict(encoder.population.config),
                         refractory_steps=encoder.population.config.refractory_steps,
                         effective_refractory_time=encoder.population.config.effective_refractory)
    if run['population_discretization'] != expected_grid:
        raise ValueError('population_discretization mismatch')
    readout = torch.nn.Linear(config['hidden_size'], 1)
    readout.load_state_dict({k.removeprefix('readout.'): v for k, v in saved['state_dict'].items()
                            if k.startswith('readout.')})
    encoder.eval()
    readout.eval()
    x, y = make_dataset(run['task'], config['test_count'], config['length'], config['data_seed']+2)
    test_hash = hashlib.sha256(x.tobytes()+y.tobytes()).hexdigest()
    if test_hash != report['datasets'][run['task']]['split_sha256'][2]:
        raise ValueError('held-out test split hash mismatch')
    row = dict(task=run['task'], model=run['model'], seed=run['seed'], status='audited',
               implementation=implementation,
               checkpoint_sha256=run['best_checkpoint_sha256'], test_split_sha256=test_hash,
               resolutions=[], factor_one_forward_exact=True)
    baseline_outputs = None
    for factor in (1, 2, 4):
        all_outputs, measurements = [], []
        total_squared_error = torch.zeros(())
        for offset in range(0, len(x), config['batch_size']):
            inputs = torch.from_numpy(x[offset:offset+config['batch_size']])
            prediction, outputs, values = trace(encoder, readout, inputs, factor)
            if factor == 1:
                with torch.no_grad():
                    actual_forward = encoder(inputs, dt=config['dt'])
                    actual_prediction = readout(actual_forward[:, -1])
                # Trace must use all actual loaded population buffers, not a
                # freshly initialized substitute that merely shares config.
                torch.testing.assert_close(outputs, actual_forward, rtol=0, atol=0)
                torch.testing.assert_close(prediction, actual_prediction, rtol=0, atol=0)
            total_squared_error += (prediction-torch.from_numpy(y[offset:offset+len(inputs)])).square().sum()
            all_outputs.append(outputs)
            measurements.append(values)
        outputs = torch.cat(all_outputs)
        mse = float(total_squared_error/y.size)
        if factor == 1:
            if report.get('hardware', {}).get('device', 'cpu') == 'cpu':
                if mse != run['test_mse']:
                    raise ValueError('replayed test MSE differs from original CPU receipt')
            else:
                torch.testing.assert_close(torch.tensor(mse), torch.tensor(run['test_mse']))
            row['replayed_test_mse'] = mse
        if baseline_outputs is None:
            baseline_outputs = outputs
        row['resolutions'].append(dict(
            factor=factor, config=measurements[0]['config'],
            effective_refractory=measurements[0]['effective_refractory'],
            maximum_mass_error=max(v['maximum_mass_error'] for v in measurements),
            maximum_escape=max(v['maximum_escape'] for v in measurements),
            minimum_mass=min(v['minimum_mass'] for v in measurements), test_mse=mse,
            output_rms_change=float((outputs-baseline_outputs).square().mean().sqrt())))
    return row


def audit(report_path):
    report = json.loads(report_path.read_text())
    config = report['config']
    torch.set_num_threads(config['cpu_threads'])
    expected = {(task, model, seed) for task in config['tasks'] for model in config['models']
                if model.startswith('population_flux') for seed in config['seeds']}
    records = {}
    for run in report['runs']:
        identity = (run['task'], run['model'], run['seed'])
        if identity in expected:
            if identity in records:
                raise ValueError('duplicate B run identity')
            records[identity] = run
    result = dict(benchmark=str(report_path), benchmark_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest(),
                  scope='validation-selected B; verified original held-out inputs; no retraining or selection',
                  device='cpu', records=[], requested_b_runs=len(expected),
                  completed_b_runs=sum(r['status'] == 'completed' for r in records.values()),
                  limitations=['Smoke weights do not qualify full-budget B.',
                  'Joint refinement sensitivity is descriptive; no universal convergence threshold asserted.'])
    for identity in sorted(expected):
        run = records.get(identity)
        row = dict(zip(('task', 'model', 'seed'), identity))
        if run is None or run['status'] != 'completed':
            row.update(status='unavailable', benchmark_status=run['status'] if run else 'missing',
                       reason=run.get('reason', 'B benchmark run did not complete') if run else 'B run missing from benchmark receipt')
        else:
            try:
                row = _audit_completed(run, report, report_path)
            except Exception as exc:
                row.update(status='failed', reason=f'{type(exc).__name__}: {exc}')
        result['records'].append(row)
    result['audited_b_runs'] = sum(r['status'] == 'audited' for r in result['records'])
    result['failed_b_audits'] = sum(r['status'] == 'failed' for r in result['records'])
    result['status'] = ('failed' if result['failed_b_audits'] else
                        'unavailable' if not result['audited_b_runs'] else
                        'passed' if result['audited_b_runs'] == len(expected) else 'partial')
    result['source_files_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in Path(__file__).parent.glob('*.py')}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--benchmark', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.benchmark)
    atomic_json(args.output, report)
    return 0 if report['status'] == 'passed' else 1 if report['status'] == 'failed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
