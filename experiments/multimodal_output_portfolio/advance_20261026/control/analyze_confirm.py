"""The single registered paired writer-cluster contrast and descriptive diagnostics."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ce(value):
    log_moment = -2 * np.asarray(value, dtype=np.float64)
    largest = float(log_moment.max())
    return float(-(largest + np.log(np.exp(log_moment - largest).mean())) / 2)


def ece(probability, outcome):
    probability, outcome = np.asarray(probability), np.asarray(outcome)
    if not len(probability):
        return {'count': 0, 'ECE': None, 'bins': []}
    indices = np.minimum((probability * 10).astype(int), 9)
    rows, error = [], 0.
    for index in range(10):
        mask = indices == index
        if mask.any():
            gap = float(probability[mask].mean() - outcome[mask].mean())
            error += int(mask.sum()) / len(mask) * abs(gap)
            rows.append({'bin': index, 'count': int(mask.sum()), 'confidence': float(probability[mask].mean()),
                'success': float(outcome[mask].mean()), 'signed_error': gap})
    return {'count': len(probability), 'ECE': error, 'bins': rows}


def moment_stats(rows):
    if not rows:
        return {'count': 0}
    values = np.asarray(rows)
    error = values[:, 0] - values[:, 1]
    return {'count': len(rows), 'mean_prediction': float(values[:, 0].mean()),
        'mean_actual_moment': float(values[:, 1].mean()),
        'mean_prediction_minus_actual_bias': float(error.mean()),
        'mean_actual_minus_prediction_residual': float(-error.mean()),
        'MSE': float(np.square(error).mean())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    began = time.perf_counter_ns()
    registration = json.loads((args.run / 'registration.json').read_text()); spec = registration['spec']
    completion = json.loads((args.run / 'completion.json').read_text())
    for name, expected in completion['files_sha256'].items():
        if sha(args.run / name) != expected:
            raise ValueError('Closed actual evidence changed: ' + name)
    for name, expected in spec['frozen_candidate_sha256'].items():
        if sha(name) != expected:
            raise ValueError('Prospective implementation changed: ' + name)
    allocation = json.loads(Path(spec['source']['allocation']).read_text())['roles']['confirmation']
    writers = np.asarray(allocation['pair_writer_ids']); unique = np.unique(writers)
    policies, views = spec['policies'], spec['views']
    shape = (len(policies), len(writers), len(views), spec['draws'])
    utility, secondary, success, wall, cpu, length = [np.full(shape, np.nan) for _ in range(6)]
    detail_costs = {name: [] for name in policies}
    selected_confidence = {name: [] for name in policies}; selected_success = {name: [] for name in policies}
    initial_confidence = {name: [] for name in policies}; initial_success = {name: [] for name in policies}
    initial_moments = {name: [] for name in policies}; continuation_moments = {name: [] for name in policies}
    initial_selected_then_undelivered = {name: 0 for name in policies}
    seen = set(); failures = {name: 0 for name in policies}; rejections = {name: 0 for name in policies}
    with gzip.open(args.run / 'scored.jsonl.gz', 'rt') as stream:
        for row in map(json.loads, stream):
            identity = (row['case'], row['view'], row['draw'], row['policy'])
            if row['seed'] != spec['seed'] or identity in seen or row['writer'] != int(writers[row['case']]):
                raise ValueError('Seed, duplicate or source-cluster identity mismatch')
            seen.add(identity)
            index = (policies.index(row['policy']), row['case'], views.index(row['view']), row['draw'])
            completed = row['status'] == 'completed'
            utility[index] = row['scores']['primary']['utility'] if completed else -1.
            secondary[index] = row['scores']['secondary']['utility'] if completed else -1.
            success[index] = row['scores']['primary']['joint_fact_correct'] if completed else 0.
            wall[index] = row['wall_ns'] / 1e6; cpu[index] = row['cpu_ns'] / 1e6
            length[index] = row['attempted_continuations']
            failures[row['policy']] += row['status'] == 'failed'
            rejections[row['policy']] += row['status'] == 'rejected'
            for detail in row['decisions']:
                detail_costs[row['policy']].append([detail[name] / 1e6
                    for name in ('feature_cpu_ns', 'admission_cpu_ns', 'head_cpu_ns')])
                action = detail['selected_index']
                if action >= 0 and not detail['admitted'][action]:
                    raise ValueError('An online policy selected outside its registered feasible set')
            if row['decisions'] and row['decisions'][0]['selected_index'] >= 0:
                first = row['decisions'][0]; action = first['selected_index']
                if first['remaining'] != 2:
                    raise ValueError('An initial-selected diagnostic must start at H2')
                policy = row['policy']
                initial_confidence[policy].append(first['calibrated_confidence'][action])
                initial_success[policy].append(success[index])
                realized = float(np.exp(-2 * (utility[index] - spec['inference']['action_cost'] * length[index])))
                pair = [first['predicted_moments'][action], realized]
                initial_moments[policy].append(pair)
                if action > 0:
                    continuation_moments[policy].append(pair)
                initial_selected_then_undelivered[policy] += not completed
            if completed:
                last = row['decisions'][-1]; action = last['selected_index']
                selected_confidence[row['policy']].append(last['calibrated_confidence'][action])
                selected_success[row['policy']].append(success[index])
    expected = {(case, view, draw, policy) for case in range(len(writers)) for view in views
                for draw in range(spec['draws']) for policy in policies}
    if seen != expected or any(not np.isfinite(value).all() for value in (utility, secondary, success, wall, cpu, length)):
        raise ValueError('Incomplete registered request or timing census')
    adjusted = utility - spec['inference']['action_cost'] * length
    rng = np.random.default_rng(spec['inference']['bootstrap_seed'])
    indices = rng.integers(0, len(unique), size=(spec['inference']['resamples'], len(unique)))

    def cluster_means(values):
        return np.stack([values[:, writers == writer].mean(axis=(1, 2, 3)) for writer in unique], 1)

    def boot_ce(values):
        largest = (-2 * values).max(axis=(1, 2, 3))
        scaled = np.exp(-2 * values - largest[:, None, None, None])
        means = cluster_means(scaled)
        return -(np.log(means[:, indices].mean(-1)) + largest[:, None]) / 2

    a, b = policies.index('constrained_paired'), policies.index('masked_teacher')
    samples = boot_ce(adjusted); difference = samples[a] - samples[b]
    alpha = spec['inference']['alpha']
    interval = np.quantile(difference, [alpha / 2, 1 - alpha / 2]).tolist()
    operationally_complete = not sum(failures.values())
    primary = {'contrast': 'constrained_paired minus masked_teacher',
        'estimand': 'CE(U - .002 * attempted non-stop actions), gamma=2',
        'point': ce(adjusted[a]) - ce(adjusted[b]), 'confidence_interval': interval,
        'confidence_level': 1 - alpha, 'lower_bound_positive': interval[0] > 0,
        'efficacy_gate': interval[0] > 0 and operationally_complete,
        'operational_gate': operationally_complete}
    descriptive = {}
    for index, policy in enumerate(policies):
        costs = np.asarray(detail_costs[policy])
        descriptive[policy] = {'raw_CE': ce(utility[index]), 'action_cost_CE': ce(adjusted[index]),
            'secondary_CE': ce(secondary[index]), 'strict_success': float(success[index].mean()),
            'mean_continuations': float(length[index].mean()), 'rejections': rejections[policy],
            'operational_failures': failures[policy], 'mean_wall_ms': float(wall[index].mean()),
            'mean_cpu_ms': float(cpu[index].mean()),
            'wall_p50_p95_p99_max_ms': np.quantile(wall[index], [.5, .95, .99, 1.]).tolist(),
            'mean_decision_cpu_ms_feature_admission_head': costs.mean(0).tolist(),
            'selected_final_decision_correctness': ece(selected_confidence[policy], selected_success[policy]),
            'initial_selected_terminal_correctness': ece(initial_confidence[policy], initial_success[policy]),
            'initial_selected_then_rejected_or_failed': initial_selected_then_undelivered[policy],
            'initial_selected_H2_moment': moment_stats(initial_moments[policy]),
            'initial_nonstop_selected_H2_moment': moment_stats(continuation_moments[policy]),
            'initial_prediction_scope': 'Actual realized terminal utility includes future attempted-action costs and later rejection/failure. Candidate H2 training used cross-fit H1 continuation choices; deployment uses the full-fit frozen H1 head. These descriptive residuals include that policy difference and source error, and do not inherit admission calibration qualification.'}
    sensitivity = {}
    for clock, costs in (('cpu', cpu), ('wall', wall)):
        sensitivity[clock] = [{'utility_price_per_ms': price,
            'cost_adjusted_CE_difference': ce(adjusted[a] - price * costs[a]) - ce(adjusted[b] - price * costs[b])}
            for price in spec['inference']['price_grid_per_ms']]
    diagnostics = analyze_counterfactuals(args.run)
    result = {'schema': 'hepta.advance.old-five-confirmation-result.v1',
        'primary': primary, 'policies': descriptive, 'cost_sensitivity_descriptive_only': sensitivity,
        'H1_same_state_diagnostics': diagnostics, 'source_pairs': len(writers), 'writer_clusters': len(unique),
        'fixed_training_seed': spec['seed'], 'requests': len(seen),
        'interval_scope': 'Paired writer-cluster percentile bootstrap; all pairs/views/future draws stay together. The three studies share this panel; alpha=.05/3 was fixed before opening. Conditional on this trained seed and known source panel, not a finite-sample or training-seed population guarantee.',
        'diagnostic_scope': 'Same-public-state ex-post feasible regret on candidate-visited H1 nodes only; private realized alternatives never enter online choice. Secondary results do not substitute for primary failure.',
        'actual_cost_scope': spec['inference']['cost_scope'],
        'source_and_implementation_sha256': {'protocol': registration['protocol_sha256'],
            'allocation': sha(spec['source']['allocation']), 'completion': sha(args.run / 'completion.json')},
        'whole_execution': completion, 'analysis_wall_ns': time.perf_counter_ns() - began,
        'production_authority': False, 'native_owner_executed': False}
    with args.output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'primary': primary, 'policies': descriptive, 'H1_diagnostics': diagnostics}))


def analyze_counterfactuals(folder):
    errors = {'candidate': [], 'teacher': [], 'zero': []}
    selected_delta = []; regrets = {'candidate': [], 'teacher': []}
    count = feasible_better = failed = selected_matches = 0
    with gzip.open(folder / 'counterfactual-scored.jsonl.gz', 'rt') as stream:
        for row in map(json.loads, stream):
            count += 1
            allowed = np.asarray(row['admitted'], dtype=bool)
            utility = np.asarray([item['scores']['primary']['utility'] if item['status'] == 'completed'
                                  else -1. for item in row['alternatives']])
            failed += sum(item['status'] != 'completed' for item in row['alternatives'])
            actual = np.exp(-2 * (utility - np.asarray([0., .002, .002, .002, .002])))
            candidate = np.asarray(row['candidate_prediction']); teacher = np.asarray(row['teacher_prediction'])
            choices = {'candidate': row['selected_index'],
                       'teacher': int(np.where(allowed, teacher, np.inf).argmin()) if allowed.any() else -1}
            optimum = float(actual[allowed].min()) if allowed.any() else float(np.exp(2))
            for name, chosen in choices.items():
                if chosen >= 0 and not allowed[chosen]:
                    raise ValueError('Counterfactual choice outside its registered feasible set')
                realized = float(actual[chosen]) if chosen >= 0 else float(np.exp(2))
                regrets[name].append(realized - optimum)
            if allowed[0]:
                comparable = allowed.copy(); comparable[0] = False
                truth = actual[comparable] - actual[0]
                errors['candidate'].extend((candidate[comparable] - candidate[0] - truth).tolist())
                errors['teacher'].extend((teacher[comparable] - teacher[0] - truth).tolist())
                errors['zero'].extend((-truth).tolist())
                feasible_better += bool((truth < 0).any())
                chosen = choices['candidate']
                if chosen > 0:
                    selected_delta.append([candidate[chosen] - candidate[0], actual[chosen] - actual[0]])
            chosen = choices['candidate']
            if chosen >= 0:
                selected_matches += row['alternatives'][chosen].get('reused_actual_selected_result', False)
    pairs = np.asarray(selected_delta).reshape(-1, 2)
    return {'candidate_visited_H1_nodes': count, 'actual_alternatives_per_node': 5,
        'alternative_generation_failures': failed, 'selected_terminal_reused': selected_matches,
        'executable_action_minus_executable_stop_count': len(errors['zero']),
        'delta_MSE': {name: float(np.mean(np.square(value))) if value else None for name, value in errors.items()},
        'mean_realized_feasible_moment_regret': {name: float(np.mean(value)) if value else None for name, value in regrets.items()},
        'nodes_with_realized_admitted_improvement_over_admitted_stop': feasible_better,
        'selected_nonstop_with_admitted_stop': len(pairs),
        'selected_actual_delta_mean': float(pairs[:, 1].mean()) if len(pairs) else None,
        'selected_prediction_bias': float((pairs[:, 0] - pairs[:, 1]).mean()) if len(pairs) else None,
        'selected_delta_MSE': float(np.square(pairs[:, 0] - pairs[:, 1]).mean()) if len(pairs) else None}


if __name__ == '__main__':
    main()
