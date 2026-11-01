"""Read-only independent record review; never imports Torch or the financial kernel."""
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path('/tmp/hcsn-recurrent-next-v1')
OUT = Path('/tmp/hcsn-recurrent-independent-review')
EXPECTED = '87f30e6c00ea88532cc1e2e7be89174a18d2caef2799a4b0712421b0e9c8f241'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    raw = (ROOT / name).read_bytes()
    if name.endswith('.gz'):
        raw = gzip.decompress(raw)
    return json.loads(raw, parse_constant=lambda s: (_ for _ in ()).throw(ValueError(s)))


def need(test, message):
    if not test:
        raise ValueError(message)


def arr(value, shape=None):
    out = np.asarray(value, dtype=np.float64)
    need(np.isfinite(out).all(), 'Nonfinite record')
    need(shape is None or out.shape == shape, 'Wrong shape')
    return out


protocol, inputs = read('RECURRENT_PROTOCOL.json'), read('RECURRENT_INPUTS.json')
audit, training = read('RECURRENT_AUDIT_V1.json.gz'), read('RECURRENT_TRAINING_V1.json.gz')
names = ['RECURRENT_PROTOCOL.json', 'RECURRENT_INPUTS.json', 'RECURRENT_AUDIT_V1.json.gz',
         'RECURRENT_TRAINING_V1.json.gz', 'RESULT_CHECK_V1.json', 'AUDIT_EXECUTION_V1.json',
         'TRAINING_EXECUTION_V1.json', 'check_recurrent_results.py'] + list(protocol['source_sha256'])
sealed = {name: sha(ROOT / name) for name in names}
need(sealed['RECURRENT_PROTOCOL.json'] == EXPECTED, 'Wrong protocol')
need(sealed['RECURRENT_INPUTS.json'] == protocol['inputs_sha256'], 'Wrong inputs')
for name, digest in protocol['source_sha256'].items():
    need(sealed[name] == digest, 'Changed frozen source ' + name)
for prefix, artifact in [('AUDIT', 'RECURRENT_AUDIT_V1.json.gz'), ('TRAINING', 'RECURRENT_TRAINING_V1.json.gz')]:
    execution = read(prefix + '_EXECUTION_V1.json')
    code_key = 'actual_exit_code' if prefix == 'AUDIT' else 'returncode'
    hash_key = 'artifact_sha256' if prefix == 'AUDIT' else 'output_sha256'
    need(execution[code_key] == 0, 'Original execution nonzero')
    need(execution[hash_key] == sealed[artifact], 'Original execution output mismatch')
need(audit['protocol_sha256'] == training['protocol_sha256'] == EXPECTED, 'Result protocol mismatch')
need(audit['audit_passed'] is True and training['training_passed'] is True, 'Writer failure')
need(training['data'] == inputs['training'], 'Training targets or inputs changed')

cfg, gates = protocol['cell'], protocol['gates']
T, B = cfg['steps'], protocol['training']['batch_size']
data = inputs['training']
need((T, B, len(training['history'])) == (16, 8, 12), 'Wrong experiment size')
need(len(audit['signed_readout']['fixtures']) == 5 and len(audit['signed_readout']['contracts']) == 13,
     'Wrong signed/contract counts')
need(all(r['passed'] is True for r in audit['signed_readout']['contracts']), 'Contract failure')
comparisons = audit['temporal']['comparisons']
need(len(comparisons) == 8, 'Wrong temporal comparison count')
errors = {}
for name, row in comparisons.items():
    actual, expected = arr(row['observed']), arr(row['reference'])
    error = np.abs(actual - expected)
    need(np.all(error <= gates['gradient_atol'] + gates['gradient_rtol'] * np.abs(expected)),
         'Gradient comparison failed: ' + name)
    errors[name] = float(np.max(error))

loss_errors = []


