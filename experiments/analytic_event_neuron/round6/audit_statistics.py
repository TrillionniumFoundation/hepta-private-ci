"""Independent final statistical reconstruction from completed actual rows.

No primary summary/statistics implementation is imported. The bootstrap keeps
the registered random stream but aggregates trajectory multiplicities and
computes percentile interpolation independently. Coverage uses erfc and
bisection, separately from the primary ndtr/Brent implementation.
"""

from collections import Counter
from functools import lru_cache
import math
from pathlib import Path

import numpy as np

from .audit_confirmation import compressed_rows, document
from .audit_transport import file_sha


def average(values):
    return math.fsum(float(x) for x in values) / len(values)


def percentile(values, fraction):
    ordered = sorted(float(x) for x in values)
    location = fraction * (len(ordered) - 1)
    lower = math.floor(location)
    if lower == len(ordered) - 1:
        return ordered[lower]
    return ordered[lower] + (location - lower) * (ordered[lower + 1] - ordered[lower])


def bootstrap(matrix, replicates, seed, alpha):
    values = np.asarray(matrix, dtype=float)
    clusters, cases = values.shape
    rng, sampled = np.random.default_rng(seed), []
    for start in range(0, replicates, 200):
        count = min(200, replicates - start)
        # Preserve the declared draw sequence for exact reproducibility, while
        # rebuilding each replicate from sample multiplicities independently.
        selected_clusters = rng.integers(clusters, size=(count, clusters, 1))
        selected_cases = rng.integers(cases, size=(count, clusters, cases))
        for replicate in range(count):
            totals = []
            for slot in range(clusters):
                frequency = np.bincount(selected_cases[replicate, slot], minlength=cases)
                selected = values[int(selected_clusters[replicate, slot, 0])]
                totals.append(float(selected @ frequency))
            sampled.append(math.fsum(totals) / (clusters * cases))
    return {'mean_difference': average(values.ravel()),
            'interval': [percentile(sampled, alpha / 2), percentile(sampled, 1 - alpha / 2)],
            'per_seed_mean_difference': [average(row) for row in values],
            'training_seed_count': clusters, 'trajectories_per_seed': cases,
            'replicates': replicates, 'interval_alpha': alpha,
            'method': 'paired two-stage seed/whole-trajectory percentile bootstrap'}


@lru_cache(maxsize=32768)
def coverage_interval(weights, means, variances):
    standard = [math.sqrt(v) for v in variances]
    bracket = min(m - 12 * s for m, s in zip(means, standard)), max(m + 12 * s for m, s in zip(means, standard))
    output = []
    for level in (.025, .975):
        lower, upper = bracket
        for _ in range(80):
            middle = (lower + upper) / 2
            cdf = math.fsum(w * .5 * math.erfc((m - middle) / (s * math.sqrt(2)))
                            for w, m, s in zip(weights, means, standard))
            if cdf < level:
                lower = middle
            else:
                upper = middle
        output.append((lower + upper) / 2)
    return output


def calibration(rows, registration):
    probabilities, labels, covered, released_nll, physical_nll, brier = [], [], [], [], [], []
    maximum_native, maximum_release = 0.0, 0.0
    for row in rows:
        stage = row['stages'][0]
        received = stage['runtime']['law']
        error = row['target'] - stage['public']['initial']
        cutoff = math.sqrt(stage['public']['repair_cost'])
        label = 0 if error <= -cutoff else (2 if error > cutoff else 1)
        p = received['probabilities']
        probabilities.append(p)
        labels.append(label)
        released_nll.append(-math.log(p[label]))
        physical_nll.append(-received['physical_log_probabilities'][label])
        brier.append(math.fsum((value - int(category == label)) ** 2 for category, value in enumerate(p)))
        law = received['conditional_law']
        lower, upper = coverage_interval(*(tuple(law[key]) for key in ('weights', 'means', 'variances')))
        covered.append(lower <= error <= upper)
        maximum_native = max(maximum_native, received['native_vs_reference_max_absolute_error'])
        maximum_release = max(maximum_release, max(abs(p1 - p2) for p1, p2 in zip(p, received['native_mixture_probabilities'])))
    bins, errors = [], []
    n = len(rows)
    for event in range(3):
        error = 0.0
        for bin_index in range(10):
            indices = [index for index, p in enumerate(probabilities) if min(int(p[event] * 10), 9) == bin_index]
            count = len(indices)
            probability = average([probabilities[i][event] for i in indices]) if count else None
            frequency = sum(labels[i] == event for i in indices) / count if count else None
            if count:
                error += abs(probability - frequency) * count / n
            bins.append({'event': event, 'bin': bin_index, 'count': count,
                         'mean_probability': probability, 'frequency': frequency})
        errors.append(error)
    result = {'classwise_ece': average(errors), 'event_ece': errors, 'bins': bins,
              'independent_sample_count': n, 'horizon_measurements_per_trajectory': 1,
              'interval_95_coverage': sum(covered) / n,
              'released_event_nll': average(released_nll), 'physical_event_nll': average(physical_nll),
              'brier': average(brier), 'maximum_native_cdf_absolute_error': maximum_native,
              'maximum_release_absolute_error': maximum_release,
              'category_labels_use_public_cost_cutoff': True, 'native_threshold_rounding_is_separate': True}
    result['ece_pass'] = result['classwise_ece'] <= registration['calibration']['maximum_ece']
    lower, upper = registration['calibration']['coverage_range']
    result['coverage_pass'] = lower <= result['interval_95_coverage'] <= upper
    result['calibration_pass'] = result['ece_pass'] and result['coverage_pass']
    return result


