"""Independent scalar CE and frequency-weighted paired bootstrap for v4.

No production reporting is imported. Checkpoint and initial-root strata remain
fixed; sampled indices become empirical frequencies rather than copied tensors.
"""

import hashlib
import math
from pathlib import Path
import time

import numpy as np

from audit_tables import MODALITIES, ce, require


def average(values):
    return math.fsum(map(float, values)) / len(values)


def percentile(values, probability):
    ordered = sorted(map(float, values))
    require(ordered and 0 <= probability <= 1, 'percentile support')
    position = (len(ordered) - 1) * probability
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def paired_statistics(returns, losses, gamma, repeats):
    returns, losses = np.asarray(returns, np.float64), np.asarray(losses, np.float64)
    require(returns.shape == losses.shape and returns.ndim == 4 and returns.shape[-1] == 4
            and all(n > 0 for n in returns.shape) and repeats > 0
            and np.isfinite(returns).all() and np.isfinite(losses).all(), 'balanced finite four-arm strata')
    seeds, roots, worlds, arms = returns.shape
    root_ce = np.empty((seeds, roots, arms), np.float64)
    for s, r, a in np.ndindex(root_ce.shape):
        root_ce[s, r, a] = ce(returns[s, r, :, a], [1 / worlds] * worlds, gamma)
    per_seed = np.array([[average(root_ce[s, :, a]) for a in range(arms)] for s in range(seeds)])
    means = np.array([average(per_seed[:, a]) for a in range(arms)])
    generator = np.random.default_rng(np.random.SeedSequence([5300000, 0]))
    draw_hash, boot_j, boot_loss = hashlib.sha256(), [], []
    for _ in range(repeats):
        draw = generator.integers(worlds, size=(seeds, roots, worlds))
        draw_hash.update(draw.astype('<i8', copy=False).tobytes())
        values, errors = [[] for _ in range(arms)], [[] for _ in range(arms)]
        for s, r in np.ndindex(seeds, roots):
            frequencies = np.bincount(draw[s, r], minlength=worlds) / worlds
            for a in range(arms):
                values[a].append(ce(returns[s, r, :, a], frequencies, gamma))
                errors[a].append(math.fsum(float(p) * float(v) for p, v in zip(frequencies, losses[s, r, :, a])))
        boot_j.append([average(v) for v in values])
        boot_loss.append([average(v) for v in errors])
    return {'conditional_root_ce': root_ce, 'per_seed_J': per_seed, 'sampled_J': means,
            'bootstrap_J': np.asarray(boot_j), 'bootstrap_mean_loss': np.asarray(boot_loss),
            'resampling_indices_sha256': draw_hash.hexdigest()}


def match_report(actual, expected, path='report'):
    """Compare every independently derived published numeric field recursively."""
    if isinstance(expected, dict):
        require(isinstance(actual, dict), ('report object', path))
        for key, value in expected.items():
            require(key in actual, ('missing reported field', path, key))
            match_report(actual[key], value, path + '.' + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), ('report sequence', path))
        for index, value in enumerate(expected):
            match_report(actual[index], value, f'{path}[{index}]')
    elif isinstance(expected, float):
        require(isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isfinite(actual) and abs(actual - expected) <= 1e-10,
                ('independent reported value', path, actual, expected))
    else:
        require(type(actual) is type(expected) and actual == expected, ('reported identity', path, actual, expected))


