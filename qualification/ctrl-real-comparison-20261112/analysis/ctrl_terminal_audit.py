"""Read-only stdlib binding audit; never imports the project or reruns scoring."""

import collections
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys

ROOT = Path('/home/qq/ctrl-real-study-20261112-1333/run-v2')
SOURCE = '3c94ea8252619ba3fa1f1821bef96a7f2b7f66fd'
REPORT_SHA = '968b1d462dcc6afc3c51ecf34f17c05c59762c2d9cda889054d10cb87c48e41a'
FROZEN_SHA = 'f75c44d6092aa1a91af1db859823a7d1e20d9219016d00ce69b843ac5d462325'
CONTRACTS = {
    'scripts/ctrl_macro_factorial.py': '31431f1dc3304b841f54e1e4c321ab065c2216c4664710abd42d8d06a79cd3f7',
    'scripts/ctrl_macro_study.py': '12f118fc1be4f904119e224466124b7599bea6bc8a3496b2bdf8c0da289be5b0',
    'scripts/ndu_real_runtime/content_identity.py': '56885e92be48f5460dc1ccdc9a33d974fa77aacc3590da06cb86bd93bb0d130a',
    'scripts/ndu_real_runtime/macro_execution.py': '7861ccbdf09a6181c577c36f6bae5abb782b0ffc8246b31532c19a8e2741133b',
    'scripts/ndu_real_runtime/macro_execution_plan.py': '6ea407e2ac35fccebbb4179e50e4c9b7c0e22b2fdd9bdfa74472bc1b8f7d7506',
    'scripts/ndu_real_runtime/macro_realization.py': 'dc72412f60e449e68d99e592299f6f6e2148d10aaf4411cab6137f9f50c8fbfb',
    'scripts/ndu_real_runtime/metacontrol_macro_contract.py': '6fb926e56ef82b85ab28e9b64861c398a567f029d316dcb35b7a3a782e2f35ea',
}
METHODS = ('STOP', 'light', 'tuned-fixed', 'point', 'unconditional', 'conditional')
MODES = ('frozen', 'adapted')
SEQUENCES = {'STOP': ['WRITE_TEXT', 'STOP'], 'READ': ['PREPARE_ROI', 'READ_ROI', 'WRITE_TEXT', 'STOP']}
INITIAL = ('candidate_features', 'candidate_metadata', 'public_features', 'public_metadata', 'remaining_seconds', 'memory_sha256', 'weights_sha256', 'legal_actions')
FRONTIER = ('initial_packet_sha256', 'source_sha256', 'evaluator_sha256', 'rubric_sha256', 'latency_tariff')
COUNTS = collections.Counter()
ISSUES = []
ISSUE_COUNTS = collections.Counter()
FILES = {}


class Mismatch(Exception):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return sha(canonical(value))


