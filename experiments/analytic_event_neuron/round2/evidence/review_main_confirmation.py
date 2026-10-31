"""Postconfirmation-only audit of saved archives and frozen aggregate statistics.

May run while the parent confirmation process is active. Only indexed completed
archives are read; verified scopes are cached under /tmp. The final report is
written only after all 15 registered scopes and RESULTS.json exist. No model,
evaluation, simulation, optimizer, or native process is invoked here.
"""

from collections import Counter
import json
from pathlib import Path
import time

import numpy as np

from main_archive_review import Checks, file_sha, review_scope


PROJECT = Path(__file__).resolve().parents[4]
RUN = Path('/tmp/aen-round2-20261027')
CACHE = Path('/tmp/aen-main-confirmation-independent-review-cache.json')
OUTPUT = Path(__file__).with_name('MAIN_CONFIRMATION_REVIEW.json')


def load(path):
    return json.loads(path.read_text())


def calibration_reference(probability, labels):
    p, y = probability.reshape(-1, 3), labels.reshape(-1)
    bins, errors = [], []
    for category in range(3):
        error = 0.0
        for index in range(10):
            selected = (p[:, category] >= index / 10) & ((p[:, category] < (index + 1) / 10)
                                                       if index < 9 else (p[:, category] <= 1))
            count = int(selected.sum())
            predicted = float(p[selected, category].mean()) if count else None
            actual = float(np.mean(y[selected] == category)) if count else None
            if count:
                error += abs(float(np.sum(p[selected, category] - (y[selected] == category)))) / len(y)
            bins.append({'event': category, 'bin': index, 'count': count,
                         'mean_probability': predicted, 'frequency': actual})
        errors.append(error)
    return {'classwise_ece': float(np.mean(errors)), 'event_ece': errors, 'bins': bins,
            'independent_sample_count': len(labels), 'horizon_measurements_per_trajectory': labels.shape[1]}


def bootstrap_reference(difference, replicates, seed, alpha):
    difference = np.asarray(difference)
    nseed, nrow = difference.shape
    random = np.random.default_rng(seed)
    bootstrap = np.empty(replicates)
    for start in range(0, replicates, 200):
        count = min(200, replicates - start)
        seed_draw = random.integers(nseed, size=(count, nseed, 1))
        row_draw = random.integers(nrow, size=(count, nseed, nrow))
        bootstrap[start:start + count] = np.sum(difference[seed_draw, row_draw], axis=(1, 2)) / (nseed * nrow)
    return {'mean_difference': float(np.mean(difference)),
            'interval': np.quantile(bootstrap, [alpha / 2, 1 - alpha / 2]).tolist(),
            'per_seed_mean_difference': np.mean(difference, axis=1).tolist(),
            'training_seed_count': nseed, 'trajectories_per_seed': nrow,
            'replicates': replicates, 'interval_alpha': alpha}


def compare_tree(check, actual, expected, path):
    if isinstance(expected, dict):
        check.require(set(expected).issubset(actual), 'aggregate_structure', path)
        for key, value in expected.items():
            compare_tree(check, actual[key], value, path + '/' + key)
    elif isinstance(expected, list) and expected and isinstance(expected[0], dict):
        check.require(len(actual) == len(expected), 'aggregate_structure', path)
        for i, value in enumerate(expected):
            compare_tree(check, actual[i], value, path + '/' + str(i))
    elif expected is None or isinstance(expected, (str, bool)):
        check.require(actual == expected, 'aggregate_exact', path)
    else:
        check.close(actual, expected, 'aggregate_numeric', path, atol=3e-12, rtol=3e-12)


