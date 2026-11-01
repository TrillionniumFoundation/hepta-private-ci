"""Four same-value gradient interventions, full time and boundary-chain audit."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np
import torch

from two_layer_common import array, comparison, pack_trace, setup, tensor, trace_checks, verify, write
from two_layer_model import GRADIENT_MODES, terminal_loss
from two_layer_reference import compose_local, reverse_steps


def error_check(name, fn, expected):
    try: fn()
    except Exception as error:
        return {'name': name, 'passed': isinstance(error, expected), 'exception_type': type(error).__name__, 'message': str(error)}
    return {'name': name, 'passed': False, 'exception_type': None, 'message': 'Unexpected acceptance'}


def wrapper_equivalence(p, data, operator, readout):
    z = tensor(data['readout_fixture_z'], True)
    rows = tensor(np.broadcast_to(np.asarray(data['base1'], dtype=np.float32), (len(z), 9)).copy(), True)
    observed = readout(rows, z)['readout']
    expected = operator.readout(torch.cat((rows, torch.exp(z).unsqueeze(-1)), dim=-1))
    go = torch.autograd.grad(observed.sum(), (rows, z)); ge = torch.autograd.grad(expected.sum(), (rows, z))
    comparisons = {'values': comparison(array(observed), array(expected), p),
                   'theta_vjp': comparison(array(go[0]), array(ge[0]), p),
                   'z_vjp': comparison(array(go[1]), array(ge[1]), p)}
    theta = tensor(data['base1']); zz = tensor(data['readout_fixture_z'])
    tests = [error_check('float64_z', lambda: readout(theta, zz.double()), TypeError),
             error_check('float64_theta', lambda: readout(theta.double(), zz), TypeError),
             error_check('bad_shared_theta_shape', lambda: readout(theta[:8], zz), ValueError),
             error_check('bad_batched_theta_shape', lambda: readout(rows.detach()[:, :8], zz), ValueError),
             error_check('empty_z', lambda: readout(theta, tensor([])), ValueError)]
    for name, value in [('nan_z', float('nan')), ('positive_infinite_z', float('inf')), ('negative_infinite_z', -float('inf'))]:
        tests.append(error_check(name, lambda value=value: readout(theta, tensor([value])), ValueError))
    invalid = theta.clone(); invalid[0] = float('nan')
    tests.append(error_check('nan_theta', lambda: readout(invalid, zz), ValueError))
    tests.append(error_check('exp_overflow', lambda: readout(theta, tensor([100.])), ValueError))
    tests.append(error_check('exp_underflow', lambda: readout(theta, tensor([-200.])), ValueError))
    invalid_finance = rows.detach().clone(); invalid_finance[2, 6] = 0.
    tests.append(error_check('financial_reject_propagates', lambda: readout(invalid_finance, zz), ArithmeticError))
    return {'comparisons': comparisons, 'contracts': tests,
            'passed': bool(all(v['passed'] for v in comparisons.values()) and all(v['passed'] for v in tests) and len(tests) == p['gates']['required_readout_contracts'])}


def evaluate_mode(model, p, data, mode):
    initial = tensor(data['initial_state'], True); u1, u2 = tensor(data['drive1'], True), tensor(data['drive2'], True)
    trace = model.rollout(*initial.unbind(-1), u1, u2, gradient_mode=mode)
    loss = terminal_loss(trace, tensor(data['target_z2']), tensor(data['target_a2']), data['loss_a_weight'])
    T = p['cell']['steps']
    targets = [model.raw_theta1, model.raw_theta2, initial, u1, u2]+trace['theta1_nodes']+trace['theta2_nodes']
    names = ['raw1', 'raw2', 'initial_state', 'drive1', 'drive2']+['theta1_node_'+str(t) for t in range(T)]+['theta2_node_'+str(t) for t in range(T)]
    gradients = torch.autograd.grad(loss, targets, allow_unused=True, retain_graph=True)
    numeric = [np.zeros(tuple(target.shape), dtype=np.float64) if grad is None else array(grad) for target, grad in zip(targets, gradients)]
    actual = dict(zip(names[:5], numeric[:5]))
    actual['theta1_nodes'] = np.asarray(numeric[5:5+T]); actual['theta2_nodes'] = np.asarray(numeric[5+T:])
    credits = []
    for t in range(T):
        g1, g2 = gradients[5+t], gradients[5+T+t]
        credit1 = torch.autograd.grad(trace['theta1_nodes'][t], model.raw_theta1, grad_outputs=g1, retain_graph=True)[0] if g1 is not None else torch.zeros_like(model.raw_theta1)
        credit2 = torch.autograd.grad(trace['theta2_nodes'][t], model.raw_theta2, grad_outputs=g2, retain_graph=True)[0] if g2 is not None else torch.zeros_like(model.raw_theta2)
        credits.append(np.concatenate((array(credit1), array(credit2))))
    actual['step_raw_credit'] = np.asarray(credits)
    return {'loss': float(loss.detach()), 'trajectory': pack_trace(trace, include_internal=True),
            'actual': {key: value.tolist() for key, value in actual.items()},
            'unused': {name: grad is None for name, grad in zip(names, gradients)}}


def financial_reference(trace, backend, p):
    records = []
    for t in range(p['cell']['steps']):
        row = {'step': t}
        for layer in (1, 2):
            block = trace['layer'+str(layer)]
            theta = np.asarray(block['effective_theta'], dtype=np.float32)
            theta = np.broadcast_to(theta, (p['experiment']['batch_size'], 9)) if layer == 1 else theta[t]
            asset = np.asarray(block['asset'][t], dtype=np.float32)
            packed = np.concatenate((theta, asset[:, None]), axis=1)
            values, jac = backend.evaluate_numpy(packed, 'asset')
            row['raw'+str(layer)] = values.tolist(); row['jac'+str(layer)] = jac.tolist()
        records.append(row)
    return records


def attach_reference(record, financial, p, data, mode):
    trace = record['trajectory']; locals_ = []
    for t, raw in enumerate(financial):
        locals_.append(compose_local(raw1=raw['raw1'], jac1=raw['jac1'], asset1=trace['layer1']['asset'][t],
                                     raw2=raw['raw2'], jac2=raw['jac2'], asset2=trace['layer2']['asset'][t],
                                     base1=data['base1'], base2=data['base2'], tanh1=trace['theta1_tanh'], tanh2=trace['theta2_tanh'][t],
                                     config=p['cell'], mode=mode))
    stacked = {key: np.stack([row[key] for row in locals_]) for key in locals_[0]}
    state = np.asarray(trace['state'], dtype=np.float64); B = p['experiment']['batch_size']
    terminal = np.zeros((B, 4)); terminal[:, 2] = 2.*(state[-1, :, 2]-np.asarray(data['target_z2']))/B
    terminal[:, 3] = 2.*data['loss_a_weight']*(state[-1, :, 3]-np.asarray(data['target_a2']))/B
    reverse = reverse_steps(stacked['A'], stacked['B'], terminal)
    dt = float(np.float32(p['cell']['dt'])); actual = record['actual']
    comparisons = {'shared_raw': comparison(np.concatenate((actual['raw1'], actual['raw2'])), reverse['shared_raw'], p),
                   'step_raw_credit': comparison(actual['step_raw_credit'], reverse['step_raw'], p),
                   'initial_state': comparison(actual['initial_state'], reverse['state_adj'][0], p),
                   'drive1': comparison(actual['drive1'], dt*reverse['state_adj'][1:, :, 0], p),
                   'drive2': comparison(actual['drive2'], dt*reverse['state_adj'][1:, :, 2], p),
                   'raw1_equals_time_sum': comparison(actual['raw1'], np.sum(np.asarray(actual['step_raw_credit'])[:, :9], axis=0), p),
                   'raw2_equals_time_sum': comparison(actual['raw2'], np.sum(np.asarray(actual['step_raw_credit'])[:, 9:], axis=0), p)}
    record['reference'] = {'A': stacked['A'].tolist(), 'B': stacked['B'].tolist(), **{key: value.tolist() for key, value in reverse.items()}}
    record['comparisons'] = comparisons; record['trace_checks'] = trace_checks(trace, p, data)
    record['passed'] = bool(all(row['passed'] for row in comparisons.values()) and all(record['trace_checks'].values()) and len(comparisons) == p['gates']['required_temporal_comparisons'])
    return stacked


def identify(modes, full_locals, p):
    full, drive, condition, detached = [modes[name] for name in ('full', 'drive_only', 'conditioning_only', 'both_detached')]
    gradient = lambda mode, layer: np.asarray(mode['actual']['raw'+str(layer)])
    comparisons = {'raw1_route_additivity': comparison(gradient(full, 1), gradient(drive, 1)+gradient(condition, 1), p),
                   'raw2_drive_mode_same': comparison(gradient(drive, 2), gradient(full, 2), p),
                   'raw2_conditioning_mode_same': comparison(gradient(condition, 2), gradient(full, 2), p),
                   'raw2_both_detached_same': comparison(gradient(detached, 2), gradient(full, 2), p)}
    adj = np.asarray(full['reference']['state_adj'])[1:, :, 2:]
    direct_condition = np.einsum('tbi,tbij->tj', adj, full_locals['boundary_raw1_condition'])
    direct_drive = np.einsum('tbi,tbij->tj', adj, full_locals['boundary_raw1_drive'])
    checks = {'four_modes_present': set(modes) == set(GRADIENT_MODES),
              'conditioning_only_upstream_gradient_nonzero': bool(np.linalg.norm(gradient(condition, 1)) > p['gates']['minimum_conditioning_vjp']),
              'direct_boundary_conditioning_path_nonzero': bool(np.linalg.norm(direct_condition) > p['gates']['minimum_direct_boundary_vjp']),
              'full_upstream_gradient_nonzero': bool(np.linalg.norm(gradient(full, 1)) > p['gates']['nonzero_gradient_floor']),
              'both_detached_upstream_gradient_zero': bool(np.count_nonzero(gradient(detached, 1)) == 0),
              'both_detached_layer1_initial_state_gradient_zero': bool(np.count_nonzero(np.asarray(detached['actual']['initial_state'])[:, :2]) == 0),
              'both_detached_external_u1_gradient_zero': bool(np.count_nonzero(detached['actual']['drive1']) == 0),
              'normal_initial_layer1_state_gradient_nonzero': bool(np.linalg.norm(np.asarray(full['actual']['initial_state'])[:, :2]) > p['gates']['nonzero_gradient_floor']),
              'normal_early_drive1_gradient_nonzero': bool(np.linalg.norm(np.asarray(full['actual']['drive1'])[0]) > p['gates']['nonzero_gradient_floor'])}
    for mode in GRADIENT_MODES[1:]:
        other = modes[mode]['trajectory']; original = full['trajectory']
        fields_equal = np.array_equal(original['state'], other['state']) and np.array_equal(original['links'], other['links']) and np.array_equal(original['used_drive2'], other['used_drive2'])
        for layer in ('layer1', 'layer2'):
            fields_equal = fields_equal and all(np.array_equal(original[layer][key], other[layer][key]) for key in ('Q_R_x', 'boundary', 'asset', 'effective_theta'))
        checks[mode+'_forward_exact_numerical_equality'] = bool(fields_equal)
    return {'checks': checks, 'comparisons': comparisons,
            'conditioning_vjp_l2': float(np.linalg.norm(gradient(condition, 1))),
            'drive_vjp_l2': float(np.linalg.norm(gradient(drive, 1))), 'full_vjp_l2': float(np.linalg.norm(gradient(full, 1))),
            'direct_boundary_condition_step': direct_condition.tolist(), 'direct_boundary_condition_total': direct_condition.sum(axis=0).tolist(),
            'direct_boundary_drive_step': direct_drive.tolist(), 'direct_boundary_drive_total': direct_drive.sum(axis=0).tolist(),
            'conditioning_state_history_remainder': (gradient(condition, 1)-direct_condition.sum(axis=0)).tolist(),
            'passed': bool(all(checks.values()) and all(v['passed'] for v in comparisons.values()))}


def run(adapter_root, financial_root, expected, output, progress):
    p, data, backend, operator, readout, model = setup(adapter_root, financial_root, expected)
    start_utc = datetime.now(timezone.utc).isoformat(); wall, cpu = time.perf_counter(), time.process_time()
    progress.update({'schema': 'hcsn.hx-two-layer-audit.v1', 'protocol_sha256': expected,
                     'readout_equivalence': wrapper_equivalence(p, data, operator, readout), 'modes': {}})
    full_locals = None
    for mode in GRADIENT_MODES:
        result = evaluate_mode(model, p, data, mode); progress['modes'][mode] = result
        if mode == 'full':
            progress['financial_reference'] = financial_reference(result['trajectory'], backend, p)
        local = attach_reference(result, progress['financial_reference'], p, data, mode)
        if mode == 'full': full_locals = local
    progress['full_local_decomposition'] = {key: value.tolist() for key, value in full_locals.items()}
    progress['identification'] = identify(progress['modes'], full_locals, p)
    backend.verify(); verify(expected)
    progress['audit_passed'] = bool(progress['readout_equivalence']['passed'] and all(row['passed'] for row in progress['modes'].values()) and progress['identification']['passed'])
    progress['runtime'] = {'evaluation_started_at_utc': start_utc, 'wall_seconds': time.perf_counter()-wall, 'process_cpu_seconds': time.process_time()-cpu,
                           'financial_calls': backend.calls, 'financial_states': backend.states, 'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available()}
    artifact = write(output, progress)
    print(json.dumps({'artifact': artifact, 'audit_passed': progress['audit_passed'], 'identification_checks': progress['identification']['checks'],
                      'conditioning_vjp_l2': progress['identification']['conditioning_vjp_l2'], 'runtime': progress['runtime']}, indent=2))
    return progress['audit_passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--adapter-root', type=Path, required=True); parser.add_argument('--financial-root', type=Path, required=True)
    parser.add_argument('--protocol-sha256', required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); torch.set_num_threads(1); torch.set_num_interop_threads(1)
    progress = {}
    try: passed = run(args.adapter_root, args.financial_root, args.protocol_sha256, args.output, progress)
    except Exception as error:
        progress.update({'audit_passed': False, 'protocol_sha256': args.protocol_sha256, 'error': repr(error)})
        if not args.output.exists(): write(args.output, progress)
        raise
    raise SystemExit(0 if passed else 1)
