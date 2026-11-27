"""Independent post-run arithmetic analysis; never opens label payloads."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np


ROOT = Path('/workspace/scratch/04b4c084dad8/cell-field-run-v1')
EVALUATION = Path('/workspace/scratch/04b4c084dad8/cell-field-evaluation-v1/evaluation.json')
OUTPUT = Path('/workspace/scratch/04b4c084dad8/cell-field-math-audit.json')
used = {}
seal = json.loads((ROOT / 'pre_evaluation_seal.json').read_bytes())


def checked(relative):
    path = ROOT / relative
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != seal['files'][relative]['sha256']:
        raise ValueError('sealed input differs: ' + relative)
    used[relative] = actual
    return path


def arrays(relative):
    with np.load(checked(relative), allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def cost(fields, actions, target, dt, price):
    error = fields - target
    parts = 0.5 * (error[-1] ** 2 + dt * np.square(error[:-1]).sum(axis=0))
    effort = 0.5 * dt * price * float(np.square(actions).sum())
    return {'current_tracking': float(parts[0]), 'old_tracking': float(parts[1]),
            'effort': effort, 'total': float(parts.sum()) + effort}


runs = json.loads(checked('runs.json').read_bytes())
plan = runs['protocol']
h, lam = plan['h'], plan['effort_price']
reference = {r['initial_id']: arrays(r['path']) for r in runs['references']}
controls = {r['run_id']: arrays(r['paths']['controller']) for r in runs['records']}
rows = []
error_cost = error_bellman = error_bound = 0.0
for record in runs['records']:
    name = record['run_id']
    key = f"seed{record['seed']}-{record['head']}"
    ref, control = reference[key], controls[name]
    trajectory = arrays(record['paths']['trajectory'])
    tangent = arrays(record['paths']['tangent'])
    fields = trajectory['observations'][:, :2] - ref['reference_observations'][:, :2]
    actual = cost(fields, trajectory['actions'], control['target'], h, lam)
    tangent_fields = np.einsum('kij,kj->ki', ref['C_extended'][:, :2], tangent['states'])
    tangent_cost = cost(tangent_fields, tangent['actions'], control['target'], h, lam)
    projected_fields = np.einsum('kij,kj->ki', control['charged'], tangent['projected_states'])
    projected_cost = cost(projected_fields, tangent['projected_actions'], control['target'], h, lam)
    full = controls[f"{key}-{record['mask']}-full"]
    advantage = 0.0
    charged_forcing = []
    for k, action in enumerate(tangent['actions']):
        optimum = -full['K'][k] @ tangent['states'][k] + full['offset'][k]
        difference = action - optimum
        advantage += 0.5 * float(difference @ full['riccati_W'][k] @ difference)
        residual = (ref['C_extended'][k + 1, :2] @ ref['A'][k]
                    - control['charged'][k + 1] @ control['F'][k] @ control['Cobs'][k])
        charged_forcing.append(float(np.linalg.norm(residual @ tangent['states'][k])))
    oracle = float(full['riccati_constant'][0])
    fields_difference = np.linalg.norm(tangent_fields - projected_fields, axis=1)
    sizes = np.linalg.norm(tangent_fields - control['target'], axis=1) + np.linalg.norm(projected_fields - control['target'], axis=1)
    action_difference = np.linalg.norm(tangent['actions'] - tangent['projected_actions'], axis=1)
    action_sizes = np.linalg.norm(tangent['actions'], axis=1) + np.linalg.norm(tangent['projected_actions'], axis=1)
    bound = 0.5 * float(fields_difference[-1] * sizes[-1] + h * np.sum(
        fields_difference[:-1] * sizes[:-1] + lam * action_difference * action_sizes))
    error_cost = max(error_cost, abs(actual['total'] - record['cost']['total']),
                     abs(tangent_cost['total'] - record['tangent']['cost']['total']))
    error_bellman = max(error_bellman, abs(tangent_cost['total'] - oracle - advantage))
    error_bound = max(error_bound, abs(bound - record['tangent']['same_policy_cost_bound']))
    row = {key_: record[key_] for key_ in ('run_id', 'seed', 'head', 'mask', 'policy')}
    row.update(nonlinear_cost=actual, tangent_cost=tangent_cost,
        nonlinear_minus_tangent=actual['total'] - tangent_cost['total'],
        projected_cost=projected_cost, oracle_value=oracle,
        combined_information_policy_gap=tangent_cost['total'] - oracle,
        advantage_sum=advantage, bellman_identity_abs_error=abs(tangent_cost['total'] - oracle - advantage),
        forcing_max=float(tangent['forcing'].max()), forcing_l2=float(np.linalg.norm(tangent['forcing'])),
        charged_two_loss_forcing_max=max(charged_forcing),
        charged_two_loss_forcing_l2=float(np.linalg.norm(charged_forcing)),
        tangent_field_transfer_terminal=float(tangent['field_discrepancy'][-1]),
        tangent_field_transfer_bound_terminal=float(tangent['field_transfer_bound'][-1]),
        same_policy_tangent_cost_difference=tangent_cost['total'] - projected_cost['total'],
        same_policy_tangent_cost_bound=bound,
        current_probe_initial=float(trajectory['observations'][0, 0]),
        old_probe_initial=float(trajectory['observations'][0, 1]),
        current_probe_final=float(trajectory['observations'][-1, 0]),
        old_probe_final=float(trajectory['observations'][-1, 1]),
        old_probe_change_from_warmup=float(trajectory['observations'][-1, 1] - trajectory['observations'][0, 1]))
    rows.append(row)
lookup = {(r['seed'], r['head'], r['mask'], r['policy']): r for r in rows}
for row in rows:
    zero = lookup[(row['seed'], row['head'], row['mask'], 'zero')]
    myopic = lookup[(row['seed'], row['head'], row['mask'], 'myopic')]
    row['current_probe_delta_vs_zero'] = row['current_probe_final'] - zero['current_probe_final']
    row['old_probe_delta_vs_zero'] = row['old_probe_final'] - zero['old_probe_final']
    row['cost_parts_delta_vs_zero'] = {name: row['nonlinear_cost'][name] - zero['nonlinear_cost'][name]
                                      for name in row['nonlinear_cost']}
    row['cost_improvement_over_myopic_percent'] = 100 * (1 - row['nonlinear_cost']['total'] / myopic['nonlinear_cost']['total'])

aggregate = []
for head, mask, policy in itertools.product(plan['head_modes'], plan['action_masks'], plan['policies']):
    subset = [lookup[(seed, head, mask, policy)] for seed in plan['seeds']]
    aggregate.append({'head': head, 'mask': mask, 'policy': policy, 'fixed_fits': len(subset),
        'nonlinear_cost_mean': {name: float(np.mean([r['nonlinear_cost'][name] for r in subset])) for name in subset[0]['nonlinear_cost']},
        'tangent_cost_mean': float(np.mean([r['tangent_cost']['total'] for r in subset])),
        'forcing_max_range': [float(min(r['forcing_max'] for r in subset)), float(max(r['forcing_max'] for r in subset))],
        'charged_two_loss_forcing_max_range': [float(min(r['charged_two_loss_forcing_max'] for r in subset)), float(max(r['charged_two_loss_forcing_max'] for r in subset))],
        'nonlinear_minus_tangent_range': [float(min(r['nonlinear_minus_tangent'] for r in subset)), float(max(r['nonlinear_minus_tangent'] for r in subset))],
        'current_probe_delta_vs_zero_mean': float(np.mean([r['current_probe_delta_vs_zero'] for r in subset])),
        'old_probe_delta_vs_zero_mean': float(np.mean([r['old_probe_delta_vs_zero'] for r in subset])),
        'cost_parts_delta_vs_zero_mean': {name: float(np.mean([r['cost_parts_delta_vs_zero'][name] for r in subset])) for name in subset[0]['nonlinear_cost']},
        'cost_improvement_over_myopic_percent_range': [float(min(r['cost_improvement_over_myopic_percent'] for r in subset)), float(max(r['cost_improvement_over_myopic_percent'] for r in subset))]})

mask_comparison = []
for seed, head, policy in itertools.product(plan['seeds'], plan['head_modes'], plan['policies']):
    bias, all_ = lookup[(seed, head, 'bias', policy)], lookup[(seed, head, 'all', policy)]
    mask_comparison.append({'seed': seed, 'head': head, 'policy': policy,
        'all_minus_bias_nonlinear_cost': all_['nonlinear_cost']['total'] - bias['nonlinear_cost']['total'],
        'all_minus_bias_tangent_cost': all_['tangent_cost']['total'] - bias['tangent_cost']['total'],
        'same_objective_oracle_bias_penalty': bias['oracle_value'] - all_['oracle_value']})

evaluation = json.loads(EVALUATION.read_bytes())
external = []
for head, mask, policy, role in itertools.product(plan['head_modes'], plan['action_masks'], plan['policies'], ('old_test','future_may','future_june')):
    selected = [r for r in evaluation['records'] if r['head'] == head and r['mask'] == mask and r['policy'] == policy and r['role'] == role]
    external.append({'head': head, 'mask': mask, 'policy': policy, 'role': role,
        **{metric: float(np.mean([r[metric] for r in selected])) for metric in ('nll','accuracy','nll_change_from_warmup','accuracy_change_from_warmup')}})

derivatives = [d for r in runs['references'] for d in r['derivative_audit']]
audit = {'schema': 'hepta.cell-field-independent-math-analysis.v1',
    'input_seal_sha256': hashlib.sha256((ROOT/'pre_evaluation_seal.json').read_bytes()).hexdigest(),
    'analysis_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'read_final_label_payload': False,
    'evaluation_sha256': hashlib.sha256(EVALUATION.read_bytes()).hexdigest(),
    'checked_sealed_inputs': used,
    'arithmetic': {'max_objective_reaggregation_abs_error': error_cost,
                  'max_bellman_identity_abs_error': error_bellman,
                  'max_transfer_cost_bound_reaggregation_abs_error': error_bound,
                  'max_gradient_fd_abs_discrepancy': max(d['loss_gradient_max_abs_fd_discrepancy'] for d in derivatives),
                  'max_transition_half_step_relative_difference': max(d.get('transition_theta_half_step_relative_difference', 0) for d in derivatives),
                  'max_observation_half_step_relative_difference': max(d['observation_half_step_relative_difference'] for d in derivatives)},
    'interpretation': ['Fixed fitted seeds are descriptive repeated fits, not independent source groups.',
        'The old-probe target is bilateral squared tracking of warmup loss: improvements and deterioration both incur cost.',
        'A smaller J can therefore accompany reversal of beneficial old-task loss improvement.',
        'Nested action-space monotonicity applies to full-state tangent optima, not arbitrary policies or nonlinear deployments.',
        'Q=0 point occupancy yields a combined information/policy gap; no irreducible information penalty is identified.',
        'Extended projected-Riccati policy is not the optimal controller for its richer information set.',
        'Raw forcing norms for two versus four observation coordinates differ in units; charged_two_loss_forcing uses the common two-loss output map, still along each own policy occupancy.',
        'Parameter effort is not measured runtime or energy.',
        'Finite-difference checks establish local numerical consistency only, not a uniform coefficient or nonlinear remainder bound.'],
    'per_run': rows, 'fixed_seed_means': aggregate, 'mask_comparisons': mask_comparison,
    'external_fixed_seed_means': external,
    'external_pointwise_contrasts': evaluation['contrasts']}
for name, old_hash in used.items():
    if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != old_hash:
        raise ValueError('input changed during independent analysis')
OUTPUT.write_text(json.dumps(audit, sort_keys=True, indent=2, allow_nan=False)+'\n')
print(json.dumps({'output': str(OUTPUT), 'arithmetic': audit['arithmetic'],
                  'cost_table': aggregate, 'mask_comparisons': mask_comparison,
                  'external': external}, ensure_ascii=False))