def main():
    started = time.perf_counter_ns()
    check = Checks()
    protocol_path = PROJECT / 'experiments/analytic_event_neuron/round2/PROTOCOL.json'
    protocol, freeze = load(protocol_path), load(RUN / 'FREEZE.json')
    index = load(RUN / 'RUN_INDEX.json')
    program = {Path(__file__).name: file_sha(Path(__file__)),
               'main_archive_review.py': file_sha(Path(__file__).with_name('main_archive_review.py'))}
    frozen_paths = {str(PROJECT / name): digest for name, digest in freeze['sources_sha256'].items()}
    frozen_paths.update({str(RUN / name): digest for name, digest in freeze['artifacts_sha256'].items()})
    for name, digest in frozen_paths.items():
        check.require(file_sha(Path(name)) == digest, 'freeze_integrity_before', name)
    check.require(len(freeze['sources_sha256']) == 56 and len(freeze['artifacts_sha256']) == 194,
                  'freeze_coverage', '56 sources and 194 fitting artifacts')
    check.require(freeze['protocol_sha256'] == file_sha(protocol_path)
                  and index['freeze_sha256'] == file_sha(RUN / 'FREEZE.json')
                  and index['source_commit'] == freeze['source_commit'], 'freeze_binding', 'protocol and source')
    registered = protocol['statistics']
    check.require(registered['minimum_useful_net_utility_gain'] == .01
                  and registered['mismatch_noninferiority_margin'] == .02
                  and registered['event_accuracy_noninferiority_margin'] == .01
                  and registered['primary_family_size'] == 3,
                  'original_gates', 'superiority .01, descriptive mismatch .02, event NI diagnostic .01')
    seeds = protocol['training_seeds']
    laws = [protocol['laws']['primary'], *protocol['laws']['mismatch']]
    expected_scopes = {(seed, law) for seed in seeds for law in laws}
    actual_scopes = [(row['training_seed'], row['law']) for row in index['scopes']]
    check.require(len(actual_scopes) == len(set(actual_scopes)) and set(actual_scopes).issubset(expected_scopes),
                  'scope_coverage', 'unique prospectively registered scopes')
    cache = load(CACHE) if CACHE.exists() else {}
    if cache.get('program_sha256') != program or cache.get('freeze_sha256') != index['freeze_sha256']:
        cache = {'program_sha256': program, 'freeze_sha256': index['freeze_sha256'], 'scopes': {}}
    for entry in index['scopes']:
        prior = cache['scopes'].get(entry['scope'])
        if prior is not None:
            check.require(prior['archive_sha256'] == entry['archive']['sha256']
                          == file_sha(RUN / entry['archive_path'])
                          and prior['analysis_sha256'] == entry['analysis_sha256']
                          == file_sha(RUN / entry['analysis_path']), 'cached_evidence_unchanged', entry['scope'])
        else:
            cache['scopes'][entry['scope']] = review_scope(RUN, entry, protocol, freeze)
            CACHE.write_text(json.dumps(cache, indent=2, sort_keys=True, allow_nan=False) + '\n')
            print(json.dumps({'phase': 'scope_review', 'scope': entry['scope'],
                              'passed': cache['scopes'][entry['scope']]['passed'],
                              'checks': cache['scopes'][entry['scope']]['total_checks'],
                              'failures': cache['scopes'][entry['scope']]['failures'][:5]}), flush=True)
    scopes = [cache['scopes'][entry['scope']] for entry in index['scopes']]
    for scope in scopes:
        check.require(scope['passed'], 'independent_scope_reviews', scope['scope'])
    all_ids = [identity for scope in scopes for identity in scope['unique_trajectory_ids']]
    check.require(len(all_ids) == len(set(all_ids)), 'holdout_disjoint', 'unique complete trajectories across scopes')
    training_ids, training_seeds = set(), set()
    for parent in (RUN / 'training', RUN / 'feedback_training', RUN / 'retention_prepared'):
        for path in parent.glob('seed_*/*.npz'):
            if any(text in path.name for text in ('TRAIN', 'DEVELOPMENT')):
                with np.load(path, allow_pickle=False) as archive:
                    training_ids.update(archive['ids'].tolist())
                    training_seeds.add(int(archive['seed']))
    check.require(not (set(all_ids) & training_ids)
                  and not ({scope['data_seed'] for scope in scopes} & training_seeds),
                  'holdout_disjoint', 'no fitting/development ID or seed reuse')
    complete = index.get('complete') and set(actual_scopes) == expected_scopes and (RUN / 'RESULTS.json').exists()
    if not complete:
        print(json.dumps({'phase': 'waiting_for_complete_confirmation', 'scopes_reviewed': len(scopes),
                          'expected_scopes': len(expected_scopes), 'passed_available_checks': not check.failures,
                          'failures': check.failures, 'cache': str(CACHE)}), flush=True)
        return 0 if not check.failures else 1

    results_path = RUN / 'RESULTS.json'
    results_hash = file_sha(results_path)
    results = load(results_path)
    arrays = {}
    for entry in index['scopes']:
        with np.load(RUN / entry['analysis_path'], allow_pickle=False) as archive:
            arrays[(entry['training_seed'], entry['law'])] = {key: archive[key] for key in archive.files}
    model_names = sorted(key.split('__')[1] for key in arrays[(seeds[0], laws[0])] if key.startswith('nll__'))
    arm_names = sorted(key.split('__')[1] for key in arrays[(seeds[0], laws[0])] if key.startswith('utility__'))
    check.require(len(model_names) == 12 and len(arm_names) == 16, 'arm_coverage', 'all final arms retained')
    recomputed = {'laws': {}, 'primary_contrasts': {}, 'mismatch_contrasts': {}, 'secondary_contrasts': {}}
    for law in laws:
        selected = [arrays[(seed, law)] for seed in seeds]
        statistics = {}
        for arm in arm_names:
            entry = {}
            for metric in ('utility', 'paid_cost', 'squared_error', 'severe_loss', 'elapsed_ns', 'cpu_ns'):
                values = np.concatenate([scope[metric + '__' + arm] for scope in selected])
                percentiles = np.percentile(values, [5, 50, 95])
                entry[metric] = {'mean': float(np.mean(values)), 'q05': float(percentiles[0]),
                                 'median': float(percentiles[1]), 'q95': float(percentiles[2])}
            action_counts = Counter(str(value) for scope in selected for value in scope['actions__' + arm])
            entry['actions'] = dict(action_counts)
            check.require(sum(action_counts.values()) == 1280, 'final_action_counts', (law, arm))
            if arm in model_names:
                for metric in ('nll', 'brier', 'mse'):
                    entry[metric] = float(np.mean(np.concatenate([scope[metric + '__' + arm] for scope in selected])))
                p = np.concatenate([scope['probabilities__' + arm] for scope in selected])
                labels = np.concatenate([scope['labels__' + arm] for scope in selected])
                z = np.concatenate([scope['standardized_error__' + arm] for scope in selected])
                entry['calibration'] = calibration_reference(p, labels)
                entry['gaussian_interval_coverage'] = {
                    label: float(np.mean(np.abs(z) <= bound)) for label, bound in (
                        ('nominal_68.27', 1), ('nominal_90', 1.6448536269514722), ('nominal_95', 1.959963984540054))}
            statistics[arm] = entry
        recomputed['laws'][law] = statistics

    def contrast(candidate, baseline, law, sequence, primary=False):
        differences = []
        for seed in seeds:
            scope = arrays[(seed, law)]
            check.close(scope['control_ids__' + candidate], scope['control_ids__' + baseline],
                        'paired_ids', (seed, law, candidate, baseline), exact=True)
            differences.append(scope['utility__' + candidate] - scope['utility__' + baseline])
        alpha = registered['family_alpha'] / registered['primary_family_size'] if primary else .05
        value = bootstrap_reference(differences, registered['bootstrap_replicates'], registered['bootstrap_seed'] + sequence, alpha)
        value.update(candidate=candidate, baseline=baseline, law=law, primary=primary)
        if primary:
            value['passes_registered_superiority'] = value['interval'][0] > .01 and min(value['per_seed_mean_difference']) > 0
        else:
            value['descriptive_only'] = True
        return value

    for sequence, item in enumerate(protocol['primary_contrasts']):
        recomputed['primary_contrasts'][item['id']] = contrast(item['candidate'], item['baseline'], 'gaussian', sequence, True)
        for offset, law in enumerate(laws[1:], 1):
            value = contrast(item['candidate'], item['baseline'], law, 100 * offset + sequence)
            value.update(empirical_lower_above_negative_margin=value['interval'][0] > -.02,
                         population_noninferiority_established=False)
            recomputed['mismatch_contrasts'][law + ':' + item['id']] = value
    for sequence, pair in enumerate(protocol['secondary_contrasts']):
        candidate, baseline = pair
        recomputed['secondary_contrasts'][candidate + '_vs_' + baseline] = contrast(candidate, baseline, 'gaussian', 1000 + sequence)
    event = recomputed['primary_contrasts']['event_vs_continuous']
    recomputed['event_accuracy_repair'] = {
        'margin': .01, 'uses_same_adjusted_interval': True,
        'passes_empirical_noninferiority': event['interval'][0] > -.01 and min(event['per_seed_mean_difference']) > -.01,
        'original_superiority_gate_unchanged': True,
        'does_not_establish_new_function_class_or_population_guarantee': True}
    for family in ('primary_contrasts', 'mismatch_contrasts', 'secondary_contrasts'):
        check.require(set(results[family]) == set(recomputed[family]), 'complete_registered_contrasts', family)
    compare_tree(check, results, recomputed, 'RESULTS')
    for law in laws:
        for policy, path in FIXED_COUNTS.items():
            check.require(recomputed['laws'][law][policy]['actions'] == {path: 1280},
                          'original_fixed_policies', (law, policy))
    check.require(results['event_accuracy_repair']['original_superiority_gate_unchanged']
                  and all(not value.get('population_noninferiority_established', False)
                          for value in results['mismatch_contrasts'].values()), 'claim_scope', 'diagnostic never replaces original superiority')
    for name, digest in frozen_paths.items():
        check.require(file_sha(Path(name)) == digest, 'freeze_integrity_after', name)
    for entry in index['scopes']:
        check.require(file_sha(RUN / entry['archive_path']) == entry['archive']['sha256']
                      and file_sha(RUN / entry['analysis_path']) == entry['analysis_sha256'],
                      'confirmation_integrity_after', entry['scope'])
    check.require(file_sha(results_path) == results_hash, 'confirmation_integrity_after', 'RESULTS.json')
    combined_counts = Counter(check.counts)
    for scope in scopes:
        combined_counts.update(scope['checks'])
    mechanism = {
        'direct_prediction_maximum_gap': max(s['event_mechanism_checks']['direct_prediction_maximum_gap'] for s in scopes),
        'direct_control_maximum_gap': max(s['event_mechanism_checks']['direct_control_maximum_gap'] for s in scopes),
        'no_residual_prediction_maximum_gap': max(s['event_mechanism_checks']['no_residual_prediction_maximum_gap'] for s in scopes),
        'no_residual_changed_action_paths': sum(s['event_mechanism_checks']['no_residual_changed_action_paths'] for s in scopes),
        'no_residual_changed_final_predictions': sum(s['event_mechanism_checks']['no_residual_changed_final_predictions'] for s in scopes),
        'gaussian_equivalent_prediction_maximum_gap': max(s['event_mechanism_checks']['gaussian_equivalent_prediction_maximum_gap'] for s in scopes),
        'interpretation': 'Error-feedback counts exactly re-encode the same quantized state on these trajectories; direct-quantization parity is an equivalence control, not evidence of a new function class.'}
    report = {
        'schema': 'hepta.analytic-event.main-confirmation-independent-review.v1',
        'passed': not check.failures and all(scope['passed'] for scope in scopes),
        'checks': dict(combined_counts), 'total_checks': sum(combined_counts.values()),
        'aggregate_failures': check.failures, 'aggregate_maximum_absolute_errors': check.maximum_errors,
        'verification_only': True, 'training_or_evaluation_calls': 0, 'generated_trajectories': 0,
        'native_process_calls': 0, 'frozen_source_model_protocol_edits': 0,
        'source_commit': freeze['source_commit'], 'protocol_sha256': file_sha(protocol_path),
        'freeze_sha256': index['freeze_sha256'], 'run_index_sha256': file_sha(RUN / 'RUN_INDEX.json'),
        'results_sha256': results_hash, 'review_program_sha256': program,
        'sources_verified': len(freeze['sources_sha256']), 'fitting_artifacts_verified': len(freeze['artifacts_sha256']),
        'scope_count': len(scopes), 'unique_confirmation_trajectories': len(all_ids),
        'prediction_rows': sum(s['prediction_rows'] for s in scopes),
        'control_rows': sum(s['control_rows'] for s in scopes),
        'all_png_delivery_replays': sum(s['reviewed_all_png_deliveries'] for s in scopes),
        'all_observation_readbacks': sum(s['reviewed_all_observations'] for s in scopes),
        'archive_member_hashes_verified': sum(s['archive_members'] for s in scopes),
        'original_model_replay_scope': 'Every scope has a hash-bound full frozen-model replay AUDIT receipt; this independent review does not rerun model inference.',
        'independent_review_scope': 'Every archived member hash, PNG bit delivery, observation payload, prediction score, control decision/cost/utility and analysis row is checked; no review subsampling.',
        'scopes': scopes, 'recomputed': recomputed, 'event_mechanism_checks': mechanism,
        'original_gates': {'minimum_useful_superiority': .01, 'mismatch_margin': .02,
                           'separate_event_accuracy_noninferiority_diagnostic_margin': .01},
        'costs': {
            'evaluation_wall_ns': sum(s['execution']['evaluation_wall_ns'] for s in scopes),
            'evaluation_parent_cpu_ns': sum(s['execution']['evaluation_parent_cpu_ns'] for s in scopes),
            'scope_wall_ns_including_audit_and_archive': sum(s['scope_wall_ns_including_audit_and_archive'] for s in scopes),
            'native_requests_recorded_by_execution': sum(s['execution']['native_requests'] for s in scopes),
            'original_sparse_ticks_recorded_by_execution': sum(s['execution']['original_sparse_ticks'] for s in scopes),
            'native_counter_scope': 'Instrumented EXECUTION receipts are verified; a native request ledger is not regenerated by this reviewer.',
            'shared_host_timing_not_hardware_speedup': True},
        'limitations': ['Three horizons belong to the same trajectory; resampling preserves whole paired trajectories and training seeds.',
                        'Five training seeds limit inference; Student-t4 squared-loss bootstrap is descriptive and not a population noninferiority guarantee.',
                        'Timestamps and frozen code establish retained chronology, not process-memory isolation or an independent trusted clock.',
                        'Native model predictions are covered by the original full replay receipts; this review checks the retained results and does not rerun native inference.',
                        'Numerical parity and event noninferiority do not establish calibration, original pulse superiority, a new function class, or production authority.'],
        'last_invocation_wall_ns': time.perf_counter_ns() - started,
    }
    OUTPUT.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'phase': 'complete_review', 'passed': report['passed'], 'checks': report['total_checks'],
                      'report': str(OUTPUT), 'sha256': file_sha(OUTPUT),
                      'aggregate_failures': check.failures[:10]}, indent=2), flush=True)
    return 0 if report['passed'] else 1


FIXED_COUNTS = {'always_stop': 'stop', 'always_repair': 'repair', 'always_wait': 'wait/stop', 'always_wait_repair': 'wait/repair'}

if __name__ == '__main__':
    raise SystemExit(main())
