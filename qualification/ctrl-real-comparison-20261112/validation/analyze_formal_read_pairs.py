"""Local descriptive READ-subset pairs from an already audited, pinned REPORT."""

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT_SHA = '968b1d462dcc6afc3c51ecf34f17c05c59762c2d9cda889054d10cb87c48e41a'
PAYLOAD_SHA = '36adf389d81232932980d75852de0792827569abb09ed5a869f928904d02c590'
AUDIT_SHA = '2e1d039b17d828316672a9b53d1dc93d84cbf0bb0baf7aa1d7ba68555a390713'
FLAGS = ('observation_bytes_changed', 'candidate_inventory_changed', 'new_recognized_text',
         'selected_candidate_changed', 'selected_text_changed',
         'written_text_differs_from_initial_selection', 'new_reference_matching_candidate',
         'semantic_information_gain', 'terminal_quality_change')
METHODS = ('STOP', 'light', 'tuned-fixed', 'point', 'unconditional', 'conditional')
CHECKS = Counter()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def parse(raw):
    def unique(items):
        value = dict(items)
        assert len(value) == len(items), 'Duplicate JSON keys'
        return value
    def invalid(value):
        raise ValueError('Nonfinite JSON: ' + value)
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def pinned(name, expected=None, size=None):
    raw = (ROOT / name).read_bytes()
    assert expected is None or sha(raw) == expected, name
    assert size is None or len(raw) == size, name
    return parse(raw), {'file': name, 'bytes': len(raw), 'sha256': sha(raw)}


def check(actual, expected):
    if type(actual) in (int, float) and type(expected) in (int, float):
        assert math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12), (actual, expected)
    else:
        assert actual == expected, (actual, expected)
    CHECKS['stored_value_checks'] += 1


def context(value):
    assert type(value['seed']) is int and value['seed'] >= 0
    return tuple(value[k] for k in ('source_id', 'case_id', 'seed'))


def count_flags(values):
    assert all(value is None or type(value) is bool for value in values)
    return [sum(v is not None for v in values), sum(v is True for v in values),
            sum(v is False for v in values), sum(v is None for v in values)]


def signs(values):
    return [sum(v > 0 for v in values), sum(v == 0 for v in values), sum(v < 0 for v in values)]


def source_mean(pairs, field):
    grouped = defaultdict(list)
    for pair in pairs:
        grouped[pair['source_id']].append(pair[field])
    return None if not grouped else math.fsum(math.fsum(v) / len(v) for v in grouped.values()) / len(grouped)


def metric(pairs, field):
    values = [p[field] for p in pairs]
    return {'known_pairs': len(values), 'unknown_pairs': 0, 'direction_counts': signs(values),
            'selected_subset_source_equal_mean': source_mean(pairs, field),
            'selected_subset_execution_mean': math.fsum(values) / len(values) if values else None}


def hash_equal(left, right):
    for value in (left, right):
        assert value is None or (type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value))
    return None if left is None or right is None else left == right


payload, payload_pin = pinned('evidence-transfer-payload.json', PAYLOAD_SHA, 13661075)
files = [f for f in payload['files'] if f['path'].endswith('/runtime/run-v2/factorial/REPORT.json')]
assert len(files) == 1
raw = files[0]['content'].encode()
assert len(raw) == files[0]['bytes'] == 3108442 and sha(raw) == files[0]['sha256'] == REPORT_SHA
report = parse(raw)
summary, summary_pin = pinned('run-v2-independent-factorial-summary.json')
audit, audit_pin = pinned('run-v2-terminal-audit.stdout.json', AUDIT_SHA, 8576)
assert audit['audit_status'] == 'PASS' and audit['mismatch_count'] == audit['unknown_count'] == 0
assert audit['report_sha256'] == summary['report_sha256'] == REPORT_SHA
assert audit['all_native_receipt_bindings_verified'] and audit['all_contexts_have_equal_12_arm_physical_frontiers']
assert report['factorial_sha256'] == summary['factorial_sha256'] == audit['factorial_sha256']
contexts = {context(c) for c in report['plan']['contexts']}
assert len(contexts) == len(report['plan']['contexts']) == 48
source_case = defaultdict(set)
for key in contexts:
    source_case[key[:2]].add(key[2])
