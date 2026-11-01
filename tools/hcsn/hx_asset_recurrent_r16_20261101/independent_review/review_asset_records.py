"""Independent record arithmetic; imports neither Torch nor financial code."""
import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path('/tmp/hcsn-asset-recurrent-next-v1')
OUT = Path('/tmp/hcsn-asset-recurrent-independent-review')
PROTOCOL = '7e4791bee5b934f0aa55f603529d7ada5362b6908e70955f1441f5378691ddaa'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    raw = (ROOT / name).read_bytes()
    if name.endswith('.gz'):
        raw = gzip.decompress(raw)
    return json.loads(raw, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def need(condition, message):
    if not condition:
        raise ValueError(message)


def array(value, shape=None):
    a = np.asarray(value, dtype=np.float64)
    need(np.isfinite(a).all(), 'Nonfinite array')
    need(shape is None or a.shape == shape, 'Wrong shape')
    return a


p, inputs = read('ASSET_PROTOCOL.json'), read('ASSET_INPUTS.json')
audit, training = read('ASSET_AUDIT_V1.json.gz'), read('ASSET_TRAINING_V1.json.gz')
names = ['ASSET_PROTOCOL.json', 'ASSET_INPUTS.json', 'ASSET_AUDIT_V1.json.gz',
         'ASSET_TRAINING_V1.json.gz', 'AUDIT_EXECUTION_V1.json', 'TRAINING_EXECUTION_V1.json'] + list(p['source_sha256'])
bindings = {name: sha(ROOT / name) for name in names}
need(bindings['ASSET_PROTOCOL.json'] == PROTOCOL, 'Wrong frozen protocol')
need(bindings['ASSET_INPUTS.json'] == p['inputs_sha256'], 'Wrong fixed inputs')
for name, digest in p['source_sha256'].items():
    need(bindings[name] == digest, 'Changed frozen source ' + name)
need(audit['protocol_sha256'] == training['protocol_sha256'] == PROTOCOL, 'Result protocol mismatch')
need(audit['audit_passed'] is True and training['training_passed'] is True, 'Original writer failure')
checkpoint_time = datetime.fromisoformat('2026-11-01T17:59:10+00:00')
executions = {}
for label, artifact in [('AUDIT', 'ASSET_AUDIT_V1.json.gz'), ('TRAINING', 'ASSET_TRAINING_V1.json.gz')]:
    execution = read(label + '_EXECUTION_V1.json')
    need(execution['returncode'] == 0, 'Original process failed')
    need(execution['output_sha256'] == bindings[artifact], 'Execution output identity mismatch')
    need(datetime.fromisoformat(execution['controller_launch_utc']) > checkpoint_time, 'Launch before remote checkpoint')
    executions[label.lower()] = {'returncode': execution['returncode'], 'controller_launch_utc': execution['controller_launch_utc']}
c, g, data = p['cell'], p['gates'], inputs['training']
T, B = c['steps'], p['training']['batch_size']
need((T, B, p['training']['updates']) == (16, 8, 12), 'Wrong declared size')
need(training['data'] == data, 'Changed training targets or inputs')
need(inputs['fixed_z_rest'] == c['z_rest'], 'Wrong fixed restoration reference')


def compare(row):
    observed, reference = array(row['observed']), array(row['reference'])
    error = np.abs(observed - reference)
    need(observed.shape == reference.shape, 'Comparison shape mismatch')
    need(np.all(error <= g['gradient_atol'] + g['gradient_rtol'] * np.abs(reference)), 'Gradient/value comparison failed')
    return float(np.max(error))


fixed = audit['fixed_potential_readout']
need(len(fixed['fixtures']) == g['required_fixed_z_fixtures'] == 5, 'Missing fixed fixtures')
need(len(fixed['contracts']) == g['required_contract_checks'] == 15, 'Missing contract checks')
need(all(r['passed'] is True and r['exception_type'] for r in fixed['contracts']), 'Contract failure')
need([r['z'] for r in fixed['fixtures']] == inputs['fixed_z_fixtures'], 'Fixed fixture identity mismatch')
for row in fixed['fixtures']:
    compare(row['value']); compare(row['gradient'])
    v, b = row['represented_asset'], row['boundary']
    need(row['actual_default_branch'] == (v <= b), 'Wrong actual fixture default branch')
    need(row['other_states_max_gradient'] == 0, 'Cross-sample gradient')
    jac = array(row['gradient']['observed'], (3, 10))
    db = array(row['boundary_theta_jacobian'], (9,))
    need(np.all(np.abs(jac[2, :9] + db / b) <= g['gradient_atol'] + g['gradient_rtol'] * np.abs(db / b)), 'Missing explicit boundary chain')
    if v <= b:
        need(row['value']['observed'][:2] == [0., 1.] and np.count_nonzero(jac[:2]) == 0, 'Wrong actual default observable/gradient')
compare(fixed['exp_derivative'])

trace_count, state_count = 0, 0
loss_errors, roundtrip_errors, minimum_nonzero_margins = [], [], []


def trace(record, sample, loss=None):
    global trace_count, state_count
    batch = len(sample['initial_z'])
    z, a = array(record['z'], (T + 1, batch)), array(record['adaptation'], (T + 1, batch))
    asset = array(record['represented_asset'], (T + 1, batch))
    margin = array(record['margin'], (T + 1, batch))
    obs = array(record['readout_Q_R_x'], (T, batch, 3))
    final = array(record['final_diagnostic_readout_Q_R_x'], (batch, 3))
    drift = array(record['drift_dz_da'], (T, batch, 2))
    need(np.array_equal(z[0], sample['initial_z']) and np.array_equal(a[0], sample['initial_adaptation']), 'Initial state changed')
    need(record['fixed_z_rest'] == c['z_rest'], 'Rest reference changed')
    need(np.array_equal(margin[:-1], obs[..., 2]) and np.array_equal(margin[-1], final[..., 2]), 'Margin logging mismatch')
    need(np.all(asset > 0) and np.array_equal(asset, asset.astype(np.float32)), 'Asset representation mismatch')
    roundtrip = np.log(asset) - z
    need(np.array_equal(roundtrip, array(record['log_asset_minus_z'])), 'Exp/log discrepancy logging mismatch')
    need(np.max(np.abs(roundtrip)) <= g['max_exp_log_roundtrip_error'], 'Exp/log discrepancy too large')
    roundtrip_errors.append(float(np.max(np.abs(roundtrip))))
    nonzero = np.abs(margin[margin != 0])
    if nonzero.size:
        minimum_nonzero_margins.append(float(np.min(nonzero)))
    z32, a32, obs32 = z.astype(np.float32), a.astype(np.float32), obs.astype(np.float32)
    drive = np.asarray(sample['drive'], dtype=np.float32)
    dz = drive - c['leak'] * (z32[:-1] - c['z_rest']) - c['k_equity'] * obs32[..., 0] - c['k_risk'] * obs32[..., 1] + a32[:-1]
    da = (c['k_risk'] * obs32[..., 1] - a32[:-1]) / c['tau']
    need(np.array_equal(drift[..., 0], dz) and np.array_equal(drift[..., 1], da), 'Wrong FP32 drift')
    need(np.array_equal(z32[1:], z32[:-1] + c['dt'] * dz), 'Wrong simultaneous z update')
    need(np.array_equal(a32[1:], a32[:-1] + c['dt'] * da), 'Wrong simultaneous adaptation update')
    need(np.min(z) >= g['min_z'] and np.max(z) <= g['max_z'], 'z outside frozen bounds')
    need(np.min(a) >= -g['range_tolerance'] and np.max(a) <= g['max_adaptation'], 'Adaptation outside frozen bounds')
    need(np.min(obs[..., 0]) >= -g['range_tolerance'] and np.min(obs[..., 1]) >= -g['range_tolerance'] and np.max(obs[..., 1]) <= 1 + g['range_tolerance'], 'Readout range failed')
    nonpositive = margin[:-1] <= 0
    need(np.all(obs[..., 0][nonpositive] == 0) and np.all(obs[..., 1][nonpositive] == 1), 'Nonpositive reported-margin observable failed')
    phases = np.sign(margin).astype(int)
    need(np.array_equal(phases, record['phase']), 'Wrong reported-margin phase')
    changes = [(t, j, int(phases[t, j]), int(phases[t + 1, j])) for t in range(T) for j in range(batch) if phases[t, j] != phases[t + 1, j]]
    need(changes == [(r['step'], r['sample'], r['from'], r['to']) for r in record['crossings']], 'Wrong sampled phase change')
    if loss is not None:
        expected_loss = np.mean((z[-1] - array(sample['target_z'])) ** 2) + sample['adaptation_loss_weight'] * np.mean((a[-1] - array(sample['target_adaptation'])) ** 2)
        error = abs(loss - expected_loss)
        need(error <= g['gradient_atol'] + g['gradient_rtol'] * abs(expected_loss), 'Wrong terminal z/a loss')
        loss_errors.append(float(error))
    trace_count += 1; state_count += z.size
    return z, a, changes


temporal = audit['temporal']; comparisons = temporal['comparisons']
need(len(comparisons) == g['required_temporal_comparisons'] == 8, 'Missing temporal comparisons')
gradient_errors = {name: compare(row) for name, row in comparisons.items()}
z, a, changes = trace(temporal['trajectory'], data, temporal['loss'])
reference = temporal['independent_discrete_reference']
A, G = array(reference['state_jacobians'], (T, B, 2, 2)), array(reference['direct_theta_jacobians'], (T, B, 2, 9))
lam = np.stack([2 * (z[-1] - array(data['target_z'])) / B, 2 * data['adaptation_loss_weight'] * (a[-1] - array(data['target_adaptation'])) / B], axis=1)
step = np.zeros((T, 9))
for t in reversed(range(T)):
    step[t] = np.einsum('bi,bij->j', lam, G[t]); lam = np.einsum('bi,bij->bj', lam, A[t])
need(np.array_equal(step, reference['step_theta']), 'Recorded manual adjoint composition mismatch')
early_theta = float(np.linalg.norm(array(comparisons['step_theta']['observed'])[0]))
need(early_theta > g['nonzero_gradient_floor'], 'Missing early theta influence')
detached = temporal['detach_negative_control']
zd, ad, _ = trace(detached['trajectory'], data, detached['loss'])
need(np.array_equal(z, zd) and np.array_equal(a, ad), 'Detach changed numerical forward values')
for key, early in [('step_theta_gradients', True), ('drive_gradient', True), ('initial_z_gradient', False), ('initial_adaptation_gradient', False)]:
    v = array(detached[key]); v = v[:-1] if early else v
    need(np.count_nonzero(v) == 0, 'Detach retained early influence')
negative = audit['all_negative']
trace(negative['trajectory'], inputs['all_negative_control'])
need(np.max(negative['trajectory']['margin']) < 0, 'Negative control not negative')
need(np.count_nonzero(negative['z_final_theta_gradient']) == np.count_nonzero(negative['adaptation_final_theta_gradient']) == 0, 'Negative local theta sensitivity')
dt, leak, tau = [float(np.float32(c[k])) for k in ('dt', 'leak', 'tau')]
negative_A = np.array([[1 - dt * leak, dt], [0., 1 - dt / tau]])
negative_error = float(np.max(np.abs(array(negative['observed_state_gradient']) - np.linalg.matrix_power(negative_A, T))))
need(negative_error <= g['linear_state_gradient_atol'], 'Negative A^16 comparison failed')
previous_raw, previous_theta = np.zeros(9), array(inputs['base_theta'])
need(len(training['history']) == 12, 'Incomplete optimizer history')
for i, row in enumerate(training['history']):
    need(row['iteration'] == i, 'Wrong iteration identity')
    need(np.array_equal(previous_raw, row['raw_theta_before_update']) and np.array_equal(previous_theta, row['effective_theta_before_update']), 'Parameter update chain broken')
    need(np.array_equal(previous_theta, row['trajectory']['theta']), 'Trajectory theta binding mismatch')
    array(row['raw_theta_gradient'], (9,)); trace(row['trajectory'], data, row['terminal_loss_before_update'])
    previous_raw, previous_theta = array(row['raw_theta_after_update'], (9,)), array(row['effective_theta_after_update'], (9,))
    need(np.max(np.abs(previous_theta / array(inputs['base_theta']) - 1)) <= c['theta_fraction'] + 2e-7, 'Theta range failed')
need(np.array_equal(previous_raw, training['trainable_parameters']['raw_theta']['final']) and np.array_equal(previous_theta, training['effective_theta_final']), 'Final parameter identity mismatch')
need(set(training['trainable_parameters']) == {'raw_theta'}, 'Unexpected trainable head')
need(np.array_equal(previous_theta, training['final_trajectory']['theta']), 'Final trace theta mismatch')
_, _, final_changes = trace(training['final_trajectory'], data, training['final_loss'])
raw_chain = (array(comparisons['shared_theta']['observed']).astype(np.float32) * np.asarray(inputs['base_theta'], dtype=np.float32)) * np.float32(c['theta_fraction'])
raw_chain_error = float(np.max(np.abs(array(training['history'][0]['raw_theta_gradient']) - raw_chain)))
need(np.all(np.abs(array(training['history'][0]['raw_theta_gradient']) - raw_chain) <= g['gradient_atol'] + g['gradient_rtol'] * np.abs(raw_chain)), 'Initial raw-parameter tanh chain mismatch')
physical = training['fixed_physical_fixture']
need(physical['z'] == inputs['fixed_z_fixtures'], 'Fixed physical fixture changed')
vi, vf = array(physical['represented_assets_initial'], (5,)), array(physical['represented_assets_final'], (5,))
need(vi.astype(np.float32).tobytes() == vf.astype(np.float32).tobytes(), 'Physical input words changed')
bi, bf = training['financial_boundary_initial'], training['financial_boundary_final']
shift = -np.log(bf / bi)
observed_shift = array(physical['readout_final_Q_R_x'])[:, 2] - array(physical['readout_initial_Q_R_x'])[:, 2]
need(np.all(np.abs(observed_shift - shift) <= g['gradient_atol'] + g['gradient_rtol'] * abs(shift)), 'Boundary/margin shift mismatch')
branch_changed = np.flatnonzero((vi <= bi) != (vf <= bf)).tolist()
changed_raw = int(np.count_nonzero(previous_raw - array(training['trainable_parameters']['raw_theta']['initial'])))
changed_effective = int(np.count_nonzero(previous_theta - array(training['effective_theta_initial'])))
for name, digest in bindings.items():
    need(sha(ROOT / name) == digest, 'Artifact changed during review')

result = {'schema': 'hcsn.fixed-potential-independent-result-review.v1', 'passed': True,
          'input_sha256': bindings, 'review_script_sha256': sha(Path(__file__)),
          'original_execution_receipts': executions,
          'remote_checkpoint': {'commit': '786e535bd2a396b14e9ffab4504bc855c6f4d6b1', 'commit_time_utc': '2026-11-01T17:59:10Z', 'provided_and_verified_by_parent_before_first_execution': True},
          'counts': {'fixed_fixtures': 5, 'contracts': 15, 'temporal_comparisons': 8, 'steps': T, 'batch': B, 'training_updates': 12, 'full_trajectories_checked': trace_count, 'trajectory_state_records_checked': state_count, 'changed_raw_parameters': changed_raw, 'changed_effective_parameters': changed_effective},
          'gradient_max_absolute_errors': gradient_errors, 'early_theta_l2': early_theta,
          'initial_raw_parameter_chain_max_absolute_error': raw_chain_error,
          'detach_early_theta_drive_initial_gradients_exactly_zero': True,
          'detach_forward_scope': 'Exact numerical equality, not a signed-zero byte comparison.',
          'all_negative_theta_gradients_exactly_zero': True, 'all_negative_A_power_16_max_error': negative_error,
          'maximum_exp_log_roundtrip_error': max(roundtrip_errors), 'minimum_nonzero_reported_abs_margin': min(minimum_nonzero_margins),
          'initial_final_sampled_phase_change_counts': [len(changes), len(final_changes)],
          'maximum_terminal_loss_recomposition_error': max(loss_errors),
          'loss': {'initial': training['initial_loss'], 'final': training['final_loss'], 'absolute_decrease': training['initial_loss'] - training['final_loss'], 'percentage_decrease': 100 * (training['initial_loss'] - training['final_loss']) / training['initial_loss'], 'interpretation': 'Small change on fixed synthetic training data; no quality/generalization or optimization-superiority result.'},
          'fixed_physical_boundary_motion': {'represented_asset_words_equal': True, 'initial_boundary': bi, 'final_boundary': bf, 'expected_margin_shift': float(shift), 'maximum_margin_shift_error': float(np.max(np.abs(observed_shift - shift))), 'changed_branch_fixture_indices': branch_changed, 'changed_branch_asset_values': vi[branch_changed].tolist(), 'interpretation': 'Boundary motion against fixed physical assets is observed. All nine parameters also change field shape; this does not isolate causal threshold benefit.'},
          'review_financial_kernel_calls': 0, 'review_pytorch_calls': 0,
          'limitations': ['Record recomposition and source review are not an independent financial oracle.', 'Raw per-trajectory exact asset branch checking is delegated to a separately disclosed same-kernel auxiliary check; this review checks the recorded margin phase and the fixed fixtures with known raw boundaries.', 'Adam algorithm not independently replayed.', 'Finite-step range/finiteness and first-order BPTT only; no convergence, nonlinear stability, autonomous spiking, energy, latency or multimodal quality claim.', 'This fixed-z candidate changes the initial-state/vector-field family from V1. Its loss is not a directly comparable architecture advantage; all V1 evidence remains retained.']}
destination = OUT / 'ASSET_RESULT_INDEPENDENT_REVIEW.json'
with destination.open('x') as f:
    json.dump(result, f, indent=2, allow_nan=False); f.write('\n')
print(json.dumps({'passed': True, 'receipt': str(destination), 'sha256': sha(destination), 'counts': result['counts'], 'loss': result['loss'], 'boundary': result['fixed_physical_boundary_motion']}))