def compare_tree(actual, expected, checks, label='independent_summary'):
    if isinstance(expected, dict):
        checks.require(isinstance(actual, dict) and set(actual) == set(expected), label + ':fields')
        for key in expected:
            compare_tree(actual[key], expected[key], checks, label + '/' + key)
    elif isinstance(expected, list):
        checks.require(isinstance(actual, list) and len(actual) == len(expected), label + ':length')
        for index, value in enumerate(expected):
            compare_tree(actual[index], value, checks, label + f'/{index}')
    elif isinstance(expected, float):
        checks.close(actual, expected, label, max(3e-12, abs(expected) * 3e-15))
    else:
        checks.require(actual == expected, label + ':value')


def reconstruct(scopes, registration):
    seeds, domains, arms = (registration[key] for key in ('seeds', 'domains', 'arms'))
    result = {'domains': {}, 'primary': {}, 'codec_noninferiority': {}, 'secondary': {}, 'ood': {}, 'equivalence': {}}
    keys = ('utility', 'cost', 'squared_error', 'wall_ns', 'cpu_ns', 'packet_bytes',
            'native_requests', 'native_ticks', 'native_roundtrip_ns', 'evidence_archive_wall_ns')
    for domain in domains:
        result['domains'][domain] = {}
        for arm in arms:
            rows = [r for seed in seeds for r in scopes[seed, domain][arm]]
            metrics = {key: {'mean': average([r[key] for r in rows]),
                             'sum': math.fsum(r[key] for r in rows)} for key in keys}
            metrics['actions'] = dict(Counter('/'.join(r['actions']) for r in rows))
            metrics['calibration'] = calibration(rows, registration)
            metrics['per_seed_utility'] = [average([r['utility'] for r in scopes[seed, domain][arm]]) for seed in seeds]
            result['domains'][domain][arm] = metrics
    sequence = 0
    contrasts = [('primary', 'nominal', registration['primary_utility_comparisons'], .025),
                 ('codec_noninferiority', 'nominal', registration['codec_noninferiority'], .025),
                 ('secondary', 'nominal', registration['secondary_comparisons'], .05)]
    contrasts += [('ood', domain, registration['primary_utility_comparisons'], .05) for domain in domains[1:]]
    for category, domain, pairs, alpha in contrasts:
        for candidate, baseline in pairs:
            matrix = [[a['utility'] - b['utility'] for a, b in zip(scopes[seed, domain][candidate], scopes[seed, domain][baseline])]
                      for seed in seeds]
            item = bootstrap(matrix, registration['bootstrap_replicates'], registration['bootstrap_seed'] + sequence, alpha)
            sequence += 1
            item.update(candidate=candidate, baseline=baseline, domain=domain)
            if category == 'primary':
                item['passes_registered_superiority'] = (item['mean_difference'] >= registration['primary_minimum_mean_utility_gain']
                    and item['interval'][0] > 0 and min(item['per_seed_mean_difference']) > 0)
            elif category == 'codec_noninferiority':
                margin = registration['codec_noninferiority_margin']
                item['passes_noninferiority'] = item['interval'][0] > -margin and min(item['per_seed_mean_difference']) > -margin
            else:
                item['descriptive_only'] = True
            key = (domain + ':' if category == 'ood' else '') + candidate + '-' + baseline
            result[category][key] = item
    for candidate, baseline in (('event', 'direct'), ('gaussian', 'probit')):
        action_mismatches, coordinates, maximum_output, maximum_probability = 0, 0, 0.0, 0.0
        for seed in seeds:
            for domain in domains:
                for left, right in zip(scopes[seed, domain][candidate], scopes[seed, domain][baseline]):
                    action_mismatches += left['actions'] != right['actions']
                    maximum_output = max(maximum_output, abs(left['delivered'] - right['delivered']))
                    for a, b in zip(left['stages'], right['stages']):
                        x, y = a['runtime'], b['runtime']
                        maximum_probability = max(maximum_probability, max(abs(p - q) for p, q in zip(
                            x['law']['probabilities'], y['law']['probabilities'])))
                        coordinates += any(x['decoder'][key] != y['decoder'][key] for key in ('components', 'values', 'sequence', 'time'))
        tolerance = 0.0 if candidate == 'event' else registration['gaussian_probit_equivalence_tolerance']
        result['equivalence'][candidate + '-' + baseline] = {
            'action_mismatches': action_mismatches, 'maximum_output_error': maximum_output,
            'maximum_probability_error': maximum_probability, 'decoded_coordinate_mismatches': coordinates,
            'tolerance': tolerance, 'passes_equivalence': (action_mismatches == 0 and maximum_output <= tolerance
                and maximum_probability <= tolerance and (candidate != 'event' or coordinates == 0))}
    result['all_primary_gates_pass'] = all(item['passes_registered_superiority'] for item in result['primary'].values())
    result['analytic_nominal_calibration_pass'] = result['domains']['nominal']['analytic']['calibration']['calibration_pass']
    result['joint_research_gate_pass'] = result['all_primary_gates_pass'] and result['analytic_nominal_calibration_pass']
    return result


