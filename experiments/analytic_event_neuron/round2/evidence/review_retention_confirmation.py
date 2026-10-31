"""Postconfirmation, read-only verification of already saved retention evidence.

This program imports no experiment implementation, generates no trajectory,
runs no optimizer or evaluation entry point, and changes no frozen artifact.
Its only write is the independent review JSON next to this program.
"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
from scipy.special import erf, erfc, expit


PROJECT = Path(__file__).resolve().parents[4]
RUN = Path('/tmp/aen-round2-20261027')
CONFIRM = RUN / 'retention_confirmation'
PREPARED = RUN / 'retention_prepared'
OUTPUT = Path(__file__).with_name('RETENTION_CONFIRMATION_REVIEW.json')
ARMS = ('frozen', 'online', 'replay', 'fixed_mixture', 'likelihood_mixture',
        'protected', 'protected_classical', 'protected_quantized', 'protected_quantized_classical')
Q = 1 << 24
CHECKS, ERRORS, MAX_ERRORS = Counter(), [], {}
STARTED = time.perf_counter_ns()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_json(path):
    return json.loads(Path(path).read_text())


def load_npz(path):
    with np.load(path, allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key]
                for key in archive.files}


def check(group, condition, detail):
    CHECKS[group] += 1
    if not bool(condition):
        ERRORS.append({'group': group, 'detail': detail})


def close(group, actual, expected, detail, atol=3e-11, rtol=3e-12):
    a, b = np.asarray(actual), np.asarray(expected)
    error = float(np.max(np.abs(a - b)))
    MAX_ERRORS[group] = max(MAX_ERRORS.get(group, 0.0), error)
    check(group, a.shape == b.shape and np.isfinite(a).all() and np.isfinite(b).all()
          and np.allclose(a, b, atol=atol, rtol=rtol), {'at': detail, 'maximum_absolute_error': error})


def equal(group, actual, expected, detail):
    check(group, np.array_equal(actual, expected), detail)


def data_digest(data):
    h = hashlib.sha256()
    for key in sorted(data):
        h.update(key.encode())
        value = data[key]
        h.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    return h.hexdigest()


def event_reference(mean, variance):
    """Independent erf/erfc branch evaluation; no production log-CDF call."""
    lower, upper = (-.6 - mean) / np.sqrt(2 * variance), (.6 - mean) / np.sqrt(2 * variance)
    put, call = .5 * erfc(-lower), .5 * erfc(upper)
    middle = np.empty_like(mean)
    left, right = upper <= 0, lower >= 0
    middle[left] = .5 * (erfc(-upper[left]) - erfc(-lower[left]))
    middle[right] = .5 * (erfc(lower[right]) - erfc(upper[right]))
    center = ~(left | right)
    middle[center] = .5 * (erf(upper[center]) - erf(lower[center]))
    p = np.stack((put, middle, call), axis=-1)
    if np.any(p <= 0) or not np.isfinite(p).all():
        raise ValueError('Independent reference encountered an unsupported underflow')
    return p, np.log(p)


def ece_reference(probability, labels):
    """Equivalent bins expressed as interval masks and summed residuals."""
    p, y = probability.reshape(-1, 3), labels.reshape(-1)
    residual = 0.0
    for category in range(3):
        prediction, observation = p[:, category], (y == category).astype(float)
        for index in range(10):
            selected = (prediction >= index / 10) & ((prediction < (index + 1) / 10)
                                                       if index < 9 else (prediction <= 1))
            residual += abs(float(np.sum(prediction[selected] - observation[selected])))
    return residual / (3 * len(y))


def public_dense_loglikelihood(model, data):
    """Independent multivariate Gaussian observation likelihood, no filter loop."""
    drift, q, scale = model['parameters']
    score = []
    for observation, timestamp, mask, sensor_variance in zip(
            data['obs'], data['times'], data['mask'], data['obs_var']):
        t, y, noise = timestamp[mask], observation[mask], sensor_variance[mask]
        covariance = 1 + q * np.minimum.outer(t, t) + np.diag(scale * noise)
        cholesky = np.linalg.cholesky(covariance)
        whitened = np.linalg.solve(cholesky, y - drift * t)
        score.append(-.5 * (len(y) * math.log(2 * math.pi)
                             + 2 * np.log(np.diag(cholesky)).sum() + whitened @ whitened))
    return np.array(score)


def supremum_nll(m0, v0, mean, variance):
    a, b, c, d = [np.asarray(x, dtype=np.longdouble) for x in (m0, v0, mean, variance)]
    delta_v, delta_m = d - b, c - a
    valid = (delta_v > 0) | ((delta_v == 0) & (delta_m == 0))
    check('certificate_domain', valid.all(), 'actual delivered Gaussian dominates anchor in the tails')
    result = np.zeros_like(a)
    nonzero = delta_v > 0
    result[nonzero] = (.5 * np.log1p(delta_v[nonzero] / b[nonzero])
                      + delta_m[nonzero] ** 2 / (2 * delta_v[nonzero]))
    return np.asarray(result, dtype=float)


def bootstrap_reference(differences):
    """Preserve frozen RNG ordering while independently reducing saved losses."""
    differences = np.asarray(differences)
    s, w, n = differences.shape
    random = np.random.default_rng(193017)
    boot = np.empty(4000)
    for start in range(0, 4000, 100):
        seed_draws = random.integers(s, size=(100, s, 1, 1))
        row_draws = random.integers(n, size=(100, s, w, n))
        selected = differences[seed_draws, np.arange(w)[None, None, :, None], row_draws]
        boot[start:start + 100] = np.sum(selected, axis=(1, 2, 3)) / (s * w * n)
    return {'mean_difference': float(differences.mean()),
            'interval95': np.quantile(boot, [.025, .975]).tolist(),
            'per_seed_mean': differences.mean((1, 2)).tolist(), 'replicates': 4000}


freeze = load_json(RUN / 'FREEZE.json')
protocol = load_json(PROJECT / 'experiments/analytic_event_neuron/round2/PROTOCOL.json')
prepared = load_json(PREPARED / 'PREPARED.json')
results = load_json(CONFIRM / 'RESULTS.json')
brief = load_json(CONFIRM / 'BRIEF.json')
verification = load_json(CONFIRM / 'FREEZE_VERIFICATION.json')
registration = protocol['retention']
seeds, laws = registration['seeds'], registration['windows']
epsilon = registration['epsilon']
input_paths = {str(PROJECT / name): digest for name, digest in freeze['sources_sha256'].items()}
input_paths.update({str(RUN / name): digest for name, digest in freeze['artifacts_sha256'].items()})
input_paths[str(RUN / 'FREEZE.json')] = sha(RUN / 'FREEZE.json')
for path in sorted(CONFIRM.iterdir()):
    if path.is_file():
        input_paths[str(path)] = sha(path)
for name, digest in input_paths.items():
    check('input_integrity_before', sha(name) == digest, name)
equal('registration', registration, prepared['registration'], 'prepared registration')
equal('registration', registration, results['registration'], 'confirmation registration')
check('registration', seeds == [101, 211, 307, 401, 503] and len(laws) == 12
      and tuple(registration['arms']) == ARMS and epsilon == .02
      and registration['old_nll_margin'] == .02 and registration['new_nll_improvement_min'] == .005,
      'five seeds, twelve windows, nine arms and original numeric gates')
check('freeze_binding', sha(CONFIRM / 'RESULTS.json') == verification['results_sha256']
      == brief['derived_from_results_sha256'], 'results identity')
check('freeze_binding', sha(RUN / 'FREEZE.json') == verification['freeze_sha256']
      and freeze['source_commit'] == verification['source_commit'] == brief['source_commit'],
      'parent source freeze identity')
check('freeze_binding', len(freeze['sources_sha256']) == verification['sources_verified'] == 56
      and len(freeze['artifacts_sha256']) == verification['artifacts_verified'] == 194,
      'complete frozen input counts')
check('freeze_binding', sha(PREPARED / 'PREPARED.json') == results['prepared_sha256'], 'prepared identity')
check('freeze_binding', freeze['protocol_sha256'] == sha(
    PROJECT / 'experiments/analytic_event_neuron/round2/PROTOCOL.json'), 'protocol identity')
check('freeze_binding', not freeze['confirmation_generated_before_freeze']
      and not prepared['holdouts_constructed'], 'frozen declaration of prospective confirmation')

training_ids, training_seeds = set(), set()
for parent in (RUN / 'training', RUN / 'feedback_training', PREPARED):
    for path in sorted(parent.glob('seed_*/*.npz')):
        if any(word in path.name for word in ('TRAIN', 'DEVELOPMENT')):
            data = load_npz(path)
            training_ids.update(data['ids'].tolist())
            training_seeds.add(data['seed'])

old_ids, new_ids, holdout_seeds = set(), set(), set()
recomputed_records, case_hashes, old_anchor_arrays = {}, {}, {}
costs = {arm: {'wall_ns': 0, 'parent_cpu_ns': 0} for arm in ARMS}
maxima = {name: 0.0 for name in (
    'protected_gaussian_increase', 'protected_event_increase', 'protected_bound',
    'quantized_gaussian_increase', 'quantized_event_increase', 'quantized_bound',
    'integer_event_increase', 'integer_event_bound', 'protected_classical_moment_gap',
    'quantized_classical_moment_gap', 'quantized_classical_count_gap')}
shift_differences = {arm: [] for arm in ('protected', 'protected_quantized')}
final_differences = {arm: [] for arm in shift_differences}
native_valid = native_total = score_forecasts = 0
minimum_probability = 1.0
for seed in seeds:
    old = load_npz(CONFIRM / f'seed_{seed}_OLD.npz')
    expected_seed = registration['seed_offset'] + 2000000 + seed
    check('holdout_identity', old['seed'] == expected_seed and old['split'] == 'retention_old_confirmation'
          and old['law'] == 'gaussian' and len(old['ids']) == registration['old_holdout_rows'],
          ('old', seed))
    equal('holdout_identity', old['ids'], [f'retention_old_confirmation:gaussian:{expected_seed}:{i}'
          for i in range(registration['old_holdout_rows'])], ('old ids', seed))
    check('holdout_disjoint', not (old_ids & set(old['ids'])), ('unique old', seed))
    old_ids.update(old['ids'].tolist())
    holdout_seeds.add(old['seed'])
    previous = None
    seed_shift = {arm: [] for arm in shift_differences}
    for window, law in enumerate(laws):
        prefix = f'seed_{seed}_window_{window:02d}'
        record = load_json(CONFIRM / (prefix + '.json'))
        checkpoint_path = PREPARED / f'seed_{seed}/window_{window:02d}_CHECKPOINT.json'
        checkpoint = load_json(checkpoint_path)
        checkpoint_hash = sha(checkpoint_path)
        equal('causal_chain', (record['seed'], record['window'], record['law_for_scoring_only']),
              (seed, window, law), prefix)
        check('causal_chain', record['checkpoint_sha256'] == checkpoint_hash
              and checkpoint['previous_checkpoint_sha256'] == previous
              and not checkpoint['holdout_used'] and not record['holdouts_fit_or_select_model'], prefix)
        check('causal_chain', freeze['artifacts_sha256'][checkpoint_path.relative_to(RUN).as_posix()]
              == checkpoint_hash == prepared['artifacts_sha256'][checkpoint_path.relative_to(PREPARED).as_posix()],
              ('checkpoint binding', prefix))
        receipts = [r for r in prepared['checkpoint_receipts'] if r['seed'] == seed and r['window'] == window]
        check('causal_chain', len(receipts) == 1 and receipts[0]['checkpoint_sha256'] == checkpoint_hash
              and all(value == 0 for value in receipts[0]['reload_max_absolute_errors'].values())
              and all(receipts[0]['optimizer_success'].values()), ('reload receipt', prefix))
        training = load_npz(PREPARED / f'seed_{seed}/window_{window:02d}_TRAIN.npz')
        check('causal_chain', data_digest(training) == checkpoint['training_dataset_sha256'], ('train identity', prefix))
        previous = checkpoint_hash
        new = load_npz(CONFIRM / (prefix + '_NEW.npz'))
        expected_seed = registration['seed_offset'] + 3000000 + 1000 * seed + window
        check('holdout_identity', new['seed'] == expected_seed and new['law'] == law
              and new['split'] == 'retention_new_confirmation'
              and len(new['ids']) == registration['new_holdout_rows'], ('new', prefix))
        equal('holdout_identity', new['ids'], [f'retention_new_confirmation:{law}:{expected_seed}:{i}'
              for i in range(registration['new_holdout_rows'])], ('new ids', prefix))
        check('holdout_disjoint', not (new_ids & set(new['ids'])), ('unique new', prefix))
        new_ids.update(new['ids'].tolist())
        holdout_seeds.add(new['seed'])
        archive = load_npz(CONFIRM / (prefix + '_SCORES.npz'))
        summaries = {arm: {} for arm in ARMS}
        rescored = {}
        for domain, data in (('old', old), ('new', new)):
            target = data['future'][:, [1, 2, 4]]
            labels = np.where(target <= -.6, 0, np.where(target > .6, 2, 1))
            arrays = {arm: {key.split('__', 2)[2]: value for key, value in archive.items()
                           if key.startswith(f'{arm}__{domain}__')} for arm in ARMS}
            baseline = arrays['frozen']
            if domain == 'old':
                if window == 0:
                    old_anchor_arrays[seed] = {k: baseline[k].copy() for k in ('mean', 'variance', 'targets', 'ids')}
                for name, initial in old_anchor_arrays[seed].items():
                    equal('old_holdout_reuse', baseline[name], initial, (prefix, name))
            anchor_ll = public_dense_loglikelihood(checkpoint['models']['frozen'], data)
            adaptive_ll = public_dense_loglikelihood(checkpoint['models']['online'], data)
            weight_reference = expit(adaptive_ll - anchor_ll)
            rescored[domain] = {}
            for arm in ARMS:
                saved = arrays[arm]
                at = (seed, window, domain, arm)
                mean, variance = saved['mean'], saved['variance']
                check('forecast_domain', mean.shape == variance.shape == target.shape == (256, 3)
                      and np.isfinite(mean).all() and np.isfinite(variance).all() and np.all(variance > 0), at)
                equal('raw_alignment', saved['ids'], data['ids'], at)
                equal('raw_alignment', saved['targets'], target, at)
                equal('raw_alignment', saved['labels'], labels, at)
                probability, logp = event_reference(mean, variance)
                minimum_probability = min(minimum_probability, float(probability.min()))
                gaussian = .5 * (np.log(2 * np.pi * variance) + (target - mean) ** 2 / variance)
                event = -np.take_along_axis(logp, labels[..., None], axis=-1)[..., 0]
                squared_error = (target - mean) ** 2
                coverage = (np.abs(target - mean) <= 1.959963984540054 * np.sqrt(variance)).mean(1)
                close('gaussian_loss', saved['gaussian_nll_by_horizon'], gaussian, at)
                close('event_loss', saved['event_nll_by_horizon'], event, at)
                close('cdf_reference', saved['probabilities'], probability, at, atol=4e-15)
                for metric, actual in (('gaussian_nll', gaussian.mean(1)), ('event_nll', event.mean(1)),
                                      ('mse', squared_error.mean(1)), ('coverage95', coverage)):
                    close('trajectory_aggregation', saved[metric], actual, (*at, metric))
                summary = {'gaussian_nll': float(gaussian.mean()), 'event_nll': float(event.mean()),
                           'mse': float(squared_error.mean()), 'coverage95': float(coverage.mean()),
                           'classwise_ece': ece_reference(probability, labels)}
                rescored[domain][arm] = {'gaussian': gaussian, 'event': event, 'probability': probability,
                                        'logp': logp, 'mean': mean, 'variance': variance}
                if 'adaptive_weight' in saved:
                    expected_weight = np.full(256, .5) if arm == 'fixed_mixture' else weight_reference
                    close('public_routing', saved['adaptive_weight'], expected_weight, at, atol=8e-13)
                    w = saved['adaptive_weight'][:, None]
                    m0, v0 = baseline['mean'], baseline['variance']
                    m1, v1 = arrays['online']['mean'], arrays['online']['variance']
                    proposal = m0 + w * (m1 - m0)
                    if arm in ('fixed_mixture', 'likelihood_mixture'):
                        close('mixture_moments', mean, proposal, at)
                        close('mixture_moments', variance,
                              (1 - w) * v0 + w * v1 + w * (1 - w) * (m1 - m0) ** 2, at)
                        g0 = rescored[domain]['frozen']['gaussian']
                        g1 = rescored[domain]['online']['gaussian']
                        e0 = rescored[domain]['frozen']['event']
                        e1 = rescored[domain]['online']['event']
                        exact = -np.logaddexp(np.log1p(-w) - g0, np.log(w) - g1)
                        exact_event = -np.logaddexp(np.log1p(-w) - e0, np.log(w) - e1)
                        close('exact_mixture_loss', saved['exact_mixture_nll'], exact.mean(1), at)
                        close('exact_mixture_loss', saved['exact_mixture_event_nll'], exact_event.mean(1), at)
                    else:
                        bound = supremum_nll(m0, v0, mean, variance)
                        close('density_certificate', saved['bound_by_horizon'], bound, at, atol=5e-12)
                        close('density_certificate', saved['correction_by_horizon'], (mean - m0) / np.sqrt(v0), at)
                        check('density_bound', bool(np.all(bound <= epsilon + 1e-12)), at)
                        g_increase = gaussian - rescored[domain]['frozen']['gaussian']
                        e_increase = event - rescored[domain]['frozen']['event']
                        check('observed_envelope', bool(np.all(g_increase <= bound + 1e-11)), at)
                        check('observed_envelope', bool(np.all(e_increase <= bound + 1e-11)), at)
                        quantified = arm.startswith('protected_quantized')
                        if not quantified:
                            correction = np.clip((proposal - m0) / np.sqrt(v0), -epsilon, epsilon)
                            close('parameter_guard_algebra', mean, m0 + np.sqrt(v0) * correction, at)
                            close('parameter_guard_algebra', variance, v0 * (1 + np.abs(correction)), at)
                        else:
                            delta = np.clip(proposal - m0, -.5 * epsilon * np.sqrt(v0), .5 * epsilon * np.sqrt(v0))
                            mq = np.rint((m0 + delta) * Q).astype(np.int64)
                            vq = np.maximum(np.ceil(v0 * (1 + np.abs((mq / Q - m0) / np.sqrt(v0))) * Q),
                                            np.ceil(v0 * Q)).astype(np.int64)
                            equal('q24_parameters', saved['mean_q24'], mq, at)
                            equal('q24_parameters', saved['variance_q24'], vq, at)
                            equal('q24_parameters', mean * Q, mq, at)
                            equal('q24_parameters', variance * Q, vq, at)
                            mask = (np.abs(mean) <= 8) & (variance <= 8) & (variance >= 1 / Q)
                            equal('native_domain', saved['native_typed_domain_mask'], mask, at)
                            if arm == 'protected_quantized':
                                native_total += mask.size
                                native_valid += int(mask.sum())
                            counts, floors = saved['q24_event_probability_counts'], saved['q24_minimum_counts']
                            check('q24_mass', np.issubdtype(counts.dtype, np.integer)
                                  and np.all(counts >= floors) and np.all(counts > 0)
                                  and np.all(counts.sum(-1) == Q), at)
                            p0 = rescored[domain]['frozen']['probability']
                            lp0 = rescored[domain]['frozen']['logp']
                            expected_floor = np.maximum(1, np.ceil(Q * p0 * math.exp(-epsilon))).astype(np.int64)
                            equal('q24_floor', floors, expected_floor, at)
                            delivered = counts / Q
                            delivered_logp = np.log(delivered)
                            qnll = -np.take_along_axis(delivered_logp, labels[..., None], axis=-1)[..., 0]
                            all_excess = lp0 - delivered_logp
                            certificate = all_excess.max(-1)
                            check('q24_event_bound', bool(np.all(all_excess <= epsilon + 1e-12)), at)
                            close('q24_event_certificate', saved['q24_event_certificate_max_excess'], certificate, at)
                            close('q24_event_loss', saved['q24_event_nll_by_horizon'], qnll, at)
                            close('q24_event_loss', saved['q24_event_nll'], qnll.mean(1), at)
                            candidate = saved['probabilities'] / saved['probabilities'].sum(-1, keepdims=True)
                            close('q24_projection', saved['q24_projection_squared_error'],
                                  ((delivered - candidate) ** 2).sum(-1), at, atol=1e-25, rtol=2e-10)
                            residual = counts - Q * candidate
                            donor = np.max(np.where(counts > floors, residual, -np.inf), axis=-1)
                            recipient = np.min(residual, axis=-1)
                            check('q24_integer_optimality', bool(np.all(donor - recipient <= 1 + 1e-8)), at)
                            summary.update(q24_event_nll=float(qnll.mean()),
                                           q24_classwise_ece=ece_reference(delivered, labels))
                            if arm == 'protected_quantized':
                                maxima['integer_event_bound'] = max(maxima['integer_event_bound'], float(certificate.max()))
                                maxima['integer_event_increase'] = max(maxima['integer_event_increase'],
                                    float((qnll - rescored[domain]['frozen']['event']).max()))
                        if arm in ('protected', 'protected_quantized'):
                            stem = 'quantized' if quantified else 'protected'
                            maxima[stem + '_gaussian_increase'] = max(maxima[stem + '_gaussian_increase'], float(g_increase.max()))
                            maxima[stem + '_event_increase'] = max(maxima[stem + '_event_increase'], float(e_increase.max()))
                            maxima[stem + '_bound'] = max(maxima[stem + '_bound'], float(bound.max()))
                for metric, value in summary.items():
                    close('record_summary', record['scores'][arm][domain][metric], value, (*at, metric))
                summaries[arm][domain] = summary
                score_forecasts += mean.size
            for arm, control, stem in (('protected', 'protected_classical', 'protected'),
                                       ('protected_quantized', 'protected_quantized_classical', 'quantized')):
                gap = max(float(np.max(np.abs(arrays[arm][key] - arrays[control][key]))) for key in ('mean', 'variance'))
                maxima[stem + '_classical_moment_gap'] = max(maxima[stem + '_classical_moment_gap'], gap)
                check('classical_equivalence', gap <= 4e-14, (prefix, domain, arm))
                if stem == 'quantized':
                    gap_q = int(np.max(np.abs(arrays[arm]['q24_event_probability_counts']
                                               - arrays[control]['q24_event_probability_counts'])))
                    maxima['quantized_classical_count_gap'] = max(maxima['quantized_classical_count_gap'], gap_q)
                    check('classical_equivalence', gap_q == 0, (prefix, domain, 'q24 counts'))
        for arm in ARMS:
            degradation = float((rescored['old'][arm]['gaussian'] - rescored['old']['frozen']['gaussian']).mean())
            close('old_degradation', record['scores'][arm]['old_nll_degradation_from_initial'], degradation, (prefix, arm))
            summaries[arm]['old_nll_degradation'] = degradation
            for key in ('wall_ns', 'parent_cpu_ns'):
                value = record['evaluation_cost'][arm][key]
                check('cost_receipts', isinstance(value, int) and value > 0, (prefix, arm, key))
                costs[arm][key] += value
        recomputed_records[(seed, window)] = summaries
        case_hashes[prefix] = {'checkpoint_sha256': checkpoint_hash,
                               'record_sha256': sha(CONFIRM / (prefix + '.json')),
                               'scores_sha256': sha(CONFIRM / (prefix + '_SCORES.npz')),
                               'new_sha256': sha(CONFIRM / (prefix + '_NEW.npz'))}
        for arm in shift_differences:
            difference = (rescored['new'][arm]['gaussian'] - rescored['new']['frozen']['gaussian']).mean(1)
            if law == 'drift_shift':
                seed_shift[arm].append(difference)
            if window == len(laws) - 1:
                final_differences[arm].append(difference)
    for arm in shift_differences:
        shift_differences[arm].append(seed_shift[arm])

check('holdout_disjoint', not ((old_ids | new_ids) & training_ids)
      and not (old_ids & new_ids) and not (holdout_seeds & training_seeds), 'all held-out IDs and seeds')
check('holdout_disjoint', len(old_ids) == 1280 and len(new_ids) == 15360 and len(holdout_seeds) == 65,
      'recurrent old cohort is 1280 unique trajectories, not 15360 independent old examples')
check('coverage', len(recomputed_records) == 60 and score_forecasts == 829440,
      '60 windows, 9 models, 2 domains, 256 trajectories, 3 dependent horizons')

windows, aggregate = [], {}
for window, law in enumerate(laws):
    arms = {}
    for arm in ARMS:
        arms[arm] = {'old_nll_degradation': float(np.mean([
            recomputed_records[(seed, window)][arm]['old_nll_degradation'] for seed in seeds]))}
        for domain in ('old', 'new'):
            metrics = recomputed_records[(seeds[0], window)][arm][domain]
            arms[arm][domain] = {metric: float(np.mean([
                recomputed_records[(seed, window)][arm][domain][metric] for seed in seeds])) for metric in metrics}
            for metric, value in arms[arm][domain].items():
                close('window_aggregation', results['windows'][window]['arms'][arm][domain][metric], value,
                      (window, arm, domain, metric))
        close('window_aggregation', results['windows'][window]['arms'][arm]['old_nll_degradation'],
              arms[arm]['old_nll_degradation'], (window, arm, 'old degradation'))
    equal('window_aggregation', (results['windows'][window]['window'], results['windows'][window]['law']),
          (window, law), 'window identity')
    windows.append({'window': window, 'law': law, 'arms': arms})

gates = {}
for arm, reported in (('protected', results), ('protected_quantized', results['quantized_protection'])):
    contrast = bootstrap_reference(shift_differences[arm])
    expected_contrast = reported['protected_shift_window_nll_contrast' if arm == 'protected'
                                 else 'shift_window_nll_contrast']
    for key, value in contrast.items():
        close('registered_bootstrap', expected_contrast[key], value, (arm, key), atol=3e-13)
    worst = max(row['arms'][arm]['old_nll_degradation'] for row in windows)
    final = float(np.mean(final_differences[arm]))
    original = worst <= registration['old_nll_margin'] and final <= 0
    efficacy = (contrast['mean_difference'] <= -registration['new_nll_improvement_min']
                and contrast['interval95'][1] < 0 and all(x < 0 for x in contrast['per_seed_mean']))
    check('registered_gates', original == reported['passes_original_bounded_retention_gate']
          and efficacy == reported['passes_additional_shift_efficacy_gate'], arm)
    close('registered_gates', reported['protected_worst_window_old_nll_degradation' if arm == 'protected'
                                     else 'worst_window_old_nll_degradation'], worst, (arm, 'worst'))
    close('registered_gates', reported['protected_final_new_nll_difference_from_frozen' if arm == 'protected'
                                     else 'final_new_nll_difference_from_frozen'], final, (arm, 'final'))
    gates[arm] = {'worst_window_old_nll_degradation': worst, 'final_new_nll_difference': final,
                  'shift_contrast': contrast, 'original_bounded_retention_pass': bool(original),
                  'separate_shift_efficacy_pass': bool(efficacy)}

for arm in ARMS:
    summary = {'worst_old_gaussian_nll_degradation': max(row['arms'][arm]['old_nll_degradation'] for row in windows),
               'cost': costs[arm]}
    for law in ('gaussian', 'drift_shift'):
        selected = [row['arms'][arm]['new'] for row in windows if row['law'] == law]
        metrics = {key: float(np.mean([row[key] for row in selected])) for key in selected[0]}
        summary[law] = metrics
        summary[law]['nominal_95_coverage_shortfall'] = .95 - metrics['coverage95']
        brief_key = 'mean_gaussian_new' if law == 'gaussian' else 'mean_shift_new'
        for metric, value in brief['arms'][arm][brief_key].items():
            close('brief_aggregation', value, metrics[metric], (arm, law, metric))
    close('brief_aggregation', brief['arms'][arm]['worst_old_gaussian_nll_degradation'],
          summary['worst_old_gaussian_nll_degradation'], (arm, 'worst old'))
    equal('brief_aggregation', brief['arms'][arm]['scoring_wall_ns'], costs[arm]['wall_ns'], (arm, 'wall'))
    equal('brief_aggregation', brief['arms'][arm]['scoring_parent_cpu_ns'], costs[arm]['parent_cpu_ns'], (arm, 'cpu'))
    aggregate[arm] = summary

qreported = results['quantized_protection']
for key, expected in (
        ('max_observed_pointwise_gaussian_nll_increase', maxima['protected_gaussian_increase']),
        ('max_observed_pointwise_event_nll_increase', maxima['protected_event_increase']),
        ('protected_classical_max_moment_difference', maxima['protected_classical_moment_gap'])):
    close('reported_extrema', results[key], expected, key)
for key, expected in (
        ('max_observed_pointwise_gaussian_nll_increase', maxima['quantized_gaussian_increase']),
        ('max_observed_pointwise_event_nll_increase', maxima['quantized_event_increase']),
        ('max_certified_pointwise_nll_bound', maxima['quantized_bound']),
        ('classical_max_moment_difference', maxima['quantized_classical_moment_gap'])):
    close('reported_extrema', qreported[key], expected, key)
for key, expected in (('max_observed_event_nll_increase', maxima['integer_event_increase']),
                      ('max_certified_event_nll_increase', maxima['integer_event_bound'])):
    close('reported_extrema', qreported['anchor_constrained_event_q24'][key], expected, key)
check('reported_extrema', native_valid == native_total == 92160
      == qreported['native_typed_domain_valid_forecasts'] == qreported['native_typed_domain_checked_forecasts'],
      'native domain count, not native execution')
check('scope', not qreported['native_execution_performed_in_this_study']
      and not qreported['native_unconstrained_probability_q24_inherits_event_nll_bound']
      and not qreported['anchor_constrained_event_q24']['gaussian_nll_gate_replaced']
      and not results['population_long_term_guarantee'] and not results['holdout_tuning']
      and not results['hidden_regime_routing'], 'explicit nonpromotion and distinct probability scope')
check('reported_counts', results['trained_optimizations'] == 120 and results['real_checkpoint_reload_count'] == 60
      and results['all_optimizers_success'] is True, 'completed before confirmation')
total_cost = {key: sum(row[key] for row in costs.values()) for key in ('wall_ns', 'parent_cpu_ns')}
for key in ('wall_ns', 'parent_cpu_ns'):
    check('cost_aggregation', results['evaluation_' + key] >= total_cost[key] > 0, key)
    equal('cost_aggregation', results['evaluation_' + key], brief['evaluation_' + key], key)
    equal('cost_aggregation', prepared['preparation_' + key], brief['preparation_' + key], key)

for name, digest in input_paths.items():
    check('input_integrity_after', sha(name) == digest, name)
report = {
    'schema': 'hepta.analytic-event.retention-confirmation-independent-review.v1',
    'passed': not ERRORS, 'total_checks': sum(CHECKS.values()), 'checks': dict(CHECKS), 'failures': ERRORS,
    'verification_only': True, 'optimizer_calls': 0, 'generated_trajectories': 0,
    'experiment_inference_or_evaluation_calls': 0, 'frozen_source_model_protocol_edits': 0,
    'methods': ['Gaussian scores independently computed from stored means, variances and targets',
                'Erf/erfc probability branches independent of production event_log_probs',
                'Dense Gaussian public-observation likelihood independently verifies saved routing weights',
                'Long-double actual-parameter density supremum checks saved certificates',
                'Integer mass, floors, per-event bounds and separable-convex exchange optimality checked',
                'Stored per-trajectory losses independently bootstrap with the frozen random seed'],
    'source_commit': freeze['source_commit'], 'freeze_sha256': sha(RUN / 'FREEZE.json'),
    'results_sha256': sha(CONFIRM / 'RESULTS.json'), 'protocol_sha256': freeze['protocol_sha256'],
    'source_count': len(freeze['sources_sha256']), 'frozen_artifact_count': len(freeze['artifacts_sha256']),
    'input_sha256_before_and_after': input_paths, 'case_artifact_identities': case_hashes,
    'unique_old_holdout_trajectories': len(old_ids), 'unique_new_holdout_trajectories': len(new_ids),
    'held_out_dataset_seeds': sorted(holdout_seeds), 'independent_training_seeds': len(seeds),
    'windows_per_seed': len(laws), 'model_domain_trajectory_rows': score_forecasts // 3,
    'dependent_horizon_forecasts': score_forecasts, 'minimum_reference_event_probability': minimum_probability,
    'max_recomputation_errors': MAX_ERRORS, 'certificates_and_equivalence': maxima,
    'recomputed_registered_gates': gates, 'arms': aggregate,
    'calibration_interpretation': {
        'nominal_gaussian_interval_coverage': .95, 'calibration_pass_claim': False,
        'no_registered_retention_ece_cutoff_added_after_confirmation': True,
        'protected_shift_coverage': aggregate['protected']['drift_shift']['coverage95'],
        'protected_quantized_shift_coverage': aggregate['protected_quantized']['drift_shift']['coverage95'],
        'finding': 'Both protected arms substantially under-cover on shifted data; density protection does not repair calibration.'},
    'classical_equivalence_interpretation': 'Classical controls match protected moments to floating-point precision; no new function class or superiority over that equivalent calculation is shown.',
    'costs': {'preparation_wall_ns': prepared['preparation_wall_ns'],
              'preparation_parent_cpu_ns': prepared['preparation_parent_cpu_ns'],
              'evaluation_wall_ns': results['evaluation_wall_ns'],
              'evaluation_parent_cpu_ns': results['evaluation_parent_cpu_ns'],
              'summed_arm_scoring': total_cost,
              'outer_timing_includes_checkpoint_readback_and_raw_persistence': True,
              'publication_compression_included': False, 'shared_host_not_hardware_benchmark': True,
              'native_execution_in_retention_study': False},
    'limitations': ['Hash receipts establish consistency with the published freeze, not an independent trusted clock.',
                    'Old holdouts recur across twelve windows; there are five training replicates, not sixty independent training runs.',
                    'Intervals are descriptive seed/trajectory bootstrap intervals and are not population or infinite-horizon guarantees.',
                    'Two protected heads use an extra frozen anchor; protection is not an event-only readout guarantee.',
                    'The post-native categorical projection is a separate adapter and its retention scores do not certify an original native owner output.',
                    'This audit verifies saved outputs and metrics; no models are refitted, no confirmation dataset regenerated, and no native runtime rerun.'],
    'review_script_sha256': sha(__file__), 'review_elapsed_ns': time.perf_counter_ns() - STARTED,
}
OUTPUT.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n')
print(json.dumps({'passed': report['passed'], 'checks': report['total_checks'], 'failures': ERRORS,
                  'report': str(OUTPUT), 'sha256': sha(OUTPUT)}, indent=2))
raise SystemExit(0 if report['passed'] else 1)
