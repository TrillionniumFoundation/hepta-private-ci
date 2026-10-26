"""Frozen source-unit summaries; failed requests remain in every task total."""

import math

import numpy as np
from scipy.stats import beta

from .calibrate import ece


def qualification(rows, missing, policy):
    selected = [r for r in rows if r['policy'] == policy]
    ood = [r for r in missing if r['policy'] == policy]
    emitted = [r for r in selected if r['initial_selected_probability'] is not None]
    selected_ece = ece([r['initial_selected_probability'] for r in emitted], [r['strict_success'] for r in emitted])
    pooled_p, pooled_y = [], []
    for row in selected:
        pooled_p.extend(row['initial_code_confidence'])
        pooled_y.extend([int(i == row['offline_target_code']) for i in range(len(row['initial_code_confidence']))])
    pooled = ece(pooled_p, pooled_y)
    accepted = sum(r['accepted'] for r in ood)
    upper = float(beta.ppf(.95, accepted + 1, len(ood) - accepted)) if accepted < len(ood) else 1.
    coverage = sum(r['request_nonempty'] for r in selected) / len(selected)
    gates = {'selected_action_ece': selected_ece is not None and selected_ece <= .03,
        'pooled_ece': pooled is not None and pooled <= .03, 'ID_request_coverage': coverage >= .25,
        'all_missing_false_acceptance': len(ood) == 600 and upper <= .004999}
    groups = {r['source_group'] for r in selected}
    return {'policy': policy, 'gates': gates, 'study_qualified': all(gates.values()),
        'ID_actual_requests': len(selected), 'ID_independent_writers': len(groups),
        'selected_initial_operations': len(emitted), 'selected_initial_operation_ECE': selected_ece,
        'pooled_fixed_endpoint_counterfactual_code_ECE': pooled, 'ID_request_coverage': coverage,
        'ID_strict_success_including_refusal': sum(r['strict_success'] for r in selected) / len(selected),
        'H1_selected_ECE_separate': ece([r['H1_selected_probability'] for r in selected if r['H1_selected_probability'] is not None],
                                       [r['strict_success'] for r in selected if r['H1_selected_probability'] is not None]),
        'all_missing_actual_requests': len(ood), 'OOD_independent_source_speakers': len({r['speaker'] for r in ood}),
        'all_missing_false_acceptances': accepted, 'all_missing_one_sided_95_upper': upper,
        'independent_missing_speaker_is_distinct_model_input': False,
        'unique_missing_public_numeric_inputs': len({r['public_numeric_input_sha256'] for r in ood}),
        'unique_missing_initial_numeric_states': len({r['initial_numeric_state_sha256'] for r in ood}),
        'unique_missing_RNG_states': len({r['RNG_state_sha256'] for r in ood}),
        'missing_scope': 'Exact structural all-input-missing state; binomial interpretation conditional on registered IID source-request sampling, not natural OOD',
        'errors_retained': sum(r['execution_error'] is not None for r in selected),
        'source_units_not_multiplied_by_routes_or_policies': True}


def confirmation(rows, seed=46117, samples=10000):
    paired = {}
    for row in rows:
        if row['route'] not in ('image', 'video'): continue
        paired.setdefault((row['case_index'], row['route']), {})[row['policy']] = row
    if any(set(pair) != {'dynamic', 'fixed_late'} for pair in paired.values()):
        raise ValueError('Every registered primary case must have both policy outcomes including failures')
    groups = {}
    for pair in paired.values():
        d, f = pair['dynamic'], pair['fixed_late']
        if d['source_group'] != f['source_group']: raise ValueError('Primary pairing crossed source groups')
        groups.setdefault(d['source_group'], []).append((d, f))
    moments, strict, wall = [], [], []
    for group in sorted(groups):
        pairs = groups[group]
        moments.append([np.mean([math.exp(-2 * (pair[k]['utility'] - pair[k]['registered_cost'])) for pair in pairs]) for k in (0, 1)])
        strict.append([np.mean([pair[k]['strict_success'] for pair in pairs]) for k in (0, 1)])
        wall.append([np.mean([pair[k]['whole_execution_wall_ns'] for pair in pairs]) for k in (0, 1)])
    moment, strict, wall = np.asarray(moments), np.asarray(strict), np.asarray(wall)
    rng = np.random.default_rng(seed)
    indices = rng.integers(len(groups), size=(samples, len(groups)))
    sampled = moment[indices].mean(1)
    delta = -.5 * np.log(sampled[:, 0]) + .5 * np.log(sampled[:, 1])
    interval = np.quantile(delta, [.05 / 6, 1 - .05 / 6]).tolist()
    point = -.5 * np.log(moment.mean(0))
    sensitivity = []
    # Utility cost per actual wall-clock second, a declared sensitivity rather
    # than a measured economic conversion or an alternative efficacy target.
    for rate in (0., .0001, .001, .01, .1, 1.):
        values = []
        for policy in ('dynamic', 'fixed_late'):
            selected = [r for pair in paired.values() for p, r in pair.items() if p == policy]
            loss = np.asarray([-2 * (r['utility'] - r['registered_cost'] - rate * r['whole_execution_wall_ns'] / 1e9) for r in selected])
            offset = loss.max()
            values.append(float(-.5 * (offset + np.log(np.exp(loss - offset).mean()))))
        sensitivity.append({'utility_cost_per_actual_second': rate, 'dynamic_CE': values[0],
                            'fixed_late_CE': values[1], 'difference': values[0] - values[1]})
    return {'schema': 'hepta.advance.native-primary-analysis.v1', 'primary_contrast': 'dynamic minus fixed_late',
        'writer_speaker_clusters': len(groups), 'paired_image_video_cases': len(paired), 'source_level_bootstrap_seed': seed,
        'bootstrap_replicates': samples, 'interval_confidence': 1 - .05 / 3,
        'dynamic_CE': float(point[0]), 'fixed_late_CE': float(point[1]), 'CE_difference': float(point[0] - point[1]),
        'paired_cluster_CE_interval': interval, 'registered_efficacy_pass': interval[0] > 0,
        'strict_success_difference': float((strict[:, 0] - strict[:, 1]).mean()),
        'mean_actual_wall_ns_difference': float((wall[:, 0] - wall[:, 1]).mean()),
        'actual_runtime_economic_sensitivity': sensitivity, 'actual_gate_or_execution_failures_not_excluded': True,
        'additional_policy_or_route_contrasts_are_secondary': True}
