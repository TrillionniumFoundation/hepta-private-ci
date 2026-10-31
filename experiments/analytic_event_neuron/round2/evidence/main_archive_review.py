"""Independent verification of saved main-confirmation archives, without inference."""

from collections import Counter
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
import struct
import tarfile

import numpy as np
from PIL import Image
from scipy.special import erf, erfc, erfcx


FIXED = {'always_stop': ['stop'], 'always_repair': ['repair'],
         'always_wait': ['wait', 'stop'], 'always_wait_repair': ['wait', 'repair']}
FIELDS = ('obs', 'times', 'mask', 'occupied', 'obs_var')


def bytes_sha(value):
    return hashlib.sha256(value).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class Checks:
    def __init__(self):
        self.counts, self.failures, self.maximum_errors = Counter(), [], {}

    def require(self, condition, group, detail):
        self.counts[group] += 1
        if not bool(condition):
            self.failures.append({'group': group, 'detail': detail})

    def close(self, actual, expected, group, detail, exact=False, atol=3e-11, rtol=3e-12):
        a, b = np.asarray(actual), np.asarray(expected)
        ok = a.shape == b.shape
        if a.dtype.kind in 'biufc' and b.dtype.kind in 'biufc':
            ok = ok and np.isfinite(a).all() and np.isfinite(b).all()
            error = float(np.max(np.abs(a.astype(float) - b.astype(float)), initial=0)) if ok else 1e300
            self.maximum_errors[group] = max(self.maximum_errors.get(group, 0.0), error)
            ok = ok and (np.array_equal(a, b) if exact else np.allclose(a, b, atol=atol, rtol=rtol))
        else:
            ok = ok and np.array_equal(a, b)
        self.require(ok, group, detail)

    def summary(self):
        return {'passed': not self.failures, 'checks': dict(self.counts), 'total_checks': sum(self.counts.values()),
                'failures': self.failures, 'maximum_absolute_errors': self.maximum_errors}


def load_npz_bytes(payload):
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        return {key: archive[key].item() if archive[key].ndim == 0 else archive[key]
                for key in archive.files}


def logical_data_sha(data):
    h = hashlib.sha256()
    for key in sorted(data):
        h.update(key.encode())
        value = data[key]
        h.update(value.tobytes() if isinstance(value, np.ndarray) else str(value).encode())
    return h.hexdigest()


def log_cdf_reference(z):
    """Scaled-complementary-error-function reference, independent of log_ndtr."""
    z = np.asarray(z)
    result = np.empty_like(z)
    left = z <= 0
    result[left] = -math.log(2) + np.log(erfcx(-z[left] / math.sqrt(2))) - .5 * z[left] ** 2
    result[~left] = np.log1p(-.5 * erfc(z[~left] / math.sqrt(2)))
    return result


def event_log_reference(mean, variance):
    lower, upper = (-.6 - mean) / np.sqrt(variance), (.6 - mean) / np.sqrt(variance)
    log_put, log_call = log_cdf_reference(lower), log_cdf_reference(-upper)
    neutral = np.empty_like(mean)
    left, right = upper <= 0, lower >= 0
    for mask, first, second in ((left, upper, lower), (right, -lower, -upper)):
        large, small = log_cdf_reference(first[mask]), log_cdf_reference(second[mask])
        neutral[mask] = large + np.log(-np.expm1(small - large))
    middle = ~(left | right)
    neutral[middle] = np.log(.5 * (erf(upper[middle] / math.sqrt(2)) - erf(lower[middle] / math.sqrt(2))))
    return np.stack((log_put, neutral, log_call), axis=-1)


def decode_png(payload):
    with Image.open(io.BytesIO(payload)) as picture:
        if (picture.format, picture.mode, picture.size) != ('PNG', 'L', (256, 32)):
            raise ValueError('Unexpected numeric PNG schema')
        pixels = np.array(picture)
    top = pixels[0, ::4]
    if not np.all((top == 0) | (top == 255)):
        raise ValueError('Nonbinary numeric PNG')
    pattern = np.repeat(top, 4)[None, :]
    if not np.all(pixels[:16] == pattern) or not np.all(pixels[16:] == 255 - pattern):
        raise ValueError('PNG replication or complement check failed')
    return struct.unpack('>d', np.packbits(top == 255, bitorder='big').tobytes())[0]