assert all(len(seeds) == 1 for seeds in source_case.values()), 'Action-to-row seed mapping is ambiguous'
arms = {mode + '/' + policy for mode in ('frozen', 'adapted') for policy in METHODS}
assert {a['arm_id'] for a in report['plan']['arms']} == set(report['observed_actions']) == arms
rows, actions = {}, {}
for row in report['rows']:
    key = (row['arm_id'], context(row))
    assert key not in rows and row['status'] == 'COMPLETED' and row['evidence_kind'] == 'native_macro'
    assert all(type(row[k]) in (int, float) and math.isfinite(row[k]) for k in ('quality', 'task_cost'))
    rows[key] = row
assert set(rows) == {(arm, key) for arm in arms for key in contexts}
assert len({r['execution_id'] for r in rows.values()}) == 576
for arm, records in report['observed_actions'].items():
    for action in records:
        pair = (action['source_id'], action['case_id'])
        assert pair in source_case
        key = (*pair, next(iter(source_case[pair])))
        assert (arm, key) not in actions and (arm, key) in rows
        attribution = action['read_attribution']
        assert attribution['schema'] == 'ndu.real.read-attribution.v1'
        assert attribution['read_executed'] is (action['macro'] == 'READ')
        assert action['macro'] in ('STOP', 'READ')
        actions[(arm, key)] = action
assert set(actions) == set(rows)

selected = []
per_arm = {}
full_context_checks = {}
for arm in sorted(arms):
    stop_arm = arm.split('/')[0] + '/STOP'
    arm_pairs = []
    for key in sorted(contexts):
        row, stop = rows[(arm, key)], rows[(stop_arm, key)]
        action, stop_action = actions[(arm, key)], actions[(stop_arm, key)]
        assert stop_action['macro'] == 'STOP'
        assert row['content_sha256'] == stop['content_sha256'] and row['shared_sha256'] == stop['shared_sha256']
        attr, base = action['read_attribution'], stop_action['read_attribution']
        assert hash_equal(attr['initial_packet_sha256'], base['initial_packet_sha256']) is True
        assert hash_equal(base['initial_selected_text_sha256'], base['finalizer_selected_text_sha256']) is True
        qdiff = row['quality'] - stop['quality']
        cdiff = row['task_cost'] - stop['task_cost']
        ndiff = (row['quality'] - row['task_cost']) - (stop['quality'] - stop['task_cost'])
        final_equal = hash_equal(attr['finalizer_selected_text_sha256'], base['finalizer_selected_text_sha256'])
        entry = {'arm_id': arm, 'source_id': key[0], 'case_id': key[1], 'seed': key[2],
                 'execution_id': row['execution_id'], 'stop_execution_id': stop['execution_id'],
                 'evidence_sha256': row['evidence_sha256'], 'stop_evidence_sha256': stop['evidence_sha256'],
                 'macro': action['macro'], 'quality': row['quality'], 'net': row['quality'] - row['task_cost'],
                 'quality_delta': qdiff, 'task_cost_delta': cdiff, 'observed_task_net_delta': ndiff,
                 'paired_delivered_text_changed': None if final_equal is None else not final_equal,
                 'initial_selection_equals_actual_STOP_delivered_text': hash_equal(attr['initial_selected_text_sha256'], base['finalizer_selected_text_sha256']),
                 **{f: attr[f] for f in FLAGS}}
        arm_pairs.append(entry)
        if action['macro'] == 'READ':
            selected.append(entry)
    saved = summary['arms'][arm]
    check(source_mean(arm_pairs, 'quality'), saved['quality']['primary'])
    check(source_mean(arm_pairs, 'net'), saved['observed_task_cost_net']['primary'])
    for metric_name, field in (('quality', 'quality_delta'), ('observed_task_cost_net', 'observed_task_net_delta')):
        saved_pair = audit['arms'][arm]['minus_same_content_STOP'][metric_name]
        check(source_mean(arm_pairs, field), saved_pair['primary'])
        check(signs([p[field] for p in arm_pairs]), saved_pair['direction_counts'])
    read_pairs = [p for p in arm_pairs if p['macro'] == 'READ']
    check(len(read_pairs), saved['actions']['READ'])
    check(48 - len(read_pairs), saved['actions']['STOP'])
    flag_counts = {flag: count_flags([p[flag] for p in read_pairs]) for flag in FLAGS}
    for flag, counts in flag_counts.items():
        check(counts, saved['actions']['read_flag_counts'][summary['read_flag_columns'].index(flag)])
    full_context_checks[arm] = {'paired_contexts': 48, 'sources': 16,
                               'non_READ_quality_directions': signs([p['quality_delta'] for p in arm_pairs if p['macro'] != 'READ'])}
    if not read_pairs:
        continue
    per_arm[arm] = {'READ_pairs': len(read_pairs), 'selected_source_count': len({p['source_id'] for p in read_pairs}),
                    'paired_delivered_text_changed': count_flags([p['paired_delivered_text_changed'] for p in read_pairs]),
                    'initial_selection_equals_actual_STOP_delivered_text': count_flags([p['initial_selection_equals_actual_STOP_delivered_text'] for p in read_pairs]),
                    'attribution_counts': flag_counts,
                    'quality_delta': metric(read_pairs, 'quality_delta'),
                    'task_cost_delta': metric(read_pairs, 'task_cost_delta'),
                    'observed_task_net_delta': metric(read_pairs, 'observed_task_net_delta')}

