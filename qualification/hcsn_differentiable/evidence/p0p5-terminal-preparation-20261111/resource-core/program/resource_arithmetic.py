"""New v2 arithmetic over saved observations; no producer, model, or numerical-kernel imports."""
import math
import statistics

ARMS = ('gru', 'cfc', 'snn_plif', 'event_time_lif', 'ssm_s4d', 'attention', 'hcsn')
SEEDS, LRS = (101, 211, 307), (.001, .003)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonnegative(value, label):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0, label+' must be finite and nonnegative')
    return value


def close(left, right, label, tolerance=2e-12):
    require(type(left) in (int, float) and type(right) in (int, float)
            and math.isfinite(left) and math.isfinite(right) and abs(left-right) <= tolerance, label+' differs')


def roster(arm=None):
    require(arm is None or arm in ARMS, 'unknown core')
    return [f'{a}-s{s}-lr{lr:g}' for a in ((arm,) if arm else ARMS) for s in SEEDS for lr in LRS]


def matrix_metrics(matrix):
    require(isinstance(matrix, list) and len(matrix) == 11
            and all(isinstance(row, list) and len(row) == 11 for row in matrix), 'eleven-class confusion matrix required')
    require(all(type(n) is int and n >= 0 for row in matrix for n in row), 'integer CM counts required')
    support, columns = [sum(row) for row in matrix], [sum(row[j] for row in matrix) for j in range(11)]
    total = sum(support)
    require(total > 0, 'empty confusion matrix')
    f1 = [2*matrix[i][i]/(support[i]+columns[i]) if support[i]+columns[i] else 0. for i in range(11)]
    present = [i for i, n in enumerate(support) if n]
    return support, {'accuracy': sum(matrix[i][i] for i in range(11))/total,
        'macro_f1_11_classes': statistics.mean(f1), 'macro_f1_present_classes': statistics.mean(f1[i] for i in present),
        'balanced_accuracy_present_classes': statistics.mean(matrix[i][i]/support[i] for i in present)}


def verify_development(row, support=None, events=31952):
    observed, metrics = matrix_metrics(row['confusion_matrix'])
    require(sum(observed) == row['events'] == events, 'development event count differs')
    require(support is None or observed == support, 'development support differs')
    for key, value in metrics.items():
        close(value, row[key], 'CM '+key)
    return observed, metrics['macro_f1_11_classes']


def first_best(points):
    eligible = [p for p in points if p['kind'] == 'complete_epoch']
    return max(eligible, key=lambda p: p['quality'], default=None)  # First equal maximum is retained.


def first_crossing(points, target=.3):
    return next((p for p in points if p['kind'] == 'complete_epoch' and p['quality'] >= target), None)


def check_points(points):
    previous = -1.
    for point in points:
        wall = nonnegative(point['wall_seconds'], 'observed quality wall')
        require(wall > previous, 'quality observations must be strictly ordered')
        previous = wall
        require(point['kind'] in ('complete_epoch', 'development_before'), 'unknown observation kind')
        quality = nonnegative(point['quality'], 'quality')
        require(quality <= 1, 'quality exceeds one')


def cost_sum(rows):
    names = [r['name'] for r in rows]
    require(len(names) == len(set(names)), 'duplicate opportunity cost')
    missing, known, cpu_missing, cpu_known, peaks = [], [], [], [], []
    for row in rows:
        full = row.get('full_chain_charged_wall_seconds')
        lower = row.get('known_chain_wall_lower_bound_seconds')
        if full is None:
            missing.append(row['name'])
            if lower is not None:
                known.append(nonnegative(lower, 'known wall lower bound'))
        else:
            known.append(nonnegative(full, 'full opportunity wall'))
            require(lower is None or 0 <= lower <= full, 'wall lower bound exceeds full bill')
        cpu = row.get('cumulative_full_CPU_seconds')
        if cpu is None:
            cpu_missing.append(row['name'])
            cpu = row.get('cumulative_CPU_lower_bound_seconds')
        if cpu is not None:
            cpu_known.append(nonnegative(cpu, 'known CPU contribution'))
        if row.get('max_attempt_RSS_bytes') is not None:
            peaks.append(nonnegative(row['max_attempt_RSS_bytes'], 'observed peak RSS'))
    return {'opportunity_count': len(rows), 'all_opportunity_wall_seconds': sum(known) if not missing else None,
        'known_wall_lower_bound_seconds': sum(known), 'missing_full_cost_names': missing,
        'known_sum_is_lower_bound': bool(missing), 'all_opportunity_full_CPU_seconds': sum(cpu_known) if not cpu_missing else None,
        'known_CPU_lower_bound_seconds': sum(cpu_known), 'missing_full_CPU_names': cpu_missing,
        'maximum_observed_attempt_RSS_bytes': max(peaks, default=None),
        'wall_scope': 'Sum of full original process plus full continuation wrapper per opportunity; overlapping attempts are not elapsed calendar time.',
        'CPU_scope': 'Original fit-entry CPU excludes pre-fit startup/import and post-report exit CPU. Known contributions are lower bounds; wrapper CPU remains separate.',
        'memory_scope': 'Maximum observed per-attempt RSS; not a tree sum or memory measured at the quality crossing.'}


