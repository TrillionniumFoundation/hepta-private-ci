"""Independent finite-record reader; never generates or fits a candidate.

The reviewed graph builder and original AST semantics are shared for source
alignment. Head arithmetic, dyadic radius, policy values, occupancy, selection,
restoration and record checks are implemented here. Original recursive task
execution supplies a separate semantic chain for the 80 sealed global policies.
"""
import argparse
import datetime as dt
from fractions import Fraction
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import signal
import struct
import time
import traceback

import numpy as np

from own_context import load as load_context
from value_graph import build as build_graph

HEADS = ('Q_1', 'B_1', 'B_2', 'G_1', 'G_2', 'T_256', 'T_1024')
FAMILIES = {'Q': HEADS[:1], 'B': HEADS[1:3], 'G': HEADS[3:5], 'T': HEADS[5:]}
DIAGNOSTICS = ('G_WITH_ORIGINAL_B', 'G_WITH_ORIGINAL_Q')
TERMINAL = (0, 4, 5)
ARRAY_TOLERANCE = 2e-12
METRIC_TOLERANCE = 2e-11
FITS = (11, 23, 37, 53, 71)
ARRAY_NAMES = ('scores', 'actions', 'values', 'occupancy', 'raw_gap')
COUNTS = dict(own_graphs=0, TRAIN_hidden_calls=0, TRAIN_hidden_rows=0,
              CONF_physical_represent_calls=0, CONF_complete_feature_rows=0,
              CONF_hidden_calls=0, CONF_hidden_rows=0, independent_policy_DPs=0,
              policy_record_aliases=0, policy_records_checked=0,
              score_calls=0, score_rows=0, original_recursive_worlds=0,
              original_recursive_visits=0, original_recursive_unique_features=0)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs_unique(pairs):
    answer = {}
    for key, value in pairs:
        require(key not in answer, 'duplicate JSON key')
        answer[key] = value
    return answer


def invalid_constant(value):
    raise ValueError('nonfinite JSON constant: ' + value)


def read_json(path):
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix == '.gz':
        raw = gzip.decompress(raw)
    return json.loads(raw, object_pairs_hook=pairs_unique, parse_constant=invalid_constant)


def verify_pin(pin):
    require(isinstance(pin, dict) and set(('path', 'bytes', 'sha256')) <= pin.keys(), 'incomplete pin')
    path = Path(pin['path'])
    require(path.is_absolute(), 'pin path must be explicit and absolute')
    require(type(pin['bytes']) is int and pin['bytes'] >= 0, 'invalid pin size')
    require(len(pin['sha256']) == 64 and set(pin['sha256']) <= set('0123456789abcdef'), 'invalid SHA')
    raw = path.read_bytes()
    require(len(raw) == pin['bytes'] and digest(raw) == pin['sha256'], 'pin changed: ' + str(path))
    return path


def read_pin(pin):
    return read_json(verify_pin(pin))


