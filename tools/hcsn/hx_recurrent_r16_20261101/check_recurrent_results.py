"""Read-only independent result gate; no financial kernel or PyTorch calls.

Recomputes recorded comparisons, Euler recurrences, temporal adjoints, losses,
counts and parameter updates. This checks receipt consistency, not financial
formula accuracy; that belongs to the previously frozen numerical protocol.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    text = gzip.decompress(path.read_bytes()).decode() if path.name.endswith('.gz') else path.read_text()
    return json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON '+value)))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def arr(value, shape=None):
    a = np.asarray(value, dtype=np.float64)
    require(np.isfinite(a).all() and (shape is None or a.shape == shape), 'Nonfinite array or wrong shape')
    return a


def check_comparison(row, gates, shape):
    observed, reference = arr(row['observed'], shape), arr(row['reference'], shape)
    allowance = gates['gradient_atol']+gates['gradient_rtol']*np.abs(reference)
    require(np.all(np.abs(observed-reference) <= allowance), 'Recomputed gradient comparison failed')
    return observed


def check_trace(row, data, protocol):
    T, B = protocol['cell']['steps'], len(data['initial_x'])
    x, a = arr(row['x'], (T+1, B)), arr(row['adaptation'], (T+1, B))
    obs, drift = arr(row['readout_Q_R_x'], (T, B, 3)), arr(row['drift_dx_da'], (T, B, 2))
    require(np.array_equal(x[0], arr(data['initial_x'])) and np.array_equal(a[0], arr(data['initial_adaptation'])), 'Initial state binding mismatch')
    require(np.array_equal(obs[..., 2], x[:-1]), 'Signed x bypass mismatch')
    require(np.array_equal(np.sign(x).astype(int), np.asarray(row['phase'])), 'Phase record mismatch')
    negative = x[:-1] <= 0.
    require(np.all(obs[..., 0][negative] == 0.) and np.all(obs[..., 1][negative] == 1.), 'Negative/zero extension mismatch')
    c, g = protocol['cell'], protocol['gates']
    require(np.max(np.abs(x)) <= g['max_abs_x'] and np.min(a) >= -g['range_tolerance'] and np.max(a) <= g['max_adaptation'], 'State bound failed')
    require(np.min(obs[..., 0]) >= -g['range_tolerance'] and np.min(obs[..., 1]) >= -g['range_tolerance'] and np.max(obs[..., 1]) <= 1.+g['range_tolerance'], 'Readout range failed')
    # Reconstruct the represented FP32 Euler operations from stored local fields.
    u = np.asarray(data['drive'], dtype=np.float32)
    require(u.shape == (T, B), 'Drive shape mismatch')
    x32, a32, o32 = x.astype(np.float32), a.astype(np.float32), obs.astype(np.float32)
    dx = u-c['leak']*x32[:-1]-c['k_equity']*o32[..., 0]-c['k_risk']*o32[..., 1]+a32[:-1]
    da = (c['k_risk']*o32[..., 1]-a32[:-1])/c['tau']
    require(np.array_equal(drift[..., 0], dx.astype(np.float64)) and np.array_equal(drift[..., 1], da.astype(np.float64)), 'Recorded Euler drift mismatch')
    require(np.array_equal(x32[1:], x32[:-1]+c['dt']*dx) and np.array_equal(a32[1:], a32[:-1]+c['dt']*da), 'Euler state recurrence mismatch')
    crossings = [(t, j, int(np.sign(x[t, j])), int(np.sign(x[t+1, j]))) for t in range(T) for j in range(B) if np.sign(x[t, j]) != np.sign(x[t+1, j])]
    require(crossings == [(r['step'], r['sample'], r['from'], r['to']) for r in row['crossings']], 'Crossing count/identity mismatch')
    return x, a, crossings


def check_loss(value, x, a, data, gates):
    expected = np.mean((x[-1]-arr(data['target_x']))**2)+data['adaptation_loss_weight']*np.mean((a[-1]-arr(data['target_adaptation']))**2)
    require(np.isfinite(value) and abs(value-expected) <= gates['gradient_atol']+gates['gradient_rtol']*abs(expected), 'Terminal loss mismatch')


def run(root, expected, audit_path, training_path, output):
    root = Path(root)
    protocol_path, inputs_path = root/'RECURRENT_PROTOCOL.json', root/'RECURRENT_INPUTS.json'
    seals = {str(p): sha(p) for p in (protocol_path, inputs_path, audit_path, training_path)}
    require(seals[str(protocol_path)] == expected, 'Wrong protocol identity')
    p, inputs, audit, training = map(read, (protocol_path, inputs_path, audit_path, training_path))
    require(sha(inputs_path) == p['inputs_sha256'], 'Input manifest changed')
    for name, digest in p['source_sha256'].items():
        require(sha(root/name) == digest, 'Source seal mismatch '+name)
        seals[str(root/name)] = digest
    require(audit['schema'] == 'hcsn.hx-recurrent-audit.v1' and training['schema'] == 'hcsn.hx-recurrent-training.v1', 'Wrong result schema')
    require(audit['protocol_sha256'] == expected == training['protocol_sha256'], 'Receipt/protocol mismatch')
    require(audit['audit_passed'] is True and training['training_passed'] is True, 'Writer reported failure')
    g, T, B = p['gates'], p['cell']['steps'], p['training']['batch_size']
    fixtures, contracts = audit['signed_readout']['fixtures'], audit['signed_readout']['contracts']
    require(len(fixtures) == g['required_signed_fixtures'] and [r['x'] for r in fixtures] == inputs['signed_fixture_x'], 'Signed fixture identity/count mismatch')
    for row in fixtures:
        check_comparison(row['value'], g, (3,)); jac = check_comparison(row['gradient'], g, (3, 10))
        require(row['other_states_max_gradient'] == 0., 'Cross-sample readout gradient')
        if row['x'] <= 0.:
            require(np.count_nonzero(jac[:2]) == 0 and row['value']['observed'][:2] == [0., 1.], 'Wrong default-side local gradients')
    expected_names = {'signed_x_negative_infinity', 'signed_x_positive_infinity', 'signed_x_nan', 'signed_x_empty', 'float64_x_rejected', 'float64_theta_rejected', 'theta_wrong_shape', 'theta_nonfinite_rejected', 'financial_rejection_propagates', 'raw_log_domain_still_rejects_negative'} | {'signed_channel_'+str(c)+'_higher_order_rejected' for c in range(3)}
    require(len(contracts) == g['required_contract_checks'] and {r['name'] for r in contracts} == expected_names and all(r['passed'] is True and r['exception_type'] for r in contracts), 'Contract failure or missing checks')
    temporal = audit['temporal']; data = inputs['training']
    x, a, crossings = check_trace(temporal['trajectory'], data, p)
    check_loss(temporal['loss'], x, a, data, g)
    require(len(crossings) >= g['minimum_sampled_phase_changes'] and set(np.sign(x).reshape(-1)) == {-1., 0., 1.}, 'Missing signed trajectory/crossing')
    shapes = {'step_theta': (T, 9), 'shared_theta': (9,), 'initial_x': (B,), 'initial_adaptation': (B,), 'drive': (T, B), 'middle_x': (B,), 'middle_adaptation': (B,), 'shared_equals_sum_of_step_contributions': (9,)}
    require(set(temporal['comparisons']) == set(shapes) and len(shapes) == g['required_temporal_comparisons'], 'Missing temporal comparisons')
    actual = {name: check_comparison(row, g, shapes[name]) for name, row in temporal['comparisons'].items()}
    ref = temporal['independent_discrete_reference']
    A, G = arr(ref['state_jacobians'], (T, B, 2, 2)), arr(ref['direct_theta_jacobians'], (T, B, 2, 9))
    lam = np.stack((2.*(x[-1]-arr(data['target_x']))/B, 2.*data['adaptation_loss_weight']*(a[-1]-arr(data['target_adaptation']))/B), axis=1)
    step = np.zeros((T, 9))
    for t in reversed(range(T)):
        step[t] = np.einsum('bi,bij->j', lam, G[t]); lam = np.einsum('bi,bij->bj', lam, A[t])
    require(np.array_equal(step, arr(ref['step_theta'], (T, 9))), 'Manual temporal composition mismatch')
    require(np.all(np.abs(actual['step_theta']-step) <= g['gradient_atol']+g['gradient_rtol']*np.abs(step)), 'Actual BPTT differs from recomposed reference')
    require(np.linalg.norm(actual['step_theta'][0]) > g['nonzero_gradient_floor'] and np.linalg.norm(actual['initial_x']) > g['nonzero_gradient_floor'] and np.linalg.norm(actual['drive'][0]) > g['nonzero_gradient_floor'], 'Missing early temporal gradient')
    detached = temporal['detach_negative_control']
    xd, ad, _ = check_trace(detached['trajectory'], data, p)
    require(np.array_equal(x, xd) and np.array_equal(a, ad), 'Detach changed forward result')
    require(np.count_nonzero(arr(detached['step_theta_gradients'], (T, 9))[:-1]) == 0 and np.count_nonzero(arr(detached['drive_gradient'], (T, B))[:-1]) == 0, 'Detach negative control retained early influence')
    require(np.count_nonzero(arr(detached['initial_x_gradient'], (B,))) == 0 and np.count_nonzero(arr(detached['initial_adaptation_gradient'], (B,))) == 0, 'Detach retained initial-state influence')
    neg = audit['all_negative']; xn, _, _ = check_trace(neg['trajectory'], inputs['all_negative_control'], p)
    require(np.max(xn) < 0. and np.count_nonzero(arr(neg['x_final_theta_gradient'], (9,))) == 0 and np.count_nonzero(arr(neg['adaptation_final_theta_gradient'], (9,))) == 0, 'All-negative control invalid')
    c = {k: float(np.float32(p['cell'][k])) for k in ('dt', 'leak', 'tau')}
    negative_matrix = np.array([[1.-c['dt']*c['leak'], c['dt']], [0., 1.-c['dt']/c['tau']]])
    require(np.max(np.abs(arr(neg['observed_state_gradient'], (2, 2))-np.linalg.matrix_power(negative_matrix, T))) <= g['linear_state_gradient_atol'], 'All-negative linear-gradient reference failed')
    history = training['history']
    require(training['data'] == data and len(history) == p['training']['updates'] and [r['iteration'] for r in history] == list(range(len(history))), 'Training count/input mismatch')
    previous = np.zeros(9)
    for row in history:
        require(np.array_equal(arr(row['raw_theta_before_update'], (9,)), previous), 'Parameter update chain broken')
        arr(row['raw_theta_gradient'], (9,)); previous = arr(row['raw_theta_after_update'], (9,))
        xt, at, _ = check_trace(row['trajectory'], data, p); check_loss(row['terminal_loss_before_update'], xt, at, data, g)
        require(np.array_equal(arr(row['effective_theta_before_update'], (9,)), arr(row['trajectory']['theta'], (9,))), 'Effective theta/trajectory mismatch')
    require(training['trainable_parameters']['raw_theta']['count'] == 9 and set(training['trainable_parameters']) == {'raw_theta'}, 'Wrong parameter set')
    require(np.array_equal(previous, arr(training['trainable_parameters']['raw_theta']['final'], (9,))) and np.linalg.norm(previous) > g['nonzero_gradient_floor'], 'No final parameter update')
    theta0, theta1 = arr(training['effective_theta_initial'], (9,)), arr(training['effective_theta_final'], (9,))
    require(np.array_equal(theta0, arr(inputs['base_theta'], (9,))) and np.max(np.abs(theta1/theta0-1.)) <= p['cell']['theta_fraction']+2e-7, 'Theta bound/initial identity failed')
    xf, af, _ = check_trace(training['final_trajectory'], data, p); check_loss(training['final_loss'], xf, af, data, g)
    require(training['initial_loss'] == history[0]['terminal_loss_before_update'], 'Initial loss binding mismatch')
    for path, digest in seals.items():
        require(sha(path) == digest, 'Artifact changed during check: '+path)
    result = {'schema': 'hcsn.hx-recurrent-independent-result-check.v1', 'passed': True,
              'protocol_sha256': expected, 'bound_artifact_sha256': seals, 'checker_sha256': sha(__file__),
              'counts': {'signed_fixtures': len(fixtures), 'contracts': len(contracts), 'temporal_comparisons': len(shapes), 'steps': T, 'batch': B, 'training_updates': len(history)},
              'financial_kernel_calls': 0, 'pytorch_calls': 0,
              'scope': 'Independent receipt/count/float32 Euler/adjoint/loss recomputation; not a replacement for financial reference validation or an adversarial proof of raw record authenticity.'}
    with Path(output).open('x') as f:
        f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': True, 'counts': result['counts'], 'receipt': str(output), 'sha256': sha(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--audit', type=Path, required=True); parser.add_argument('--training', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.root, args.protocol_sha256, args.audit, args.training, args.output)