def audit_statistics(seed_directories, table_audits, protocol, published, development=False):
    started, cpu = time.perf_counter(), time.process_time()
    seeds = [protocol['development']['study_seed']] if development else protocol['seeds']
    require(set(seed_directories) == set(table_audits) == set(seeds), 'complete registered fixed checkpoints')
    settings = protocol['development' if development else 'confirmation']
    replicates = settings['worlds_per_condition_initial_mode']
    count, arms = 32 * replicates, protocol['policies']['arms']
    require(arms == ['dynamic', 'initial_feedback_committed_open_loop', 'myopic',
                     'clean_no_disturbance_reference'], 'ordered registered four arms')
    price, gamma = protocol['objective']['mac_price_lambda'], protocol['objective']['gamma']
    resource = protocol['resource_contract']
    decoder = np.array([resource['decoder_macs'][m] for m in MODALITIES], np.int64)
    refine = np.array([resource['refine_macs'][m] for m in MODALITIES], np.int64)
    loss = np.empty((len(seeds), 32, replicates, 4), np.float64)
    returns, exact = np.empty_like(loss), np.empty((len(seeds), 4), np.float64)
    rows, total_costs = {arm: [] for arm in arms}, []
    for s, seed in enumerate(seeds):
        audit = table_audits[seed]
        require(audit['passed'] and audit['study_seed'] == seed, 'independent table evidence required')
        plan_macs = 8 * resource['anchor_macs'] + 4992 * refine[0] + 5032 * decoder.sum()
        costs = {'seed': seed, 'shared_planning_linear_macs': int(plan_macs),
                 'online_linear_macs_by_arm': {}, 'amortization_by_arm': {}}
        for a, arm in enumerate(arms):
            with np.load(Path(seed_directories[seed]) / arm / 'scores.npz', allow_pickle=False) as saved:
                record = {key: saved[key] for key in ('loss', 'per_modality_error', 'contradiction',
                                                     'macs', 'refinement_counts', 'world_id')}
            for key, shape, dtype in (('loss', (count,), np.float64), ('per_modality_error', (count, 4), np.float64),
                ('contradiction', (count,), np.float64), ('macs', (count,), np.int64),
                ('refinement_counts', (count, 4), np.int64), ('world_id', (count,), np.int64)):
                value = record[key]
                require(value.shape == shape and value.dtype == dtype and np.isfinite(value).all(), ('statistic evidence', key))
            require(np.array_equal(record['world_id'], np.arange(count)), 'complete paired world IDs')
            counts, macs, errors = record['refinement_counts'], record['macs'], record['per_modality_error']
            require(np.all(counts >= 0) and np.all(counts.sum(1) <= 2) and np.all(macs <= resource['budget_macs_all_arms'])
                    and np.array_equal(macs, resource['native_init_charge_macs'] + decoder.sum() + counts @ refine),
                    'all complete output costs paid once')
            require(np.all((errors >= 0) & (errors <= 2)) and np.all((record['contradiction'] >= 0) & (record['contradiction'] <= 1))
                    and np.max(np.abs(record['loss'] - errors.mean(1) - .25 * record['contradiction'])) <= 1e-10,
                    'global loss components')
            if arm == 'clean_no_disturbance_reference':
                require(np.all(counts == 0), 'clean diagnostic performs no refinement')
            loss[s, :, :, a] = record['loss'].reshape(32, replicates)
            returns[s, :, :, a] = (-record['loss'] - price * macs).reshape(32, replicates)
            exact[s, a] = average(audit['conditional_post_init_root_values'][arm]) - price * resource['native_init_charge_macs']
            row = {'seed': seed, 'worlds': count, 'mean_external_loss': average(record['loss']),
                   'mean_per_modality_error': {m: average(errors[:, i]) for i, m in enumerate(MODALITIES)},
                   'mean_contradiction': average(record['contradiction']),
                   'mean_refinement_counts': {m: average(counts[:, i]) for i, m in enumerate(MODALITIES)},
                   'mean_allocated_linear_macs': {m: average(counts[:, i] * refine[i] + decoder[i]) for i, m in enumerate(MODALITIES)},
                   'shared_init_macs_per_world': resource['native_init_charge_macs'],
                   'mean_online_linear_macs': average(macs), 'total_online_linear_macs': int(macs.sum()),
                   'refinement_depth_counts': [int(np.count_nonzero(counts.sum(1) == d)) for d in range(3)]}
            rows[arm].append(row)
            costs['online_linear_macs_by_arm'][arm] = int(macs.sum())
            costs['amortization_by_arm'][arm] = {'N_1': float(plan_macs + average(macs)),
                                               'N_1024': float(plan_macs / 1024 + average(macs))}
        costs['planning_and_online_linear_macs_subtotal'] = int(plan_macs + sum(costs['online_linear_macs_by_arm'].values()))
        total_costs.append(costs)
    repeats = protocol['performance_analysis']['bootstrap_replicates']
    sampled = paired_statistics(returns, loss, gamma, repeats)
    arm_report, comparisons = {}, {}
    for a, arm in enumerate(arms):
        for s, row in enumerate(rows[arm]):
            row.update(sampled_J=float(sampled['per_seed_J'][s, a]), exact_finite_model_J=float(exact[s, a]),
                       conditional_root_CE=sampled['conditional_root_ce'][s, :, a].tolist())
        entry = {'worlds': len(seeds) * count, 'sampled_J': float(sampled['sampled_J'][a]),
                 'exact_finite_model_J': average(exact[:, a]), 'per_seed': rows[arm]}
        for key in ('mean_external_loss', 'mean_contradiction', 'mean_online_linear_macs'):
            entry[key] = average([row[key] for row in rows[arm]])
        for key in ('mean_per_modality_error', 'mean_refinement_counts', 'mean_allocated_linear_macs'):
            entry[key] = {m: average([row[key][m] for row in rows[arm]]) for m in MODALITIES}
        entry['total_online_linear_macs'] = sum(row['total_online_linear_macs'] for row in rows[arm])
        entry['refinement_depth_counts'] = [sum(row['refinement_depth_counts'][d] for row in rows[arm]) for d in range(3)]
        arm_report[arm] = entry
    for a in (1, 2):
        interval = [percentile(sampled['bootstrap_J'][:, 0] - sampled['bootstrap_J'][:, a], p)
                    for p in protocol['performance_analysis']['bootstrap_percentiles']]
        comparisons[arms[a]] = {
            'sampled_J_difference': float(sampled['sampled_J'][0] - sampled['sampled_J'][a]),
            'sampled_J_paired_stratified_bootstrap_95_interval': interval,
            'exact_finite_model_J_difference': average(exact[:, 0] - exact[:, a]),
            'per_seed_sampled_J_difference': {str(seed): float(sampled['per_seed_J'][s, 0] - sampled['per_seed_J'][s, a]) for s, seed in enumerate(seeds)},
            'per_seed_exact_J_difference': {str(seed): float(exact[s, 0] - exact[s, a]) for s, seed in enumerate(seeds)},
            'mean_external_loss_difference': average((loss[..., 0] - loss[..., a]).ravel()),
            'mean_external_loss_paired_bootstrap_95_interval': [percentile(
                sampled['bootstrap_mean_loss'][:, 0] - sampled['bootstrap_mean_loss'][:, a], p)
                for p in protocol['performance_analysis']['bootstrap_percentiles']],
            'interval_lower_strictly_positive': interval[0] > 0,
            'inference_role': 'registered primary' if a == 1 else 'descriptive unadjusted secondary'}
    expected = {'development': development, 'confirmatory': not development, 'seeds': seeds,
                'arms': arm_report, 'comparisons_dynamic_minus': comparisons,
                'primary_superiority_passed': bool(not development and comparisons[arms[1]]['interval_lower_strictly_positive']),
                'bootstrap': {'replicates': repeats, 'rng_seed_sequence': [5300000, 0], 'paired_across_arms': True,
                    'checkpoint_resampling': False, 'strata': len(seeds) * 32, 'observations_per_stratum': replicates,
                    'quantile_method': 'linear', 'gamma': gamma},
                'costs': {'per_seed': total_costs, 'planning_and_online_linear_macs_subtotal':
                          sum(row['planning_and_online_linear_macs_subtotal'] for row in total_costs)}}
    match_report(published, expected)
    return {'passed': True, 'independent_estimates': expected,
            'resampling_indices_sha256': sampled['resampling_indices_sha256'], 'audit_linear_macs': 0,
            'audit_wall_seconds': time.perf_counter() - started, 'audit_process_cpu_seconds': time.process_time() - cpu}