def iso(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(parsed.tzinfo is not None, 'timezone required')
    return parsed.astimezone(dt.timezone.utc)


def close_number(actual, expected, name, tolerance=METRIC_TOLERANCE):
    require(isinstance(actual, (int, float)) and not isinstance(actual, bool), name + ' numeric type')
    require(math.isfinite(float(actual)) and math.isfinite(float(expected)), name + ' finite')
    require(abs(float(actual) - float(expected)) <= tolerance * (1 + abs(float(expected))), name + ' differs')


def head_rows(model):
    n = model['network']
    w, b = np.asarray(n['w2'], dtype=np.float64), np.asarray(n['b2'], dtype=np.float64)
    require(w.shape == (4, 48) and b.shape == (4,), '196-coordinate shape')
    rows = np.empty((4, 49), dtype=np.float64)
    rows[:, :48], rows[:, 48] = w, b
    require(np.isfinite(rows).all(), 'finite readout')
    return rows


def readout_bytes(rows):
    values = rows[:, :48].reshape(-1).tolist() + rows[:, 48].tolist()
    return struct.pack('<196d', *values)


def units(value):
    numerator, denominator = float(value).as_integer_ratio()
    exponent = denominator.bit_length() - 1
    require(denominator == 1 << exponent and exponent <= 1074, 'not a finite F64 dyadic')
    return numerator << (1074 - exponent)


def radius_check(anchor, candidate):
    aa = [units(x) for x in anchor.flat]
    bb = [units(x) for x in candidate.flat]
    q_squared = sum(x * x for x in aa[:147])
    delta_squared = sum((b - a) ** 2 for a, b in zip(aa, bb))
    require(q_squared > 0 and 4 * delta_squared <= q_squared, 'exact shared radius violated')
    return {'anchor_q147_squared_units_hex': format(q_squared, 'x'),
            'delta_squared_units_hex': format(delta_squared, 'x'), 'within_shared_ball': True}


def model_check(entry, anchor, expected_family=None):
    model = read_pin(entry['model_pin'])
    family = entry['family']
    require(family in ('KEEP', 'Q', 'B', 'G', 'T', 'DIAGNOSTIC'), 'unknown model family')
    if expected_family is not None:
        require(family == expected_family, 'family binding')
    original, rows = head_rows(anchor), head_rows(model)
    require(entry['readout_sha256'] == digest(readout_bytes(rows)), 'export readout SHA')
    require(entry['canonical_model_sha256'] == digest(canonical(model).encode()), 'model canonical SHA')
    protected = json.loads(canonical(model))
    for name in ('w2', 'b2'):
        protected['network'][name] = anchor['network'][name]
    require(canonical(protected) == canonical(anchor), 'protected model fields changed')
    mask = entry['row_mask']
    expected_masks = {'KEEP': 0, 'Q': 7, 'B': 8, 'G': 15, 'T': 15}
    require(type(mask) is int and mask in (0, 7, 8, 15), 'unknown row mask')
    if family in expected_masks:
        require(mask == expected_masks[family], 'family row mask')
    for row in range(4):
        if not (mask & (1 << row)):
            require(rows[row].tobytes() == original[row].tobytes(), 'protected readout row changed')
    norm = radius_check(original, rows)
    for name, value in norm.items():
        require(entry['exact_norm'][name] == value, 'independent dyadic witness differs')
    if family == 'KEEP':
        require(readout_bytes(rows) == readout_bytes(original), 'KEEP changed')
    return model, rows


def independent_hidden(model, X):
    X = np.asarray(X, dtype=np.float64)
    w = np.asarray(model['network']['w1'], dtype=np.float64)
    b = np.asarray(model['network']['b1'], dtype=np.float64)
    require(X.ndim == 2 and X.shape[1] == 85 and w.shape == (48, 85) and b.shape == (48,), 'hidden shape')
    require(np.isfinite(X).all() and np.isfinite(w).all() and np.isfinite(b).all(), 'finite hidden input')
    H = np.ones((len(X), 49), dtype=np.float64)
    for j in range(48):
        H[:, j] = np.tanh(np.sum(X * w[j][None, :], axis=1) + b[j])
    return H


def independent_scores(rows, H):
    COUNTS['score_calls'] += 1
    COUNTS['score_rows'] += len(H)
    logits = np.empty((len(H), 4), dtype=np.float64)
    for j in range(4):
        logits[:, j] = np.sum(H * rows[j][None, :], axis=1)
    p = 1.0 / (1.0 + np.exp(-np.clip(logits[:, 3], -700, 700)))
    scores = np.zeros((len(H), 6), dtype=np.float64)
    scores[:, 1:4], scores[:, 4], scores[:, 5] = logits[:, :3], 1 - 2 * p, 2 * p - 1
    require(np.isfinite(scores).all(), 'finite independent scores')
    return scores


def scalar_policy(graph, scores, incumbent_occupancy=None):
    COUNTS['independent_policy_DPs'] += 1
    masks = np.asarray(graph['masks'], dtype=bool)
    count = len(masks)
    require(scores.shape == (count, 6), 'complete policy scores')
    action = []
    for i in range(count):
        legal = [a for a in range(6) if masks[i, a]]
        require(legal, 'no legal action')
        action.append(max(legal, key=lambda a: (float(scores[i, a]), -a)))
    order = sorted(range(count), key=lambda i: (graph['states'][i]['tick'], i))
    value, visit = [0.0] * count, [0.0] * count
    terminal = np.asarray(graph['terminal'], dtype=np.float64)
    for i in reversed(order):
        a = action[i]
        if a in TERMINAL:
            value[i] = float(terminal[i, a])
        else:
            for probability, after, fee in graph['edges'][i][a - 1]:
                if probability:
                    value[i] += float(probability) * (value[after] - float(fee))
    visit[graph['initial']] = 1.0
    for i in order:
        if action[i] not in TERMINAL:
            for probability, after, _ in graph['edges'][i][action[i] - 1]:
                if probability:
                    visit[after] += visit[i] * float(probability)
    mass = reward = fee_total = terminal_gap = continuation_gap = 0.0
    qstar, optimum = np.asarray(graph['qstar']), np.asarray(graph['optimal_values'])
    gap = np.array([float(optimum[i]) - float(qstar[i, action[i]]) for i in range(count)])
    require(np.isfinite(gap).all() and float(gap.min()) >= -2e-12, 'raw optimal gap')
    for i in order:
        contribution = visit[i] * float(gap[i])
        if action[i] in TERMINAL:
            mass += visit[i]
            reward += visit[i] * float(terminal[i, action[i]])
            terminal_gap += contribution
        else:
            continuation_gap += contribution
            for probability, _, fee in graph['edges'][i][action[i] - 1]:
                fee_total += visit[i] * float(probability) * float(fee)
    require(abs(mass - 1) <= 2e-10, 'terminal mass')
    initial = graph['initial']
    residual = float(optimum[initial]) - value[initial] - terminal_gap - continuation_gap
    tolerance = 1e-10 * (1 + abs(float(optimum[initial])) + abs(value[initial]) + abs(terminal_gap + continuation_gap))
    require(abs(residual) <= tolerance and abs(value[initial] - reward + fee_total) <= tolerance, 'PDI/payoff identity')
    original = np.asarray(visit if incumbent_occupancy is None else incumbent_occupancy, dtype=np.float64)
    require(original.shape == (count,) and np.isfinite(original).all() and np.all(original >= 0), 'incumbent occupancy')
    require(original.sum() > 0 and sum(visit) > 0, 'positive occupancy normalizer')
    error = ((scores[:, 5] + 1) / 2 - np.asarray(graph['posterior'])) ** 2
    rank_gap = []
    for i in range(count):
        choices = [a for a in TERMINAL if masks[i, a]]
        selected = max(choices, key=lambda a: (float(scores[i, a]), -a))
        rank_gap.append(max(float(terminal[i, a]) for a in choices) - float(terminal[i, selected]))
    common, actual = original / original.sum(), np.asarray(visit) / sum(visit)
    diagnostics = {
        'original_full_decision_occupancy_normalizer': float(original.sum()),
        'candidate_full_decision_occupancy_normalizer': float(sum(visit)),
        'own_posterior_MSE_original_occupancy': float(np.sum(common * error)),
        'own_posterior_MSE_candidate_occupancy': float(np.sum(actual * error)),
        'terminal_rank_own_gap_original_occupancy': float(np.sum(common * rank_gap)),
        'terminal_rank_own_gap_candidate_occupancy': float(np.sum(actual * rank_gap)),
        'terminal_rank_own_gap_full_state_max': float(max(rank_gap)),
    }
    metrics = {'utility': value[initial], 'optimal_utility': float(optimum[initial]),
               'optimal_regret': float(optimum[initial]) - value[initial], 'terminal_mass': mass,
               'expected_terminal_reward': reward, 'expected_expense': fee_total,
               'expected_decisions': float(sum(visit)), 'terminal_gap_contribution': terminal_gap,
               'continuation_gap_contribution': continuation_gap, 'PDI_residual': residual,
               'PDI_tolerance': tolerance, 'raw_minimum_gap': float(gap.min()),
               'complete_state_count': count, 'reached_state_count': sum(x != 0 for x in visit),
               'belief_diagnostics': diagnostics}
    arrays = {'scores': scores, 'actions': np.asarray(action, dtype=np.int64),
              'values': np.asarray(value), 'occupancy': np.asarray(visit), 'raw_gap': gap}
    return metrics, arrays


def winner(values, candidates):
    chosen, best = 'KEEP', float(values['KEEP'])
    require(math.isfinite(best), 'finite KEEP selection utility')
    for name in candidates:
        if name in values:
            value = float(values[name])
            require(math.isfinite(value), 'nonfinite selected mean')
            if value > best + 1e-12:
                chosen, best = name, value
    return chosen


def compare_metrics(record, expected):
    if isinstance(expected, dict):
        require(isinstance(record, dict), 'metric mapping type')
        for name, value in expected.items():
            compare_metrics(record[name], value)
    elif isinstance(expected, (list, tuple)):
        require(isinstance(record, (list, tuple)) and len(record) == len(expected), 'metric sequence length')
        for actual, value in zip(record, expected, strict=True):
            compare_metrics(actual, value)
    elif expected is None or isinstance(expected, (str, bool)):
        require(type(record) is type(expected) and record == expected, 'metric literal differs')
    elif type(expected) is int:
        require(type(record) is int and record == expected, 'metric integer differs')
    else:
        close_number(record, expected, 'independent metric')


def check_arrays(archive, prefix, expected, record):
    for name, value in expected.items():
        actual = archive[prefix + '__' + name]
        require(actual.shape == value.shape and actual.dtype == value.dtype, 'array shape/dtype: ' + name)
        if name in ('actions', 'scores'):
            require(actual.tobytes() == value.tobytes(), 'exact action/score bytes: ' + name)
        else:
            require(np.isfinite(actual).all(), 'nonfinite recorded array')
            require(np.all(np.abs(actual - value) <= ARRAY_TOLERANCE * (1 + np.abs(value))), 'independent array: ' + name)
    require(record['action_sha256'] == digest(archive[prefix + '__actions'].tobytes()), 'action array SHA')
    require(record['occupancy_sha256'] == digest(archive[prefix + '__occupancy'].tobytes()), 'occupancy array SHA')


def pin_file(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=digest(raw))


def save_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(canonical(value) + '\n')


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def nonnegative(value, name):
    close_number(value, value, name)
    require(value >= 0, name + ' negative')


def aggregate(worlds, names):
    summaries = {}
    for name in names:
        metrics = [world[name] for world in worlds]
        values = [r['utility'] for r in metrics]
        originals = [world['KEEP']['utility'] for world in worlds]
        candidate, original, optimal = (float(np.mean(a)) for a in
            (values, originals, [r['optimal_utility'] for r in metrics]))
        denominator = optimal - original
        summaries[name] = dict(utility=candidate, original_utility=original,
            optimal_utility=optimal, delta_original=candidate - original,
            optimal_regret=optimal - candidate, absolute_retention_denominator=optimal,
            absolute_retention=candidate / optimal if optimal > 1e-12 else None,
            opportunity_denominator=denominator,
            opportunity_recovery=(candidate - original) / denominator if denominator > 1e-12 else None,
            worlds=len(worlds), per_world_utilities=values,
            delta_original_min=float(np.min(np.asarray(values) - originals)),
            delta_original_max=float(np.max(np.asarray(values) - originals)),
            belief_diagnostics={key: float(np.mean([m['belief_diagnostics'][key] for m in metrics]))
                for key in ('own_posterior_MSE_original_occupancy', 'own_posterior_MSE_candidate_occupancy',
                            'terminal_rank_own_gap_original_occupancy', 'terminal_rank_own_gap_candidate_occupancy')})
    return summaries


def configure_budget(protocol, start_wall):
    limits = protocol['resources']['reader']
    require(limits == dict(CPU_hard=60, CPU_soft=55, wall_hard=120), 'reader frozen resource envelope')
    require(protocol['resources']['affinity_CPU'] == 7 and
            protocol['resources']['address_space_bytes'] == 536870912, 'reader hardware contract')
    os.sched_setaffinity(0, {7})
    resource.setrlimit(resource.RLIMIT_AS, (536870912, 536870912))
    resource.setrlimit(resource.RLIMIT_CPU, (55, 60))
    def exhausted(*unused):
        raise TimeoutError('independent reader resource cap; no retry')
    signal.signal(signal.SIGXCPU, exhausted)
    signal.signal(signal.SIGALRM, exhausted)
    signal.alarm(120)
    def check():
        if time.process_time() >= 55 or time.perf_counter() - start_wall >= 120:
            exhausted()
    return check


def protocol_check(protocol, protocol_pin):
    require(protocol['schema'] == 'hepta-value-retention-frozen-v1', 'frozen protocol required')
    require(set(protocol['input_specs']) == set(map(str, FITS)), 'five frozen fits')
    for group in ('source_pins', 'semantic_sources', 'provenance_sources'):
        for item in protocol[group].values():
            verify_pin(item)
    require(protocol['source_pins']['verify_records.py'] == pin_file(__file__), 'reader source identity')
    for item in [protocol['draft_pin'], protocol['public_domain_source'], protocol['preflight_pin']] + protocol['review_pins']:
        verify_pin(item)
    require(iso(read_pin(protocol['preflight_pin'])['created_utc']) <= iso(protocol['created_utc']), 'preflight before freeze')
    require(read_pin(protocol['preflight_pin'])['status'] == 'PASS', 'preflight status')
    fields, known = protocol['schedule_fields'], set()
    require(len(fields) == len(set(fields)) == 13, 'complete public schedule contract')
    for expected_count, item in zip((3456, 20, 160), protocol['history_inputs'], strict=True):
        inventory = read_pin(item)
        keys = inventory['keys']
        require(len(keys) == len(set(keys)) == expected_count and not known.intersection(keys), 'historical inventory identity')
        known.update(keys)
    require(sorted(known) == protocol['known_schedule_hashes'] and len(known) == 3636, 'historical exclusion union')
    metadata = read_pin(protocol['public_domain_source'])
    require(protocol['public_domains'] == dict(iid=metadata['train_domain'], ood=metadata['ood_domain'],
        prior_distances=metadata['prior_distances']), 'public domains from original source')
    for phase, limits in [('main', (145, 150, 240)), ('confirmation', (55, 60, 120)), ('reader', (55, 60, 120))]:
        require(protocol['resources'][phase] == dict(CPU_soft=limits[0], CPU_hard=limits[1], wall_hard=limits[2]), 'frozen phase limits')
    verify_pin(protocol_pin)
    return known


def process_check(output, phase, protocol, protocol_pin):
    output = Path(output).resolve()
    result_pin = pin_file(output / 'RESULTS.json')
    result = read_pin(result_pin)
    process_pin = pin_file(output.parent / 'PROCESS.json')
    process = read_pin(process_pin)
    launch = read_json(output.parent / 'LAUNCH.json')
    require(process['schema'] == 'hepta-value-process-receipt-v1' and process['phase'] == phase, 'process role')
    require(process['status'] == 'COMPLETED' and process['returncode'] == 0 and
        process['wall_timeout'] is False and process['error'] is None and
        process['protocol_and_entry_unchanged'] is True and process['result_status'] == 'COMPLETED', 'process completion')
    require(process['result_pin'] == result_pin and process['protocol_pin'] == protocol_pin, 'process result/source identity')
    entry = 'run_main.py' if phase == 'main' else 'run_confirmation.py'
    require(process['entry_pin'] == protocol['source_pins'][entry] and
            process['supervisor_pin'] == protocol['source_pins']['supervise.py'], 'process executable source pins')
    for key in launch:
        if key != 'schema':
            require(launch[key] == process[key], 'launch/receipt disagreement: ' + key)
    limits = protocol['resources'][phase]
    require((process['CPU_soft_seconds'], process['CPU_hard_seconds'], process['wall_seconds']) ==
            (limits['CPU_soft'], limits['CPU_hard'], limits['wall_hard']), 'process resource declaration')
    require(process['affinity'] == [7] and process['threads'] == 1 and
            process['address_space_bytes'] == 536870912 and process['retry_permitted'] is False, 'process isolation')
    for name in ('child_CPU_seconds', 'child_user_CPU_seconds', 'child_system_CPU_seconds',
                 'child_wall_seconds', 'supervisor_CPU_seconds', 'supervisor_wall_seconds'):
        nonnegative(process[name], 'process ' + name)
    close_number(process['child_CPU_seconds'], process['child_user_CPU_seconds'] + process['child_system_CPU_seconds'], 'child CPU components', 1e-12)
    require(process['child_CPU_seconds'] <= limits['CPU_hard'] and
            process['child_wall_seconds'] <= limits['wall_hard'], 'completed process exceeded hard limit')
    require(result['status'] == 'COMPLETED' and result['protocol_sha256'] == protocol_pin['sha256'], 'result completion/source')
    require(iso(protocol['created_utc']) <= iso(process['created_utc']) <= iso(result['created_utc']) <=
            iso(result['completed_utc']) <= iso(process['completed_utc']), 'process temporal order')
    require(not (output / 'FAILED.json').exists() and not (output / 'CONF_FAILED_COLLISION.json').exists(), 'failed attempt cannot pass')
    for pin in (process['protocol_pin'], process['entry_pin'], process['supervisor_pin']):
        verify_pin(pin)
    return result, result_pin, process, process_pin


def load_train(protocol, fit):
    spec = protocol['input_specs'][str(fit)]
    for item in spec.values():
        verify_pin(item)
    base = read_pin(spec['model'])
    require(base['schema'] == 'joint-policy-v1' and base['family'] == 'renewal' and
            base['head_dimensions'] == [85, 48, 4], 'original checkpoint architecture')
    reconstruction, family, publics = [read_pin(spec[name]) for name in ('reconstruction', 'family', 'publics')]
    for actual, previous in ((spec['model'], family['source_C']), (spec['data'], reconstruction['dataset']),
                             (spec['teacher'], family['teacher'])):
        require(all(actual[key] == previous[key] for key in ('bytes', 'sha256')), 'original input provenance')
    require(family['program']['own_law_labels_only'] is True, 'own-law teacher source')
    with np.load(spec['data']['path'], allow_pickle=False) as archive:
        X, masks, scores = [archive[key] for key in ('X', 'legal_masks', 'C_scores')]
    with np.load(spec['teacher']['path'], allow_pickle=False) as archive:
        teacher, posterior, weights = [archive[key] for key in ('own_optimal_targets', 'own_posterior', 'sample_weights')]
    n = reconstruction['train_rows']
    for array, shape, dtype in ((X, (n, 85), np.float64), (masks, (n, 6), np.bool_),
                               (scores, (n, 6), np.float64), (teacher, (n, 4), np.float64),
                               (posterior, (n,), np.float64), (weights, (n, 4), np.float64)):
        require(array.shape == shape and array.dtype == dtype and np.isfinite(array).all(), 'original array contract')
    require(len(publics) == len(reconstruction['reconstructed_worlds']) == len(family['program']['TRAIN']) == 64, 'complete 64-world source')
    offset, sections = 0, []
    for i, (public, world, label) in enumerate(zip(publics, reconstruction['reconstructed_worlds'], family['program']['TRAIN'], strict=True)):
        require(world['rows'] == label['rows'] and public['id'] == world['world_id'] == label['world_id'] and
                world['state_order_sha256'] == label['state_order_sha256'], 'TRAIN world/teacher order')
        section = slice(offset, offset + world['rows'])
        require(digest(teacher[section].tobytes()) == label['teacher_sha256'] and
                digest(weights[section].tobytes()) == label['sample_weight_sha256'], 'per-world teacher hash')
        sections.append((section.start, section.stop, world['state_order_sha256']))
        offset = section.stop
    require(offset == n, 'all TRAIN rows covered')
    keys = [digest(canonical({key: public[key] for key in protocol['schedule_fields']}).encode()) for public in publics]
    order = sorted(range(64), key=lambda i: (digest(canonical([
        'hepta-value-retention-20261121/train-split/v1', fit, keys[i]]).encode()), i))
    split = dict(GEN=order[:32], SELECT=order[32:48], TRAIN_AUDIT=order[48:], schedule_hashes=keys,
                 rule='sha256(canonical([namespace,fit,schedule_hash])), original-index tie')
    require(split == protocol['splits'][str(fit)] and set(keys) <= set(protocol['known_schedule_hashes']), 'exposed TRAIN deterministic split')
    H = independent_hidden(base, X)
    COUNTS['TRAIN_hidden_calls'] += 1
    COUNTS['TRAIN_hidden_rows'] += n
    require(independent_scores(head_rows(base), H).tobytes() == scores.tobytes(), 'original saved H49 scores exact')
    return dict(base=base, X=X, H=H, masks=masks, scores=scores, teacher=teacher,
                posterior=posterior, publics=publics, sections=sections, split=split)


def graph_check(ctx, base, public, graph_pin, budget):
    saved = read_pin(graph_pin)
    actual = build_graph(ctx, public, base, 4096, budget)
    COUNTS['own_graphs'] += 1
    converted = {key: value.tolist() if isinstance(value, np.ndarray) else value for key, value in actual.items()}
    require(canonical(saved) == canonical(converted), 'full original-own-law graph replay differs')
    require(len(saved['states']) <= 4096, 'complete graph cap')
    return saved


def phase_check(record_pin, phase, fit, models, indices, items, protocol_sha, budget, domain=None):
    record = read_pin(record_pin)
    names = ['KEEP'] + ([name for name in HEADS if name in models] if domain is None else
                        ['Q_SELECTED', 'B_SELECTED', 'G_SELECTED', 'T_SELECTED'])
    names += [name for name in DIAGNOSTICS if name in models]
    require(record['schema'] == 'hepta-own-law-phase-records-v1' and record['phase'] == phase and
            record['fit'] == fit and record['domain'] == domain and record['protocol_sha256'] == protocol_sha, 'phase contract')
    require(record['models'] == models and record['arm_order'] == names and record['world_indices'] == indices, 'phase identity/order')
    require(iso(record['started_utc']) <= iso(record['completed_utc']), 'phase time order')
    nonnegative(record['CPU_seconds'], 'phase complete CPU')
    require(len(record['worlds']) == len(indices), 'phase complete worlds')
    verify_pin(record['arrays_pin'])
    metrics_by_index, keep_by_index, sums, expected_keys = {}, {}, {name: 0.0 for name in names}, set()
    paid_DPs, paid_rows = 0, 0
    parameters = {name: head_rows(read_pin(entry['model_pin'])) for name, entry in models.items()}
    with np.load(record['arrays_pin']['path'], allow_pickle=False) as archive:
        for index, world in zip(indices, record['worlds'], strict=True):
            budget()
            item, identity_to_name, all_arrays, all_metrics = items[index], {}, {}, {}
            graph, H = item['graph'], item['H']
            require(world['world_index'] == index and world['world_id'] == graph['public']['id'] and
                    world['graph_pin'] == item['graph_pin'] and world['state_order_sha256'] == graph['state_order_sha256'] and
                    world['rows'] == len(graph['states']) and set(world['arms']) == set(names), 'phase full-state identity')
            if domain is not None:
                require(world['features_pin'] == item['features_pin'], 'CONF complete feature source')
            for name in names:
                arm = world['arms'][name]
                identity = models[name]['canonical_model_sha256']
                previous = identity_to_name.get(identity)
                expected_prefix = f'w{index:03d}__{previous or name}'
                require(arm['array_prefix'] == expected_prefix and arm['alias_of'] == previous, 'exact-head alias contract')
                nonnegative(arm['evaluation_CPU_seconds'], 'arm evaluation CPU')
                if previous is not None:
                    require(arm['evaluation_CPU_seconds'] == 0, 'alias records no second evaluation')
                    expected, arrays = all_metrics[previous], all_arrays[previous]
                    COUNTS['policy_record_aliases'] += 1
                else:
                    expected, arrays = scalar_policy(graph, independent_scores(parameters[name], H),
                        None if name == 'KEEP' else all_arrays['KEEP']['occupancy'])
                    identity_to_name[identity] = name
                    expected_keys.update(expected_prefix + '__' + key for key in ARRAY_NAMES)
                    if not (phase == 'GEN' and name == 'KEEP'):
                        paid_DPs += 1
                        paid_rows += len(H)
                compare_metrics(arm['metrics'], expected)
                require(arm['metrics']['belief_diagnostics']['same_weights_across_candidates'] == 'original occupancy only' and
                        arm['metrics']['belief_diagnostics']['selection_criterion'] is False, 'posterior diagnostic role')
                check_arrays(archive, expected_prefix, arrays, arm['metrics'])
                all_arrays[name], all_metrics[name] = arrays, expected
                sums[name] += arm['evaluation_CPU_seconds']
                COUNTS['policy_records_checked'] += 1
            metrics_by_index[index] = all_metrics
            if phase == 'GEN':
                keep_by_index[index] = all_arrays['KEEP']
        require(set(archive.files) == expected_keys, 'no omitted or extra state-array keys')
    for name in names:
        close_number(record['evaluation_CPU_by_arm'][name], sums[name], 'arm CPU sum')
    expected_work = dict(hidden_forward_calls=0, hidden_forward_rows=0, readout_forward_calls=paid_DPs,
        readout_forward_rows=paid_rows, own_graphs=0, semantic_physical_calls=0,
        semantic_complete_rows=0, complete_policy_DPs=paid_DPs, own_optimal_DPs=0)
    require(record['work_delta'] == expected_work, 'phase actual work and incumbent reuse accounting')
    summaries = aggregate([metrics_by_index[index] for index in indices], names)
    require(set(record['means']) == set(models), 'complete phase summary inventory')
    compare_metrics(record['means'], summaries)
    return record, metrics_by_index, keep_by_index, summaries


def screening_check(row, data, items, gen_record, gen_keep, protocol, fit):
    report = read_pin(row['screening_pin'])
    baseline = read_pin(row['incumbent_GEN_record_pin'])
    indices = data['split']['GEN']
    require(report['schema'] == 'hepta-value-gen-screening-v1' and report['fit'] == fit and
            report['protocol_sha256'] == gen_record['protocol_sha256'] and report['GEN_world_indices'] == indices,
            'GEN-only screening role')
    require(report['incumbent_record_pin'] == row['incumbent_GEN_record_pin'] == gen_record['precomputed_KEEP_record_pin'] and
            report['source_input_pins'] == protocol['input_specs'][str(fit)], 'GEN baseline source')
    require(baseline['schema'] == 'hepta-own-law-phase-records-v1' and baseline['phase'] == 'GEN_INCUMBENT_ONLY' and
            baseline['fit'] == fit and baseline['domain'] is None and baseline['world_indices'] == indices and
            baseline['models'] == {'KEEP': row['models']['KEEP']} and baseline['arm_order'] == ['KEEP'] and
            baseline['protocol_sha256'] == gen_record['protocol_sha256'], 'incumbent complete contract')
    require(iso(baseline['started_utc']) <= iso(baseline['completed_utc']) <= iso(gen_record['started_utc']), 'baseline before generated evaluation')
    verify_pin(baseline['arrays_pin'])
    baseline_cpu = 0.0
    expected_keys = set()
    with np.load(baseline['arrays_pin']['path'], allow_pickle=False) as archive:
        require(len(baseline['worlds']) == len(indices), 'baseline world count')
        for index, old, new in zip(indices, baseline['worlds'], gen_record['worlds'], strict=True):
            require(all(old[k] == new[k] for k in ('world_index', 'world_id', 'graph_pin', 'state_order_sha256', 'rows')) and
                    set(old['arms']) == {'KEEP'}, 'baseline complete world identity')
            previous, reused = old['arms']['KEEP'], new['arms']['KEEP']
            require(previous['alias_of'] is None and previous['array_prefix'] == reused['array_prefix'] and
                    previous['metrics'] == reused['metrics'] and reused['evaluation_CPU_seconds'] == 0, 'paid-once incumbent reuse')
            check_arrays(archive, previous['array_prefix'], gen_keep[index], previous['metrics'])
            expected_keys.update(previous['array_prefix'] + '__' + key for key in ARRAY_NAMES)
            nonnegative(previous['evaluation_CPU_seconds'], 'incumbent CPU')
            baseline_cpu += previous['evaluation_CPU_seconds']
        require(set(archive.files) == expected_keys, 'baseline complete arrays')
    close_number(baseline['evaluation_CPU_by_arm']['KEEP'], baseline_cpu, 'incumbent CPU total')
    require(gen_record['evaluation_CPU_by_arm']['KEEP'] == 0, 'GEN no repeated incumbent execution charge')
    nonnegative(baseline['CPU_seconds'], 'incumbent enclosing cost')
    compare_metrics(baseline['means'], {'KEEP': gen_record['means']['KEEP']})
    baseline_work = dict(hidden_forward_calls=0, hidden_forward_rows=0, readout_forward_calls=32,
        readout_forward_rows=sum(len(gen_keep[index]['actions']) for index in indices), own_graphs=0,
        semantic_physical_calls=0, semantic_complete_rows=0, complete_policy_DPs=32, own_optimal_DPs=0)
    require(baseline['work_delta'] == baseline_work, 'single paid GEN incumbent work')
    H, masks, qstar, scores, visit, global_ids, initial_rows = [], [], [], [], [], [], []
    offset = 0
    for index in indices:
        item = items[index]
        graph = item['graph']
        lo, hi, _ = data['sections'][index]
        H.append(item['H']); masks.append(np.asarray(graph['masks'], dtype=bool))
        qstar.append(np.asarray(graph['qstar'], dtype=np.float64))
        scores.append(gen_keep[index]['scores']); visit.append(gen_keep[index]['occupancy'])
        global_ids.extend(range(lo, hi)); initial_rows.append(offset + graph['initial'])
        offset += hi - lo
    H, masks, qstar, scores, visit = [np.concatenate(a) for a in (H, masks, qstar, scores, visit)]
    target = np.array([max(np.flatnonzero(mask), key=lambda a: (float(qstar[i, a]), -int(a)))
                       for i, mask in enumerate(masks)], dtype=np.int64)
    old_action = np.array([max(np.flatnonzero(mask), key=lambda a: (float(scores[i, a]), -int(a)))
                           for i, mask in enumerate(masks)], dtype=np.int64)
    gap = qstar[np.arange(len(H)), target] - qstar[np.arange(len(H)), old_action]
    require(float(gap.min()) >= -2e-12, 'screen raw optimal gap')
    mass = visit * np.maximum(gap, 0)
    opportunity = sorted((i for i in range(len(H)) if mass[i] > 0), key=lambda i: (-float(mass[i]), global_ids[i]))[:128]
    retained = sorted((i for i in range(len(H)) if visit[i] > 0 and gap[i] == 0), key=lambda i: (-float(visit[i]), global_ids[i]))[:64]
    selected = sorted(set(opportunity + retained + initial_rows), key=lambda i: global_ids[i])
    require(0 < len(selected) <= 224, 'fixed GEN selection bound')
    targets = target[selected]
    margins = np.maximum(0, qstar[selected, targets, None] - qstar[selected])
    margins += 1e-6 * (np.arange(6)[None, :] < targets[:, None])
    expected = dict(H=H[selected], masks=masks[selected], targets=targets, margins=margins)
    verify_pin(report['problem_pin'])
    with np.load(report['problem_pin']['path'], allow_pickle=False) as archive:
        require(set(archive.files) == set(expected), 'GEN problem has only permitted inputs')
        for name, array in expected.items():
            require(archive[name].shape == array.shape and archive[name].dtype == array.dtype and
                    archive[name].tobytes() == array.tobytes(), 'independent GEN problem: ' + name)
    wanted = dict(selected_rows=len(selected), opportunity_rows=len(opportunity), retention_rows=len(retained),
        initial_rows=len(initial_rows), GEN_rows=len(H), positive_original_occupancy_rows=int(np.count_nonzero(visit)),
        zero_original_occupancy_rows=int(np.count_nonzero(visit == 0)), total_old_occupancy_gap=float(mass.sum()),
        selected_old_occupancy_gap=float(mass[selected].sum()),
        omitted_old_occupancy_gap=float(mass.sum()) - float(mass[selected].sum()))
    compare_metrics(report, wanted)
    require(report['global_row_ids'] == [global_ids[i] for i in selected] and
            report['selected_H_sha256'] == digest(expected['H'].tobytes()) and
            report['candidate_utility_bound'] is False and
            report['loss_weighting'] == 'uniform selected states; old occupancy*gap only screens', 'GEN screening provenance')
    for name, value in radius_check(head_rows(data['base']), head_rows(data['base'])).items():
        require(report['exact_radius'][name] == value, 'GEN radius source')
    return report, expected, baseline


def nonlinear_loss(rows, anchor, problem):
    scores = independent_scores(rows, problem['H'])
    losses = []
    for index, target in enumerate(problem['targets']):
        alternatives = [float(scores[index, action]) - float(scores[index, target]) + float(problem['margins'][index, action])
                        for action in range(6) if problem['masks'][index, action] and action != target]
        losses.append(max(0.0, max(alternatives)))
    exact_q = sum((Fraction.from_float(float(x)) ** 2 for x in anchor[:3].flat), Fraction(0))
    radius = math.sqrt(float(exact_q / 4))
    return float(np.mean(losses) + 0.001 / (2 * radius ** 2) * np.sum((rows - anchor) ** 2))


def conic_payload_check(payload, name, checkpoint, candidate, anchor, center, problem, family):
    active = list(range(147)) if family == 'Q' else (list(range(147, 196)) if family == 'B' else list(range(196)))
    x, dual = payload[name + '__primal'], payload[name + '__dual']
    count, n = len(problem['H']), len(active)
    require(x.shape == (n + count,) and np.isfinite(x).all() and dual.ndim == 1 and np.isfinite(dual).all(), 'saved conic raw coordinates')
    restored = anchor.copy().reshape(-1)
    restored[active] = anchor.reshape(-1)[active] + x[:n]
    require(restored.reshape(4, 49).tobytes() == candidate.tobytes(), 'candidate is saved raw conic proposal')
    center_scores = independent_scores(center, problem['H'])
    center_delta = (center - anchor).reshape(-1)
    violation, largest_rhs, constraints = 0.0, 0.0, 0
    def slope_row(action, h, slope):
        row = np.zeros(196)
        if action in (1, 2, 3):
            row[(action - 1) * 49:action * 49] = h
        elif action in (4, 5):
            row[147:] = h * (-slope if action == 4 else slope)
        return row
    for i, h in enumerate(problem['H']):
        target = int(problem['targets'][i])
        logit = float(np.sum(center[3] * h))
        p = 1 / (1 + np.exp(-np.clip(logit, -700, 700)))
        slope = 2 * p * (1 - p) if -700 < logit < 700 else 0.0
        for action in range(6):
            if not problem['masks'][i, action] or action == target:
                continue
            difference = slope_row(action, h, slope) - slope_row(target, h, slope)
            rhs = -(center_scores[i, action] - center_scores[i, target] + problem['margins'][i, action] -
                    float(np.sum(difference * center_delta)))
            observed = float(np.sum(difference[active] * x[:n]) - x[n + i] - rhs)
            violation = max(violation, observed)
            largest_rhs = max(largest_rhs, abs(float(rhs)))
            constraints += 1
        violation = max(violation, -float(x[n + i])); constraints += 1
        if family != 'Q':
            complete = slope_row(5, h, 1.0)
            displacement = float(np.sum(complete * center_delta))
            for sign in (1, -1):
                rhs = 0.5 + sign * displacement
                violation = max(violation, float(sign * np.sum(complete[active] * x[:n]) - rhs))
                largest_rhs = max(largest_rhs, abs(rhs)); constraints += 1
    require(violation <= 1e-7 * (1 + largest_rhs), 'independent selected affine constraints')
    require(checkpoint['linear_constraints'] == constraints and checkpoint['active_coordinates'] == n and
            checkpoint['selected_states'] == count and len(dual) == constraints + n + 1, 'conic raw problem dimensions')
    close_number(checkpoint['independently_recomputed_linear_violation'], violation, 'selected linear residual')


def generation_check(row, problem, screen, base, selection_time, fit, protocol_sha):
    require(set(row['generation']) == set(FAMILIES) and set(row['candidate_slots']) == set(HEADS), 'all fixed generation slots retained')
    anchor = head_rows(base)
    seen = {'KEEP'}
    for family, names in FAMILIES.items():
        generation_pin = row['generation'][family]
        record = read_pin(generation_pin)
        require(record['schema'] == 'hepta-value-family-generation-v1' and record['fit'] == fit and
                record['family'] == family and record['protocol_sha256'] == protocol_sha and
                record['problem_pin'] == screen['problem_pin'] and record['screening_pin'] == row['screening_pin'] and
                record['source_model_pin'] == screen['source_input_pins']['model'], 'generation fixed GEN source')
        require(iso(record['started_utc']) <= iso(record['completed_utc']) <= selection_time, 'generation before selection seal')
        cap = 1.5 if family == 'Q' else 3.0
        require(record['nominal_CPU_cap'] == cap and set(record['checkpoints']) == set(names), 'generation frozen limits/checkpoints')
        for key in ('CPU_seconds', 'wall_seconds'):
            nonnegative(record[key], 'generation ' + key)
        for key in ('lifecycle_CPU_through_record', 'lifecycle_wall_through_record', 'numerical_call_CPU_seconds',
                    'artifact_and_revalidation_CPU_seconds', 'other_family_bookkeeping_CPU_seconds'):
            nonnegative(record[key], 'full generation ' + key)
        close_number(record['lifecycle_CPU_through_record'], record['numerical_call_CPU_seconds'] +
            record['artifact_and_revalidation_CPU_seconds'] + record['other_family_bookkeeping_CPU_seconds'],
            'full family lifecycle accounting', 1e-12)
        require(record['CPU_seconds'] <= record['numerical_call_CPU_seconds'] <= record['lifecycle_CPU_through_record'],
                'numerical family time nested in full generation cost')
        payload = None
        if record['raw_payloads_pin'] is not None:
            verify_pin(record['raw_payloads_pin'])
            payload = np.load(record['raw_payloads_pin']['path'], allow_pickle=False)
        emitted = {}
        center = anchor
        try:
            for name in names:
                slot, checkpoint = row['candidate_slots'][name], record['checkpoints'][name]
                require(slot['family'] == family and slot['generation_record_pin'] == generation_pin and
                        slot['checkpoint_report'] == checkpoint and slot['status'] in ('VALID', 'UNKNOWN'), 'fixed slot record')
                valid = slot['status'] == 'VALID'
                require(valid == (name in row['models']), 'unknown candidates cannot enter selection')
                if not valid:
                    require(slot['model_pin'] is None, 'unknown candidate exported model')
                    continue
                entry = row['models'][name]
                require(entry['generation_id'] == name and entry['family'] == family and entry['diagnostic_only'] is False and
                        entry['generation_record_pin'] == generation_pin and slot['model_pin'] == entry['model_pin'], 'generated model identity')
                elapsed = checkpoint['family_CPU_through_checkpoint']
                nonnegative(elapsed, 'checkpoint actual CPU')
                require(elapsed <= cap and elapsed <= record['CPU_seconds'], 'candidate accepted after CPU cap')
                _, candidate = model_check(entry, base, family)
                if family == 'T':
                    require(checkpoint['status'] == 'COMPLETED' and checkpoint['step'] == int(name.split('_')[1]) and
                            record['steps_completed'] >= checkpoint['step'] and record['training_is_196_only'] is True, 'fixed gradient checkpoint')
                else:
                    require(checkpoint['status'] in ('Solved', 'AlmostSolved') and checkpoint['accepted_numeric_proposal'] is True and
                            checkpoint['primal_residual'] <= 1e-7 and checkpoint['dual_residual'] <= 1e-6 and payload is not None,
                            'structured numerical qualification')
                    nonnegative(checkpoint['primal_residual'], 'primal numerical residual')
                    nonnegative(checkpoint['dual_residual'], 'dual numerical residual')
                    conic_payload_check(payload, name, checkpoint, candidate, anchor, center, problem, family)
                close_number(checkpoint['actual_nonlinear_loss'], nonlinear_loss(candidate, anchor, problem), 'matched nonlinear GEN loss')
                emitted[name] = entry['model_pin']; seen.add(name)
                center = candidate
        finally:
            if payload is not None:
                payload.close()
        require(record['emitted_model_pins'] == emitted, 'complete emitted model inventory')
    require(set(row['models']) == seen, 'no undeclared generated models')


def main_fit_check(protocol, fit, row, sealed, diagnostic, seal_time, diagnostic_time, ctx, budget, protocol_sha):
    require(all(row[key] == value for key, value in sealed.items()), 'MAIN altered preselection seal')
    require(row['diagnostic_models'] == diagnostic['models'] and set(diagnostic['models']) == set(DIAGNOSTICS), 'diagnostic inventory')
    data = load_train(protocol, fit)
    base, H, spec = data['base'], data['H'], protocol['input_specs'][str(fit)]
    require(set(row['models']) <= {'KEEP', *HEADS} and 'KEEP' in row['models'], 'main model scope')
    identities, parameters = {}, {}
    for name, entry in dict(row['models'], **row['diagnostic_models']).items():
        expected_family = 'DIAGNOSTIC' if name in DIAGNOSTICS else ('KEEP' if name == 'KEEP' else name.split('_')[0])
        _, parameters[name] = model_check(entry, base, expected_family)
        identities[name] = {key: entry[key] for key in ('model_pin', 'canonical_model_sha256', 'readout_sha256')}
    require(all(row['models']['KEEP']['model_pin'][key] == spec['model'][key] for key in ('bytes', 'sha256')), 'KEEP exact original gzip bytes')
    require(row['models']['KEEP']['diagnostic_only'] is False, 'KEEP ordinary original')
    restore = row['restore_pin']
    verify_pin(restore)
    require(all(restore[key] == spec['model'][key] for key in ('bytes', 'sha256')), 'isolated restore exact original bytes')
    selected_g = row['family_choice']['G']
    require(diagnostic['G_SELECTED'] == selected_g, 'diagnostic causal source')
    for name, changed_rows, mask in ((DIAGNOSTICS[0], range(3), 7), (DIAGNOSTICS[1], (3,), 8)):
        restored = head_rows(base)
        for index in changed_rows:
            restored[index] = parameters[selected_g][index]
        require(parameters[name].tobytes() == restored.tobytes() and
                row['diagnostic_models'][name]['diagnostic_only'] is True and
                row['diagnostic_models'][name]['row_mask'] == mask, 'exact G component restoration')
    verify_pin(row['hidden_pin'])
    with np.load(row['hidden_pin']['path'], allow_pickle=False) as archive:
        require(archive.files == ['H'] and archive['H'].shape == H.shape and archive['H'].dtype == np.float64 and
                archive['H'].tobytes() == H.tobytes(), 'independent TRAIN hidden bytes')
    manifest = read_pin(row['graph_manifest_pin'])
    require(manifest['schema'] == 'hepta-own-law-graph-manifest-v1' and manifest['fit'] == fit and
            manifest['model_anchor_pin'] == spec['model'] and len(manifest['graphs']) == 64 and
            manifest['semantic_source_manifest_sha256'] == digest(canonical(protocol['semantic_sources']).encode()), 'graph manifest sources')
    items = {}
    for index, saved in enumerate(manifest['graphs']):
        budget()
        lo, hi, state_sha = data['sections'][index]
        require((saved['world_index'], saved['row_start'], saved['row_end'], saved['state_order_sha256']) ==
                (index, lo, hi, state_sha), 'graph/input row boundary')
        graph = graph_check(ctx, base, data['publics'][index], saved['graph_pin'], budget)
        require(graph['state_order_sha256'] == state_sha and len(graph['states']) == hi - lo, 'complete TRAIN state order')
        for actual, expected, name in ((np.asarray(graph['masks'], dtype=bool), data['masks'][lo:hi], 'masks'),
            (np.asarray(graph['posterior'], dtype=np.float64), data['posterior'][lo:hi], 'posterior'),
            (np.asarray(graph['qstar'], dtype=np.float64)[:, 1:4], data['teacher'][lo:hi, :3], 'own Q')):
            require(actual.tobytes() == expected.tobytes(), 'original teacher exact ' + name)
        authentication = saved['source_teacher_authentication']
        require(all(authentication[key] is True for key in ('state_order_exact', 'masks_bits_exact',
            'posterior_bits_exact', 'continuation_Q_bits_exact')) and authentication['continuation_Q_max_abs_error'] == 0,
            'recorded exact teacher authentication')
        items[index] = dict(graph=graph, graph_pin=saved['graph_pin'], H=H[lo:hi])
    records, metrics, summaries, gen_keep = {}, {}, {}, None
    require(set(row['phase_records']) == {'GEN', 'SELECT', 'TRAIN_AUDIT'}, 'all old phases present')
    for phase in ('GEN', 'SELECT', 'TRAIN_AUDIT'):
        phase_models = dict(row['models'])
        if phase == 'TRAIN_AUDIT':
            phase_models.update(row['diagnostic_models'])
        record, world_metrics, keep, summary = phase_check(row['phase_records'][phase], phase, fit, phase_models,
            data['split'][phase], items, protocol_sha, budget)
        if phase == 'TRAIN_AUDIT':
            require(iso(record['started_utc']) >= diagnostic_time, 'AUDIT after both immutable seals')
        else:
            require(iso(record['completed_utc']) <= seal_time, 'GEN/SELECT before immutable seal')
            require(row[phase + '_record_pin'] == row['phase_records'][phase], 'phase source alias')
        records[phase], metrics[phase], summaries[phase] = record, world_metrics, summary
        if phase == 'GEN':
            gen_keep = keep
    compare_metrics(row['phase_summaries'], summaries)
    all_metrics = {index: world for phase in metrics.values() for index, world in phase.items()}
    require(set(all_metrics) == set(range(64)), 'old full-world partition')
    compare_metrics(row['all_TRAIN_summaries'], aggregate([all_metrics[i] for i in range(64)],
        ['KEEP'] + [name for name in HEADS if name in row['models']]))
    values = {name: summary['utility'] for name, summary in summaries['SELECT'].items()}
    compare_metrics(row['SELECT_means'], values)
    choices = {family: winner(values, names) for family, names in FAMILIES.items()}
    global_choice = winner(values, [name for name in HEADS if name in set(choices.values())])
    require(row['family_choice'] == choices and row['global_choice'] == global_choice, 'independent full-task selection')
    screen, problem, baseline = screening_check(row, data, items, records['GEN'], gen_keep, protocol, fit)
    generation_check(row, problem, screen, base, seal_time, fit, protocol_sha)
    for generation_pin in row['generation'].values():
        record = read_pin(generation_pin)
        require(iso(baseline['completed_utc']) <= iso(record['started_utc']) and
                iso(record['completed_utc']) <= iso(records['GEN']['started_utc']), 'generation admission order')
    return identities, {phase: summaries[phase] for phase in summaries}
