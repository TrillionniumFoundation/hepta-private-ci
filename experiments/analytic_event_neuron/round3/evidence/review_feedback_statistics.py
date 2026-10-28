"""Independent final feedback statistics from fully reviewed whole-trajectory arrays."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
import traceback

import numpy as np

from . import review_feedback_evidence as e
from .review_feedback_confirmation import CONTRASTS


def bootstrap(delta, seed, alpha):
    rng = np.random.default_rng(seed)
    draws = np.empty(4000)
    # Match the registered random stream layout, then independently reduce
    # each sampled seed's paired trajectory outcomes. No horizon resampling.
    for start in range(0, 4000, 200):
        selected_seeds = rng.integers(0, delta.shape[0], size=(200, delta.shape[0], 1))
        selected_cases = rng.integers(0, delta.shape[1], size=(200, delta.shape[0], delta.shape[1]))
        for rep in range(200):
            means = [float(delta[int(selected_seeds[rep, j, 0]), selected_cases[rep, j]].mean()) for j in range(delta.shape[0])]
            draws[start + rep] = sum(means) / len(means)
    return np.quantile(draws, [alpha / 2, 1 - alpha / 2]), delta.mean(axis=1)


def calibration(probability, labels, covered):
    n = len(labels)
    selected = probability[np.arange(n), labels]
    zeros = int(np.count_nonzero(selected == 0))
    confidence, correct = probability.max(axis=1), probability.argmax(axis=1) == labels
    def ece(values, observed):
        bins = np.minimum(np.floor(values * 10).astype(int), 9)
        sums = np.bincount(bins, weights=values, minlength=10)
        hits = np.bincount(bins, weights=observed.astype(float), minlength=10)
        return float(np.sum(np.abs(sums - hits)) / n)
    return {'initial_terminal_top_label_ece': ece(confidence, correct),
        'initial_terminal_classwise_ece': float(np.mean([ece(probability[:, j], labels == j) for j in range(3)])),
        'initial_95_gaussian_coverage': float(np.mean(covered)),
        'initial_terminal_brier': float(np.sum((probability - np.eye(3)[labels]) ** 2) / n),
        'initial_terminal_nll': None if zeros else float(-np.sum(np.log(selected)) / n),
        'true_event_zero_probability_count': zeros}


def aggregate(root, review):
    root = Path(root)
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    frozen = e.verify_freeze(root, review)
    protocol = e.read_json(e.PROJECT / 'PROTOCOL.json')['feedback']
    seeds = protocol['seeds']
    settings = protocol['statistics']
    review.require(tuple(map(tuple, protocol['primary_contrasts'] + protocol['secondary_contrasts'])) == CONTRASTS
        and settings['bootstrap_replicates'] == 4000 and settings['bootstrap_seed'] == 28102840
        and settings['family_alpha'] == .05 and settings['primary_family_size'] == 3
        and settings['superiority_margin'] == .01 and settings['event_noninferiority_margin'] == .01,
        'registration', 'exact prospectively frozen contrasts, resampling and margins')
    index = e.read_json(root / 'FEEDBACK_INDEX.json')
    review.require(index['complete'] and [x['seed'] for x in index['scopes']] == seeds
        and index['source_commit'] == frozen['source_commit'], 'coverage', 'complete immutable confirmation')
    summary = e.read_json(root / 'FEEDBACK_RESULTS.json')
    review.require(summary['complete'] and summary['source_commit'] == frozen['source_commit']
        and summary['training_seeds'] == seeds and summary['frozen_source_and_model_binding'], 'identity', 'summary binding')
    reports, scopes = [], []
    for entry in index['scopes']:
        seed = entry['seed']
        path = root / 'reviews' / f'FEEDBACK_INDEPENDENT_{seed}.json'
        report = e.read_json(path)
        review.require(report['passed'] and report['seed'] == seed and report['indexed_files_sha256'] == entry['files_sha256']
            and report['freeze_sha256'] == e.file_hash(root / 'FREEZE.json'), 'identity', 'complete independent scope review')
        for name, sha in entry['files_sha256'].items():
            review.require(e.file_hash(root / name) == sha, 'identity', 'immutable scientific input')
        derived = root / report['derived_arrays']
        review.require(e.file_hash(derived) == report['derived_arrays_sha256'], 'identity', 'derived arrays receipt')
        scope = e.arrays(derived)
        review.require(scope['arms'].tolist() == list(e.ARMS) and len(scope['ids']) == protocol['confirmation_rows']
            and len(set(scope['ids'])) == len(scope['ids']), 'coverage', 'whole trajectory axes')
        reports.append({'path': str(path.relative_to(root)), 'sha256': e.file_hash(path), 'checks': report['total_checks']})
        scopes.append(scope)
        receipt = next(x for x in summary['execution_receipts'] if x['seed'] == seed)
        for key, expected in report['actual_cost'].items():
            if key in receipt:
                review.require(receipt[key] == expected, 'accounting', 'published actual cost ' + key)
        review.require(receipt['episodes'] == report['control_executions']
            and receipt['typed_ticks_replayed'] == report['native_replay_performed_by_frozen_author_audit']['typed_ticks']
            and receipt['sparse_ticks_replayed'] == report['native_replay_performed_by_frozen_author_audit']['sparse_ticks'], 'accounting', 'published replay coverage')
    review.require(len(set(np.concatenate([x['ids'] for x in scopes]))) == len(seeds) * protocol['confirmation_rows'], 'coverage', 'independent trajectory IDs across seeds')
    arrays = {key: np.stack([x[key] for x in scopes]) for key in scopes[0] if key not in ('ids', 'arms')}
    metrics, zero_mass = {}, {}
    for j, arm in enumerate(e.ARMS):
        probability = arrays['probabilities'][:, j].reshape(-1, 3)
        labels = arrays['labels'][:, j].reshape(-1)
        expected = calibration(probability, labels, arrays['coverage'][:, j].reshape(-1))
        expected.update({key: float(np.mean(arrays[key][:, j])) for key in ('utility', 'squared_error', 'cost', 'wall_ns')})
        actions = arrays['actions'][:, j].reshape(-1)
        expected.update(episodes=len(labels), waits=int(np.count_nonzero(np.char.find(actions, 'wait') >= 0)),
            repairs=int(np.count_nonzero(np.char.find(actions, 'repair') >= 0)),
            logical_unit_events=int(np.sum(arrays['logical_unit_events'][:, j])), packet_bytes=int(np.sum(arrays['packet_bytes'][:, j])))
        actual = summary['arms'][arm]
        for key, value in expected.items():
            if value is None:
                review.require(actual[key] is None, 'calibration', 'infinite realized NLL encoded null')
            else:
                review.close(actual[key], value, 'calibration' if key.startswith('initial_') else 'summary', arm + '/' + key)
        review.require(actual['nll_definition'] == 'Actual delivered head probabilities, no clipping; mean null if any zero-mass realized event',
                       'calibration', 'no clipping promise')
        metrics[arm] = expected
        zero_mass[arm] = {'initial_forecasts_with_any_zero_probability': int(np.any(probability == 0, axis=1).sum()),
            'zero_probabilities_by_category': np.count_nonzero(probability == 0, axis=0).tolist(),
            'true_event_zero_probability_count': expected['true_event_zero_probability_count']}
    contrasts, mechanisms = {}, {}
    for k, (candidate, baseline) in enumerate(CONTRASTS):
        a, b = e.ARMS.index(candidate), e.ARMS.index(baseline)
        name = candidate + '_vs_' + baseline
        delta = arrays['utility'][:, a] - arrays['utility'][:, b]
        alpha = .05 / 3 if k < 3 else .05
        interval, per_seed = bootstrap(delta, 28102840 + k, alpha)
        actual = summary['contrasts'][name]
        expected = {'mean_difference': float(delta.mean()), 'interval': interval.tolist(),
                    'per_seed_mean_difference': per_seed.tolist()}
        for key, value in expected.items():
            review.close(actual[key], value, 'bootstrap', name + '/' + key, 2e-14)
        gates = {'empirical_superiority_001': bool(interval[0] > .01 and np.all(per_seed > 0)),
                 'empirical_noninferiority_001': bool(interval[0] > -.01 and np.all(per_seed > -.01))}
        review.require(all(actual[key] == value for key, value in gates.items()) and actual['family_adjusted'] == (k < 3)
            and actual['interval_alpha'] == alpha and actual['replicates'] == 4000 and actual['training_seed_count'] == len(seeds)
            and actual['trajectories_per_seed'] == protocol['confirmation_rows'] and not actual['population_or_production_guarantee']
            and actual['candidate'] == candidate and actual['baseline'] == baseline, 'gates', name + ' exact preregistered rules')
        contrasts[name] = {**expected, **gates, 'family_adjusted': k < 3, 'interval_alpha': alpha}
        expected_mechanism = {'action_disagreements': int(np.count_nonzero(arrays['actions'][:, a] != arrays['actions'][:, b])),
            'final_output_disagreements': int(np.count_nonzero(arrays['delivered'][:, a] != arrays['delivered'][:, b])),
            'maximum_initial_probability_difference': float(np.max(abs(arrays['probabilities'][:, a] - arrays['probabilities'][:, b]))),
            'mean_squared_error_reduction': float(np.mean(arrays['squared_error'][:, b] - arrays['squared_error'][:, a])),
            'mean_paid_cost_increase': float(np.mean(arrays['cost'][:, a] - arrays['cost'][:, b]))}
        for key, value in expected_mechanism.items():
            review.close(summary['mechanism'][name][key], value, 'mechanism', name + '/' + key)
        mechanisms[name] = expected_mechanism
    unique = len(seeds) * protocol['confirmation_rows']
    review.require(summary['independent_confirmation_trajectories'] == summary['unique_trajectories'] == unique
        and summary['initial_terminal_event_labels'] == summary['control_executions'] == unique * len(e.ARMS), 'coverage', 'published denominator')
    review.require(summary['actual_runtime_profile_scored'] and summary['all_terms_public_and_target_only_postdelivery']
        and not summary['production_promotion'] and summary['action_cost_is_not_cpu_time_or_dollars'], 'scope', 'qualified claims only')
    e.verify_freeze(root, review)
    return {'schema': 'hepta.round3.independent-feedback-statistics-review.v1', 'passed': True,
        'source_commit': frozen['source_commit'], 'freeze_sha256': e.file_hash(root / 'FREEZE.json'),
        'feedback_results_sha256': e.file_hash(root / 'FEEDBACK_RESULTS.json'), 'feedback_index_sha256': e.file_hash(root / 'FEEDBACK_INDEX.json'),
        'reviewer_sha256': {p.name: e.file_hash(p) for p in (Path(__file__), Path(e.__file__), Path(__file__).with_name('review_feedback_confirmation.py'))},
        'scope_reviews': reports, 'checks': dict(review.counts), 'total_checks': sum(review.counts.values()),
        'maximum_absolute_errors': review.maximum, 'independent_trajectories': unique, 'control_executions': unique * len(e.ARMS),
        'metrics': metrics, 'contrasts': contrasts, 'mechanism': mechanisms, 'initial_terminal_zero_mass': zero_mass,
        'all_contrasts_independently_recomputed': len(contrasts), 'bootstrap_replicates_per_contrast': 4000,
        'sampling_unit': 'training seed, then paired whole trajectory; no dependent-stage resampling',
        'limitations': ['Five training seeds support empirical bootstrap inference only.',
                       'Realized finite NLL does not rule out zero-mass tails on unseen data; no pointwise density-retention certificate.',
                       'Native internal dynamics independently replayed in the prior frozen audit, not executed again by this reviewer.'],
        'wall_ns': time.perf_counter_ns() - began, 'cpu_ns': time.process_time_ns() - cpu}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run-dir', required=True)
    args = parser.parse_args(); root = Path(args.run_dir); review = e.Review()
    try:
        report = aggregate(root, review)
    except Exception:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        e.write_new(root / 'reviews' / f'FEEDBACK_STATISTICS_REVIEW_FAILURE_{stamp}.json',
            {'passed': False, 'traceback': traceback.format_exc(), 'checks': dict(review.counts),
             'reviewer_sha256': e.file_hash(__file__), 'scientific_files_modified': False})
        raise
    output = root / 'reviews' / 'FEEDBACK_STATISTICS_INDEPENDENT.json'
    e.write_new(output, report)
    print({'passed': True, 'path': str(output), 'sha256': e.file_hash(output), 'checks': report['total_checks']}, flush=True)


if __name__ == '__main__':
    main()