def need(value, message):
    if not value:
        raise Mismatch(message)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def parse(raw):
    def unique(items):
        result = dict(items)
        need(len(result) == len(items), 'duplicate_json_key')
        return result

    def invalid(value):
        raise Mismatch('nonfinite_json_number:' + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def raw_file(path, limit=32 * 1024 * 1024):
    path = Path(path)
    need(path.is_absolute() and '..' not in path.parts, 'unsafe_absolute_path')
    for parent in [*reversed(path.parents), path]:
        need(not stat.S_ISLNK(parent.lstat().st_mode), 'symlink_path')
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        need(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'not_regular_single_link')
        need(0 < before.st_size <= limit, 'file_size_bound')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    signature = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
    need(signature(before) == signature(after) and len(raw) == before.st_size, 'file_changed_during_read')
    key = str(path)
    pin = sha(raw)
    need(key not in FILES or FILES[key] == pin, 'file_changed_between_reads')
    FILES[key] = pin
    return raw


def read(path, expected=None):
    raw = raw_file(path)
    if expected is not None:
        need(sha(raw) == expected, 'raw_sha256_mismatch:' + Path(path).name)
    return parse(raw), raw


def bound(root, pin):
    need(type(pin) is dict and set(pin) == {'path', 'bytes', 'sha256'}, 'bound_fields')
    name = Path(pin['path'])
    need(not name.is_absolute() and '..' not in name.parts, 'unsafe_relative_binding')
    raw = raw_file(root / name)
    need(type(pin['bytes']) is int and len(raw) == pin['bytes'] and sha(raw) == pin['sha256'], 'bound_bytes_sha256')
    COUNTS['optional_artifacts_bound'] += 1
    return raw


def issue(kind, stage, error):
    ISSUE_COUNTS[kind] += 1
    if len(ISSUES) < 16:
        ISSUES.append({'kind': kind, 'stage': stage, 'error': str(error)[:240]})


def context_key(context):
    need(type(context['seed']) is int and context['seed'] >= 0, 'context_seed')
    return tuple(context[k] for k in ('source_id', 'case_id', 'seed'))


def schedule(cases):
    arms = [(mode, policy) for policy in METHODS for mode in MODES]
    order = sorted(range(len(cases)), key=lambda i: sha(json.dumps([20261112, *context_key(cases[i])], separators=(',', ':')).encode()))
    return [{'context_index': i, 'mode': mode, 'policy': policy}
            for row, i in enumerate(order)
            for position in (0, 1, 11, 2, 10, 3, 9, 4, 8, 5, 7, 6)
            for mode, policy in [arms[(position + row) % 12]]]


def mean(values):
    grouped = collections.defaultdict(list)
    for context, value in values.items():
        grouped[context[0]].append(value)
    return None if not grouped else math.fsum(math.fsum(v) / len(v) for v in grouped.values()) / len(grouped)


def stats(values, total):
    average = mean(values)
    return {'contexts': len(values), 'sources': len({k[0] for k in values}),
            'primary': average if len(values) == total else None, 'observed_subset': average,
            'direction_counts': [sum(v > 0 for v in values.values()), sum(v == 0 for v in values.values()), sum(v < 0 for v in values.values())]}


def audit_native(directory, operation, context, arm, plan, registered, realization, terminal):
    native = directory / 'native'
    profile = plan['profiles'][arm['arm_id']]
    config, case = plan['config'], registered['case']
    macro = realization['macro']
    need(macro in SEQUENCES, 'realization_macro')
    actions = SEQUENCES[macro]
    snapshot = 'delivery-%02d' % len(actions)
    required = {'launch.json', 'trajectory.json', 'result.json', snapshot + '/delivery.json', snapshot + '/evaluation.json'}
    need(set(realization['artifact_sha256s']) == required, 'artifact_inventory')
    originals = {}
    for name, pin in realization['artifact_sha256s'].items():
        rel = Path(name)
        need(not rel.is_absolute() and '..' not in rel.parts, 'artifact_relative_path')
        raw = raw_file(native / rel)
        need(sha(raw) == pin, 'native_artifact_hash:' + name)
        originals[name] = raw
        COUNTS['native_artifact_hashes_checked'] += 1
    need(set(realization['optional_inputs']) == {'public_input', 'initial_public_input', 'reference'}, 'original_optional_binding_inventory')
    optional = {name: bound(native, pin) for name, pin in realization['optional_inputs'].items()}
    parsed = {name: parse(raw) for name, raw in originals.items()}
    result, launch = parsed['result.json'], parsed['launch.json']
    steps = parsed['trajectory.json']['steps']
    delivery, score = parsed[snapshot + '/delivery.json'], parsed[snapshot + '/evaluation.json']
    need(all(result[k] == expected for k, expected in {
        'original_operation_id': operation, 'case_id': case['id'], 'source_group_id': case['source_id'],
        'source_sha256': case['source_sha256'], 'model_sha256': profile['model_sha256']}.items()), 'native_registered_identity')
    need(result['terminal_status'] == terminal['native_terminal_status'] == 'Completed' and result['actions'] == actions, 'native_terminal_or_actions')
    need(terminal['native_error'] == result.get('error') and terminal['source_sha256'] == case['source_sha256'], 'terminal_native_binding')
    need(len(steps) == len(actions) and [s['action']['action'] for s in steps] == actions, 'trajectory_actions')
    need(launch['schema'] == 'ndu.real.actor-isolation.v1' and type(launch['exit_code']) is int and launch['exit_code'] == 0, 'launch_identity_or_exit')
    need(launch['enforced_before_actor_exec'] is True and launch['launcher_source_sha256'] == config['isolator_sha256'], 'recorded_isolation_identity')
    need(all(launch[k] is None for k in ('callback_error', 'protocol_error', 'limit_reason')), 'launch_error')
    wire = [line.encode() for line in launch['stdout'].split('\n') if line.strip()]
    exchanges = launch['host_exchanges']
    need(len(wire) == len(exchanges) == len(steps) + 1 and len(wire) <= 1024, 'wire_count')
    need(all(sha(raw) == item['event_sha256'] for raw, item in zip(wire, exchanges)), 'wire_event_hash')
    events = [parse(raw) for raw in wire]
    ready = events[0]
    need(ready['schema'] == 'ndu.real.actor-ready.v1' and ready['case_id'] == case['id'], 'ready_identity')
    need(ready['weights_sha256'] == profile['model_sha256'] and ready['macro_policy_sha256'] == profile['macro_policy']['sha256'], 'ready_model_policy')
    need(ready['content_identity_profile'] == 'ndu.real.content-selection.v1', 'ready_content_profile')
    public = steps[0]['controller']['macro_public_state']
    need(public['features'] == steps[0]['public_features'] and public['remaining_seconds'] == plan['action_budget_seconds'], 'initial_public_feature_budget')
    for index, (step, event) in enumerate(zip(steps, events[1:])):
        need(type(step['step']) is int and step['step'] == index and type(event['step']) is int and event['step'] == index, 'step_ordinal')
        need(event['schema'] == 'ndu.real.actor-observation.v1' and event['case_id'] == case['id'], 'event_identity')
        need({k: v for k, v in step.items() if k != 'observed_action_seconds'} == event, 'original_wire_trajectory')
        need(step['weights_sha256'] == profile['model_sha256'] and step['parameters_unchanged'] is True, 'trajectory_model_stability')
        c = step['controller']
        need(c['macro'] == macro and c['macro_policy'] == arm['policy'] and type(c['macro_step']) is int and c['macro_step'] == index, 'controller_action_identity')
        need(c['macro_deployment_sha256'] == profile['macro_policy']['sha256'] and c['macro_public_state_sha256'] == digest(public), 'controller_frozen_public_binding')
        captured = raw_file(native / ('macro-public-%02d.json' % index))
        need(sha(captured) == exchanges[index]['reply_sha256'] and len(captured) == exchanges[index]['reply_bytes'], 'captured_host_reply')
        if index == 0:
            need(captured == optional['initial_public_input'], 'initial_public_exact_bytes')
        if index == actions.index('WRITE_TEXT'):
            need(captured == optional['public_input'], 'finalizer_public_exact_bytes')
    initial = {name: steps[0][name] for name in INITIAL}
    binding = realization['comparison_binding']
    need(binding['initial_public_state_sha256'] == digest(initial), 'initial_state_digest')
    for name in ('initial_public_input', 'public_input'):
        packet = parse(optional[name])
        need(packet['schema'] == 'ndu.real.actor-step.v1' and packet['case_id'] == case['id'] and packet['forced_action'] is None, 'retained_public_identity')
        observation = packet['observation']
        rel = Path(observation['path'])
        need(not rel.is_absolute() and '..' not in rel.parts, 'observation_relative_path')
        pixels = raw_file(native / 'public' / rel)
        need(sha(pixels) == observation['sha256'], 'observation_original_bytes')
        COUNTS['observation_byte_hashes_checked'] += 1
        if name == 'initial_public_input':
            need(binding['initial_packet_sha256'] == observation['sha256'], 'physical_initial_packet_binding')
    writer = steps[actions.index('WRITE_TEXT')]
    need(delivery['schema'] == 'ndu.real.delivery.v1' and delivery['case_id'] == case['id'] and delivery['text'] == writer['action']['arguments']['text'], 'native_write_delivery')
    need(score['schema'] == 'ndu.real.independent-evaluation.v1' and score['case_id'] == case['id'], 'score_identity')
    need(score['evaluator_source_sha256'] == config['evaluator_sha256'] and score['rubric_sha256'] == config['rubric_sha256'], 'score_implementation_binding')
    need(score['delivery_sha256'] == sha(originals[snapshot + '/delivery.json']), 'score_delivery_hash')
    need(score['reference_sha256'] == case['reference']['sha256'] == sha(optional['reference']) and score['role'] == case['role'], 'score_reference_role')
    need(result['score_components'] == score and result['rubric_sha256'] == config['rubric_sha256'] and result['output_text_sha256'] == digest(delivery['text']), 'host_scored_result_binding')
    need(finite(score['quality']) and 0 <= score['quality'] <= 1 and score['quality'] == result['gross_score'] == terminal['row']['quality'], 'terminal_original_score')
    execution = realization['stages']['execution']
    need(execution['completed'] is True and execution['scored'] is True and execution['payload_delivered'] is True, 'realization_execution_flags')
    need(execution['delivery_sha256'] == sha(originals[snapshot + '/delivery.json']) and execution['evaluation_sha256'] == sha(originals[snapshot + '/evaluation.json']), 'realization_score_delivery_hashes')
    need(binding['source_sha256'] == case['source_sha256'] and binding['model_sha256'] == profile['model_sha256'], 'realization_source_model')
    need(binding['evaluator_sha256'] == config['evaluator_sha256'] and binding['rubric_sha256'] == config['rubric_sha256'] and binding['latency_tariff'] == config['latency_weight'], 'realization_evaluator_tariff')
    need(binding['scored_reference_sha256'] == score['reference_sha256'], 'realization_reference_binding')
    need(realization['case_id_sha256'] == digest(case['id']) and realization['source_group_sha256'] == digest(case['source_id']), 'realization_case_source_identity')
    COUNTS['native_bindings_verified'] += 1
    return {'source_id': context['source_id'], 'case_id': context['case_id'], 'macro': macro, 'controller': steps[0]['controller'], 'read_attribution': realization['read_attribution']}, {k: binding[k] for k in FRONTIER}


def run():
    report, report_raw = read(ROOT / 'factorial/REPORT.json', REPORT_SHA)
    need(len(report_raw) == 3108442, 'report_expected_bytes')
    frozen, _ = read(ROOT / 'factorial/FROZEN.json', FROZEN_SHA)
    need(report['schema'] == 'ctrl.content-control-factorial-report.v1' and report['factorial_sha256'] == FROZEN_SHA, 'factorial_report_identity')
    need(frozen['schema'] == 'ctrl.content-control-factorial.v1', 'factorial_freeze_schema')
    repository = Path(frozen['repository'])
    for name, expected in CONTRACTS.items():
        need(sha(raw_file(repository / name)) == expected, 'sourceJ_contract:' + name)
        COUNTS['exact_sourceJ_contract_files_checked'] += 1
    need(frozen['driver_sha256'] == CONTRACTS['scripts/ctrl_macro_factorial.py'], 'factorial_driver_sha')
    modes = {}
    for mode in MODES:
        registration = frozen['studies'][mode]
        directory = Path(registration['directory'])
        need(directory == ROOT / mode, 'registered_study_directory')
        study, _ = read(directory / 'FROZEN.json', registration['freeze_sha256'])
        need(study['driver_sha256'] == CONTRACTS['scripts/ctrl_macro_study.py'] and study['repository'] == str(repository), 'study_source_binding')
        plan, _ = read(directory / 'EXECUTION_PLAN.json')
        pin_file, _ = read(directory / 'EXECUTION_PIN.json')
        pin = pin_file['canonical_sha256']
        need(digest(plan) == pin and plan['schema'] == 'ndu.real.macro-execution-plan.v1', 'execution_plan_digest')
        actual_plan, _ = read(directory / 'evaluation/PLAN.json')
        need(actual_plan == plan, 'original_execution_plan')
        executed, _ = read(directory / 'evaluation/RUN.json')
        need(executed == {'schema': 'ndu.real.macro-execution.v1', 'plan_sha256': pin, 'evidence_kind': 'native_macro'}, 'original_native_run_identity')
        collection = study['collection_plan']
        need(plan['registered_cases'] == study['evaluation_cases'], 'registered_evaluation_roster')
        need(all(plan[k] == collection[k] for k in ('config', 'action_budget_seconds', 'source_pins')), 'registered_execution_inputs')
        need(plan['observer_sha256'] == study['observer_sha256'], 'registered_observer')
        cohort = plan['cohort']
        need(digest(cohort) == plan['cohort_sha256'] and [a['arm_id'] for a in cohort['arms']] == list(METHODS), 'six_arm_cohort_identity')
        need(cohort['contexts'] == [{k: c[k] for k in ('source_id', 'case_id', 'seed')} for c in study['evaluation_cases']], 'cohort_context_roster')
        need(set(plan['profiles']) == set(METHODS), 'six_deployment_inventory')
        for source_pin in plan['source_pins']:
            need(sha(raw_file(source_pin['path'])) == source_pin['sha256'], 'frozen_runtime_source_pin')
        checkpoint, checkpoint_raw = read(directory / 'CHECKPOINT.json', registration['checkpoint_sha256'])
        cold, _ = read(directory / 'COLD_LOAD.json')
        need(cold['checkpoint_sha256'] == registration['checkpoint_sha256'] and cold['context_sha256'] == digest(checkpoint['context']) and cold['fresh_process'] is True, 'critic_cold_load_binding')
        for arm in cohort['arms']:
            profile = plan['profiles'][arm['arm_id']]
            need({k: v for k, v in profile.items() if k != 'macro_policy'} == collection['profile'], 'executed_content_profile')
            deployment, _ = read(profile['macro_policy']['path'], profile['macro_policy']['sha256'])
            need(deployment['policy'] == arm['policy'] == arm['arm_id'] and deployment['checkpoint_utf8'] == checkpoint_raw.decode() and deployment['checkpoint_sha256'] == registration['checkpoint_sha256'], 'deployment_policy_critic_binding')
            need(deployment['weights_sha256'] == profile['model_sha256'] == arm['content_sha256'], 'deployment_weight_identity')
            need(deployment['read_seconds_bound'] == study['read_seconds_bound'] and deployment['finalizer_seconds_reserve'] == study['finalizer_seconds_reserve'], 'deployment_bound_identity')
            need(arm['critic_context_sha256'] == digest(checkpoint['context']), 'arm_critic_context_identity')
            need(sha(raw_file(profile['weights'])) == profile['model_sha256'], 'actual_weight_file_pin')
        modes[mode] = (directory, study, plan, pin)
        COUNTS['mode_plans_verified'] += 1
    cases = modes['frozen'][1]['evaluation_cases']
    need(cases == modes['adapted'][1]['evaluation_cases'], 'same_content_contexts')
    keys = [context_key(c) for c in cases]
    need(len(keys) == 48 and len(set(keys)) == 48 and len({k[0] for k in keys}) == 16, '48_contexts_16_sources')
    need(set(collections.Counter(k[0] for k in keys).values()) == {3}, 'three_contexts_per_source')
    expected_schedule = schedule(cases)
    need(frozen['execution_order'] == expected_schedule and len(expected_schedule) == 576, 'frozen_Williams_schedule')
    combined = parse(canonical(modes['frozen'][2]['cohort']))
    combined.update(arms=[], one_off_costs={}, factorial=frozen['factorial'])
    for mode in MODES:
        c = modes[mode][2]['cohort']
        need(all(c[k] == combined[k] for k in ('contexts', 'partitions', 'shared')), 'common_factorial_frontier_plan')
        for arm in c['arms']:
            name = mode + '/' + arm['arm_id']
            combined['arms'].append({**arm, 'arm_id': name, 'content_mode': 'off' if mode == 'frozen' else 'on'})
            combined['one_off_costs'][name] = c['one_off_costs'][arm['arm_id']]
    need(report['plan'] == combined, 'combined_report_plan')
    indexed = {}
    for row in report['rows']:
        key = (row['arm_id'], context_key(row))
        need(key not in indexed, 'duplicate_report_row')
        indexed[key] = row
    expected_keys = {(mode + '/' + policy, key) for mode in MODES for policy in METHODS for key in keys}
    need(set(indexed) == expected_keys and len(indexed) == 576, 'full_576_report_rows')
    starts, verified_rows, frontiers = [], {}, collections.defaultdict(list)
    actions = collections.defaultdict(list)
    for mode, (directory, study, plan, pin) in modes.items():
        contexts = plan['cohort']['contexts']
        roster = [('macro-' + digest([pin, context, arm['arm_id']]), context, arm) for context in contexts for arm in plan['cohort']['arms']]
        root = directory / 'evaluation'
        need(not ({p.name for p in root.iterdir()} - {'PLAN.json', 'RUN.json', *(op for op, _, _ in roster)}), 'unregistered_operation_directory')
        cases_by_key = {context_key(c): c for c in study['evaluation_cases']}
        for operation, context, arm in roster:
            COUNTS['planned_executions'] += 1
            name = mode + '/' + arm['arm_id']
            key = context_key(context)
            op_root = root / operation
            try:
                need(not ({p.name for p in op_root.iterdir()} - {'START.json', 'TERMINAL.json', 'REALIZATION.json', 'native'}), 'unknown_operation_artifact')
                start, start_raw = read(op_root / 'START.json')
                need(start == {'schema': 'ndu.real.macro-start.v1', 'plan_sha256': pin, 'operation_id': operation, 'context': context, 'arm_id': arm['arm_id'], 'evidence_kind': 'native_macro', 'time_ns': start['time_ns']}, 'original_start_identity')
                need(type(start['time_ns']) is int and start['time_ns'] > 0, 'positive_integer_start_clock')
                starts.append((start['time_ns'], {'context_index': keys.index(key), 'mode': mode, 'policy': arm['arm_id']}))
                COUNTS['starts_verified'] += 1
                terminal, _ = read(op_root / 'TERMINAL.json')
                need(set(terminal) == {'schema', 'start_sha256', 'row', 'elapsed_seconds', 'full_cost_observed', 'native_terminal_status', 'native_error', 'source_sha256', 'runner_error'}, 'terminal_closed_fields')
                actual = terminal['row']
                invariant = {**context, 'arm_id': arm['arm_id'], 'execution_id': operation, 'shared_sha256': digest(plan['cohort']['shared']), 'content_sha256': arm['content_sha256'], 'critic_context_sha256': arm['critic_context_sha256'], 'full_cost_observed': False, 'evidence_kind': 'native_macro'}
                need(all(actual[k] == value for k, value in invariant.items()), 'terminal_row_identity')
                need(terminal['schema'] == 'ndu.real.macro-terminal.v1' and terminal['start_sha256'] == sha(start_raw), 'terminal_original_start_hash')
                need(terminal['full_cost_observed'] is False and actual['status'] == 'COMPLETED' and terminal['runner_error'] is None, 'terminal_status')
                need(finite(terminal['elapsed_seconds']) and terminal['elapsed_seconds'] >= 0 and actual['task_cost'] == terminal['elapsed_seconds'] * plan['config']['latency_weight'], 'observed_task_cost_exact')
                need({**actual, 'arm_id': name} == indexed[(name, key)], 'terminal_original_report_row')
                COUNTS['terminals_verified'] += 1
                realization, _ = read(op_root / 'REALIZATION.json', actual['evidence_sha256'])
                need(realization['schema'] == 'ndu.real.macro-realization.v1' and realization['operation_id'] == operation and realization['observer_source_sha256'] == plan['observer_sha256'], 'realization_operation_observer')
                need(realization['stages']['execution']['quality'] == actual['quality'], 'realization_terminal_quality')
                action, frontier = audit_native(op_root, operation, context, arm, plan, cases_by_key[key], realization, terminal)
                need(all(v is not None for v in frontier.values()), 'unknown_physical_frontier')
                frontiers[key].append(frontier)
                actions[name].append(action)
                verified_rows[(name, key)] = actual
                COUNTS['realizations_verified'] += 1
            except Mismatch as error:
                issue('mismatch', operation, error)
            except (OSError, KeyError, TypeError, ValueError, IndexError) as error:
                issue('UNKNOWN', operation, error)
    clocks = [t for t, _ in starts]
    need(len(clocks) == len(set(clocks)), 'duplicate_start_clocks')
    ordered = [entry for _, entry in sorted(starts, key=lambda x: x[0])]
    need(ordered == frozen['execution_order'][:len(ordered)], 'original_start_order_prefix')
    need(type(frozen['time_ns']) is int and min(clocks) > frozen['time_ns'], 'freeze_precedes_first_actor')
    need(report['execution_order']['verified_started_prefix'] == len(starts), 'report_start_prefix_count')
    COUNTS['original_start_order_prefix_verified'] = len(starts)
    for key, values in frontiers.items():
        need(all(value == values[0] for value in values), 'cross_arm_physical_frontier')
        if len(values) == 12:
            COUNTS['contexts_with_all_12_physical_frontiers_verified'] += 1
    need(set(report['observed_actions']) == {mode + '/' + policy for mode in MODES for policy in METHODS}, 'observed_action_arm_roster')
    for name, values in actions.items():
        if len(values) == 48:
            need(collections.Counter(map(digest, values)) == collections.Counter(map(digest, report['observed_actions'][name])), 'original_observed_action_multiset:' + name)
            COUNTS['complete_arm_action_multisets_verified'] += 1
    arms = {}
    for mode in MODES:
        for policy in METHODS:
            name = mode + '/' + policy
            values = {key: row for (arm, key), row in verified_rows.items() if arm == name}
            baseline = {key: row for (arm, key), row in verified_rows.items() if arm == mode + '/STOP'}
            common = set(values) & set(baseline)
            qualities = {key: row['quality'] for key, row in values.items()}
            nets = {key: row['quality'] - row['task_cost'] for key, row in values.items()}
            qdiff = {key: values[key]['quality'] - baseline[key]['quality'] for key in common}
            ndiff = {key: (values[key]['quality'] - values[key]['task_cost']) - (baseline[key]['quality'] - baseline[key]['task_cost']) for key in common}
            diffs = {'quality': stats(qdiff, 48), 'observed_task_cost_net': stats(ndiff, 48)}
            if policy != 'STOP':
                original = [c for c in report['cohort']['paired_contrasts'] if {c['candidate'], c['baseline']} == {name, mode + '/STOP'}]
                need(len(original) == 1, 'stored_pair_identity')
                orientation = 1 if original[0]['candidate'] == name else -1
                for metric, observed in diffs.items():
                    stored = original[0][metric]
                    if observed['primary'] is not None:
                        need(finite(stored['source_equal_difference']) and math.isclose(observed['primary'], orientation * stored['source_equal_difference'], rel_tol=0, abs_tol=1e-12), 'stored_pair_mean:' + name + ':' + metric)
                        need(stored['paired_contexts'] == 48 and stored['paired_sources'] == 16, 'stored_pair_denominator')
                        COUNTS['stored_pair_metric_means_verified'] += 1
            arms[name] = {'planned': 48, 'original_bindings_verified': len(values), 'UNKNOWN_original_bindings': 48 - len(values),
                          'quality_source_equal': mean(qualities), 'observed_task_cost_net_source_equal': mean(nets),
                          'actions': dict(collections.Counter(a['macro'] for a in actions[name])),
                          'reason_counts': dict(collections.Counter(a['controller']['reason'] for a in actions[name])),
                          'minus_same_content_STOP': diffs}
    return {'arms': arms, 'planned_contexts': 48, 'independent_sources': 16, 'planned_executions': 576,
            'report_sha256': REPORT_SHA, 'factorial_sha256': FROZEN_SHA,
            'original_start_order_rechecked': len(starts) == 576,
            'all_native_receipt_bindings_verified': len(verified_rows) == 576,
            'all_contexts_have_equal_12_arm_physical_frontiers': COUNTS['contexts_with_all_12_physical_frontiers_verified'] == 48}


output = {'schema': 'ctrl.independent-original-terminal-audit.v1', 'source_commit': SOURCE,
          'scope': 'Read-only stdlib original START/TERMINAL/REALIZATION, native wire/delivery/scorer receipt and file-hash binding audit; no project imports or execution.',
          'limits': {'rescored': False, 'ocr_rerun': False, 'models_loaded': False, 'actors_launched': False, 'run_files_modified': False,
                     'native_owner_authenticated': False, 'image_decodability_rechecked': False,
                     'semantic_read_attribution_recomputed': False, 'full_cost_benefit_established': False,
                     'excluded_costs': ['provider', 'energy', 'fit', 'calibration', 'tuning'], 'new_source_confirmation': False,
                     'observed_net': 'original TERMINAL quality minus measured task_cost; paired within context, then equal source means'},
          'direction_count_order': ['positive', 'zero', 'negative']}
try:
    output.update(run())
except Mismatch as error:
    issue('mismatch', 'global', error)
except (OSError, KeyError, TypeError, ValueError, IndexError) as error:
    issue('UNKNOWN', 'global', error)
output.update(counts=dict(COUNTS), mismatch_count=ISSUE_COUNTS['mismatch'], unknown_count=ISSUE_COUNTS['UNKNOWN'],
              issue_samples=ISSUES, files_read=len(FILES), file_hash_manifest_sha256=digest(FILES))
output['audit_status'] = 'PASS' if not ISSUE_COUNTS and COUNTS['native_bindings_verified'] == 576 else 'INCOMPLETE_OR_MISMATCH'
print(json.dumps(output, sort_keys=True, separators=(',', ':'), allow_nan=False), flush=True)
sys.exit(0 if output['audit_status'] == 'PASS' else 3)