def trace(record, sample, loss=None):
    batch = len(sample['initial_x'])
    x = arr(record['x'], (T + 1, batch))
    a = arr(record['adaptation'], (T + 1, batch))
    obs = arr(record['readout_Q_R_x'], (T, batch, 3))
    drift = arr(record['drift_dx_da'], (T, batch, 2))
    need(np.array_equal(x[0], sample['initial_x']) and np.array_equal(a[0], sample['initial_adaptation']), 'Changed initial state')
    need(np.array_equal(obs[..., 2], x[:-1]), 'Signed state bypass changed')
    mask = x[:-1] <= 0
    need(np.all(obs[..., 0][mask] == 0) and np.all(obs[..., 1][mask] == 1), 'Default extension changed')
    x32, a32, o32 = x.astype(np.float32), a.astype(np.float32), obs.astype(np.float32)
    drive = np.asarray(sample['drive'], dtype=np.float32)
    dx = drive - cfg['leak'] * x32[:-1] - cfg['k_equity'] * o32[..., 0] - cfg['k_risk'] * o32[..., 1] + a32[:-1]
    da = (cfg['k_risk'] * o32[..., 1] - a32[:-1]) / cfg['tau']
    need(np.array_equal(dx, drift[..., 0]) and np.array_equal(da, drift[..., 1]), 'Wrong FP32 drift')
    need(np.array_equal(x32[1:], x32[:-1] + cfg['dt'] * dx), 'Wrong FP32 x recurrence')
    need(np.array_equal(a32[1:], a32[:-1] + cfg['dt'] * da), 'Wrong FP32 adaptation recurrence')
    need(np.max(np.abs(x)) <= gates['max_abs_x'] and np.min(a) >= -gates['range_tolerance'] and np.max(a) <= gates['max_adaptation'], 'Unbounded trace')
    phases = np.sign(x).astype(int)
    changes = [(t, j, int(phases[t, j]), int(phases[t + 1, j])) for t in range(T) for j in range(batch) if phases[t, j] != phases[t + 1, j]]
    need(changes == [(r['step'], r['sample'], r['from'], r['to']) for r in record['crossings']], 'Wrong sampled crossing record')
    if loss is not None:
        expected_loss = np.mean((x[-1] - arr(sample['target_x'])) ** 2) + sample['adaptation_loss_weight'] * np.mean((a[-1] - arr(sample['target_adaptation'])) ** 2)
        error = abs(loss - expected_loss)
        need(error <= gates['gradient_atol'] + gates['gradient_rtol'] * abs(expected_loss), 'Wrong recorded terminal loss')
        loss_errors.append(float(error))
    return x, a, changes


temporal = audit['temporal']
x, a, changes = trace(temporal['trajectory'], data, temporal['loss'])
detached = temporal['detach_negative_control']
xd, ad, _ = trace(detached['trajectory'], data, detached['loss'])
need(np.array_equal(x, xd) and np.array_equal(a, ad), 'Detach changed numerical forward values')
for key, slicing in [('step_theta_gradients', True), ('drive_gradient', True), ('initial_x_gradient', False), ('initial_adaptation_gradient', False)]:
    value = arr(detached[key]); value = value[:-1] if slicing else value
    need(np.count_nonzero(value) == 0, 'Detach control retained early influence')
reference = temporal['independent_discrete_reference']
A = arr(reference['state_jacobians'], (T, B, 2, 2))
G = arr(reference['direct_theta_jacobians'], (T, B, 2, 9))
lam = np.stack([2 * (x[-1] - arr(data['target_x'])) / B,
                2 * data['adaptation_loss_weight'] * (a[-1] - arr(data['target_adaptation'])) / B], axis=1)
step = np.zeros((T, 9))
for t in range(T - 1, -1, -1):
    step[t] = np.einsum('bi,bij->j', lam, G[t])
    lam = np.einsum('bi,bij->bj', lam, A[t])
need(np.array_equal(step, arr(reference['step_theta'])), 'Manual adjoint composition mismatch')
early = float(np.linalg.norm(arr(comparisons['step_theta']['observed'])[0]))
need(early > gates['nonzero_gradient_floor'], 'No early theta contribution')
negative = audit['all_negative']
xn, _, _ = trace(negative['trajectory'], inputs['all_negative_control'])
need(np.max(xn) < 0, 'Negative control crossed boundary')
need(np.count_nonzero(negative['x_final_theta_gradient']) == np.count_nonzero(negative['adaptation_final_theta_gradient']) == 0, 'Negative theta sensitivity')
dt, leak, tau = [float(np.float32(cfg[k])) for k in ('dt', 'leak', 'tau')]
negative_A = np.array([[1 - dt * leak, dt], [0., 1 - dt / tau]])
negative_error = float(np.max(np.abs(arr(negative['observed_state_gradient']) - np.linalg.matrix_power(negative_A, T))))
need(negative_error <= gates['linear_state_gradient_atol'], 'Negative control A^16 mismatch')

previous_raw, previous_theta = np.zeros(9), arr(inputs['base_theta'])
for index, row in enumerate(training['history']):
    need(row['iteration'] == index, 'Iteration gap')
    need(np.array_equal(arr(row['raw_theta_before_update'], (9,)), previous_raw), 'Raw theta update chain broken')
    need(np.array_equal(arr(row['effective_theta_before_update'], (9,)), previous_theta), 'Effective theta update chain broken')
    need(np.array_equal(row['trajectory']['theta'], previous_theta), 'Trajectory theta mismatch')
    arr(row['raw_theta_gradient'], (9,))
    trace(row['trajectory'], data, row['terminal_loss_before_update'])
    previous_raw, previous_theta = arr(row['raw_theta_after_update'], (9,)), arr(row['effective_theta_after_update'], (9,))
    need(np.max(np.abs(previous_theta / arr(inputs['base_theta']) - 1)) <= cfg['theta_fraction'] + 2e-7, 'Theta bound violated')
