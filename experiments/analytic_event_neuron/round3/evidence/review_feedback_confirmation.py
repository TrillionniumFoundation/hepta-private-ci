"""Independent report-only verification of immutable paid-feedback confirmations.

Run as a module with --run-dir and optional --seed. --aggregate requires all
five completed independent scope reports plus the frozen scientific summary.
This program never imports scientific calculations or executes native ticks.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import itertools
import json
import math
from pathlib import Path
import time
import traceback

import numpy as np
from scipy.integrate import quad

from . import review_feedback_evidence as e

CONTRASTS = (('event', 'gaussian'), ('analytic', 'numeric'), ('analytic', 'gaussian'),
             ('analytic', 'history'), ('analytic', 'zero'), ('analytic', 'reset'),
             ('event', 'quantized'), ('gaussian', 'probit'))
LEARNED = ('numeric', 'analytic', 'history', 'zero', 'reset')
SOURCES = (Path(__file__), Path(e.__file__))


def feature(stage, arm, model, case, sequence, review):
    public = stage['public']
    if arm not in LEARNED:
        review.require(stage['feature'] is None and stage['native'] == [], 'feature', 'reference path')
        return None
    precision = sum(1 / x for x in public['variances'])
    observed = sum(x / v for x, v in zip(public['residuals'], public['variances'])) / precision
    raw = [observed, math.log(1 / precision), math.log(public['repair_cost'])]
    z = (np.asarray(raw) - model['calibration']['public_center']) / model['calibration']['public_scale']
    if arm == 'history':
        powers = [p for p in itertools.product(range(4), repeat=3) if sum(p) <= 3]
        vector = [float(np.prod(z ** p)) for p in powers]
        vector.extend(np.exp(-.5 * np.sum((model['calibration']['history_centers'] - z) ** 2, axis=1)))
        review.require(stage['native'] == [], 'feature', 'history baseline does not call sparse ticks')
    else:
        p = stage['law']['probabilities']
        drives = np.tanh(z / 3) if arm == 'numeric' else [p[2] - p[0], 2 * p[1] - 1, math.tanh(z[2] / 3)]
        if arm == 'zero':
            drives = [0.0] * 3
        review.require(len(stage['native']) == 3, 'sparse', 'three matched-width channels')
        vector = []
        for channel, drive in enumerate(drives):
            saved = stage['native'][channel]
            count = round(float(drive) * e.Q)
            review.require(saved['case'] == case + f'/stage{sequence}/channel{channel}' and saved['channel'] == channel
                and saved['public_sha256'] == e.digest(public) and saved['drive_q24'] == count
                and saved['native_binary_sha256'] == model['native_binary_sha256'], 'sparse', 'public drive, case and frozen binary')
            review.require(saved['original_sparse_tick_calls'] == 2 and len(saved['ticks']) == 2
                and saved['checkpoint_reset_intervention'] == (arm == 'reset') and saved['authority'] == 'DENY_ALL'
                and not saved['native_owner_integration'], 'sparse', 'paired-call ablation metadata')
            first_drive = [max(-count, 0), max(count, 0), e.Q // 4] + [0] * 7
            for j, tick in enumerate(saved['ticks']):
                predecessor = e.ZERO if j == 0 or arm == 'reset' else saved['ticks'][0]['checkpoint_after']
                review.require(tick['drive_q24'] == (first_drive if j == 0 else [0] * 10)
                    and tick['stage'] == j and tick['logical_clock_micros'] == j + 1
                    and tick['sequence'] == (1 if arm == 'reset' else j + 1) and tick['checkpoint_before'] == predecessor,
                    'sparse', 'actual input and reset/state ancestry')
                review.require(tick['authority'] == 'DENY_ALL' and tick['requires_calibration'] and not tick['native_owner_integration']
                    and tick['checkpoint_bounded_bytes'] == 648 and tick['native_ns'] > 0, 'sparse', 'experimental native receipt')
                review.require(all(len(tick[k]) == 10 and all(type(x) is int for x in tick[k]) for k in
                    ('drive_q24', 'activation_q24', 'eligibility_q24', 'threshold_q24')), 'sparse', 'bounded integer state')
            last = saved['ticks'][1]
            current = [v / e.Q for key in ('activation_q24', 'eligibility_q24') for v in last[key]]
            review.close(saved['features'], current, 'feature', 'native readout exact', 0)
            vector.extend([1.0] + current)
    review.require(len(vector) == len(model['heads'][arm]['weights']) == 63, 'fairness', 'matched 63-dimensional learned head')
    review.close(stage['feature'], vector, 'feature', 'independent feature assembly')
    return vector


def scope_review(root, seed, review):
    root = Path(root)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    frozen = e.verify_freeze(root, review)
    protocol = e.read_json(e.PROJECT / 'PROTOCOL.json')['feedback']
    index = e.read_json(root / 'FEEDBACK_INDEX.json')
    entries = [s for s in index['scopes'] if s['seed'] == seed]
    review.require(len(entries) == 1 and index['source_commit'] == frozen['source_commit'], 'identity', 'one completed indexed scope')
    entry = entries[0]
    scope = root / 'feedback_confirmation' / f'seed_{seed}'
    expected_files = {str(p.relative_to(root)) for p in scope.iterdir() if p.is_file()}
    review.require(expected_files == set(entry['files_sha256']), 'identity', 'exact completed scope inventory')
    for name, expected in entry['files_sha256'].items():
        review.require(e.file_hash(root / name) == expected, 'identity', 'immutable indexed artifact ' + name)
    model_path = root / 'feedback_prepared' / f'seed_{seed}' / 'MODELS.json'
    model = e.read_json(model_path)
    summary, audit = [e.read_json(scope / name) for name in ('SUMMARY.json', 'AUDIT.json')]
    review.require(e.file_hash(model_path) == summary['model_file_sha256'] == frozen['artifacts_sha256'][str(model_path.relative_to(root))]
        and summary['model_sha256'] == e.digest(model) and summary['seed'] == seed, 'identity', 'frozen fitted model')
    review.require(audit['passed'] and audit['dataset_split'] == 'confirmation' and not summary['development_only']
        and audit['source_sha256'] == frozen['sources_sha256'][str((e.PROJECT / 'feedback_audit.py').relative_to(e.REPO))], 'identity', 'completed frozen native audit')
    data, public = e.arrays(scope / 'DATA.npz'), e.arrays(scope / 'PUBLIC.npz')
    required = {'initial_output', 'self_evaluation', 'wait_evaluation', 'sensor_variance', 'wait_variance',
                'repair_cost', 'wait_cost', 'ids', 'seed', 'split', 'law'}
    review.require(set(public) == required and set(data) == required | {'target'}, 'privacy', 'exact target-free worker schema')
    for key in public:
        review.close(public[key], data[key], 'privacy', 'worker copy ' + key, 0)
    count, data_seed = protocol['confirmation_rows'], protocol['data_offset'] + 100 * seed + 3
    ids = [f'feedback3:confirmation:{data_seed}:{i}' for i in range(count)]
    review.require(data['ids'].tolist() == ids and data['seed'] == data_seed and data['split'] == 'confirmation'
        and data['law'] == 'gaussian_error_paid_independent_sensor_v3', 'coverage', 'complete registered unique trajectories')
    review.require(summary['policy_process_separate_from_target_generator_and_scorer'] and not summary['policy_worker_private_target_schema']
        and not summary['hostile_process_or_filesystem_access_control_claimed'] and summary['all_final_readbacks_before_scoring'],
        'privacy', 'process separation, no adversarial ACL claim')
    with gzip.open(scope / 'ROWS.json.gz', 'rt') as stream:
        rows = json.load(stream)
    with gzip.open(scope / 'EXECUTION.json.gz', 'rt') as stream:
        execution = json.load(stream)
    private_fields = {'target', 'squared_error', 'score_started_ns', 'utility', 'terminal_error'}
    review.require(len(rows) == len(execution['rows']) == count * len(e.ARMS), 'coverage', 'all execution rows retained')
    for row, before in zip(rows, execution['rows']):
        review.require(not private_fields.intersection(before) and {k: v for k, v in row.items() if k not in private_fields} == before,
                       'privacy', 'post-delivery fields only added by scorer')
    for key, value in execution.items():
        if key != 'rows':
            review.require(summary[key] == value, 'identity', 'worker summary unchanged ' + key)
    del execution
    transport = e.archive_index(scope / 'readbacks.tar.gz', summary['readbacks'], review, 'readbacks', True)
    owners = e.archive_index(scope / 'owners.tar.gz', summary['owners'], review, 'owners')
    replay = e.archive_index(scope / 'audit_native.tar.gz', audit['native_replay_archive'], review, 'audit_native')
    receipts, used, seen, subjects = transport['receipts'], set(), set(), set()
    locations = {case: i for i, case in enumerate(ids)}
    by_key, typed, sparse, native_ns, quadratures = {}, 0, 0, 0, 0
    for row in rows:
        case, arm = row['case'], row['arm']
        review.require(case in locations and arm in e.ARMS and (case, arm) not in seen, 'coverage', 'unique complete episode')
        seen.add((case, arm)); by_key[case, arm] = row
        i = locations[case]
        def read(kind, stage):
            key = (case, arm, kind, stage)
            review.require(key in receipts and key not in used, 'transport', 'one acquired operation')
            used.add(key)
            return receipts[key]
        _, initial = read('delivery', 'initial')
        _, sensor = read('observation', 'sensor')
        terms = {key: read('observation', key)[1] for key in ('sensor_variance', 'repair_cost', 'wait_variance', 'wait_cost')}
        observation, residual = read('delivery', 'residual')
        evalues = [float(data[k][i]) for k in ('initial_output', 'self_evaluation', 'sensor_variance', 'repair_cost', 'wait_variance', 'wait_cost')]
        review.close([initial, sensor, *terms.values()], evalues, 'readback', 'actual public dataset values', 0)
        review.close(residual, sensor - initial, 'readback', 'delivered residual', 0)
        public_history = {'initial': initial, 'residuals': [residual], 'variances': [terms.pop('sensor_variance')], **terms}
        previous, owned, cost, expected_actions = None, [], 0.0, []
        for stage_number, stage in enumerate(row['stages']):
            if stage_number:
                _, sensor2 = read('observation', 'wait_sensor')
                observation, residual2 = read('delivery', 'wait_residual')
                review.close([sensor2, residual2], [data['wait_evaluation'][i], data['wait_evaluation'][i] - initial], 'readback', 'paid public observation', 0)
                public_history = {**public_history, 'residuals': [residual, residual2],
                                  'variances': [public_history['variances'][0], public_history['wait_variance']]}
            review.require(stage['public'] == public_history and set(public_history) == {'initial', 'residuals', 'variances', 'repair_cost', 'wait_cost', 'wait_variance'},
                           'privacy', 'only actually acquired public context')
            review.require(observation['readback_ns'] <= stage['decision_ns'], 'chronology', 'acquisition before decision')
            mean, variance = e.posterior(model['calibration'], public_history)
            if arm in ('gaussian', 'probit'):
                review.require(stage['runtime'] is None and not stage['law']['native_quantized'], 'runtime', 'continuous reference')
                review.close([stage['law']['mean'], stage['law']['variance']], [mean, variance], 'posterior', 'Gaussian/probit shared conditional')
                cut = math.sqrt(public_history['repair_cost'])
                review.close(stage['law']['probabilities'], e.probability(mean, variance, -cut, cut), 'cdf', 'continuous terminal probabilities', 3e-15)
            else:
                current = stage['runtime']
                law = e.runtime_receipt(current, [case, arm], model, previous, review,
                                        'direct_quantization' if arm == 'quantized' else 'error_feedback')
                review.require(stage['law'] == law, 'runtime', 'policy uses receiver law')
                previous = current; owned.append(current); typed += 1
                native_ns += current['native']['subprocess_roundtrip_ns']
            vector = feature(stage, arm, model, case, stage_number, review)
            sparse += 2 * len(stage['native'])
            native_ns += sum(n['subprocess_roundtrip_ns'] for n in stage['native'])
            mean, variance = stage['law']['mean'], stage['law']['variance']
            amount = round(mean * e.Q) / e.Q
            repair = 2 * amount * mean - amount * amount - public_history['repair_cost']
            wait = e.wait_value(mean, variance, public_history['repair_cost'], model['calibration']['noise_scale'] * public_history['wait_variance'], public_history['wait_cost'])
            review.close([stage['values'][k] for k in ('repair_amount', 'repair_gain', 'wait_gain')], [amount, repair, wait], 'action_value', 'conditional expected values')
            if arm == 'gaussian' and stage_number == 0 and quadratures < 12:
                spread = math.sqrt(variance * variance / (variance + model['calibration']['noise_scale'] * public_history['wait_variance']))
                cut = math.sqrt(public_history['repair_cost'])
                payoff = lambda z: (((mean + spread * z) ** 2 - cut * cut) * math.exp(-z * z / 2) / math.sqrt(2 * math.pi))
                reference = quad(payoff, -np.inf, (-cut - mean) / spread, epsabs=1e-12)[0] + quad(payoff, (cut - mean) / spread, np.inf, epsabs=1e-12)[0] - public_history['wait_cost']
                review.close(wait, reference, 'quadrature', 'independent positive-square integration', 2e-10)
                quadratures += 1
            repair_score = repair if vector is None else float(np.dot(vector, model['heads'][arm]['weights'])) + model['heads'][arm]['offset']
            scores = {'stop': 0.0, 'repair': repair_score}
            if stage_number == 0:
                scores['wait'] = wait
            review.require(set(stage['scores']) == set(scores), 'choice', 'legal action set')
            for key in scores:
                review.close(stage['scores'][key], scores[key], 'action_score', key)
            action = max(scores, key=scores.get)
            review.require(stage['action'] == action, 'choice', 'frozen policy/tie order')
            expected_actions.append(action)
            cost += public_history['wait_cost'] if action == 'wait' else public_history['repair_cost'] if action == 'repair' else 0
        review.require(row['actions'] == expected_actions and len(row['stages']) == (2 if expected_actions[0] == 'wait' else 1)
                       and expected_actions[-1] in ('repair', 'stop'), 'choice', 'legal complete action sequence')
        if owned:
            subject = e.owner_state(owners, owned, review); subjects.add(subject)
            for name in ('state.journal', 'anchor.witness'):
                review.require(owners['hashes'][owners['prefix'] + subject + '/native/' + name]
                               == replay['hashes'][replay['prefix'] + subject + '/' + name], 'native_replay', 'original versus prior complete native replay bytes')
        delivered_receipt, delivered = read('delivery', 'final')
        review.close(delivered, initial + (amount if expected_actions[-1] == 'repair' else 0), 'delivery', 'actual chosen repaired output', 0)
        target = float(data['target'][i])
        expected = {'target': target, 'delivered': delivered, 'cost': cost, 'squared_error': (delivered - target) ** 2,
                    'utility': 1 - (delivered - target) ** 2 - cost, 'terminal_error': target - initial}
        for key, value in expected.items():
            review.close(row[key], value, 'scoring', key, 0)
        review.require(delivered_receipt['action'] == '/'.join(expected_actions) and stage['decision_ns'] <= delivered_receipt['began_ns']
            <= delivered_receipt['readback_ns'] <= row['final_readback_ns'] < row['score_started_ns'] and row['wall_ns'] > 0,
            'chronology', 'actual final readback strictly before target scoring')
        review.require(row['model_sha256'] == e.digest(model), 'identity', 'all decisions frozen model')
    review.require(used == set(receipts) and len(seen) == count * len(e.ARMS), 'coverage', 'all rows and transport operations')
    owner_subjects = {name.split('/')[1] for name in owners['hashes'] if name.endswith('/state.json')}
    replay_subjects = {name.split('/')[1] for name in replay['hashes'] if name.endswith('/state.journal')}
    review.require(subjects == owner_subjects == replay_subjects and len(subjects) == count * 7, 'coverage', 'all native owners')
    review.require(typed == audit['typed_ticks_replayed'] and sparse == audit['sparse_ticks_replayed']
        and typed + sparse == summary['native_ticks'] == audit['replay_cost']['native_ticks']
        and typed + sparse // 2 == summary['native_requests'] == audit['replay_cost']['native_requests']
        and native_ns == summary['native_roundtrip_ns'], 'accounting', 'exhaustive actual native request/tick/IPC totals')
    for case in ids:
        reference = by_key[case, 'gaussian']
        for arm in e.ARMS:
            row = by_key[case, arm]
            review.require(row['stages'][0]['public'] == reference['stages'][0]['public'], 'fairness', 'all arms same initial acquired information')
        for a, b in (('gaussian', 'probit'), ('event', 'quantized'), ('analytic', 'numeric')):
            x, y = by_key[case, a], by_key[case, b]
            for s, t in zip(x['stages'], y['stages']):
                review.require(s['public'] == t['public'], 'fairness', 'same acquired information at shared stage')
                review.close([s['law']['mean'], s['law']['variance'], *s['law']['probabilities']],
                             [t['law']['mean'], t['law']['variance'], *t['law']['probabilities']], 'fairness_law', a + '/' + b, 3e-15)
            if (a, b) != ('analytic', 'numeric'):
                review.require(x['actions'] == y['actions'], 'fairness', a + '/' + b + ' exact actions')
                review.close([x['delivered'], x['cost'], x['utility']], [y['delivered'], y['cost'], y['utility']], 'fairness', 'matched outcomes', 0)
    ids = sorted(ids)
    derived = {'ids': np.asarray(ids), 'arms': np.asarray(e.ARMS)}
    metrics = ('utility', 'squared_error', 'cost', 'wall_ns', 'delivered')
    for key in metrics:
        derived[key] = np.array([[by_key[case, arm][key] for case in ids] for arm in e.ARMS])
    derived['actions'] = np.array([['/'.join(by_key[case, arm]['actions']) for case in ids] for arm in e.ARMS])
    derived['probabilities'] = np.array([[by_key[case, arm]['stages'][0]['law']['probabilities'] for case in ids] for arm in e.ARMS])
    labels, covered, events, bytecounts = [], [], [], []
    for arm in e.ARMS:
        arm_labels, arm_covered, arm_events, arm_bytes = [], [], [], []
        selected = [by_key[case, arm] for case in ids]
        for row in selected:
            s = row['stages'][0]; error = row['terminal_error']
            lower, upper = (-math.sqrt(s['public']['repair_cost']), math.sqrt(s['public']['repair_cost'])) if s['runtime'] is None else s['runtime']['native']['head']['parameters_q24_decoded'][2:]
            arm_labels.append(0 if error <= lower else 2 if error > upper else 1)
            arm_covered.append(abs(error - s['law']['mean']) <= 1.959963984540054 * math.sqrt(s['law']['variance']))
            arm_events.append(sum(t['runtime']['logical_unit_events'] for t in row['stages'] if t['runtime']))
            arm_bytes.append(sum(t['runtime']['packet_bytes'] for t in row['stages'] if t['runtime']))
        labels.append(arm_labels); covered.append(arm_covered); events.append(arm_events); bytecounts.append(arm_bytes)
        for key in ('utility', 'squared_error', 'cost', 'wall_ns'):
            review.close(summary['summary'][arm][key], np.mean([r[key] for r in selected]), 'summary', arm + '/' + key)
        review.require(summary['summary'][arm]['episodes'] == count and summary['summary'][arm]['waits'] == sum('wait' in r['actions'] for r in selected)
            and summary['summary'][arm]['repairs'] == sum('repair' in r['actions'] for r in selected), 'summary', 'actual action counts')
    derived.update(labels=np.array(labels), coverage=np.array(covered), logical_unit_events=np.array(events), packet_bytes=np.array(bytecounts))
    zero_mass = {arm: {'initial_forecasts_with_any_zero_probability': int(np.any(derived['probabilities'][j] == 0, axis=1).sum()),
        'zero_probabilities_by_category': np.sum(derived['probabilities'][j] == 0, axis=0).tolist(),
        'true_event_zero_probability_count': int(np.sum(derived['probabilities'][j, np.arange(count), derived['labels'][j]] == 0))} for j, arm in enumerate(e.ARMS)}
    e.verify_freeze(root, review)
    output = root / 'reviews' / f'FEEDBACK_INDEPENDENT_{seed}.npz'
    with output.open('xb') as stream:
        np.savez_compressed(stream, **derived)
    return {'schema': 'hepta.round3.independent-feedback-review.v1', 'passed': True, 'seed': seed,
        'source_commit': frozen['source_commit'], 'freeze_sha256': e.file_hash(root / 'FREEZE.json'),
        'indexed_files_sha256': entry['files_sha256'], 'reviewer_sha256': {p.name: e.file_hash(p) for p in SOURCES},
        'checks': dict(review.counts), 'total_checks': sum(review.counts.values()), 'maximum_absolute_errors': review.maximum,
        'independent_trajectories': count, 'control_executions': len(rows), 'initial_terminal_zero_mass': zero_mass,
        'all_archive_members_verified': sum(len(x['hashes']) for x in (transport, owners, replay)),
        'all_delivery_pngs_decoded': summary['readbacks']['deliveries'], 'all_native_calls_recomputed_by_this_review': False,
        'native_replay_performed_by_frozen_author_audit': {'typed_ticks': typed, 'sparse_ticks': sparse},
        'native_journal_and_anchor_original_vs_author_replay_bytes_exact': True,
        'independent_quadrature_references': quadratures,
        'actual_cost': {'native_requests': typed + sparse // 2, 'native_ticks': typed + sparse, 'native_roundtrip_ns': native_ns,
                        'evaluation_wall_ns': summary['wall_ns'], 'evaluation_cpu_ns': summary['cpu_ns'],
                        'audit_wall_ns': audit['wall_ns'], 'audit_native_roundtrip_ns': audit['replay_cost']['native_roundtrip_ns']},
        'derived_arrays': str(output.relative_to(root)), 'derived_arrays_sha256': e.file_hash(output),
        'scope_limits': ['No new native execution; opaque Rust state equations rely on prior complete frozen audit replay plus exact durable-byte equality.',
                         'Target-free worker payload and policy histories verified; no adversarial process/filesystem access control claim.',
                         'Terminal remaining-error probabilities; neither first passage nor repair-gain probabilities.',
                         'Q24 zero categories may exist even when all realized NLLs are finite; no anchored density-retention guarantee.',
                         'Action cost is the registered task penalty, not wall time or currency.'],
        'wall_ns': time.perf_counter_ns() - started, 'cpu_ns': time.process_time_ns() - cpu}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--seed', type=int, required=True)
    args = parser.parse_args()
    root = Path(args.run_dir); (root / 'reviews').mkdir(exist_ok=True)
    review = e.Review()
    try:
        report = scope_review(root, args.seed, review)
    except Exception:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        path = root / 'reviews' / f'FEEDBACK_REVIEW_FAILURE_{args.seed}_{stamp}.json'
        e.write_new(path, {'passed': False, 'seed': args.seed, 'traceback': traceback.format_exc(),
            'checks': dict(review.counts), 'maximum_absolute_errors': review.maximum,
            'reviewer_sha256': {p.name: e.file_hash(p) for p in SOURCES}, 'scientific_files_modified': False})
        raise
    path = root / 'reviews' / f'FEEDBACK_INDEPENDENT_{args.seed}.json'
    e.write_new(path, report)
    print(json.dumps({'report': str(path), 'sha256': e.file_hash(path), 'checks': report['total_checks'],
                      'seed': args.seed, 'passed': True, 'wall_seconds': report['wall_ns'] / 1e9}, sort_keys=True), flush=True)


if __name__ == '__main__':
    main()
