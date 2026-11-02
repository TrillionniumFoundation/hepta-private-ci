"""Twelve updates of nine shared financial parameters, full traces retained."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from asset_model import terminal_loss
from asset_common import array, pack_trace, setup, tensor, trace_checks, verify, write


def run(adapter_root, financial_root, expected, output, progress):
    protocol, inputs, backend, _, _, cell = setup(adapter_root, financial_root, expected)
    data, config = inputs['training'], protocol['training']
    z0, a0, drive = tensor(data['initial_z']), tensor(data['initial_adaptation']), tensor(data['drive'])
    tx, ta = tensor(data['target_z']), tensor(data['target_adaptation'])
    optimizer = torch.optim.Adam(cell.parameters(), lr=config['learning_rate'])
    initial_raw, initial_theta = array(cell.raw_theta), array(cell.theta())
    history = []
    progress['completed_history'] = history
    started = datetime.now(timezone.utc).isoformat()
    start, cpu = time.perf_counter(), time.process_time()
    with torch.no_grad():
        initial_fixture_readout, initial_fixture_assets = cell.readout.evaluate(cell.theta(), tensor(inputs['fixed_z_fixtures']))
    for iteration in range(config['updates']):
        progress['current_iteration'] = iteration
        optimizer.zero_grad(set_to_none=True)
        trace = cell.rollout(z0, a0, drive)
        loss = terminal_loss(trace, tx, ta, data['adaptation_loss_weight'])
        if not bool(torch.isfinite(loss)):
            raise ArithmeticError('Nonfinite terminal loss')
        loss.backward()
        grad = cell.raw_theta.grad
        if grad is None or not bool(torch.isfinite(grad).all()):
            raise ArithmeticError('Missing/nonfinite raw-theta gradient')
        record = {'iteration': iteration, 'terminal_loss_before_update': float(loss.detach()),
                  'raw_theta_before_update': array(cell.raw_theta).tolist(),
                  'effective_theta_before_update': array(trace['theta']).tolist(),
                  'raw_theta_gradient': array(grad).tolist(), 'gradient_l2': float(np.linalg.norm(array(grad))),
                  'trajectory': pack_trace(trace)}
        record['trace_checks'] = trace_checks(record['trajectory'], protocol)
        optimizer.step()
        if not bool(torch.isfinite(cell.raw_theta).all()):
            raise ArithmeticError('Nonfinite optimizer update at iteration '+str(iteration))
        record['raw_theta_after_update'] = array(cell.raw_theta).tolist()
        record['effective_theta_after_update'] = array(cell.theta()).tolist()
        history.append(record)
        if not all(record['trace_checks'].values()):
            write(output, {'schema': 'hcsn.hx-fixed-potential-training.v1', 'protocol_sha256': expected,
                           'training_passed': False, 'history': history, 'error': 'Failed finite or trajectory gate; no rows discarded'})
            return False
    with torch.no_grad():
        final_trace = cell.rollout(z0, a0, drive)
        final_loss = terminal_loss(final_trace, tx, ta, data['adaptation_loss_weight'])
    final_raw, final_theta = array(cell.raw_theta), array(cell.theta())
    record = pack_trace(final_trace)
    with torch.no_grad():
        final_fixture_readout, final_fixture_assets = cell.readout.evaluate(cell.theta(), tensor(inputs['fixed_z_fixtures']))
    theta_pair = np.stack((initial_theta, final_theta)).astype(np.float32)
    boundary_values, boundary_j, status = backend.kernel.batch(theta_pair, np.full(2, protocol['fixed_boundary_probe_asset'], dtype=np.float32), ['asset']*2, 'float64')
    if np.any(status != 0) or not np.isfinite(boundary_values).all() or not np.isfinite(boundary_j).all():
        raise ArithmeticError('Boundary diagnostic rejected')
    backend.verify(); verify(expected)
    expected_margin_shift = -np.log(boundary_values[1, 0]/boundary_values[0, 0])
    actual_margin_shift = array(final_fixture_readout)[:, 2]-array(initial_fixture_readout)[:, 2]
    checks = trace_checks(record, protocol)
    checks.update({'fixed_physical_fixture_assets_unchanged': bool(torch.equal(initial_fixture_assets, final_fixture_assets)),
                   'boundary_moved_against_fixed_physical_assets': bool(abs(boundary_values[1, 0]-boundary_values[0, 0]) > protocol['gates']['nonzero_gradient_floor']),
                   'fixed_asset_margin_shift_matches_boundary': bool(np.all(np.abs(actual_margin_shift-expected_margin_shift) <= protocol['gates']['gradient_atol']+protocol['gates']['gradient_rtol']*abs(expected_margin_shift))),
                   'fixed_initial_z_and_rest_throughout_training': bool(all(row['trajectory']['z'][0] == data['initial_z'] and row['trajectory']['fixed_z_rest'] == protocol['cell']['z_rest'] for row in history)),
                   'complete_training_history': len(history) == config['updates'],
                   'nine_trainable_parameters_only': sum(p.numel() for p in cell.parameters()) == 9,
                   'finite_parameters_and_gradients': bool(np.isfinite(final_raw).all() and all(np.isfinite(row['raw_theta_gradient']).all() for row in history)),
                   'actual_parameter_update': bool(np.linalg.norm(final_raw-initial_raw) > protocol['gates']['nonzero_gradient_floor']),
                   'bounded_theta_change': bool(np.max(np.abs(final_theta/initial_theta-1.)) <= protocol['cell']['theta_fraction']+2e-7)})
    result = {'schema': 'hcsn.hx-fixed-potential-training.v1', 'protocol_sha256': expected,
              'training_passed': bool(all(checks.values()) and all(all(row['trace_checks'].values()) for row in history)),
              'scope': 'Fixed physical z initial states, fixed z_rest and fixed synthetic training data only. Demonstrates first-order time unrolling and nine financial-parameter updates; loss reduction, spiking and task quality are not acceptance gates.',
              'trainable_parameters': {'raw_theta': {'count': 9, 'initial': initial_raw.tolist(), 'final': final_raw.tolist()}},
              'effective_theta_initial': initial_theta.tolist(), 'effective_theta_final': final_theta.tolist(),
              'fixed_physical_fixture': {'z': inputs['fixed_z_fixtures'], 'represented_assets_initial': array(initial_fixture_assets).tolist(), 'represented_assets_final': array(final_fixture_assets).tolist(),
                                         'readout_initial_Q_R_x': array(initial_fixture_readout).tolist(), 'readout_final_Q_R_x': array(final_fixture_readout).tolist(),
                                         'expected_margin_shift_from_boundary': float(expected_margin_shift), 'actual_margin_shift': actual_margin_shift.tolist()},
              'financial_boundary_initial': float(boundary_values[0, 0]), 'financial_boundary_final': float(boundary_values[1, 0]),
              'initial_loss': history[0]['terminal_loss_before_update'], 'final_loss': float(final_loss),
              'raw_parameter_update_l2': float(np.linalg.norm(final_raw-initial_raw)),
              'effective_parameter_update_l2': float(np.linalg.norm(final_theta-initial_theta)),
              'data': data, 'history': history, 'final_trajectory': record, 'checks': checks,
              'runtime': {'evaluation_started_at_utc': started, 'wall_seconds': time.perf_counter()-start, 'process_cpu_seconds': time.process_time()-cpu,
                          'financial_calls': backend.calls, 'financial_states': backend.states,
                          'additional_boundary_diagnostic_calls': 1, 'additional_boundary_diagnostic_states': 2,
                          'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available()}}
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'training_passed': result['training_passed'], 'initial_loss': result['initial_loss'],
                      'final_loss': result['final_loss'], 'parameter_update_l2': result['raw_parameter_update_l2'],
                      'checks': checks, 'runtime': result['runtime']}, indent=2))
    return result['training_passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--adapter-root', type=Path, required=True); p.add_argument('--financial-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    progress = {}
    try:
        passed = run(a.adapter_root, a.financial_root, a.protocol_sha256, a.output, progress)
    except Exception as error:
        if not a.output.exists():
            write(a.output, {'training_passed': False, 'protocol_sha256': a.protocol_sha256, 'error': repr(error), 'progress': progress})
        print(json.dumps({'training_passed': False, 'error': repr(error)}))
        raise
    raise SystemExit(0 if passed else 1)