def core_table(arm, rows, fixed_lr=None):
    require(len(rows) == 6 and {r['name'] for r in rows} == set(roster(arm)), 'all six named opportunities required')
    require(all(r['arm'] == arm and r['name'] == f"{arm}-s{r['seed']}-lr{r['learning_rate']:g}"
                for r in rows), 'candidate identities differ')
    groups = []
    for lr in LRS:
        selected = [next(r for r in rows if r['seed'] == seed and r['learning_rate'] == lr) for seed in SEEDS]
        verified = [r for r in selected if r.get('quality_verified') is True and r.get('quality') is not None]
        values = [nonnegative(r['quality'], 'verified quality') for r in verified]
        require(all(q <= 1 for q in values), 'quality exceeds one')
        stats = {'mean': statistics.mean(values), 'sample_standard_deviation': statistics.stdev(values)} if len(values) == 3 else None
        groups.append({'learning_rate': lr, 'verified_quality_count': len(values),
                       'verified_three_seed_statistics': stats, 'members': [r['name'] for r in selected]})
    if arm == 'hcsn':
        require(fixed_lr is None, 'C2 HCSN common LR cannot be supplied by a caller')
        choice = min(groups, key=lambda g: (-g['verified_three_seed_statistics']['mean'], g['learning_rate'])) \
            if all(g['verified_quality_count'] == 3 for g in groups) else None
    else:
        require(fixed_lr in LRS, 'baseline common LR must be the frozen earlier selection')
        choice = next(g for g in groups if g['learning_rate'] == fixed_lr)
        if choice['verified_quality_count'] != 3:
            choice = None
    chosen = [r for r in rows if choice and r['learning_rate'] == choice['learning_rate']]
    crosses = [{'name': r['name'], 'crossing': r.get('first_observed_target_crossing'),
                'right_censor_outer_wall_seconds': r.get('full_chain_charged_wall_seconds')
                    if r.get('first_observed_target_crossing') is None else None} for r in chosen]
    crossing_count = sum(c['crossing'] is not None for c in crosses)
    adequate = sum(r.get('independent_adequate') is True and r.get('quality_verified') is True for r in chosen)
    return {'arm': arm, 'learning_rate_candidates': groups,
        'selected_common_learning_rate': choice['learning_rate'] if choice else None,
        'selected_statistics': choice['verified_three_seed_statistics'] if choice else None,
        'selection_status': 'verified_saved_quality' if choice else 'withheld_missing_or_unverified_seed',
        'selected_independently_adequate_count': adequate, 'selected_trained_comparison_supported': bool(choice and adequate == 3),
        'selected_target_crossings': crosses, 'selected_observed_crossing_count': crossing_count,
        'median_first_observed_target_seconds': statistics.median(c['crossing']['wall_seconds'] for c in crosses)
            if choice and len(crosses) == crossing_count == 3 else None,
        'all_six_opportunity_cost': cost_sum(rows),
        'all_six_inadequate_names': [r['name'] for r in rows if r.get('independent_adequate') is not True],
        'memory_at_quality_crossing_known': False, 'energy_joules': None, 'GPU_VRAM_bytes': None, 'billed_currency': None}