def audit_statistics(run_dir, expected_freeze, checks):
    root = Path(run_dir)
    registration = document(root / 'PREPARED.json')['registration']
    actual = document(root / 'RESULTS.json')
    scopes, identities = {}, {}
    for seed in registration['seeds']:
        for domain in registration['domains']:
            directory = root / 'confirmation' / f'seed_{seed}' / domain
            rows = compressed_rows(directory / 'ROWS.json.gz')
            scopes[seed, domain] = {arm: sorted((r for r in rows if r['arm'] == arm), key=lambda r: r['index'])
                                   for arm in registration['arms']}
            for arm in registration['arms']:
                checks.require([r['index'] for r in scopes[seed, domain][arm]]
                               == list(range(registration['confirmation_rows_per_seed_domain'])), 'independent complete statistical pairing')
            identities[str(directory.relative_to(root))] = {
                'run_completed_sha256': file_sha(directory / 'RUN_COMPLETED.json'),
                'summary_sha256': file_sha(directory / 'SUMMARY.json'),
                'rows_sha256': file_sha(directory / 'ROWS.json.gz'), 'data_sha256': file_sha(directory / 'DATA.npz')}
    checks.require(actual['freeze_sha256'] == expected_freeze and actual['production_promotion'] is False,
                   'statistical output binds frozen research scope')
    compare_tree(actual['scope_identities'], identities, checks, 'statistical input byte identities')
    n = len(registration['seeds']) * len(registration['domains']) * registration['confirmation_rows_per_seed_domain']
    checks.require(actual['independent_confirmation_trajectories'] == n
                   and actual['arm_executions'] == n * len(registration['arms']), 'independent statistical sample count')
    expected = reconstruct(scopes, registration)
    for key, value in expected.items():
        compare_tree(actual[key], value, checks, 'independent_results/' + key)
    return {'results_sha256': file_sha(root / 'RESULTS.json'),
            'independent_calibration_cells': len(registration['domains']) * len(registration['arms']),
            'independent_paired_bootstrap_contrasts': sum(len(expected[key]) for key in ('primary', 'codec_noninferiority', 'secondary', 'ood')),
            'bootstrap_replicates_per_contrast': registration['bootstrap_replicates'],
            'joint_research_gate_pass': expected['joint_research_gate_pass'],
            'statistical_values_independently_recomputed': True,
            'finite_sample_coverage_guarantee_claimed': False}
