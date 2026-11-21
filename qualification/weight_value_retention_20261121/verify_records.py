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
