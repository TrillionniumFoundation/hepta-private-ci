"""Finite, branch, chain and temporal-gradient audit; no financial requalification."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch

from asset_model import terminal_loss
from asset_common import array, comparison, pack_trace, setup, tensor, trace_checks, verify, write


def expect_error(name, action, expected):
    try:
        action()
    except Exception as error:
        return {'name': name, 'passed': isinstance(error, expected), 'exception_type': type(error).__name__, 'message': str(error)}
    return {'name': name, 'passed': False, 'exception_type': None, 'message': 'Accepted unexpectedly'}


def fixed_potential_audit(inputs, protocol, backend, operator, readout):
    theta = tensor(inputs['base_theta'], True)
    z = tensor(inputs['fixed_z_fixtures'], True)
    observed, assets = readout.evaluate(theta, z)
    packed = np.concatenate((np.broadcast_to(array(theta).astype(np.float32), (len(z), 9)), array(assets).astype(np.float32)[:, None]), axis=1)
    raw, jac = backend.evaluate_numpy(packed, 'asset')
    entries = []
    for j, v in enumerate(array(assets)):
        b, equity, first_hit = raw[j, :3]
        expected_value = np.array([equity/b, 1.-(1.-first_hit)**2, np.log(v/b)])
        expected_jac = np.zeros((3, 10))
        expected_jac[0] = jac[j, 1]/b-equity*jac[j, 0]/(b*b)
        expected_jac[1] = 2.*(1.-first_hit)*jac[j, 2]
        expected_jac[:2, 9] *= v
        expected_jac[2, :9] = -jac[j, 0, :9]/b
        expected_jac[2, 9] = 1.
        gradients = []; cross_state_max = 0.
        for channel in range(3):
            g_theta, g_z = torch.autograd.grad(observed[j, channel], (theta, z), retain_graph=True)
            gradients.append(np.concatenate((array(g_theta), array(g_z)[j:j+1])))
            cross_state_max = max(cross_state_max, float(np.max(np.abs(np.delete(array(g_z), j)))))
        value_check = comparison(array(observed[j]), expected_value, protocol)
        chain_check = comparison(gradients, expected_jac, protocol)
        default = bool(v <= b)
        default_exact = bool(not default or (np.array_equal(array(observed[j])[:2], [0., 1.]) and np.array_equal(np.asarray(gradients)[:2], np.zeros((2, 10)))))
        entries.append({'z': float(z[j].detach()), 'represented_asset': float(v), 'boundary': float(b),
                        'actual_default_branch': default, 'value': value_check, 'gradient': chain_check,
                        'boundary_theta_jacobian': jac[j, 0, :9].tolist(),
                        'explicit_Q_quotient_boundary_term': (-equity*jac[j, 0, :9]/b**2).tolist(),
                        'log_asset_minus_z': float(np.log(v)-float(z[j].detach())),
                        'other_states_max_gradient': cross_state_max, 'default_Q_R_exact': default_exact,
                        'passed': bool(value_check['passed'] and chain_check['passed'] and cross_state_max == 0. and default_exact)})
    g_asset_theta, g_asset_z = torch.autograd.grad(assets.sum(), (theta, z), allow_unused=True)
    exp_check = comparison(array(g_asset_z), array(assets), protocol)
    contracts = []
    for name, invalid_z in [('negative_infinity', [-float('inf')]), ('positive_infinity', [float('inf')]), ('nan', [float('nan')]), ('empty', [])]:
        contracts.append(expect_error('z_'+name, lambda values=invalid_z: readout(theta, tensor(values)), ValueError))
    contracts.append(expect_error('float64_z_rejected', lambda: readout(theta, z.double()), TypeError))
    contracts.append(expect_error('float64_theta_rejected', lambda: readout(theta.double(), z), TypeError))
    contracts.append(expect_error('theta_wrong_shape', lambda: readout(theta.unsqueeze(0), z), ValueError))
    bad_theta = theta.detach().clone(); bad_theta[0] = float('nan')
    contracts.append(expect_error('theta_nonfinite_rejected', lambda: readout(bad_theta, z), ValueError))
    invalid_finance = theta.detach().clone(); invalid_finance[6] = 0.
    contracts.append(expect_error('financial_rejection_propagates', lambda: readout(invalid_finance, z), ArithmeticError))
    contracts.append(expect_error('exp_overflow_rejected', lambda: readout(theta, tensor([100.])), ValueError))
    contracts.append(expect_error('exp_underflow_rejected', lambda: readout(theta, tensor([-200.])), ValueError))
    raw_zero = torch.cat((theta.detach(), tensor([0.])))
    contracts.append(expect_error('original_asset_domain_rejects_zero', lambda: operator(raw_zero), ValueError))
    for channel in range(3):
        zz = tensor([inputs['fixed_z_fixtures'][-1]], True)
        value = readout(theta, zz)[0, channel]
        contracts.append(expect_error('channel_'+str(channel)+'_higher_order_rejected',
                                      lambda value=value, zz=zz: torch.autograd.grad(value, (theta, zz), create_graph=True), RuntimeError))
    checks = {'asset_independent_of_theta_at_fixed_z': g_asset_theta is None,
              'represented_exp_derivative': exp_check['passed'],
              'default_and_continuation_covered': {row['actual_default_branch'] for row in entries} == {False, True},
              'fixed_z_boundary_parameter_chain_nonzero': all(np.linalg.norm(row['gradient']['observed'][2][:9]) > protocol['gates']['nonzero_gradient_floor'] for row in entries),
              'roundtrip_error_disclosed_and_bounded': max(abs(row['log_asset_minus_z']) for row in entries) <= protocol['gates']['max_exp_log_roundtrip_error'],
              'complete_fixture_and_contract_counts': len(entries) == protocol['gates']['required_fixed_z_fixtures'] and len(contracts) == protocol['gates']['required_contract_checks']}
    return {'fixtures': entries, 'contracts': contracts, 'checks': checks, 'exp_derivative': exp_check,
            'passed': bool(all(row['passed'] for row in entries+contracts) and all(checks.values())),
            'interpretation': 'The same represented physical asset is independent of theta. Full original asset derivatives and the V=exp(z) chain are used. x=log(V_repr/b), not an exact floating identity z-log(b).'}


def independent_discrete_reverse(trace, data, config, backend):
    z = array(torch.stack(trace['z'])); a = array(torch.stack(trace['adaptation']))
    assets = array(torch.stack(trace['assets'])).astype(np.float32)
    theta = array(trace['theta']).astype(np.float32)
    T, B = z.shape[0]-1, z.shape[1]
    c = {name: float(np.float32(config[name])) for name in ('dt', 'leak', 'k_equity', 'k_risk', 'tau')}
    state_jac, theta_jac = [], []
    for t in range(T):
        packed = np.concatenate((np.broadcast_to(theta, (B, 9)), assets[t, :, None]), axis=1)
        values, j = backend.evaluate_numpy(packed, 'asset')
        b, e, f = values[:, 0], values[:, 1], values[:, 2]
        jq = j[:, 1]/b[:, None]-e[:, None]*j[:, 0]/b[:, None]**2
        jr = 2.*(1.-f[:, None])*j[:, 2]
        q_z, r_z = jq[:, 9]*assets[t].astype(np.float64), jr[:, 9]*assets[t].astype(np.float64)
        A = np.zeros((B, 2, 2)); G = np.zeros((B, 2, 9))
        A[:, 0, 0] = 1.-c['dt']*(c['leak']+c['k_equity']*q_z+c['k_risk']*r_z)
        A[:, 0, 1] = c['dt']
        A[:, 1, 0] = c['dt']*c['k_risk']*r_z/c['tau']
        A[:, 1, 1] = 1.-c['dt']/c['tau']
        G[:, 0] = -c['dt']*(c['k_equity']*jq[:, :9]+c['k_risk']*jr[:, :9])
        G[:, 1] = c['dt']*c['k_risk']*jr[:, :9]/c['tau']
        state_jac.append(A); theta_jac.append(G)
    target_z = np.asarray(data['target_z'], dtype=np.float32).astype(np.float64)
    target_a = np.asarray(data['target_adaptation'], dtype=np.float32).astype(np.float64)
    lam = np.stack((2.*(z[-1]-target_z)/B, 2.*float(np.float32(data['adaptation_loss_weight']))*(a[-1]-target_a)/B), axis=1)
    adjoints = [None]*(T+1); adjoints[T] = lam.copy()
    step_theta = np.zeros((T, 9)); drive = np.zeros((T, B))
    for t in reversed(range(T)):
        step_theta[t] = np.einsum('bi,bij->j', lam, theta_jac[t])
        drive[t] = c['dt']*lam[:, 0]
        lam = np.einsum('bi,bij->bj', lam, state_jac[t]); adjoints[t] = lam.copy()
    return {'state_jacobians': np.asarray(state_jac), 'direct_theta_jacobians': np.asarray(theta_jac),
            'step_theta': step_theta, 'shared_theta': step_theta.sum(axis=0),
            'state_adjoints': np.asarray(adjoints), 'drive': drive}


def temporal_audit(inputs, protocol, backend, cell):
    data = inputs['training']
    z0, a0, drive = tensor(data['initial_z'], True), tensor(data['initial_adaptation'], True), tensor(data['drive'], True)
    tx, ta = tensor(data['target_z']), tensor(data['target_adaptation'])
    trace = cell.rollout(z0, a0, drive)
    loss = terminal_loss(trace, tx, ta, data['adaptation_loss_weight'])
    T = protocol['cell']['steps']; middle = T//2
    requested = trace['theta_nodes']+[trace['theta'], z0, a0, drive, trace['z'][middle], trace['adaptation'][middle]]
    gradients = torch.autograd.grad(loss, requested, retain_graph=True)
    actual = {'step_theta': np.stack([array(g) for g in gradients[:T]]), 'shared_theta': array(gradients[T]),
              'initial_z': array(gradients[T+1]), 'initial_adaptation': array(gradients[T+2]),
              'drive': array(gradients[T+3]), 'middle_z': array(gradients[T+4]), 'middle_adaptation': array(gradients[T+5])}
    reference = independent_discrete_reverse(trace, data, protocol['cell'], backend)
    expected = {'step_theta': reference['step_theta'], 'shared_theta': reference['shared_theta'],
                'initial_z': reference['state_adjoints'][0, :, 0], 'initial_adaptation': reference['state_adjoints'][0, :, 1],
                'drive': reference['drive'], 'middle_z': reference['state_adjoints'][middle, :, 0],
                'middle_adaptation': reference['state_adjoints'][middle, :, 1]}
    comparisons = {name: comparison(value, expected[name], protocol) for name, value in actual.items()}
    comparisons['shared_equals_sum_of_step_contributions'] = comparison(actual['shared_theta'], actual['step_theta'].sum(axis=0), protocol)
    detached = cell.rollout(z0, a0, drive, detach_state=True)
    detached_loss = terminal_loss(detached, tx, ta, data['adaptation_loss_weight'])
    requested_detached = detached['theta_nodes']+[z0, a0, drive]
    detached_grad = torch.autograd.grad(detached_loss, requested_detached, allow_unused=True)
    dg = [np.zeros(tuple(p.shape), dtype=np.float64) if g is None else array(g) for p, g in zip(requested_detached, detached_grad)]
    normal_record, detached_record = pack_trace(trace), pack_trace(detached)
    checks = trace_checks(normal_record, protocol)
    checks.update({'terminal_only_loss': True,
                   'normal_early_theta_nonzero': bool(np.linalg.norm(actual['step_theta'][0]) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_initial_state_nonzero': bool(np.linalg.norm(actual['initial_z']) > protocol['gates']['nonzero_gradient_floor'] and np.linalg.norm(actual['initial_adaptation']) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_early_drive_nonzero': bool(np.linalg.norm(actual['drive'][0]) > protocol['gates']['nonzero_gradient_floor']),
                   'normal_middle_state_nonzero': bool(np.linalg.norm(actual['middle_z']) > protocol['gates']['nonzero_gradient_floor']),
                   'detached_forward_exact_numerical_equal': bool(np.array_equal(normal_record['z'], detached_record['z']) and np.array_equal(normal_record['adaptation'], detached_record['adaptation'])),
                   'detached_early_theta_zero': bool(np.count_nonzero(np.asarray(dg[:T-1])) == 0),
                   'detached_initial_state_zero': bool(np.count_nonzero(dg[T]) == 0 and np.count_nonzero(dg[T+1]) == 0),
                   'detached_early_drive_zero': bool(np.count_nonzero(dg[T+2][:-1]) == 0),
                   'input_driven_branch_crossing_observed': bool(len(normal_record['crossings']) >= protocol['gates']['minimum_sampled_phase_changes']),
                   'negative_and_positive_margins_observed': bool({-1, 1}.issubset(set(np.asarray(normal_record['phase']).reshape(-1).tolist()))),
                   'complete_temporal_comparison_count': len(comparisons) == protocol['gates']['required_temporal_comparisons']})
    return {'loss': float(loss.detach()), 'trajectory': normal_record, 'comparisons': comparisons, 'checks': checks,
            'independent_discrete_reference': {k: v.tolist() for k, v in reference.items()},
            'detach_negative_control': {'trajectory': detached_record, 'loss': float(detached_loss.detach()),
                                        'step_theta_gradients': np.asarray(dg[:T]).tolist(),
                                        'initial_z_gradient': dg[T].tolist(), 'initial_adaptation_gradient': dg[T+1].tolist(),
                                        'drive_gradient': dg[T+2].tolist(), 'unused_initial_z': detached_grad[T] is None,
                                        'unused_initial_adaptation': detached_grad[T+1] is None},
            'passed': bool(all(checks.values()) and all(c['passed'] for c in comparisons.values()))}


def negative_control(inputs, protocol, cell):
    data = inputs['all_negative_control']
    z0, a0 = tensor(data['initial_z'], True), tensor(data['initial_adaptation'], True)
    trace = cell.rollout(z0, a0, tensor(data['drive']))
    gx = torch.autograd.grad(trace['z'][-1].sum(), (z0, a0, trace['theta']), retain_graph=True)
    ga = torch.autograd.grad(trace['adaptation'][-1].sum(), (z0, a0, trace['theta']), retain_graph=True)
    c = {k: float(np.float32(protocol['cell'][k])) for k in ('dt', 'leak', 'tau')}
    A = np.array([[1.-c['dt']*c['leak'], c['dt']], [0., 1.-c['dt']/c['tau']]])
    powered = np.linalg.matrix_power(A, protocol['cell']['steps'])
    observed = np.array([[float(gx[0][0]), float(gx[1][0])], [float(ga[0][0]), float(ga[1][0])]])
    record = pack_trace(trace)
    checks = trace_checks(record, protocol)
    checks.update({'all_margins_strictly_negative': bool(np.max(record['margin']) < 0.),
                   'theta_gradients_exactly_zero': bool(torch.count_nonzero(gx[2]) == 0 and torch.count_nonzero(ga[2]) == 0),
                   'exact_default_observables': bool(np.array_equal(np.asarray(record['readout_Q_R_x'])[..., 0], np.zeros((protocol['cell']['steps'], len(z0)))) and np.array_equal(np.asarray(record['readout_Q_R_x'])[..., 1], np.ones((protocol['cell']['steps'], len(z0))))),
                   'linear_discrete_state_gradient': bool(np.max(np.abs(observed-powered)) <= protocol['gates']['linear_state_gradient_atol'])})
    return {'trajectory': record, 'checks': checks, 'single_step_matrix': A.tolist(), 'matrix_power': powered.tolist(),
            'observed_state_gradient': observed.tolist(), 'absolute_error': np.abs(observed-powered).tolist(),
            'z_final_theta_gradient': array(gx[2]).tolist(), 'adaptation_final_theta_gradient': array(ga[2]).tolist(),
            'passed': bool(all(checks.values())),
            'interpretation': 'All-negative direct theta insensitivity is real. An earlier positive phase could still carry theta sensitivity through later negative states; no claim that entering default erases history.'}


def run(adapter_root, financial_root, expected, output):
    protocol, inputs, backend, operator, readout, cell = setup(adapter_root, financial_root, expected)
    started = datetime.now(timezone.utc).isoformat()
    start, cpu = time.perf_counter(), time.process_time()
    result = {'schema': 'hcsn.hx-fixed-potential-audit.v1', 'protocol_sha256': expected,
              'scope': 'New fixed-physical-potential asset readout and discrete first-order BPTT wiring, not a new financial accuracy holdout or model-quality experiment.',
              'fixed_potential_readout': fixed_potential_audit(inputs, protocol, backend, operator, readout),
              'temporal': temporal_audit(inputs, protocol, backend, cell),
              'all_negative': negative_control(inputs, protocol, cell)}
    backend.verify(); verify(expected)
    result['runtime'] = {'evaluation_started_at_utc': started, 'wall_seconds': time.perf_counter()-start, 'process_cpu_seconds': time.process_time()-cpu,
                         'financial_calls': backend.calls, 'financial_states': backend.states,
                         'torch': torch.__version__, 'numpy': np.__version__, 'cuda_available': torch.cuda.is_available()}
    result['audit_passed'] = bool(all(result[name]['passed'] for name in ('fixed_potential_readout', 'temporal', 'all_negative')))
    artifact = write(output, result)
    print(json.dumps({'artifact': artifact, 'audit_passed': result['audit_passed'],
                      'fixed_potential_readout_passed': result['fixed_potential_readout']['passed'], 'temporal_checks': result['temporal']['checks'],
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