assert len(selected) == 62
cross_tabs = {}
for flag in ('new_recognized_text', 'new_reference_matching_candidate', 'paired_delivered_text_changed'):
    cross_tabs[flag] = {}
    for label, value in (('true', True), ('false', False), ('unknown', None)):
        part = [p for p in selected if p[flag] is value]
        cross_tabs[flag][label] = {'pairs': len(part), 'quality_directions': signs([p['quality_delta'] for p in part]),
                                 'observed_task_net_directions': signs([p['observed_task_net_delta'] for p in part])}
out = {'schema': 'ctrl.formal-read-paired-effects.v1',
       'inputs': {'payload': payload_pin, 'report': {'bytes': len(raw), 'sha256': REPORT_SHA, 'path': files[0]['path']},
                  'prior_original_binding_audit': audit_pin, 'independent_summary': summary_pin,
                  'analysis_script_sha256': sha(Path(__file__).read_bytes())},
       'scope': 'Descriptive subset of policy-selected READ executions, paired to actually executed same-content STOP at identical source/case/seed; no randomized READ-subset causal effect or new-source/full-cost claim.',
       'delivery_scope': 'Delivered TEXT change inferred from finalizer_selected_text_sha256 under the previously admitted and byte-audited selection-to-WRITE_TEXT-to-delivery binding; not a raw delivery.json or image-byte comparison.',
       'count_order': ['known', 'true', 'false', 'unknown'], 'direction_order': ['positive', 'zero', 'negative'],
       'alignment': {'registered_contexts': 48, 'independent_source_units_full_evaluation': 16,
                     'registered_source_case_pairs': len(source_case), 'source_case_seed_mapping_unique': True,
                     'all_576_row_action_identities_unique_and_aligned': True, 'full_context_checks': full_context_checks,
                     'selected_READ_executions': len(selected), 'selected_distinct_contexts': len({context(p) for p in selected}),
                     'selected_distinct_sources': len({p['source_id'] for p in selected}),
                     'actual_STOP_pair_matches': len(selected), 'selected_pair_evidence_ledger_sha256': sha(canonical(selected))},
       'per_READ_arm': per_arm,
       'aggregate_counts_only': {'READ_executions': len(selected),
                                'paired_delivered_text_changed': count_flags([p['paired_delivered_text_changed'] for p in selected]),
                                'initial_selection_equals_actual_STOP_delivered_text': count_flags([p['initial_selection_equals_actual_STOP_delivered_text'] for p in selected]),
                                'attribution_counts': {f: count_flags([p[f] for p in selected]) for f in FLAGS},
                                'quality_directions': signs([p['quality_delta'] for p in selected]),
                                'task_cost_directions': signs([p['task_cost_delta'] for p in selected]),
                                'observed_task_net_directions': signs([p['observed_task_net_delta'] for p in selected]),
                                'cross_tabs': cross_tabs},
       'checks': {**dict(CHECKS), 'mismatches': 0},
       'limits': {'original_REPORT_modified': False, 'original_null_terminal_quality_change_preserved': True,
                  'semantic_information_gain_known': False, 'native_artifacts_reread': False,
                  'actors_or_models_executed': False, 'OCR_or_scores_rerun': False,
                  'selected_subset_source_means_use_only_sources_with_selected_READ': True,
                  'selected_subset_means_are_not_full_48_context_policy_effects': True}}
path = ROOT / 'run-v2-formal-read-paired-effects.json'
with path.open('x') as stream:
    json.dump(out, stream, sort_keys=True, indent=2, allow_nan=False)
    stream.write('\n')
print(json.dumps({'path': str(path), 'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size,
                  'checks': out['checks'], 'aggregate': out['aggregate_counts_only'],
                  'per_arm': {k: {f: v[f] for f in ('READ_pairs', 'selected_source_count', 'paired_delivered_text_changed', 'quality_delta', 'observed_task_net_delta')} for k, v in per_arm.items()}}, sort_keys=True))
