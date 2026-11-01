"""Twelve updates of eighteen parameters; retain every represented trajectory."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np
import torch

from two_layer_common import array, pack_trace, setup, tensor, trace_checks, verify, write
from two_layer_model import terminal_loss


def run(adapter_root, financial_root, expected, output, progress):
    p, data, backend, _, _, model = setup(adapter_root, financial_root, expected)
    initial = tensor(data['initial_state']); u1, u2 = tensor(data['drive1']), tensor(data['drive2'])
    target_z2, target_a2 = tensor(data['target_z2']), tensor(data['target_a2'])
    optimizer = torch.optim.Adam(model.parameters(), lr=p['experiment']['learning_rate'])
    initial_raw = [array(model.raw_theta1).copy(), array(model.raw_theta2).copy()]
    started = datetime.now(timezone.utc).isoformat(); wall, cpu = time.perf_counter(), time.process_time()
    history = []
    progress.update({'schema': 'hcsn.hx-two-layer-training.v1', 'protocol_sha256': expected,
                     'training_passed': False, 'data': data, 'history': history})
    for iteration in range(p['experiment']['updates']):
        progress['current_iteration'] = iteration
        optimizer.zero_grad(set_to_none=True)
        trace = model.rollout(*initial.unbind(-1), u1, u2, gradient_mode='full')
        loss = terminal_loss(trace, target_z2, target_a2, data['loss_a_weight'])
        if not bool(torch.isfinite(loss)):
            raise ArithmeticError('Nonfinite terminal loss')
        loss.backward()
        gradients = [model.raw_theta1.grad, model.raw_theta2.grad]
        if any(g is None or not bool(torch.isfinite(g).all()) for g in gradients):
            raise ArithmeticError('Missing/nonfinite raw-parameter gradient')
        # Snapshot live raw Parameter references BEFORE optimizer.step.
        record = {'iteration': iteration, 'loss_before_update': float(loss.detach()),
                  'raw1_before': array(model.raw_theta1).tolist(), 'raw2_before': array(model.raw_theta2).tolist(),
                  'grad_raw1': array(gradients[0]).tolist(), 'grad_raw2': array(gradients[1]).tolist(),
                  'trajectory': pack_trace(trace, include_internal=False)}
        record['trace_checks'] = trace_checks(record['trajectory'], p, data)
        history.append(record)
        if not all(record['trace_checks'].values()):
            raise ArithmeticError('Trajectory gate failed; complete prefix retained')
        optimizer.step()
        if not all(bool(torch.isfinite(v).all()) for v in (model.raw_theta1, model.raw_theta2)):
            raise ArithmeticError('Nonfinite optimizer update; complete prefix retained')
        record.update({'raw1_after': array(model.raw_theta1).tolist(), 'raw2_after': array(model.raw_theta2).tolist()})
    with torch.no_grad():
        final_trace = model.rollout(*initial.unbind(-1), u1, u2, gradient_mode='full')
        final_loss = terminal_loss(final_trace, target_z2, target_a2, data['loss_a_weight'])
    final_record = pack_trace(final_trace, include_internal=False)
    final_raw = [array(model.raw_theta1), array(model.raw_theta2)]
    parameter_records = {'raw_theta'+str(i+1): {'initial': initial_raw[i].tolist(), 'final': final_raw[i].tolist()} for i in range(2)}
    updates = {'raw_theta'+str(i+1): float(np.linalg.norm(final_raw[i]-initial_raw[i])) for i in range(2)}
    checks = trace_checks(final_record, p, data)
    checks.update({'complete_training_history': len(history) == p['experiment']['updates'],
                   'only_eighteen_raw_parameters': sum(v.numel() for v in model.parameters()) == 18 and len(list(model.parameters())) == 2,
                   'finite_final_loss': bool(torch.isfinite(final_loss)),
                   'finite_parameters_and_gradients': bool(all(np.isfinite(v).all() for v in final_raw) and all(np.isfinite(row[key]).all() for row in history for key in ('grad_raw1', 'grad_raw2'))),
                   'layer1_parameters_updated': updates['raw_theta1'] > p['gates']['nonzero_gradient_floor'],
                   'layer2_parameters_updated': updates['raw_theta2'] > p['gates']['nonzero_gradient_floor']})
    backend.verify(); verify(expected)
    progress.update({'training_passed': bool(all(checks.values()) and all(all(row['trace_checks'].values()) for row in history)),
                     'scope': 'Finite two-layer time-unrolling and eighteen-parameter update demonstration. Terminal loss uses z2/a2 only; loss improvement, spiking and task quality are not gates.',
                     'parameters': parameter_records, 'final_trajectory': final_record,
                     'initial_loss': history[0]['loss_before_update'], 'final_loss': float(final_loss),
                     'parameter_update_l2': updates, 'checks': checks,
                     'runtime': {'evaluation_started_at_utc': started, 'wall_seconds': time.perf_counter()-wall,
                                 'process_cpu_seconds': time.process_time()-cpu, 'financial_calls': backend.calls,
                                 'financial_states': backend.states, 'torch': torch.__version__, 'numpy': np.__version__,
                                 'cuda_available': torch.cuda.is_available()}})
    artifact = write(output, progress)
    print(json.dumps({'artifact': artifact, 'training_passed': progress['training_passed'],
                      'initial_loss': progress['initial_loss'], 'final_loss': progress['final_loss'],
                      'parameter_update_l2': updates, 'checks': checks, 'runtime': progress['runtime']}, indent=2))
    return progress['training_passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--adapter-root', type=Path, required=True); parser.add_argument('--financial-root', type=Path, required=True)
    parser.add_argument('--protocol-sha256', required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); torch.set_num_threads(1); torch.set_num_interop_threads(1)
    progress = {}
    try: passed = run(args.adapter_root, args.financial_root, args.protocol_sha256, args.output, progress)
    except Exception as error:
        progress.update({'training_passed': False, 'protocol_sha256': args.protocol_sha256, 'error': repr(error)})
        if not args.output.exists(): write(args.output, progress)
        raise
    raise SystemExit(0 if passed else 1)
