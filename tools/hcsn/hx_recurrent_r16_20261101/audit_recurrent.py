"""Finite, branch, chain and temporal-gradient audit; no financial requalification."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from recurrent import terminal_loss
from recurrent_common import array, comparison, pack_trace, setup, tensor, trace_checks, verify, write


def expect_error(name, action, expected):
    try:
        action()
    except Exception as error:
        return {'name': name, 'passed': isinstance(error, expected), 'exception_type': type(error).__name__, 'message': str(error)}
    return {'name': name, 'passed': False, 'exception_type': None, 'message': 'Accepted unexpectedly'}


def signed_audit(inputs, protocol, backend, operator, readout):
    theta = tensor(inputs['base_theta'], True)
    x = tensor(inputs['signed_fixture_x'], True)
    observed = readout(theta, x)
    packed = np.concatenate((np.broadcast_to(array(theta).astype(np.float32), (len(x), 9)), np.maximum(array(x), 0.).astype(np.float32)[:, None]), axis=1)
    raw, jac = backend.evaluate_numpy(packed, 'log_distance')
    entries = []
    for j, value in enumerate(array(x)):
        b, equity, first_hit = raw[j, :3]
        expected_value = np.array([equity/b, 1.-(1.-first_hit)**2, value])
        expected_jac = np.zeros((3, 10))
        expected_jac[0] = jac[j, 1]/b-equity*jac[j, 0]/(b*b)
        expected_jac[1] = 2.*(1.-first_hit)*jac[j, 2]
        expected_jac[2, 9] = 1.
        if value <= 0.:
            expected_value[:2] = [0., 1.]
            expected_jac[:2] = 0.
        gradients = []
        cross_state_max = 0.
        for channel in range(3):
            g_theta, g_x = torch.autograd.grad(observed[j, channel], (theta, x), retain_graph=True)
            gradients.append(np.concatenate((array(g_theta), array(g_x)[j:j+1])))
            cross_state_max = max(cross_state_max, float(np.max(np.abs(np.delete(array(g_x), j)))))
        value_check = comparison(array(observed[j]), expected_value, protocol)
        chain_check = comparison(gradients, expected_jac, protocol)
        constants_exact = bool(value > 0. or (np.array_equal(array(observed[j])[:2], [0., 1.]) and np.array_equal(np.asarray(gradients)[:2], np.zeros((2, 10)))))
        entries.append({'x': float(value), 'phase': int(np.sign(value)), 'value': value_check, 'gradient': chain_check,
                        'other_states_max_gradient': cross_state_max, 'negative_or_zero_constants_exact': constants_exact,
                        'passed': bool(value_check['passed'] and chain_check['passed'] and cross_state_max == 0. and constants_exact)})
    contracts = []
    for name, invalid_x in [('negative_infinity', [-float('inf')]), ('positive_infinity', [float('inf')]), ('nan', [float('nan')]), ('empty', [])]:
        contracts.append(expect_error('signed_x_'+name, lambda values=invalid_x: readout(theta, tensor(values)), ValueError))
    contracts.append(expect_error('float64_x_rejected', lambda: readout(theta, x.double()), TypeError))
    contracts.append(expect_error('float64_theta_rejected', lambda: readout(theta.double(), x), TypeError))
    contracts.append(expect_error('theta_wrong_shape', lambda: readout(theta.unsqueeze(0), x), ValueError))
    bad_theta = theta.detach().clone(); bad_theta[0] = float('nan')
    contracts.append(expect_error('theta_nonfinite_rejected', lambda: readout(bad_theta, x), ValueError))
    invalid_finance = theta.detach().clone(); invalid_finance[6] = 0.
    contracts.append(expect_error('financial_rejection_propagates', lambda: readout(invalid_finance, x), ArithmeticError))
    raw_negative = torch.cat((theta.detach(), tensor([-.01])))
    contracts.append(expect_error('raw_log_domain_still_rejects_negative', lambda: operator(raw_negative), ValueError))
    for channel in range(3):
        z = tensor([.01], True)
        value = readout(theta, z)[0, channel]
        contracts.append(expect_error('signed_channel_'+str(channel)+'_higher_order_rejected',
                                      lambda value=value, z=z: torch.autograd.grad(value, (theta, z), create_graph=True), RuntimeError))
    return {'fixtures': entries, 'contracts': contracts,
            'passed': bool(all(row['passed'] for row in entries+contracts)),
            'interpretation': 'Direct clamp/where extension of the three neural observables only. Original raw financial x>=0 domain is unchanged.'}


def independent_discrete_reverse(trace, data, config, backend):
    """Manual real-formula Jacobian composition at the actual rounded states.

    Uses raw C API Jacobians and quotient/observable chains independently of
    the PyTorch recurrent graph. It does not differentiate FP32 rounding.
    """
    x = array(torch.stack(trace['x']))
    a = array(torch.stack(trace['adaptation']))
    theta = array(trace['theta']).astype(np.float32)
    T, B = x.shape[0]-1, x.shape[1]
    c = {name: float(np.float32(config[name])) for name in ('dt', 'leak', 'k_equity', 'k_risk', 'tau')}
    state_jac, theta_jac = [], []
    for t in range(T):
        packed = np.concatenate((np.broadcast_to(theta, (B, 9)), np.maximum(x[t], 0.).astype(np.float32)[:, None]), axis=1)
        values, j = backend.evaluate_numpy(packed, 'log_distance')
        b, e, f = values[:, 0], values[:, 1], values[:, 2]
        jq = j[:, 1]/b[:, None]-e[:, None]*j[:, 0]/b[:, None]**2
        jr = 2.*(1.-f[:, None])*j[:, 2]
        jq[x[t] <= 0.] = 0.; jr[x[t] <= 0.] = 0.
        A = np.zeros((B, 2, 2)); G = np.zeros((B, 2, 9))
        A[:, 0, 0] = 1.-c['dt']*(c['leak']+c['k_equity']*jq[:, 9]+c['k_risk']*jr[:, 9])
        A[:, 0, 1] = c['dt']
        A[:, 1, 0] = c['dt']*c['k_risk']*jr[:, 9]/c['tau']
        A[:, 1, 1] = 1.-c['dt']/c['tau']
        G[:, 0] = -c['dt']*(c['k_equity']*jq[:, :9]+c['k_risk']*jr[:, :9])
        G[:, 1] = c['dt']*c['k_risk']*jr[:, :9]/c['tau']
        state_jac.append(A); theta_jac.append(G)
    target_x = np.asarray(data['target_x'], dtype=np.float32).astype(np.float64)
    target_a = np.asarray(data['target_adaptation'], dtype=np.float32).astype(np.float64)
    lam = np.stack((2.*(x[-1]-target_x)/B, 2.*float(np.float32(data['adaptation_loss_weight']))*(a[-1]-target_a)/B), axis=1)
    adjoints = [None]*(T+1); adjoints[T] = lam.copy()
    step_theta = np.zeros((T, 9)); drive = np.zeros((T, B))
    for t in reversed(range(T)):
        step_theta[t] = np.einsum('bi,bij->j', lam, theta_jac[t])
        drive[t] = c['dt']*lam[:, 0]
        lam = np.einsum('bi,bij->bj', lam, state_jac[t])
        adjoints[t] = lam.copy()
    return {'state_jacobians': np.asarray(state_jac), 'direct_theta_jacobians': np.asarray(theta_jac),
            'step_theta': step_theta, 'shared_theta': step_theta.sum(axis=0),
            'state_adjoints': np.asarray(adjoints), 'drive': drive}


def temporal_audit(inputs, protocol, backend, cell):
    data = inputs['training']
    x0, a0, drive = tensor(data['initial_x'], True), tensor(data['initial_adaptation'], True), tensor(data['drive'], True)
    tx, ta = tensor(data['target_x']), tensor(data['target_adaptation'])
    trace = cell.rollout(x0, a0, drive)
    loss = terminal_loss(trace, tx, ta, data['adaptation_loss_weight'])
    T = protocol['cell']['steps']; middle = T//2
    requested = trace['theta_nodes']+[trace['theta'], x0, a0, drive, trace['x'][middle], trace['adaptation'][middle]]
    gradients = torch.autograd.grad(loss, requested, retain_graph=True)
    actual = {'step_theta': np.stack([array(g) for g in gradients[:T]]), 'shared_theta': array(gradients[T]),
              'initial_x': array(gradients[T+1]), 'initial_adaptation': array(gradients[T+2]),
              'drive': array(gradients[T+3]), 'middle_x': array(gradients[T+4]), 'middle_adaptation': array(gradients[T+5])}
    reference = independent_discrete_reverse(trace, data, protocol['cell'], backend)
    expected = {'step_theta': reference['step_theta'], 'shared_theta': reference['shared_theta'],
                'initial_x': reference['state_adjoints'][0, :, 0], 'initial_adaptation': reference['state_adjoints'][0, :, 1],
                'drive': reference['drive'], 'middle_x': reference['state_adjoints'][middle, :, 0],
                'middle_adaptation': reference['state_adjoints'][middle, :, 1]}
    comparisons = {name: comparison(value, expected[name], protocol) for name, value in actual.items()}
    comparisons['shared_equals_sum_of_step_contributions'] = comparison(actual['shared_theta'], actual['step_theta'].sum(axis=0), protocol)
    detached = cell.rollout(x0, a0, drive, detach_state=True)
    detached_loss = terminal_loss(detached, tx, ta, data['adaptation_loss_weight'])
    requested_detached = detached['theta_nodes']+[x0, a0, drive]
    detached_grad = torch.autograd.grad(detached_loss, requested_detached, allow_unused=True)
    dg = [np.zeros(tuple(p.shape), dtype=np.float64) if g is None else array(g) for p, g in zip(requested_detached, detached_grad)]
    normal_record, detached_record = pack_trace(trace), pack_trace(detached)
    checks = trace_checks(normal_record, protocol)
    checks.update({'terminal_only_loss': True,
                   'normal_early_theta_nonzero': bool(np.linalg.norm(actual['step_theta'][0]) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_initial_state_nonzero': bool(np.linalg.norm(actual['initial_x']) > protocol['gates']['nonzero_gradient_floor'] and np.linalg.norm(actual['initial_adaptation']) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_early_drive_nonzero': bool(np.linalg.norm(actual['drive'][0]) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_middle_state_nonzero': bool(np.linalg.norm(actual['middle_x']) > protocol['gates']['nonzero_gradient_floor']),
                   'detached_forward_bitwise_equal': bool(np.array_equal(normal_record['x'], detached_record['x']) and np.array_equal(normal_record['adaptation'], detached_record['adaptation'])),
                   'detached_early_theta_zero': bool(np.count_nonzero(np.asarray(dg[:T-1])) == 0),
                   'detached_initial_state_zero': bool(np.count_nonzero(dg[T]) == 0 and np.count_nonzero(dg[T+1]) == 0),
                   'detached_early_drive_zero': bool(np.count_nonzero(dg[T+2][:-1]) == 0),
                   'input_driven_branch_crossing_observed': bool(len(normal_record['crossings']) >= protocol['gates']['minimum_sampled_phase_changes']),
                   'negative_zero_positive_states_observed': bool(set(np.asarray(normal_record['phase']).reshape(-1).tolist()) == {-1, 0, 1})})
    return {'loss': float(loss.detach()), 'trajectory': normal_record, 'comparisons': comparisons, 'checks': checks,
            'independent_discrete_reference': {k: v.tolist() for k, v in reference.items()},
            'detach_negative_control': {'trajectory': detached_record, 'loss': float(detached_loss.detach()),
                                        'step_theta_gradients': np.asarray(dg[:T]).tolist(),
                                        'initial_x_gradient': dg[T].tolist(), 'initial_adaptation_gradient': dg[T+1].tolist(),
                                        'drive_gradient': dg[T+2].tolist(), 'unused_initial_x': detached_grad[T] is None,
                                        'unused_initial_adaptation': detached_grad[T+1] is None},
            'passed': bool(all(checks.values()) and all(c['passed'] for c in comparisons.values()))}


def negative_control(inputs, protocol, cell):
    data = inputs['all_negative_control']
    x0, a0 = tensor(data['initial_x'], True), tensor(data['initial_adaptation'], True)
    trace = cell.rollout(x0, a0, tensor(data['drive']))
    gx = torch.autograd.grad(trace['x'][-1].sum(), (x0, a0, trace['theta']), retain_graph=True)
    ga = torch.autograd.grad(trace['adaptation'][-1].sum(), (x0, a0, trace['theta']), retain_graph=True)
    c = {k: float(np.float32(protocol['cell'][k])) for k in ('dt', 'leak', 'tau')}
    A = np.array([[1.-c['dt']*c['leak'], c['dt']], [0., 1.-c['dt']/c['tau']]])
    powered = np.linalg.matrix_power(A, protocol['cell']['steps'])
    observed = np.array([[float(gx[0][0]), float(gx[1][0])], [float(ga[0][0]), float(ga[1][0])]])
    record = pack_trace(trace)
    checks = trace_checks(record, protocol)
    checks.update({'all_states_strictly_negative': bool(np.max(record['x']) < 0.),
                   'theta_gradients_exactly_zero': bool(torch.count_nonzero(gx[2]) == 0 and torch.count_nonzero(ga[2]) == 0),
                   'exact_default_observables': bool(np.array_equal(np.asarray(record['readout_Q_R_x'])[..., 0], np.zeros((protocol['cell']['steps'], len(x0)))) and np.array_equal(np.asarray(record['readout_Q_R_x'])[..., 1], np.ones((protocol['cell']['steps'], len(x0))))),
                   'linear_discrete_state_gradient': bool(np.max(np.abs(observed-powered)) <= protocol['gates']['linear_state_gradient_atol'])})
    return {'trajectory': record, 'checks': checks, 'single_step_matrix': A.tolist(), 'matrix_power': powered.tolist(),
            'observed_state_gradient': observed.tolist(), 'absolute_error': np.abs(observed-powered).tolist(),
            'x_final_theta_gradient': array(gx[2]).tolist(), 'adaptation_final_theta_gradient': array(ga[2]).tolist(),
            'passed': bool(all(checks.values())),
            'interpretation': 'All-negative direct theta insensitivity is real. An earlier positive phase could still carry theta sensitivity through later negative states; no claim that entering default erases history.'}


def run(adapter_root, financial_root, expected, output):
    protocol, inputs, backend, operator, readout, cell = setup(adapter_root, financial_root, expected)
    start, cpu = time.perf_counter(), time.process_time()
    result = {'schema': 'hcsn.hx-recurrent-audit.v1', 'protocol_sha256': expected,
              'scope': 'New neural readout and discrete first-order BPTT wiring, not a new financial accuracy holdout or model-quality experiment.',
              'signed_readout': signed_audit(inputs, protocol, backend, operator, readout),
              'temporal': temporal_audit(inputs, protocol, backend, cell),
              'all_negative': negative_control(inputs, protocol, cell)}
    backend.verify(); verify(expected)
    result['runtime'] = {'wall_seconds': time.perf_counter()-start, 'process_cpu_seconds': time.process_time()-cpu,
                         'financial_calls': backend.calls, 'financial_states': backend.states,
                         'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available()}
    result['audit_passed'] = bool(all(result[name]['passed'] for name in ('signed_readout', 'temporal', 'all_negative')))
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'audit_passed': result['audit_passed'],
                      'signed_passed': result['signed_readout']['passed'], 'temporal_checks': result['temporal']['checks'],
                      'negative_checks': result['all_negative']['checks'], 'runtime': result['runtime']}, indent=2))
    return result['audit_passed']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--adapter-root', type=Path, required=True); p.add_argument('--financial-root', type=Path, required=True)
    p.add_argument('--protocol-sha256', required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    try:
        passed = run(a.adapter_root, a.financial_root, a.protocol_sha256, a.output)
    except Exception as error:
        if not a.output.exists():
            write(a.output, {'audit_passed': False, 'protocol_sha256': a.protocol_sha256, 'error': repr(error)})
        print(json.dumps({'audit_passed': False, 'error': repr(error)}))
        raise
    raise SystemExit(0 if passed else 1)
