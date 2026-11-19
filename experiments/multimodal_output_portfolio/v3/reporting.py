"""Registered contrasts and explicit non-closure of broader research claims."""

import numpy as np

from metrics import paired_bootstrap


def feedback_report(retained, summary, preferences, source_summary, costs, protocol, smoke):
    settings = protocol['feedback']
    def contrast(scenario, candidate, baseline, metric='loss', statistic='mean'):
        left = np.stack([x[metric] for x in retained[(scenario, candidate)]])
        right = np.stack([x[metric] for x in retained[(scenario, baseline)]])
        return paired_bootstrap(left, right, statistic=statistic, seed=2189,
            replicates=100 if smoke else protocol['statistics']['bootstrap_replicates'], shared_worlds=False)
    primary = contrast('nominal_noise', 'ndu_feedback', 'ndu_static')
    candidate = retained[('nominal_noise', 'ndu_feedback')]
    baseline = retained[('nominal_noise', 'ndu_static')]
    ratio = np.mean([x['linear_macs'].mean() for x in candidate]) / np.mean([x['linear_macs'].mean() for x in baseline])
    bounds = settings['primary_gates']
    gates = {'mean_external_loss': primary['estimate'] <= bounds['mean_external_loss_delta_max'],
             'paired_ci_upper': primary['ci_high'] < bounds['paired_ci95_upper_below'],
             'online_linear_mac_ratio': ratio <= bounds['online_linear_mac_ratio_max'],
             'output_budget_contracts': all(row['all_four_outputs'] and row['budget_violations'] == 0 for row in summary),
             'registered_seeds': not smoke and primary['n_seeds'] == len(protocol['seeds'])}
    primary.update({'contrast': settings['primary_contrast'], 'linear_mac_ratio': float(ratio),
                    'gates': gates, 'pass': all(gates.values())})
    secondary = {}
    for scenario in settings['scenarios']:
        for candidate, baseline in (
                ('ndu_feedback', 'ndu_myopic'), ('ndu_feedback', 'matched_supervised_feedback'),
                ('ndu_robust', 'ndu_feedback'), ('ndu_feedback', 'ndu_no_refine'),
                ('ndu_feedback', 'clean_no_disturbance_reference')):
            secondary[scenario + ':' + candidate + '-' + baseline] = {
                'mean_loss': contrast(scenario, candidate, baseline),
                'cvar90': contrast(scenario, candidate, baseline, statistic='cvar90'),
                'mean_quality': contrast(scenario, candidate, baseline, metric='quality'),
                'descriptive_unadjusted': True}
    gradient = []
    for cost in costs:
        history = cost['training']['ndu']['history']
        positive = sum(np.isfinite(row['refinement_objective_gradient_l2'])
                       and row['refinement_objective_gradient_l2'] > 0 for row in history)
        gradient.append({'seed': cost['seed'], 'recorded_steps': len(history),
                         'nonzero_utility_only_steps': int(positive), 'pass': positive >= len(history) / 2})
    profile_errors = [profile['absolute_error'] for row in preferences for profile in row['profiles']]
    source_gates = [{'seed': row['seed'], 'scenario': row['scenario'], 'quality': row['mean_quality'],
                     'pass': row['mean_quality'] >= protocol['robust_sources']['gates']['robust_verified_quality_min_per_stress_scenario']}
                    for row in source_summary if row['arm'] == 'robust_verified' and row['scenario'] != 'iid']
    refined = sum(np.count_nonzero(row['depth']) for row in retained[('nominal_noise', 'ndu_feedback')])
    worlds = sum(len(row['depth']) for row in retained[('nominal_noise', 'ndu_feedback')])
    fraction = refined / worlds
    adaptive_groups = sum(row['condition_depth_groups_with_both_actions'] for row in summary
                          if row['arm'] == 'ndu_feedback' and row['scenario'] == 'nominal_noise')
    return {'schema': 'hepta.feedback-generation.result.v3', 'smoke': smoke,
            'primary': primary, 'secondary': secondary,
            'mechanisms': {'refinement_gradient': gradient, 'nominal_refined_fraction': fraction,
                           'condition_depth_groups_with_both_actions': adaptive_groups,
                           'observed_latent_feedback_gate': adaptive_groups > 0,
                           'nondegeneracy_fraction_gate': .05 <= fraction <= .95},
            'preference': {'max_absolute_error': max(profile_errors),
                           'registered_error_gate': max(profile_errors) <= protocol['preference']['acceptance_absolute_gamma_error'],
                           'real_user_identification': False},
            'new_witness_stress_gates': source_gates,
            'independent_new_witness_is_required': True,
            'broad_claims_not_established': ['natural-data all-modal foundation-model training',
                'general coupled nonlinear FBSDE solver', 'global neural parameter optimum',
                'production NeuronRuntime integration', 'dedicated runner attestation'],
            'source_uncertainty_limit': '1/7 top1 bound only under registered symmetric all-shared-wrong model',
            'external_disturbance_scope': 'mandatory artificial corruption benchmark; clean direct generation can bypass it'}