def histories(data, i):
    initial = {key: [0.0] * 8 for key in ('obs', 'times')}
    initial.update(mask=[False] * 8, occupied=[False] * 8, obs_var=[1.0] * 8)
    for key in ('obs', 'times', 'mask', 'obs_var'):
        initial[key][:6] = data[key][i].tolist()
    initial['occupied'][:6] = [True] * 6
    result = {'initial': initial}
    for stage, sensors in (('repair', ['repair']), ('wait', ['wait']), ('wait_repair', ['wait', 'wait_repair'])):
        h = {key: list(value) for key, value in initial.items()}
        for column, sensor in enumerate(sensors, 6):
            h['obs'][column] = float(data[sensor + '_observation'][i])
            h['times'][column] = float(data['times'][i, -1] + (sensor != 'repair'))
            h['obs_var'][column] = .64 if sensor == 'wait' else .04
            h['mask'][column] = h['occupied'][column] = True
        result[stage] = h
    return result


def review_scope(root, entry, protocol, freeze):
    check = Checks()
    scope = entry['scope']
    archive_path, analysis_path = root / entry['archive_path'], root / entry['analysis_path']
    check.require(file_sha(archive_path) == entry['archive']['sha256'], 'archive_hash', scope)
    check.require(file_sha(analysis_path) == entry['analysis_sha256'], 'analysis_hash', scope)
    check.require(archive_path.stat().st_size == entry['archive']['compressed_bytes'], 'archive_size', scope)
    content, hashes = {}, {}
    with tarfile.open(archive_path, 'r|gz') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            check.require(member.isfile() and not name.is_absolute() and '..' not in name.parts
                          and member.name not in content, 'archive_member', member.name)
            raw = archive.extractfile(member).read()
            check.require(len(raw) == member.size, 'archive_member', ('bytes', member.name))
            content[member.name], hashes[member.name] = raw, bytes_sha(raw)
    manifest = json.loads(content['ARCHIVE_MANIFEST.json'])
    check.require(manifest == {k: v for k, v in hashes.items() if k != 'ARCHIVE_MANIFEST.json'},
                  'archive_manifest', scope)
    check.require(len(content) == entry['archive']['file_count'], 'archive_manifest', 'member count')
    models, metadata, summary, execution, replay = [json.loads(content[name]) for name in (
        'MODELS.json', 'DATASET.json', 'SUMMARY.json', 'EXECUTION.json', 'AUDIT.json')]
    data = load_npz_bytes(content['DATA.npz'])
    analysis = load_npz_bytes(analysis_path.read_bytes())
    n = protocol['rows']['confirmation' if entry['law'] == 'gaussian' else 'each_mismatch']
    data_seed = protocol['data_offsets'][entry['law']] + entry['training_seed']
    check.require(n == 256 and data['seed'] == metadata['data_seed'] == entry['data_seed'] == data_seed
                  and data['split'] == 'confirmation' and data['law'] == entry['law'], 'dataset_identity', scope)
    check.require(metadata['npz_sha256'] == hashes['DATA.npz'] and metadata['dataset_digest'] == logical_data_sha(data),
                  'dataset_identity', 'data hashes')
    check.close(data['ids'], [f'confirmation:{entry["law"]}:{data_seed}:{i}' for i in range(n)],
                'dataset_identity', 'trajectory IDs', exact=True)
    model_path = f'training/seed_{entry["training_seed"]}/MODELS.json'
    check.require(hashes['MODELS.json'] == freeze['artifacts_sha256'][model_path]
                  == file_sha(root / model_path), 'frozen_models', scope)
    expected_models = {'analytic', 'equivalent_gaussian', 'event_direct', 'event_feedback', 'event_no_residual',
                       'fixed', 'history', 'mean_drive', 'native', 'oracle', 'pulse', 'pulse_no_reset'}
    check.require(set(models) == expected_models, 'arm_coverage', '12 frozen model arms')
    check.require(replay['passed'] and replay['offline_replay'] and replay['frozen_model_binding']
                  and replay['models'] == 12 and replay['trajectories'] == n
                  and replay['prediction_rows'] == n * 12 and replay['control_rows'] == n * 16
                  and replay['model_sha256'] == hashes['MODELS.json'], 'original_full_replay_receipt', scope)
    check.require(replay['audit_source_sha256'] == freeze['sources_sha256'][
        'experiments/analytic_event_neuron/round2/audit.py'], 'original_full_replay_receipt', 'frozen audit source')
    for name, digest in replay['evidence_sha256'].items():
        check.require(hashes[name] == digest, 'original_full_replay_receipt', name)
    predictions = [json.loads(line) for line in content['PREDICTION.jsonl'].splitlines()]
    controls = [json.loads(line) for line in content['CONTROL.jsonl'].splitlines()]
    prediction_map = {(row['case'], row['arm']): row for row in predictions}
    control_map = {(row['case'], row['arm']): row for row in controls}
    check.require(len(predictions) == len(prediction_map) == n * 12
                  and len(controls) == len(control_map) == n * 16, 'arm_coverage', 'unique raw rows')
    positions = {identity: i for i, identity in enumerate(data['ids'])}
    for row in predictions:
        case, arm = row['case'], row['arm']
        i = positions[case]
        mean, variance = np.asarray(row['mean']), np.asarray(row['variance'])
        target = data['future'][i, [1, 2, 4]]
        labels = np.where(target <= -.6, 0, np.where(target > .6, 2, 1))
        check.close(row['targets'], target, 'prediction_alignment', (case, arm), exact=True)
        check.close(row['labels'], labels, 'prediction_alignment', (case, arm), exact=True)
        check.require(row['law'] == entry['law'] and arm in models and np.all(variance > 0),
                      'prediction_alignment', (case, arm, 'domain'))
        logp = event_log_reference(mean, variance)
        probabilities = np.exp(logp)
        nll = -logp[np.arange(3), labels]
        brier = np.sum((probabilities - np.eye(3)[labels]) ** 2, axis=1)
        for name, value in (('probabilities', probabilities), ('nll', nll), ('brier', brier)):
            check.close(row[name], value, 'prediction_loss_reference', (case, arm, name), atol=5e-11)
    receipts, used = {}, set()
    expected_transport, delivery_count, observation_count = {'transport/TRANSPORT_RECEIPTS.jsonl'}, 0, 0
    for row in [json.loads(line) for line in content['transport/TRANSPORT_RECEIPTS.jsonl'].splitlines()]:
        identity = (row['case'], row['arm'], row['kind'], row['stage'])
        check.require(identity not in receipts and row['scope'] == scope and not row['private_target_supplied'],
                      'transport_receipt', identity)
        check.require(0 < row['began_ns'] <= row['written_ns'] <= row['readback_ns'], 'transport_chronology', identity)
        if row['kind'] == 'observation':
            observation_count += 1
            path = 'transport/' + row['path']
            expected_transport.add(path)
            payload = json.loads(content[path])
            check.require(hashes[path] == row['sha256']
                          and payload['schema'] == 'hepta.analytic-event.public-observation.v1', 'transport_payload', identity)
            value = payload['value']
        else:
            delivery_count += 1
            text_path, png_path = 'transport/' + row['text_path'], 'transport/' + row['image_path']
            expected_transport.update((text_path, png_path))
            check.require(row['kind'] == 'delivery' and hashes[text_path] == row['text_sha256']
                          and hashes[png_path] == row['image_sha256'], 'transport_payload', identity)
            value = decode_png(content[png_path])
            check.require(struct.pack('>d', value) == struct.pack('>d', float(content[text_path]))
                          == struct.pack('>d', row['prediction']), 'all_png_bit_replay', identity)
        receipts[identity] = (row, value)
    check.require(expected_transport == {name for name in content if name.startswith('transport/')},
                  'transport_coverage', 'all transport members')
    check.require(delivery_count == 2 * n * 16 == execution['actual_transport']['deliveries']
                  and observation_count == execution['actual_transport']['observations']
                  and len(receipts) == replay['transport_receipts'], 'transport_coverage', 'all receipt counts')
    check.require(execution['actual_transport']['files'] == len(expected_transport) - 1
                  and execution['actual_transport']['receipt_sha256'] == hashes['transport/TRANSPORT_RECEIPTS.jsonl'],
                  'transport_coverage', 'execution receipt binding')
    for row in controls:
        case, arm = row['case'], row['arm']
        i, history = positions[case], histories(data, positions[case])
        name = 'analytic' if arm in FIXED else arm
        model = models[name]
        if model.get('known_law_reference_only'):
            model = {**model, 'parameters': [data['drift'], .18, 1.0]}
        check.require(row['model_sha256'] == bytes_sha(json.dumps(model, sort_keys=True).encode())
                      and row['actual_transport'] and row['law'] == entry['law'], 'control_model_binding', (case, arm))

        def receipt(kind, stage):
            identity = (case, arm, kind, stage)
            used.add(identity)
            return receipts[identity]

        initial_receipt, initial = receipt('observation', 'initial')
        terms_receipt, multiplier = receipt('observation', 'terms')
        preview_receipt, preview = receipt('delivery', 'initial')
        final_receipt, delivered = receipt('delivery', 'final')
        check.require(initial == row['initial_public_history'] == history['initial'], 'public_information', (case, arm, 'initial'))
        check.close(multiplier, data['cost_multiplier'][i], 'public_terms', (case, arm), exact=True)
        check.require(row['public_terms'] == {'cost_multiplier': multiplier, 'base_wait_cost': .07, 'base_repair_cost': .12},
                      'public_terms', (case, arm, 'rates'))
        check.close([row['initial_prediction'], row['delivered_prediction'], row['proposed_final_prediction']],
                    [preview, delivered, delivered], 'delivery_parity', (case, arm), exact=True)
        check.close(preview, prediction_map[(case, name)]['mean'][2], 'prediction_control_parity', (case, arm), atol=5e-12)
        timeline = [initial_receipt['readback_ns'], row['initial_observation_ns'], terms_receipt['began_ns'],
                    terms_receipt['readback_ns'], row['terms_readback_ns'], preview_receipt['began_ns'],
                    preview_receipt['readback_ns'], row['preview_readback_ns'], row['stages'][0]['decision_ns']]
        check.require(all(a <= b for a, b in zip(timeline, timeline[1:])), 'control_chronology', (case, arm, 'initial'))
        actions = row['actions']
        expected_final = {('stop',): 'initial', ('repair',): 'repair', ('wait', 'stop'): 'wait',
                          ('wait', 'repair'): 'wait_repair'}[tuple(actions)]
        sensor_names = {'initial': [], 'repair': ['repair'], 'wait': ['wait'], 'wait_repair': ['wait', 'wait_repair']}[expected_final]
        check.require(row['final_public_history'] == history[expected_final]
                      and [o['stage'] for o in row['observations']] == sensor_names
                      and len(row['stages']) == len(actions), 'public_information', (case, arm, 'acquired only'))
        policy = arm if arm in FIXED else 'variance_voi'
        check.require(row['policy_mode'] == policy, 'decision', (case, arm, 'policy'))
        if arm in FIXED:
            check.require(actions == FIXED[arm], 'original_fixed_policies', (case, arm))
        for step, decision in enumerate(row['stages']):
            at = (case, arm, step)
            stage, horizon = ('initial', 2.0) if step == 0 else ('wait', 1.0)
            diagnostic = decision['diagnostics']
            check.require(decision['stage'] == stage and decision['horizon'] == horizon
                          and decision['public_history'] == history[stage] and decision['policy_mode'] == policy,
                          'decision', at)
            check.close([diagnostic['planning_q'], diagnostic['planning_noise_scale'], diagnostic['cost_multiplier']],
                        [model['planning_q'], model['planning_noise_scale'], multiplier], 'decision_inputs', at)
            p, terminal, scale, q = [diagnostic[k] for k in ('current_variance', 'terminal_variance', 'planning_noise_scale', 'planning_q')]
            r = .04 * scale
            scores = {'stop': terminal, 'repair': max(0.0, terminal - p * p / (p + r)) + .12 * multiplier}
            if horizon == 2:
                propagated = p + q
                posterior = propagated * (.64 * scale) / (propagated + .64 * scale)
                future = max(0.0, terminal - (propagated - posterior))
                scores['wait'] = .07 * multiplier + min(future, max(0.0, future - posterior ** 2 / (posterior + r)) + .12 * multiplier)
            check.require(set(scores) == set(decision['expected_squared_error_plus_cost']), 'decision', (*at, 'legal choices'))
            for action, score in scores.items():
                check.close(decision['expected_squared_error_plus_cost'][action], score, 'decision_scores', (*at, action))
            chosen = FIXED[arm][step] if arm in FIXED else min(scores, key=scores.get)
            check.require(decision['selected'] == actions[step] == chosen, 'decision', (*at, 'selected'))
            check.close(decision['predicted_mean'], diagnostic['terminal_mean'], 'decision_inputs', (*at, 'mean'))
            if step == 0:
                check.close(diagnostic['terminal_mean'], prediction_map[(case, name)]['mean'][2], 'prediction_control_parity', at)
                check.close(diagnostic['terminal_variance'], prediction_map[(case, name)]['variance'][2], 'prediction_control_parity', at)
        for observation in row['observations']:
            sensor = observation['stage']
            sensor_receipt, value = receipt('observation', sensor)
            check.close([observation['value'], value], [data[sensor + '_observation'][i]] * 2,
                        'actual_feedback', (case, arm, sensor), exact=True)
            previous = row['stages'][1 if sensor == 'wait_repair' else 0]['decision_ns']
            following = row['stages'][1]['decision_ns'] if sensor == 'wait' else final_receipt['began_ns']
            check.require(previous <= sensor_receipt['began_ns'] <= sensor_receipt['readback_ns']
                          <= observation['readback_ns'] <= following, 'control_chronology', (case, arm, sensor))
        cost = multiplier * (.07 * ('wait' in actions) + .12 * ('repair' in actions))
        check.close(row['paid_cost'], cost, 'actual_cost', (case, arm))
        check.require([line['action'] for line in row['cost_items']] == [a for a in actions if a != 'stop'],
                      'actual_cost', (case, arm, 'ledger'))
        for line in row['cost_items']:
            base = .07 if line['action'] == 'wait' else .12
            check.close([line['base_cost'], line['multiplier'], line['paid_cost']], [base, multiplier, base * multiplier],
                        'actual_cost', (case, arm, 'ledger values'))
        target = data['future'][i, 4]
        square = (delivered - target) ** 2
        utility = 1 - square - cost
        check.close([row['terminal_target'], row['squared_error'], row['utility']], [target, square, utility],
                    'actual_utility', (case, arm))
        check.require(row['severe_loss'] == (utility < -2), 'actual_utility', (case, arm, 'tail loss'))
        check.require(row['stages'][-1]['decision_ns'] <= final_receipt['began_ns'] <= final_receipt['readback_ns']
                      <= row['final_readback_ns'] <= row['score_started_ns'], 'target_after_delivery', (case, arm))
        check.require(final_receipt['action'] == '/'.join(actions) and preview_receipt['action'] == 'preview',
                      'delivery_parity', (case, arm, 'bound action'))
        check.require(row['elapsed_ns'] > 0 and row['cpu_ns'] > 0
                      and row['elapsed_ns'] >= row['score_started_ns'] - initial_receipt['began_ns'],
                      'measured_cost', (case, arm))
    check.require(used == set(receipts), 'transport_coverage', 'every receipt causally used exactly by its owner')
    for arm in models:
        rows = sorted((r for r in predictions if r['arm'] == arm), key=lambda row: row['case'])
        check.close(analysis['prediction_ids__' + arm], [r['case'] for r in rows], 'analysis_alignment', arm, exact=True)
        expected = {'nll': [np.mean(r['nll']) for r in rows], 'brier': [np.mean(r['brier']) for r in rows],
                    'probabilities': [r['probabilities'] for r in rows], 'labels': [r['labels'] for r in rows],
                    'mse': [np.mean((np.asarray(r['mean']) - r['targets']) ** 2) for r in rows],
                    'standardized_error': [(np.asarray(r['targets']) - r['mean']) / np.sqrt(r['variance']) for r in rows]}
        for metric, value in expected.items():
            check.close(analysis[metric + '__' + arm], value, 'analysis_prediction_parity', (arm, metric), exact=True)
        for key, value in {'event_nll': np.mean(expected['nll']), 'brier': np.mean(expected['brier']), 'mse': np.mean(expected['mse']),
                           'accuracy': np.mean(np.argmax(expected['probabilities'], -1) == expected['labels'])}.items():
            check.close(summary['prediction'][arm][key], value, 'raw_summary', (arm, key))
    for arm in set(models) | set(FIXED):
        rows = sorted((r for r in controls if r['arm'] == arm), key=lambda row: row['case'])
        check.close(analysis['control_ids__' + arm], [r['case'] for r in rows], 'analysis_alignment', arm, exact=True)
        for metric in ('utility', 'paid_cost', 'elapsed_ns', 'cpu_ns', 'severe_loss', 'squared_error'):
            check.close(analysis[metric + '__' + arm], [r[metric] for r in rows], 'analysis_control_parity', (arm, metric), exact=True)
        actions = ['/'.join(row['actions']) for row in rows]
        check.close(analysis['actions__' + arm], actions, 'analysis_control_parity', (arm, 'actions'), exact=True)
        for key, value in {'mean_utility': np.mean([r['utility'] for r in rows]),
                           'mean_squared_error': np.mean([r['squared_error'] for r in rows]),
                           'mean_action_cost': np.mean([r['paid_cost'] for r in rows]),
                           'severe_loss_fraction': np.mean([r['severe_loss'] for r in rows]),
                           'wait_count': sum('wait' in r['actions'] for r in rows),
                           'repair_count': sum('repair' in r['actions'] for r in rows),
                           'wall_ns': sum(r['elapsed_ns'] for r in rows), 'cpu_ns': sum(r['cpu_ns'] for r in rows)}.items():
            check.close(summary['control'][arm][key], value, 'raw_summary', (arm, key))
        check.require(summary['control'][arm]['action_sequences'] == dict(Counter(actions)), 'raw_summary', (arm, 'action counts'))
    equivalence = {'direct_prediction_maximum_gap': 0.0, 'direct_control_maximum_gap': 0.0,
                   'no_residual_prediction_maximum_gap': 0.0, 'no_residual_changed_action_paths': 0,
                   'no_residual_changed_final_predictions': 0, 'gaussian_equivalent_prediction_maximum_gap': 0.0}
    for identity in data['ids']:
        event, direct, naive = [prediction_map[(identity, arm)] for arm in ('event_feedback', 'event_direct', 'event_no_residual')]
        for key in ('mean', 'variance', 'probabilities', 'nll', 'brier'):
            a, b, c = [np.asarray(row[key]) for row in (event, direct, naive)]
            gap, changed = float(np.max(abs(a - b))), float(np.max(abs(a - c)))
            equivalence['direct_prediction_maximum_gap'] = max(equivalence['direct_prediction_maximum_gap'], gap)
            equivalence['no_residual_prediction_maximum_gap'] = max(equivalence['no_residual_prediction_maximum_gap'], changed)
            check.require(np.array_equal(a, b), 'event_direct_equivalence', (identity, key))
        for key in ('mean', 'variance'):
            gap = float(np.max(abs(np.asarray(prediction_map[(identity, 'analytic')][key])
                                   - prediction_map[(identity, 'equivalent_gaussian')][key])))
            equivalence['gaussian_equivalent_prediction_maximum_gap'] = max(equivalence['gaussian_equivalent_prediction_maximum_gap'], gap)
        a, b, c = [control_map[(identity, arm)] for arm in ('event_feedback', 'event_direct', 'event_no_residual')]
        check.require(a['actions'] == b['actions'], 'event_direct_equivalence', (identity, 'actions'))
        for key in ('initial_prediction', 'delivered_prediction', 'proposed_final_prediction', 'paid_cost', 'utility', 'squared_error'):
            check.close(a[key], b[key], 'event_direct_equivalence', (identity, key), exact=True)
            equivalence['direct_control_maximum_gap'] = max(equivalence['direct_control_maximum_gap'], abs(a[key] - b[key]))
        for da, db in zip(a['stages'], b['stages']):
            check.require(da['diagnostics'] == db['diagnostics'] and da['expected_squared_error_plus_cost'] == db['expected_squared_error_plus_cost'],
                          'event_direct_equivalence', (identity, 'decision inputs'))
        equivalence['no_residual_changed_action_paths'] += int(a['actions'] != c['actions'])
        equivalence['no_residual_changed_final_predictions'] += int(a['delivered_prediction'] != c['delivered_prediction'])
    total_wall = sum(row['elapsed_ns'] for row in controls)
    check.require(execution['evaluation_wall_ns'] >= total_wall
                  and entry['scope_wall_ns_including_audit_and_archive'] >= execution['evaluation_wall_ns']
                  + replay['audit_elapsed_ns'] and execution['private_target_first_read_after_final_delivery'],
                  'cost_accounting', 'execution plus replay/archive')
    return {**check.summary(), 'scope': scope, 'training_seed': entry['training_seed'], 'law': entry['law'],
            'data_seed': data_seed, 'unique_trajectory_ids': data['ids'].tolist(),
            'archive_sha256': entry['archive']['sha256'], 'analysis_sha256': entry['analysis_sha256'],
            'archive_members': len(content), 'archive_manifest_sha256': hashes['ARCHIVE_MANIFEST.json'],
            'model_sha256': hashes['MODELS.json'], 'prediction_rows': len(predictions), 'control_rows': len(controls),
            'reviewed_all_png_deliveries': delivery_count, 'reviewed_all_observations': observation_count,
            'original_full_model_replay_receipt': replay, 'model_inference_replayed_by_this_review': False,
            'review_is_sampled': False, 'event_mechanism_checks': equivalence, 'execution': execution,
            'scope_wall_ns_including_audit_and_archive': entry['scope_wall_ns_including_audit_and_archive']}