need(np.array_equal(previous_raw, training['trainable_parameters']['raw_theta']['final']), 'Final raw theta mismatch')
need(np.array_equal(previous_theta, training['effective_theta_final']), 'Final effective theta mismatch')
need(np.array_equal(previous_theta, training['final_trajectory']['theta']), 'Final trajectory theta mismatch')
_, _, final_changes = trace(training['final_trajectory'], data, training['final_loss'])
changed_raw = int(np.count_nonzero(previous_raw - arr(training['trainable_parameters']['raw_theta']['initial'])))
changed_effective = int(np.count_nonzero(previous_theta - arr(training['effective_theta_initial'])))
need(changed_raw == changed_effective == 9, 'Not all nine parameters changed')
need(set(training['trainable_parameters']) == {'raw_theta'}, 'Unexpected trainable head')
for name, digest in sealed.items():
    need(sha(ROOT / name) == digest, 'Artifact changed during review')

result = {
    'schema': 'hcsn.independent-recurrent-result-review.v1', 'passed': True,
    'source_review': 'Joint C1 signed neural observable, old-state Euler updates, complete theta chain and normal undetached temporal graph reviewed separately in PREVALIDATION_REVIEW.',
    'input_sha256': sealed, 'review_script_sha256': sha(Path(__file__)),
    'counts': {'signed_fixtures': 5, 'contracts': 13, 'temporal_comparisons': 8, 'steps': T, 'batch': B, 'training_updates': 12, 'changed_raw_theta_entries': changed_raw, 'changed_effective_theta_entries': changed_effective, 'full_recorded_trajectories_checked': 16},
    'temporal_gradient_max_absolute_errors': errors,
    'early_theta_contribution_l2': early,
    'initial_x_gradient_l2': float(np.linalg.norm(comparisons['initial_x']['observed'])),
    'initial_and_final_sampled_phase_changes': [len(changes), len(final_changes)],
    'sampled_change_types': sorted({str(c[2]) + '->' + str(c[3]) for c in changes}),
    'all_negative_theta_gradients_exactly_zero': True, 'all_negative_A_power_16_max_error': negative_error,
    'detach_early_theta_drive_initial_gradients_exactly_zero': True,
    'detach_forward_equality': 'Exact numerical equality via NumPy array_equal; this comparison does not distinguish positive and negative zero.',
    'loss': {'initial': training['initial_loss'], 'final': training['final_loss'], 'absolute_decrease': training['initial_loss'] - training['final_loss'], 'percentage_decrease': 100 * (training['initial_loss'] - training['final_loss']) / training['initial_loss'], 'interpretation': 'Nearly unchanged training loss; no optimization-effectiveness or generalization claim.'},
    'maximum_terminal_loss_recomposition_error': max(loss_errors),
    'boundary_diagnostic': {'initial': training['financial_boundary_initial'], 'final': training['financial_boundary_final'], 'interpretation': 'Independent x is held fixed; V=b(theta)*exp(x) changes with b. A changed b alone is not proof of threshold movement against fixed asset input.'},
    'original_execution_returncodes': {'audit': 0, 'training': 0},
    'review_financial_kernel_calls': 0, 'review_pytorch_calls': 0,
    'chronology': 'Local protocol/source freeze and functions.store preceded first recurrent audit. Parent remote checkpoint a629f9b was published after first audit; this is not remote preregistration before opening.',
    'scope': ['Deterministic finite-step functional integration proof only; full local Jacobian and BPTT records retained.', 'Record arithmetic and source identities independently reviewed; Adam algorithm was not independently replayed.', 'Not a new financial holdout, quality-gate closure, analytic temporal solution, stability proof, spike proof, multimodal result, energy or performance advantage.', 'V1 remains unchanged. A future fixed-z asset model changes initial-state/drive/leak semantics and is a separate candidate, not an equivalent coordinate rewrite.']
}
destination = OUT / 'RECURRENT_RESULT_INDEPENDENT_REVIEW.json'
with destination.open('x') as handle:
    json.dump(result, handle, indent=2, allow_nan=False)
    handle.write('\n')
print(json.dumps({'passed': True, 'receipt': str(destination), 'sha256': sha(destination), 'counts': result['counts'], 'loss': result['loss']}))
