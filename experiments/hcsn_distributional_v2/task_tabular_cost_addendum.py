"""Post-panel cost addendum for the already registered tabular reference.

No controller, checkpoint, threshold, data or ordinary-reference selection is
changed.  The original learned-head cost analysis remains intact.  This script
was written after the five-policy quality panel was observed; its status is
explicitly supplementary, not a new pre-heldout superiority registration.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    names = ['PROTOCOL.json', 'REGISTRATION.json', 'SELECTION_LOCK.json',
             'TRAINING_SUMMARY.json', 'EVALUATION_SUMMARY.json', 'COST_SCENARIOS.json',
             'CAMPAIGN_EXECUTION.json', 'AUDIT.json']
    identities = {name: sha(source / name) for name in names}
    write(output / 'REGISTRATION.json', {
        'schema': 'hcsn-tabular-reference-cost-addendum.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'Supplementary calculation after the registered five-policy panel was observed',
        'source_directory': str(source), 'source_files_sha256': identities,
        'analysis_source_sha256': sha(__file__),
        'candidate': 'tabular_bellman', 'reference': 'The ordinary family selected on VAL before original new-test access',
        'changes_to_policy_data_selection_or_original_analysis': False,
        'rates_lifetimes_and_allocations': 'Reuse the exact original cost grid/definitions; change only the reported candidate family'})
    cost, evaluation, training, protocol = (read(source / name) for name in (
        'COST_SCENARIOS.json', 'EVALUATION_SUMMARY.json', 'TRAINING_SUMMARY.json', 'PROTOCOL.json'))
    candidate, reference = 'tabular_bellman', training['best_ordinary_family']
    utility = {family: sum(evaluation['actual_native'][str(price)][family]['mean_utility']
                           for price in protocol['prices']) / len(protocol['prices'])
               for family in (candidate, reference)}
    scenarios = []
    for original in cost['scenarios']:
        allocation = original['allocation']
        lifetime, rate = original['future_stream_lifetime'], original['utility_units_per_cpu_second']
        if allocation == 'measured_method_components':
            candidate_setup = cost['scenario_one_time_setup_by_family'][candidate]
            reference_setup = cost['scenario_one_time_setup_by_family'][reference]
        else:
            candidate_setup = (cost['historical_backbone_search_cpu_seconds']
                               + cost['total_new_campaign_and_prior_attempt_cpu_seconds'])
            reference_setup = cost['historical_backbone_search_cpu_seconds']
        candidate_charge = cost['native_runtime_cpu_per_stream'][candidate] + candidate_setup / lifetime
        reference_charge = cost['native_runtime_cpu_per_stream'][reference] + reference_setup / lifetime
        candidate_net = utility[candidate] - rate * candidate_charge
        reference_net = utility[reference] - rate * reference_charge
        scenarios.append({'allocation': allocation, 'future_stream_lifetime': lifetime,
            'utility_units_per_cpu_second': rate, 'tabular_net_utility': candidate_net,
            'ordinary_net_utility': reference_net, 'difference': candidate_net - reference_net,
            'tabular_higher_point_estimate': candidate_net > reference_net})
    quality = evaluation['counterfactual_macro_paired_comparisons'][candidate]
    summary = {'status': 'completed', 'candidate': candidate, 'reference': reference,
               'same_registered_rate_lifetime_grid': True, 'scenarios': scenarios,
               'positive_point_estimates': sum(row['tabular_higher_point_estimate'] for row in scenarios),
               'actual_native_mean_utility': utility,
               'actual_native_runtime_cpu_per_stream': {family: cost['native_runtime_cpu_per_stream'][family]
                                                        for family in (candidate, reference)},
               'counterfactual_quality_from_original_registered_panel': quality,
               'measured_setup_by_family': {family: cost['scenario_one_time_setup_by_family'][family]
                                            for family in (candidate, reference)},
               'source_files_sha256': identities,
               'analysis_parent_self_cpu_seconds_through_summary': time.process_time(),
               'scope': 'No new inference/training/native process. Task planning reference result, not a financial operator, learned-head, v2 neural-content or foundation-model superiority claim.'}
    if any(sha(source / name) != digest for name, digest in identities.items()):
        raise AssertionError('Original panel changed during supplementary analysis')
    write(output / 'SUMMARY.json', summary)
    interval = quality['nominal_descriptive_bootstrap_interval']
    minimum, maximum = min(row['difference'] for row in scenarios), max(row['difference'] for row in scenarios)
    lines = ['# Supplementary cost audit of the registered tabular task planner', '',
        '**This addendum was produced after the original five-policy panel was observed.** It extends the original cost calculation to the already registered tabular Bellman reference. The original learned-head cost report, its negative result, every policy, selected threshold, checkpoint and heldout sample remain unchanged.', '',
        f'The ordinary reference, selected on validation before the original fresh-test access, is **{reference}**.', '',
        '| Scope | Tabular task planner | Ordinary reference |', '| --- | ---: | ---: |',
        f'| Actual native mean utility, 16 three-task streams, macro over three prices | {utility[candidate]:.8f} | {utility[reference]:.8f} |',
        f'| Measured actual execution CPU per stream | {cost["native_runtime_cpu_per_stream"][candidate]:.6f} s | {cost["native_runtime_cpu_per_stream"][reference]:.6f} s |',
        f'| Component-allocated one-time research/setup CPU | {cost["scenario_one_time_setup_by_family"][candidate]:.6f} s | {cost["scenario_one_time_setup_by_family"][reference]:.6f} s |', '',
        f'The previously registered 128-stream counterfactual quality panel gives paired tabular-minus-ordinary reward **{quality["mean_paired_difference"]:.8f}**, with nominal descriptive stream-bootstrap interval **[{interval[0]:.8f}, {interval[1]:.8f}]**. This interval belongs to the full counterfactual quality panel, not to the smaller actual-native cost panel.', '',
        f'The tabular point estimate remains higher in **{summary["positive_point_estimates"]}/{len(scenarios)}** original-grid cost scenarios. The complete cost-adjusted native difference ranges from **{minimum:.8f}** to **{maximum:.8f}**. The two allocations respectively charge measured method components, or charge the whole new campaign (including the failed first attempt) to the tabular alternative while granting the ordinary reference free new setup. Complete historical backbone training, teacher fitting/solving, actual runtime and complete recovery verification are included in their stated scopes.', '',
        'These are sensitivity calculations, not measured dollars/energy or a fresh statistical confirmation. The native panel has 16 streams, the classifier is a single frozen v1 backbone, and confidence bins form an approximate Markov state. The direct planner stores fitted transition/reward tables and uses dynamic programming; its capacity and setup differ from the 66-parameter heads. A successful reference planner does not establish an advantage of financial J/G neural operators, v2 distributional content, or the compressed value head.', '',
        'The original learned value head remains below the ordinary reference and wins 0/24 original cost scenarios. Keeping that negative result alongside the positive planning reference identifies a concrete remaining problem: compressing/learning the useful finite-task policy without losing its reward behavior.', '']
    with (output / 'REPORT.md').open('x') as handle:
        handle.write('\n'.join(lines))
    write(output / 'EXECUTION.json', {'whole_analysis_self_cpu_seconds': time.process_time(),
        'source_sha256': sha(__file__), 'report_sha256': sha(output / 'REPORT.md'),
        'summary_sha256': sha(output / 'SUMMARY.json'), 'new_training_or_inference': False})
    print(json.dumps({'status': 'completed', 'positive_cost_point_estimates': summary['positive_point_estimates'],
                      'scenarios': len(scenarios), 'native_reward_difference': utility[candidate] - utility[reference],
                      'net_difference_range': [minimum, maximum]}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)
