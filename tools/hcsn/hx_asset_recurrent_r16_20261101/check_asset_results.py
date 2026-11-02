"""Independent record gate plus actual frozen-kernel branch-predicate checks.

No Torch or optimizer rerun. Reuses the same financial kernel for raw b and five
local input/Jacobian bindings; it is explicitly not an independent finance oracle.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    path = Path(path)
    text = gzip.decompress(path.read_bytes()).decode() if path.name.endswith('.gz') else path.read_text()
    return json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON '+x)))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def arr(value, shape=None):
    out = np.asarray(value, dtype=np.float64)
    require(np.isfinite(out).all() and (shape is None or out.shape == shape), 'Nonfinite array or wrong shape')
    return out


def close(value, reference, gates, message):
    value, reference = arr(value), arr(reference)
    require(value.shape == reference.shape and np.all(np.abs(value-reference) <= gates['gradient_atol']+gates['gradient_rtol']*np.abs(reference)), message)


def native_references(financial_root, protocol, inputs, fixtures, specs, seals):
    financial_root = Path(financial_root)
    fp = financial_root/'RECOVERY_PROTOCOL_V1.json'
    require(sha(fp) == protocol['dependencies']['financial_protocol_sha256'], 'Wrong financial protocol')
    original = read(fp)
    files = dict(original['source_sha256'])
    files.update({'RECOVERY_PROTOCOL_V1.json': protocol['dependencies']['financial_protocol_sha256'],
                  'recovered.so': original['binary_sha256'], 'RECOVERED_BUILD.json': original['build_receipt_sha256'],
                  'RECOVERY_CASES_V1.json': original['manifest_sha256']})
    for name, expected in files.items():
        require(sha(financial_root/name) == expected, 'Changed financial source '+name)
        seals[str(financial_root/name)] = expected
    unique, index = [], {}
    for _, row, _ in specs:
        theta = arr(row['theta'], (9,))
        require(np.array_equal(theta, theta.astype(np.float32).astype(np.float64)), 'Theta is not represented FP32')
        key = tuple(theta.tolist())
        if key not in index:
            index[key] = len(unique); unique.append(theta)
    theta_rows = unique+[arr(inputs['base_theta'], (9,)) for _ in fixtures]
    state_rows = [protocol['fixed_boundary_probe_asset']]*len(unique)+[row['represented_asset'] for row in fixtures]
    spec = importlib.util.spec_from_file_location('_asset_record_frozen_kernel', financial_root/'compiled.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    kernel = module.Kernel(financial_root/'recovered.so')
    values, jacobians, status = kernel.batch(np.asarray(theta_rows, dtype=np.float32), np.asarray(state_rows, dtype=np.float32), ['asset']*len(theta_rows), 'float64')
    require(np.all(status == 0) and np.isfinite(values).all() and np.isfinite(jacobians).all(), 'Native branch reference rejected')
    boundaries = {key: float(values[i, 0]) for key, i in index.items()}
    return boundaries, values[len(unique):], jacobians[len(unique):], {
        'calls': 1, 'states': len(theta_rows), 'unique_trajectory_theta': len(unique),
        'boundaries': [{'theta': list(key), 'boundary': b} for key, b in boundaries.items()],
        'scope': 'Same frozen FP64 kernel, raw boundary and five fixed local records only; not a new independent financial oracle or accuracy qualification.'}


def check_trace(row, data, p, boundary):
    T, B, g, c = p['cell']['steps'], len(data['initial_z']), p['gates'], p['cell']
    z, a = arr(row['z'], (T+1, B)), arr(row['adaptation'], (T+1, B))
    obs, final = arr(row['readout_Q_R_x'], (T, B, 3)), arr(row['final_diagnostic_readout_Q_R_x'], (B, 3))
    assets, margin = arr(row['represented_asset'], z.shape), arr(row['margin'], z.shape)
    drift = arr(row['drift_dz_da'], (T, B, 2))
    require(row['fixed_z_rest'] == c['z_rest'] and np.array_equal(z[0], arr(data['initial_z'])) and np.array_equal(a[0], arr(data['initial_adaptation'])), 'Fixed physical initial/rest identity failed')
    require(np.array_equal(assets, assets.astype(np.float32).astype(np.float64)) and np.min(assets) > 0., 'Unrepresented or nonpositive physical asset')
    roundtrip = np.log(assets)-z
    require(np.max(np.abs(roundtrip)) <= g['max_exp_log_roundtrip_error'], 'exp/log roundtrip too large')
    close(row['log_asset_minus_z'], roundtrip, g, 'Roundtrip disclosure mismatch')
    close(margin, np.log(assets/boundary), g, 'Margin is not bound to true raw financial boundary')
    require(np.array_equal(margin[:-1], obs[..., 2]) and np.array_equal(margin[-1], final[:, 2]), 'Recorded margin/readout mismatch')
    # Unlike merely testing sign(log(V/b)), this uses the actual kernel b.
    default = assets <= boundary
    require(np.array_equal(default, margin <= 0.), 'Actual V<=b branch differs from reported margin phase')
    require(np.array_equal(np.sign(margin).astype(int), np.asarray(row['phase'])), 'Phase mismatch')
    all_obs = np.concatenate((obs, final[None, :, :]), axis=0)
    require(np.all(all_obs[..., 0][default] == 0.) and np.all(all_obs[..., 1][default] == 1.), 'Actual financial default Q/R mismatch')
    require(np.min(z) >= g['min_z'] and np.max(z) <= g['max_z'] and np.min(a) >= -g['range_tolerance'] and np.max(a) <= g['max_adaptation'], 'State range failed')
    require(np.min(all_obs[..., 0]) >= -g['range_tolerance'] and np.min(all_obs[..., 1]) >= -g['range_tolerance'] and np.max(all_obs[..., 1]) <= 1.+g['range_tolerance'], 'Readout range failed')
    u = np.asarray(data['drive'], dtype=np.float32); require(u.shape == (T, B), 'Drive shape mismatch')
    z32, a32, o32 = z.astype(np.float32), a.astype(np.float32), obs.astype(np.float32)
    dz = u-c['leak']*(z32[:-1]-c['z_rest'])-c['k_equity']*o32[..., 0]-c['k_risk']*o32[..., 1]+a32[:-1]
    da = (c['k_risk']*o32[..., 1]-a32[:-1])/c['tau']
    require(np.array_equal(drift[..., 0], dz.astype(np.float64)) and np.array_equal(drift[..., 1], da.astype(np.float64)), 'Euler drift mismatch')
    require(np.array_equal(z32[1:], z32[:-1]+c['dt']*dz) and np.array_equal(a32[1:], a32[:-1]+c['dt']*da), 'Euler recurrence mismatch')
    changes = [(t, j, int(np.sign(margin[t, j])), int(np.sign(margin[t+1, j]))) for t in range(T) for j in range(B) if np.sign(margin[t, j]) != np.sign(margin[t+1, j])]
    require(changes == [(v['step'], v['sample'], v['from'], v['to']) for v in row['crossings']], 'Phase-change count/identity mismatch')
    return z, a, {'states_checked': int(z.size), 'actual_default_states': int(default.sum()), 'minimum_absolute_reported_margin': float(np.min(np.abs(margin))), 'sampled_phase_changes': len(changes)}


def loss_check(loss, z, a, data, gates):
    expected = np.mean((z[-1]-arr(data['target_z']))**2)+data['adaptation_loss_weight']*np.mean((a[-1]-arr(data['target_adaptation']))**2)
    close(float(loss), float(expected), gates, 'Terminal physical z/a loss mismatch')


def run(root, expected, audit_path, training_path, financial_root, output):
    root = Path(root); pp, ip = root/'ASSET_PROTOCOL.json', root/'ASSET_INPUTS.json'
    seals = {str(path): sha(path) for path in (pp, ip, audit_path, training_path, Path(__file__))}
    require(seals[str(pp)] == expected, 'Wrong fixed-potential protocol')
    p, inputs, audit, train = map(read, (pp, ip, audit_path, training_path))
    require(sha(ip) == p['inputs_sha256'], 'Input manifest changed')
    for name, digest in p['source_sha256'].items():
        require(sha(root/name) == digest, 'Source changed '+name); seals[str(root/name)] = digest
    require(audit['schema'] == 'hcsn.hx-fixed-potential-audit.v1' and train['schema'] == 'hcsn.hx-fixed-potential-training.v1', 'Wrong result schema')
    require(audit['protocol_sha256'] == expected == train['protocol_sha256'], 'Receipt/protocol mismatch')
    require(audit['audit_passed'] is True and train['training_passed'] is True, 'Original writer reported failure')
    g, T, B = p['gates'], p['cell']['steps'], p['training']['batch_size']
    fixtures, contracts = audit['fixed_potential_readout']['fixtures'], audit['fixed_potential_readout']['contracts']
    require(len(fixtures) == g['required_fixed_z_fixtures'] and [v['z'] for v in fixtures] == inputs['fixed_z_fixtures'], 'Fixed-z fixture identity/count mismatch')
    names = {'z_negative_infinity', 'z_positive_infinity', 'z_nan', 'z_empty', 'float64_z_rejected', 'float64_theta_rejected', 'theta_wrong_shape', 'theta_nonfinite_rejected', 'financial_rejection_propagates', 'exp_overflow_rejected', 'exp_underflow_rejected', 'original_asset_domain_rejects_zero'} | {'channel_'+str(c)+'_higher_order_rejected' for c in range(3)}
    require(len(contracts) == g['required_contract_checks'] and {v['name'] for v in contracts} == names and all(v['passed'] is True and v['exception_type'] for v in contracts), 'Incomplete interface contracts')
    history = train['history']; data = inputs['training']; temporal = audit['temporal']
    require(train['data'] == data and len(history) == p['training']['updates'] and [v['iteration'] for v in history] == list(range(len(history))), 'Training input/count mismatch')
    specs = [('audit', temporal['trajectory'], data), ('detached', temporal['detach_negative_control']['trajectory'], data), ('all_default', audit['all_negative']['trajectory'], inputs['all_negative_control'])]
    specs += [('training_'+str(i), v['trajectory'], data) for i, v in enumerate(history)]+[('final', train['final_trajectory'], data)]
    boundaries, local_values, local_j, native = native_references(financial_root, p, inputs, fixtures, specs, seals)
    for row, values, jac in zip(fixtures, local_values, local_j):
        v, b, e, f = row['represented_asset'], values[0], values[1], values[2]
        require(row['actual_default_branch'] == bool(v <= b), 'Fixed fixture raw branch mismatch')
        expected_value = np.array([e/b, 1.-(1.-f)**2, np.log(v/b)])
        expected_j = np.zeros((3, 10)); expected_j[0] = jac[1]/b-e*jac[0]/b**2
        expected_j[1] = 2.*(1.-f)*jac[2]; expected_j[:2, 9] *= v
        expected_j[2, :9] = -jac[0, :9]/b; expected_j[2, 9] = 1.
        close(row['value']['observed'], expected_value, g, 'Fixed-z local values mismatch')
        close(row['gradient']['observed'], expected_j, g, 'Fixed-z full asset/exp/boundary chain mismatch')
        close(row['gradient']['reference'], expected_j, g, 'Recorded local reference mismatch')
        require(row['other_states_max_gradient'] == 0., 'Cross-sample derivative')
    branch_records = {}; trace_arrays = {}
    for name, row, datum in specs:
        theta = tuple(arr(row['theta'], (9,)).tolist())
        z, a, record = check_trace(row, datum, p, boundaries[theta]); branch_records[name] = record; trace_arrays[name] = (z, a)
    require(branch_records['audit']['sampled_phase_changes'] >= g['minimum_sampled_phase_changes'], 'Missing driven phase change')
    loss_check(temporal['loss'], *trace_arrays['audit'], data, g)
    shapes = {'step_theta': (T, 9), 'shared_theta': (9,), 'initial_z': (B,), 'initial_adaptation': (B,), 'drive': (T, B), 'middle_z': (B,), 'middle_adaptation': (B,), 'shared_equals_sum_of_step_contributions': (9,)}
    require(set(temporal['comparisons']) == set(shapes) and len(shapes) == g['required_temporal_comparisons'], 'Missing temporal comparisons')
    actual = {}
    for name, row in temporal['comparisons'].items():
        actual[name] = arr(row['observed'], shapes[name]); close(actual[name], arr(row['reference'], shapes[name]), g, 'Temporal gradient comparison failed')
    ref = temporal['independent_discrete_reference']; A, G = arr(ref['state_jacobians'], (T, B, 2, 2)), arr(ref['direct_theta_jacobians'], (T, B, 2, 9))
    z, a = trace_arrays['audit']; lam = np.stack((2.*(z[-1]-arr(data['target_z']))/B, 2.*data['adaptation_loss_weight']*(a[-1]-arr(data['target_adaptation']))/B), axis=1)
    adjoints = np.zeros((T+1, B, 2)); adjoints[T] = lam; per_step = np.zeros((T, 9)); drive = np.zeros((T, B))
    dt = float(np.float32(p['cell']['dt']))
    for t in reversed(range(T)):
        per_step[t] = np.einsum('bi,bij->j', lam, G[t]); drive[t] = dt*lam[:, 0]
        lam = np.einsum('bi,bij->bj', lam, A[t]); adjoints[t] = lam
    expected_grad = {'step_theta': per_step, 'shared_theta': per_step.sum(axis=0), 'initial_z': adjoints[0, :, 0], 'initial_adaptation': adjoints[0, :, 1], 'drive': drive, 'middle_z': adjoints[T//2, :, 0], 'middle_adaptation': adjoints[T//2, :, 1], 'shared_equals_sum_of_step_contributions': per_step.sum(axis=0)}
    for name, value in expected_grad.items(): close(actual[name], value, g, 'Independent temporal reassembly failed '+name)
    require(np.linalg.norm(actual['step_theta'][0]) > g['nonzero_gradient_floor'] and np.linalg.norm(actual['initial_z']) > g['nonzero_gradient_floor'] and np.linalg.norm(actual['drive'][0]) > g['nonzero_gradient_floor'], 'Missing actual early temporal sensitivity')
    detached = temporal['detach_negative_control']; zd, ad = trace_arrays['detached']
    require(np.array_equal(z, zd) and np.array_equal(a, ad), 'Detached forward changed')
    require(np.count_nonzero(arr(detached['step_theta_gradients'], (T, 9))[:-1]) == 0 and np.count_nonzero(arr(detached['drive_gradient'], (T, B))[:-1]) == 0 and np.count_nonzero(arr(detached['initial_z_gradient'], (B,))) == 0 and np.count_nonzero(arr(detached['initial_adaptation_gradient'], (B,))) == 0, 'Detach negative control retained early gradients')
    neg = audit['all_negative']; c = {k: float(np.float32(p['cell'][k])) for k in ('dt', 'leak', 'tau')}
    M = np.array([[1.-c['dt']*c['leak'], c['dt']], [0., 1.-c['dt']/c['tau']]])
    require(branch_records['all_default']['actual_default_states'] == branch_records['all_default']['states_checked'] and np.count_nonzero(arr(neg['z_final_theta_gradient'], (9,))) == 0 and np.count_nonzero(arr(neg['adaptation_final_theta_gradient'], (9,))) == 0, 'All-default parameter control failed')
    require(np.max(np.abs(arr(neg['observed_state_gradient'], (2, 2))-np.linalg.matrix_power(M, T))) <= g['linear_state_gradient_atol'], 'All-default discrete state reference failed')
    previous = np.zeros(9)
    for i, row in enumerate(history):
        require(np.array_equal(arr(row['raw_theta_before_update'], (9,)), previous), 'Optimizer parameter chain broken')
        arr(row['raw_theta_gradient'], (9,)); previous = arr(row['raw_theta_after_update'], (9,))
        require(np.array_equal(arr(row['effective_theta_before_update'], (9,)), arr(row['trajectory']['theta'], (9,))), 'Effective theta/trace mismatch')
        loss_check(row['terminal_loss_before_update'], *trace_arrays['training_'+str(i)], data, g)
    require(set(train['trainable_parameters']) == {'raw_theta'} and train['trainable_parameters']['raw_theta']['count'] == 9 and np.array_equal(previous, arr(train['trainable_parameters']['raw_theta']['final'], (9,))) and np.linalg.norm(previous) > g['nonzero_gradient_floor'], 'No actual nine-parameter update')
    theta0, theta1 = arr(train['effective_theta_initial'], (9,)), arr(train['effective_theta_final'], (9,))
    require(np.array_equal(theta0, arr(inputs['base_theta'], (9,))) and np.max(np.abs(theta1/theta0-1.)) <= p['cell']['theta_fraction']+2e-7, 'Theta initialization/bound failed')
    require(np.array_equal(theta1, arr(train['final_trajectory']['theta'], (9,))), 'Final theta binding failed')
    loss_check(train['final_loss'], *trace_arrays['final'], data, g)
    fixed = train['fixed_physical_fixture']; require(fixed['z'] == inputs['fixed_z_fixtures'], 'Fixed physical probe changed')
    v0, v1 = arr(fixed['represented_assets_initial'], (5,)), arr(fixed['represented_assets_final'], (5,))
    require(np.array_equal(v0, v1) and np.array_equal(v0, arr([v['represented_asset'] for v in fixtures])), 'Physical assets changed with theta')
    b0, b1 = boundaries[tuple(theta0.tolist())], boundaries[tuple(theta1.tolist())]
    require(abs(b1-b0) > g['nonzero_gradient_floor'] and abs(b0-train['financial_boundary_initial']) <= g['gradient_atol'] and abs(b1-train['financial_boundary_final']) <= g['gradient_atol'], 'Actual fixed-physical boundary movement failed')
    before, after = arr(fixed['readout_initial_Q_R_x'], (5, 3)), arr(fixed['readout_final_Q_R_x'], (5, 3))
    close(before[:, 2], np.log(v0/b0), g, 'Initial physical margin/b binding failed'); close(after[:, 2], np.log(v1/b1), g, 'Final physical margin/b binding failed')
    close(after[:, 2]-before[:, 2], np.full(5, -np.log(b1/b0)), g, 'Physical margin did not follow full boundary shift')
    for path, digest in seals.items(): require(sha(path) == digest, 'Artifact changed during check '+path)
    result = {'schema': 'hcsn.hx-fixed-potential-result-check.v1', 'passed': True, 'protocol_sha256': expected,
              'bound_artifact_sha256': seals, 'counts': {'fixed_z_fixtures': len(fixtures), 'contracts': len(contracts), 'temporal_comparisons': len(shapes), 'steps': T, 'batch': B, 'training_updates': len(history), 'full_trajectories': len(specs)},
              'native_branch_reference': native, 'actual_branch_checks': branch_records,
              'total_trace_state_branches_checked': sum(v['states_checked'] for v in branch_records.values()),
              'all_reported_margin_phase_default_masks_equal_actual_V_le_b': True,
              'physical_fixed_fixture': {'boundary_before': b0, 'boundary_after': b1, 'represented_assets': v0.tolist(), 'actual_default_before': (v0 <= b0).tolist(), 'actual_default_after': (v0 <= b1).tolist(), 'margin_shift': float(-np.log(b1/b0))},
              'pytorch_calls': 0, 'optimizer_replays': 0,
              'scope': 'Read-only count/input/source binding, fixed FP32 Euler and adjoint records, true raw-boundary branch predicates and fixed physical boundary movement. Same financial kernel, not a second finance oracle, quality test or stability proof.'}
    with Path(output).open('x') as f: f.write(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(json.dumps({'passed': True, 'counts': result['counts'], 'branch_states': result['total_trace_state_branches_checked'], 'native_reference_states': native['states'], 'output': str(output), 'sha256': sha(output)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True); parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--audit', type=Path, required=True); parser.add_argument('--training', type=Path, required=True)
    parser.add_argument('--financial-root', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args(); run(a.root, a.protocol_sha256, a.audit, a.training, a.financial_root, a.output)
