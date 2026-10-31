"""Independent dense reference audit of Round 4 prepared and scored evidence.

The reference derives Gaussian covariances directly, then scores the mixture
with SciPy log-CDFs. Production forecast calls are used only as the object
being checked during preparation; no production math helper defines reference
likelihoods, posterior weights, densities, interval masses or selection scores.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import expit, log_ndtr, logsumexp, ndtr

HORIZONS = np.array([0., .5, 1., 2.])


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    with np.load(path, allow_pickle=False) as source:
        return {key: source[key].item() if source[key].ndim == 0 else source[key] for key in source.files}


class Review:
    def __init__(self):
        self.checks, self.scalars, self.maximum_error = 0, 0, 0.
        self.failures = []

    def check(self, condition, label):
        self.checks += 1
        if not condition:
            self.failures.append(label)

    def close(self, actual, expected, label, tolerance=2e-10):
        actual, expected = np.asarray(actual), np.asarray(expected)
        self.scalars += actual.size
        if actual.shape != expected.shape:
            self.check(False, label + ':shape')
            return
        finite = np.isfinite(expected)
        same_nonfinite = np.array_equal(actual[~finite], expected[~finite])
        error = float(np.max(np.abs(actual[finite] - expected[finite]), initial=0.))
        if np.isfinite(error):
            self.maximum_error = max(self.maximum_error, error)
        self.check(same_nonfinite and bool(np.isfinite(actual[finite]).all()) and error <= tolerance, label)


def dense_component(parameters, history):
    """Batch independent covariance conditioning, grouped only by observed mask."""
    drift, process, sensor = np.asarray(parameters)
    times, observations = history['times'], history['obs']
    occupied = history.get('occupied', np.ones_like(times, dtype=bool))
    observed = occupied & history['mask']
    n = len(times)
    endpoint = np.max(np.where(occupied, times, 0.), axis=1)
    future = endpoint[:, None] + HORIZONS
    mean, variance, likelihood = np.empty((n, 4)), np.empty((n, 4)), np.empty(n)
    masks, membership = np.unique(observed, axis=0, return_inverse=True)
    for group, mask in enumerate(masks):
        selected = np.flatnonzero(membership == group)
        t, y = times[selected][:, mask], observations[selected][:, mask]
        size = t.shape[1]
        if size == 0:
            mean[selected], variance[selected], likelihood[selected] = drift * future[selected], 1 + process * future[selected], 0.
            continue
        covariance = 1 + process * np.minimum(t[:, :, None], t[:, None, :])
        diag = np.arange(size)
        covariance[:, diag, diag] += sensor * history['obs_var'][selected][:, mask]
        residual, cross = y - drift * t, 1 + process * t
        solved = np.linalg.solve(covariance, np.stack([residual, cross], axis=-1))
        sign, logdet = np.linalg.slogdet(covariance)
        if np.any(sign != 1):
            raise ValueError('Reference covariance lost positive definiteness')
        mean[selected] = drift * future[selected] + np.sum(cross * solved[..., 0], axis=1)[:, None]
        variance[selected] = 1 + process * future[selected] - np.sum(cross * solved[..., 1], axis=1)[:, None]
        likelihood[selected] = -.5 * (size * np.log(2 * np.pi) + logdet + np.sum(residual * solved[..., 0], axis=1))
    return mean, variance, likelihood


def cache_components(model, query, context, reusable):
    means, variances, evidence = [], [], []
    for name in ('anchor', 'adaptive'):
        parameters = np.asarray(model[name]['parameters'])
        if model['parameter_q24']:
            parameters = np.rint(parameters * (1 << 24)) / (1 << 24)
        key = tuple(parameters)
        if key not in reusable:
            m, v, ell = dense_component(parameters, query)
            context_ll = dense_component(parameters, context)[2].reshape(len(query['obs']), 8).sum(1)
            reusable[key] = m, v, ell, context_ll
        m, v, ell, context_ll = reusable[key]
        means.append(m)
        variances.append(v)
        evidence.append(ell + (context_ll if model['context_count'] else 0.))
    return np.stack(means, -1), np.stack(variances, -1), np.stack(evidence, -1)


def reference_distribution(model, cache):
    mean, variance, likelihood = cache
    prior = model['prior']
    if model['parameter_q24']:
        prior = np.rint(prior * (1 << 24)) / (1 << 24)
    with np.errstate(divide='ignore'):
        joint = likelihood + np.log(np.array([1 - prior, prior]))
    logweight = joint - logsumexp(joint, axis=1, keepdims=True)
    weight = np.exp(logweight)
    if model['projection']:
        projected = np.sum(weight[:, None, :] * mean, axis=-1)
        projected_variance = np.sum(weight[:, None, :] * (variance + mean ** 2), axis=-1) - projected ** 2
        mean, variance = projected[..., None], projected_variance[..., None]
        weight, logweight = np.ones((len(mean), 1)), np.zeros((len(mean), 1))
    return {'weights': weight, 'log_weights': logweight, 'means': mean, 'variances': variance}


def reference_arrays(dist, query):
    targets = query['future'][:, [0, 1, 2, 4]]
    mean, variance, logweight = dist['means'], dist['variances'], dist['log_weights'][:, None, :]
    density = logsumexp(logweight - .5 * (np.log(2 * np.pi * variance) + (targets[..., None] - mean) ** 2 / variance), -1)
    lo, hi = (-.6 - mean) / np.sqrt(variance), (.6 - mean) / np.sqrt(variance)
    below, above = log_ndtr(lo), log_ndtr(-hi)
    left, right = np.where(lo > 0, log_ndtr(-lo), log_ndtr(hi)), np.where(lo > 0, log_ndtr(-hi), log_ndtr(lo))
    with np.errstate(divide='ignore'):
        middle = left + np.log(-np.expm1(right - left))
    event_logs = logsumexp(logweight[..., None] + np.stack([below, middle, above], -1), axis=-2)[:, 1:]
    labels = np.where(targets[:, 1:] <= -.6, 0, np.where(targets[:, 1:] > .6, 2, 1))
    marginal_mean = np.sum(dist['weights'][:, None, :] * mean, axis=-1)[:, 1:]
    return {'density_nll_by_horizon': -density[:, 1:], 'density_nll': -density[:, 1:].mean(1),
            'event_nll': -np.take_along_axis(event_logs, labels[..., None], -1)[..., 0].mean(1),
            'probabilities': np.exp(event_logs), 'labels': labels, 'targets': targets[:, 1:],
            'mean': marginal_mean, 'mse': ((targets[:, 1:] - marginal_mean) ** 2).mean(1)}


def public_history(query):
    return {key: query[key] for key in ('obs', 'times', 'mask', 'obs_var')}


def artifacts_review(review, run):
    prepared_path = run / 'calibration_prepared' / 'PREPARED.json'
    prepared = json.loads(prepared_path.read_text())
    repo = Path(__file__).resolve().parents[4]
    for name, digest in prepared['source_sha256'].items():
        review.check(sha(repo / name) == digest, 'source:' + name)
    for name, digest in prepared['artifacts_sha256'].items():
        review.check(sha(prepared_path.parent / name) == digest, 'artifact:' + name)
    review.check(not prepared['holdouts_constructed'], 'prepare_without_holdouts')
    return prepared


def prepared_review(review, run, prepared):
    from .. import calibration as production
    reg, component_changes, prior_changes = prepared['registration'], [], []
    optimizer_outcomes = Counter()
    for seed in reg['seeds']:
        root = run / 'calibration_prepared' / f'seed_{seed}'
        anchor_document = json.loads((root / 'ANCHOR.json').read_text())
        anchor = anchor_document['model']
        original = load(root / 'ORIGINAL_TRAIN.npz')
        old_train = {key: value[:256] if isinstance(value, np.ndarray) and value.ndim and len(value) == len(original['obs']) else value for key, value in original.items()}
        old_train_context = load(root / 'OLD_TRAIN_CONTEXT.npz')
        optimizer_outcomes[str(anchor_document['fit']['optimizer_success'])] += 1
        previous = None
        for window in range(len(reg['windows'])):
            prefix = f'window_{window:02d}'
            checkpoint_path = root / (prefix + '_CHECKPOINT.json')
            checkpoint = json.loads(checkpoint_path.read_text())
            review.check(checkpoint['previous_checkpoint_sha256'] == previous, f'chain:{seed}:{window}')
            review.check(checkpoint['holdout_used'] is False, f'no_holdout:{seed}:{window}')
            previous = sha(checkpoint_path)
            domains = {}
            for name in ('OLD_DEV', 'NEW_DEV'):
                query, context = load(root / (prefix + '_' + name + '.npz')), load(root / (prefix + '_' + name + '_CONTEXT.npz'))
                review.check(set(context) == {'obs', 'times', 'mask', 'occupied', 'obs_var'}, f'context_public_schema:{seed}:{window}:{name}')
                review.check(len(context['obs']) == 8 * len(query['obs']) == 8 * reg['development_rows_per_domain'], f'context_budget:{seed}:{window}:{name}')
                reusable, reference_cache = {}, {}
                for arm in reg['arms']:
                    model = checkpoint['models'][arm]
                    cache = cache_components(model, query, context, reusable)
                    expected = reference_distribution(model, cache)
                    h = public_history(query)
                    h['occupied'] = np.ones_like(h['mask'])
                    actual = production.predict_distribution(model, h, context)
                    for key in expected:
                        review.close(actual[key], expected[key], f'forecast:{seed}:{window}:{name}:{arm}:{key}')
                    reference_cache[arm] = cache
                domains[name] = query, context, reusable, reference_cache
            current_train = load(root / (prefix + '_TRAIN.npz'))
            current_context = load(root / (prefix + '_TRAIN_CONTEXT.npz'))
            training_parts = [(old_train, old_train_context, {}), (current_train, current_context, {})]
            for name, receipt in checkpoint['prior_training'].items():
                model = checkpoint['models'][name]
                fit_parts = [(cache_components(model, query, context, reusable), query['future'][:, [0, 1, 2, 4]])
                             for query, context, reusable in training_parts]
                def objective(logit):
                    values = []
                    candidate = {**model, 'prior': float(expit(logit))}
                    for cache, target in fit_parts:
                        dist = reference_distribution(candidate, cache)
                        logs = dist['log_weights'][:, None, :] - .5 * (np.log(2 * np.pi * dist['variances'])
                                + (target[..., None] - dist['means']) ** 2 / dist['variances'])
                        values.append(-logsumexp(logs, axis=-1))
                    return float(np.concatenate(values).mean())
                for trace_index, point in enumerate(receipt['objective_trace']):
                    logit = point['prior_logit']
                    review.close(point['nll'], objective(logit), f'fit_objective:{seed}:{window}:{name}:{trace_index}')
                    numerical = (objective(logit + 1e-5) - objective(logit - 1e-5)) / 2e-5
                    review.close(point['gradient'], numerical, f'fit_gradient:{seed}:{window}:{name}:{trace_index}', 2e-8)
                review.close(receipt['fitted_prior'], checkpoint['selection'][name]['fit_prior'], f'fit_selection_binding:{seed}:{window}:{name}', 0.)
            for name, selection in checkpoint['selection'].items():
                review.check(len(selection['candidates']) == 21 and selection['development_labelled_queries'] == 512,
                             f'selection_budget:{seed}:{window}:{name}')
                values = []
                for index, row in enumerate(selection['candidates']):
                    candidate = deepcopy(checkpoint['models'][name])
                    if name == 'replay':
                        pars = ((1 - row['strength']) * np.asarray(anchor['parameters'])
                                + row['strength'] * np.asarray(checkpoint['replay_state']['parameters'])).tolist()
                        candidate['anchor']['parameters'] = candidate['adaptive']['parameters'] = pars
                    else:
                        candidate['prior'] = row['strength'] * selection['fit_prior']
                    losses, old_base = [], None
                    for domain in ('OLD_DEV', 'NEW_DEV'):
                        query, context, reusable, stored_cache = domains[domain]
                        cache = cache_components(candidate, query, context, reusable) if name == 'replay' else stored_cache[name]
                        losses.append(reference_arrays(reference_distribution(candidate, cache), query)['density_nll'])
                        if domain == 'OLD_DEV':
                            old_base = reference_arrays(reference_distribution(checkpoint['models']['frozen'], stored_cache['frozen']), query)['density_nll']
                    delta = losses[0] - old_base
                    upper = float(delta.mean() + 1.645 * delta.std(ddof=1) / np.sqrt(len(delta)))
                    review.close(row['old_nll_change'], delta.mean(), f'old_selection:{seed}:{window}:{name}:{index}')
                    review.close(row['old_upper_heuristic'], upper, f'guard:{seed}:{window}:{name}:{index}')
                    review.close(row['new_nll'], losses[1].mean(), f'new_selection:{seed}:{window}:{name}:{index}')
                    review.check(row['eligible'] == (upper <= .02), f'eligible:{seed}:{window}:{name}:{index}')
                    values.append((float(losses[1].mean()), index, upper <= .02))
                chosen = min((value for value in values if value[2]), key=lambda value: (round(value[0], 12), value[1]))[1]
                actual_chosen = selection['selected_index']
                chosen_row = selection['candidates'][actual_chosen]
                if name == 'replay':
                    parameters = ((1 - chosen_row['strength']) * np.asarray(anchor['parameters'])
                                  + chosen_row['strength'] * np.asarray(checkpoint['replay_state']['parameters']))
                    for component in ('anchor', 'adaptive'):
                        review.close(checkpoint['models'][name][component]['parameters'], parameters,
                                     f'replay_selected_binding:{seed}:{window}:{component}', 0.)
                else:
                    review.close(checkpoint['models'][name]['prior'], chosen_row['prior'], f'selected_prior_binding:{seed}:{window}:{name}', 0.)
                # Exact ties use original values; a dense rounding difference may only
                # interchange candidates whose NLLs agree within numeric tolerance.
                review.check(values[actual_chosen][2] and abs(values[actual_chosen][0] - values[chosen][0]) < 2e-10,
                             f'chosen:{seed}:{window}:{name}')
            for receipt in checkpoint['component_training'].values():
                component_changes.append(float(np.linalg.norm(np.asarray(receipt['final_parameters']) - receipt['initial_parameters'])))
                optimizer_outcomes[str(receipt['optimizer_success'])] += 1
            for receipt in checkpoint['prior_training'].values():
                prior_changes.append(receipt['prior_logit_change'])
                optimizer_outcomes[str(receipt['optimizer_success'])] += 1
                review.check(receipt['training_trajectories'] == 512, f'prior_fit_budget:{seed}:{window}')
    return {'component_fit_count_excluding_anchors': len(component_changes), 'anchor_fit_count': len(reg['seeds']),
            'prior_fit_count': len(prior_changes), 'component_min_parameter_change': min(component_changes),
            'prior_min_logit_change': min(prior_changes), 'optimizer_outcomes': dict(optimizer_outcomes),
            'full_development_candidates_recomputed': len(reg['seeds']) * len(reg['windows']) * 5 * 21}


def ece(probabilities, labels):
    p, labels = probabilities.reshape(-1, 3), labels.reshape(-1)
    errors = []
    for category in range(3):
        bins = np.minimum(np.floor(10 * p[:, category]).astype(int), 9)
        total = 0.
        for index in range(10):
            mask = bins == index
            if mask.any():
                total += float(mask.mean()) * abs(float(p[mask, category].mean()) - float((labels[mask] == category).mean()))
        errors.append(total)
    return float(np.mean(errors))


def bootstrap(values, count, seed, alpha):
    values = np.asarray(values)
    groups, windows, rows = values.shape
    rng, output = np.random.default_rng(seed), []
    for start in range(0, count, 100):
        n = min(100, count - start)
        sampled_groups = rng.integers(groups, size=(n, groups, 1, 1))
        sampled_rows = rng.integers(rows, size=(n, groups, windows, rows))
        selected = values[sampled_groups, np.arange(windows)[None, None, :, None], sampled_rows]
        output.extend(selected.mean(axis=(1, 2, 3)).tolist())
    return np.quantile(output, [alpha / 2, 1 - alpha / 2])


def confirmation_review(review, run, prepared):
    reg, scopes = prepared['registration'], {}
    directory = run / 'calibration_confirmation'
    index = json.loads((directory / 'INDEX.json').read_text())
    review.check(index['prepared_sha256'] == sha(run / 'calibration_prepared' / 'PREPARED.json'), 'confirmation_prepared_binding')
    for record in index['records']:
        seed, window = record['seed'], record['window']
        prefix = f'seed_{seed}_window_{window:02d}'
        score_path = directory / record['score_path']
        review.check(sha(score_path) == record['score_sha256'], 'scores:' + prefix)
        scored = load(score_path)
        scopes[seed, window] = scored
        checkpoint = json.loads((run / 'calibration_prepared' / f'seed_{seed}' / f'window_{window:02d}_CHECKPOINT.json').read_text())
        for domain, path in (('old', f'seed_{seed}_OLD'), ('new', prefix + '_NEW')):
            query, context, reusable = load(directory / (path + '.npz')), load(directory / (path + '_CONTEXT.npz')), {}
            for arm in reg['arms']:
                model = checkpoint['models'][arm]
                dist = reference_distribution(model, cache_components(model, query, context, reusable))
                arrays = reference_arrays(dist, query)
                for key, expected in arrays.items():
                    review.close(scored[arm + '__' + domain + '__' + key], expected, f'score:{prefix}:{domain}:{arm}:{key}')
                quantiles = scored[arm + '__' + domain + '__quantiles95']
                for j, level in enumerate((.025, .975)):
                    z = (quantiles[..., j, None] - dist['means'][:, 1:]) / np.sqrt(dist['variances'][:, 1:])
                    actual = np.sum(dist['weights'][:, None, :] * ndtr(z), axis=-1)
                    review.close(actual, np.full_like(actual, level), f'quantile:{prefix}:{domain}:{arm}:{level}', 2e-11)
                coverage = ((arrays['targets'] >= quantiles[..., 0]) & (arrays['targets'] <= quantiles[..., 1])).mean(1)
                review.close(scored[arm + '__' + domain + '__coverage95'], coverage, f'coverage:{prefix}:{domain}:{arm}', 0.)
                scalar = record['summary'][arm][domain]
                for key in ('density_nll', 'event_nll', 'mse'):
                    review.close(scalar[key], arrays[key].mean(), f'mean:{prefix}:{domain}:{arm}:{key}')
                review.close(scalar['coverage95'], coverage.mean(), f'mean_coverage:{prefix}:{domain}:{arm}')
                review.close(scalar['classwise_ece'], ece(arrays['probabilities'], arrays['labels']), f'ece:{prefix}:{domain}:{arm}')
    result = json.loads((directory / 'RESULTS.json').read_text())
    for arm_index, arm in enumerate(reg['arms']):
        old = np.array([[scopes[s, w][arm + '__old__density_nll'] - scopes[s, w]['frozen__old__density_nll']
                         for w in range(12)] for s in reg['seeds']])
        final = np.array([[scopes[s, 11][arm + '__new__density_nll'] - scopes[s, 11]['frozen__new__density_nll']] for s in reg['seeds']])
        shifted = [scopes[s, w] for s in reg['seeds'] for w in range(1, 12, 2)]
        calibration = ece(np.concatenate([x[arm + '__new__probabilities'] for x in shifted]),
                          np.concatenate([x[arm + '__new__labels'] for x in shifted]))
        coverage = float(np.concatenate([x[arm + '__new__coverage95'] for x in shifted]).mean())
        alpha = reg['primary_interval_alpha'] if arm in reg['primary_profiles'] else reg['diagnostic_interval_alpha']
        bounds = bootstrap(final, reg['bootstrap_replicates'], reg['bootstrap_seed'] + arm_index, alpha)
        entry = result['arms'][arm]
        for key, expected in (('worst_cross_seed_mean_old_nll_increase', old.mean((0, 2)).max()),
                              ('worst_single_seed_window_old_nll_increase', old.mean(2).max()),
                              ('old_nll_increase_by_window', old.mean((0, 2))),
                              ('pooled_shifted_classwise_ece', calibration), ('pooled_shifted_coverage95', coverage)):
            review.close(entry[key], expected, f'aggregate:{arm}:{key}')
        review.close(entry['final_new_nll_difference']['interval'], bounds, 'bootstrap:' + arm)
        review.close(entry['final_new_nll_difference']['mean_difference'], final.mean(), 'mean_delta:' + arm)
        review.close(entry['final_new_nll_difference']['per_seed_mean'], final.mean((1, 2)), 'seed_delta:' + arm)
        retention_ok = bool(old.mean((0, 2)).max() <= .02 and final.mean() <= 0)
        efficacy = bool(retention_ok and final.mean() <= -.005 and bounds[1] < 0 and final.mean((1, 2)).max() < 0)
        calibration_ok = bool(calibration <= .04 and .92 <= coverage <= .98)
        for key, expected in (('passes_retention_gate', retention_ok), ('passes_nll_efficacy_gate', efficacy),
                              ('passes_calibration_gate', calibration_ok), ('passes_joint_empirical_gate', efficacy and calibration_ok)):
            review.check(entry[key] == expected, f'gate:{arm}:{key}')
    for name, actual in result['mechanism_comparisons'].items():
        left, right = name.split('_minus_')
        difference = np.array([[scopes[s, w][left + '__new__density_nll'] - scopes[s, w][right + '__new__density_nll']
                                for w in range(1, 12, 2)] for s in reg['seeds']])
        review.close(actual['mean_difference'], difference.mean(), 'mechanism_mean:' + name)
        review.close(actual['interval'], bootstrap(difference, reg['bootstrap_replicates'], reg['bootstrap_seed'] + 100, .05), 'mechanism_bootstrap:' + name)
    return {'scopes': len(index['records']), 'independently_rescored_model_domain_query_rows': len(index['records']) * 2 * len(reg['arms']) * 256,
            'independent_bootstrap_intervals': len(reg['arms']) + len(result['mechanism_comparisons'])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('prepare', 'confirm'))
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    run, review = Path(args.run_dir), Review()
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    prepared = artifacts_review(review, run)
    details = prepared_review(review, run, prepared) if args.phase == 'prepare' else confirmation_review(review, run, prepared)
    result = {'schema': 'hepta.analytic-event.calibration-independent-review.v4', 'phase': args.phase,
              'passed': not review.failures, 'checks': review.checks, 'scalar_comparisons': review.scalars,
              'maximum_absolute_numeric_error': review.maximum_error, 'failure_count': len(review.failures),
              'failures': review.failures, 'details': details, 'reviewer_source_sha256': sha(__file__),
              'prepared_sha256': sha(run / 'calibration_prepared' / 'PREPARED.json'),
              'wall_ns': time.perf_counter_ns() - started, 'parent_cpu_ns': time.process_time_ns() - cpu}
    output = Path(args.output) if args.output else run / 'reviews' / ('CALIBRATION_' + args.phase.upper() + '_REVIEW.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x') as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('failures', 'details')}), flush=True)
    if review.failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
