"""Read-only, pinned post-run audit. Prints hashes/metadata, never delivered text.

Runs no task models and does not rescore outputs or confer native authority.
The candidate replay verifier is reused only after its complete source manifest
is checked; all artifact bindings and roster/cost cross-checks are independent.
"""

import base64
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import traceback

BASE = Path('/home/qq/ndu-runtime-meter-v2-20261107-673721095449')
ORIGINAL = Path('/home/qq/ndu-real-runtime-20261107-bc2efaf10cd0/pilot-run-v1')
SPECS = [
    (BASE, '1a1b852687c-12894-e4f',
     'a05f5b15466c7e355dd97a124879d59d0ce1d8dee08023a181d3684634936e91',
     '4ccdeb67700949cc6ecc2eb4e53e488fafd0dbe7c760f4b34c1a5c201d062fbd'),
    (Path(str(BASE) + '-attempt02'), '1a1b85a7c49-12894-e9e',
     'b03848dfd0f0cce23bb6592903561283e67ac7ef8d82b6fe5b7398100139d5d0',
     'fb739608629e7723b6098a43f9a8475074ae6cfe85e32b878e8d8f61e73eb113'),
]
PINS = {
    'PILOT_PLAN.json': '139a8c0ce912f4eadb62d80463674ac7295b04fad4c455296654ec7630946880',
    'selected-sources.json': 'bf743708f668815f907ee7e574e4b90d8ef82aa98318eef2210a3505faccc4ca',
    'selection-lock.json': '410cc42b2ea09a9532963d5fa67b5e248af55ab86d3b1ffbd274edbcc3dec0ef',
}
FAMILIES = {'text_sufficient', 'text_image_complementary', 'selective_refinement',
            'preparation_required', 'continuation_not_worthwhile'}
FILES, SEEN_METERS = {}, set()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(value):
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


def read(path, expected=None, limit=32 * 1024 * 1024):
    path = Path(path)
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'Invalid regular file: ' + str(path))
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    require(identity(before) == identity(after) == identity(path.lstat()), 'File changed during read: ' + str(path))
    digest = sha(raw)
    require(expected is None or digest == expected, 'File SHA256 mismatch: ' + str(path))
    previous = FILES.get(str(path))
    require(previous is None or previous['identity'] == identity(after), 'File changed between reads: ' + str(path))
    FILES[str(path)] = {'identity': identity(after), 'sha256': digest, 'bytes': len(raw)}
    return raw


def hash_file(path, expected=None):
    path = Path(path)
    cached = FILES.get(str(path))
    if cached:
        require(cached['identity'] == identity(path.lstat()), 'Pinned file changed: ' + str(path))
        digest = cached['sha256']
    else:
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
            before = os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode), 'Not a regular file: ' + str(path))
            value = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                value.update(block)
            after = os.fstat(stream.fileno())
        require(identity(before) == identity(after) == identity(path.lstat()), 'File changed while hashing: ' + str(path))
        digest = value.hexdigest()
        FILES[str(path)] = {'identity': identity(after), 'sha256': digest, 'bytes': after.st_size}
    require(expected is None or digest == expected, 'Pinned hash mismatch: ' + str(path))
    return digest


def strict(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda value: require(False, 'Nonfinite JSON'))


def document(path, expected=None):
    return strict(read(path, expected))


def within(root, relative):
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts, 'Unsafe bound relative path')
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()), 'Bound artifact escapes root')
    return path


def bound(root, binding):
    path = within(root, binding['path'])
    raw = read(path, binding['sha256'])
    require(len(raw) == binding['bytes'], 'Bound byte count differs: ' + str(path))
    return path, raw


def near(a, b, label):
    require(type(a) in (int, float) and type(b) in (int, float)
            and math.isfinite(a) and math.isfinite(b) and abs(a-b) < 1e-8, label)


def journal(receipt, path):
    record = record_from_jsonl(read(path))
    replay = verify_record(record, expected_sha256=receipt['raw_spans_sha256'])
    require(replay['valid'] and record == receipt['raw_spans'], 'Raw journal differs from receipt: ' + str(path))
    meter_id = replay['header']['meter_id']
    require(meter_id not in SEEN_METERS, 'Duplicate meter identity across inventory')
    SEEN_METERS.add(meter_id)
    return replay


def meter_check(result, output, trajectory, second):
    meter = result['deployment_meter']
    host = journal(meter, output / 'deployment.meter.jsonl')
    require(host['complete_record'], 'Host meter is not terminal')
    status = {'Completed': 'SUCCEEDED', 'BudgetStop': 'BUDGET_STOP', 'Failed': 'FAILED'}[result['terminal_status']]
    require(host['envelope']['status'] == status, 'Host terminal status differs')
    actors = actor_receipts([step['meter'] for step in trajectory['steps']], output / 'actor-output')
    actor_bindings = []
    for actor in actors:
        replay = verify_record(actor['raw_spans'], expected_sha256=actor['raw_spans_sha256'])
        suffix = replay['header']['operation_id'].rsplit('/decision/', 1)[1]
        path = output / 'actor-output' / ('decision-' + suffix + '.meter.jsonl')
        journal(actor, path)
        actor_bindings.append({'path': str(path), 'sha256': hash_file(path),
                               'record_sha256': actor['raw_spans_sha256'],
                               'complete_record': replay['complete_record'],
                               'event_count': len(actor['raw_spans']['events'])})
    base = {**meter, 'wall_seconds': host['envelope']['inclusive_wall_ns'] / 1e9}
    replayed = reconcile(base, actors)
    tail_wall = tail_cpu = 0.0
    require(('observer_tail' in meter) == second, 'Observer-tail version differs from frozen attempt')
    if second:
        tail = meter['observer_tail']
        last = host['envelope']
        require(sha(canonical(tail)) == meter['observer_tail_sha256'], 'Observer-tail digest differs')
        require(tail['parent_record_sha256'] == meter['raw_spans_sha256']
                and tail['process_id'] == host['header']['process_id']
                and tail['start_monotonic_ns'] == last['end_monotonic_ns']
                and tail['start_process_time_ns'] == last['end_process_time_ns']
                and tail['category'] == 'UNKNOWN', 'Observer-tail origin differs')
        tail_wall = (tail['end_monotonic_ns'] - tail['start_monotonic_ns']) / 1e9
        tail_cpu = (tail['end_process_time_ns'] - tail['start_process_time_ns']) / 1e9
        require(min(tail_wall, tail_cpu) >= 0, 'Observer-tail clock regression')
    require(meter['interval_reconciliation'] == replayed['interval_reconciliation']
            and meter['actor_record_sha256s'] == replayed['actor_record_sha256s'], 'Replayed actor binding differs')
    for category in CATEGORIES:
        near(meter['costs'][category], replayed['costs'][category], 'Category replay differs: ' + category)
    near(meter['wall_seconds'], base['wall_seconds'] + tail_wall, 'Deployment wall replay differs')
    near(meter['cpu_seconds'], replayed['cpu_seconds'] + tail_cpu, 'Deployment CPU replay differs')
    near(meter['observed_unclassified_overhead_seconds'],
         replayed['observed_unclassified_overhead_seconds'] + tail_wall, 'UNKNOWN replay differs')
    near(sum(meter['costs'].values()) + meter['observed_unclassified_overhead_seconds'],
         meter['wall_seconds'], 'Exclusive partition does not close')
    require(meter['energy_joules'] is None and meter['provider_charges'] is None
            and meter['full_physical_cost_complete'] is False, 'Unsupported physical cost claim')
    return host, actor_bindings, tail_wall, tail_cpu


def aggregate(rows):
    result = {'attempts': len(rows), 'terminal_counts': dict(Counter(row['terminal_status'] for row in rows))}
    for key in ('deployment_wall_seconds', 'deployment_observed_cpu_seconds', 'deployment_unknown_seconds',
                'observer_tail_wall_seconds', 'observer_tail_own_cpu_seconds', 'outer_wall_seconds',
                'outer_task_and_reaped_children_cpu_seconds', 'external_evaluation_wall_seconds'):
        result[key] = math.fsum(row[key] for row in rows)
    result['exclusive_category_wall_seconds'] = {
        key: math.fsum(row['exclusive_category_wall_seconds'][key] for row in rows) for key in CATEGORIES}
    result['nonadditive_scopes'] = 'Deployment and evaluation are nested inside outer task; do not sum them with outer costs.'
    result['sum_is_elapsed_campaign_time'] = False
    return result


def main():
    global CATEGORIES, record_from_jsonl, verify_record, actor_receipts, reconcile
    manifests = []
    for base, job, manifest_pin, result_pin in SPECS:
        manifest = document(base / 'code/CODE_MANIFEST.json', manifest_pin)
        for binding in manifest['files']:
            bound(base / 'code', binding)
        require(len(manifest['files']) == 30, 'Unexpected source manifest size')
        manifests.append({'root': str(base), 'native_job_id': job, 'sha256': manifest_pin, 'files': manifest['files']})
    sys.path.insert(0, str(SPECS[1][0] / 'code/scripts'))
    from ndu_real_runtime.span_meter import CATEGORIES, record_from_jsonl, verify_record
    from ndu_real_runtime.interval_costs import actor_receipts, reconcile
    plan = document(ORIGINAL / 'PILOT_PLAN.json', PINS['PILOT_PLAN.json'])
    selected = document(ORIGINAL / 'selected-sources.json', PINS['selected-sources.json'])
    lock = document(ORIGINAL / 'selection-lock.json', PINS['selection-lock.json'])
    for binding in plan['source_pins']:
        require(len(read(binding['path'], binding['sha256'])) == binding['bytes'], 'Original source byte count changed')
    source = sorted(selected['groups']['pilot_new'])[0]
    cases = {row['task_family']: row for row in selected['cases']['pilot_new'] if row['source_id'] == source}
    require(set(cases) == FAMILIES and all(row['role'] == 'development' for row in cases.values()), 'Development roster differs')
    fit = plan['independent_fit_roster'][0]['fit_id']
    profiles = {(row['profile']['regime'], row['profile']['arm']): row['profile']
                for row in lock['selected'] if row['profile']['fit_id'] == fit}
    expected = {(regime, arm, family) for regime, arm in profiles for family in FAMILIES}
    require(len(profiles) == 24 and len(expected) == 120, 'Wrong profile denominator')
    config = plan['execution']
    material = Path(config['material_root'])
    reference_index = document(material / 'private/reference-index.v2.json', config['reference_index_sha256'])
    rubric_path, _ = bound(material, reference_index['rubric'])
    hash_file(rubric_path, config['rubric_sha256'])
    require(plan['confirmation_actor_access_authorized'] is False and plan['adoption_authorized'] is False, 'Original boundary changed')
    inventory, runs, first_by_key = [], [], {}
    for number, (base, job, manifest_pin, result_pin) in enumerate(SPECS, 1):
        root = base / 'diagnostic-run-v1'
        summary = document(root / 'DIAGNOSTIC_RESULT.json', result_pin)
        contract = document(root / 'DIAGNOSTIC_CONTRACT.json')
        require(all(summary[key] == value for key, value in contract.items()), 'Contract and result differ')
        require(summary['code_manifest_sha256'] == manifest_pin and summary['source_group_id'] == source
                and summary['fit_id'] == fit and summary['planned_episodes'] == 120
                and summary['observed_episodes'] == 120 and summary['profile_count'] == 24
                and summary['budgets'] == plan['design']['budgets'], 'Diagnostic denominator/pins/budget differ')
        require(summary['original_plan_sha256'] == PINS['PILOT_PLAN.json']
                and summary['original_selected_sha256'] == PINS['selected-sources.json']
                and summary['original_lock_sha256'] == PINS['selection-lock.json'], 'Original input pins differ')
        require(summary['model_fits'] == 0 and summary['scientific_admission'] == 'HOLD'
                and summary['confirmation_access_authorized'] is False and summary['adoption_authorized'] is False
                and summary['full_physical_cost_complete'] is False, 'Diagnostic authority/scope changed')
        episode_code = read(base / 'code/scripts/ndu_real_runtime/episode.py').decode()
        require('max_output_bytes=4 * 1024 * 1024' in episode_code
                and 'if step >= 8 or remaining <= 0:' in episode_code, 'Output/action budget marker changed')
        hash_file(base / 'code/scripts/ndu_real_materials/evaluator.py', config['evaluator_sha256'])
        phase = document(root / 'qualification/phase-result.json', summary['phase_result_sha256'])
        admitted = document(root / 'qualification/admitted-inventory.json')
        require(phase['planned'] == phase['dispatched'] == phase['completed_or_unresolved'] == 120
                and not phase['not_started_requests'] and not summary['not_started_requests'], 'Incomplete phase denominator')
        require(admitted['maximum_workers'] == phase['maximum_workers'] == plan['design']['budgets']['max_workers']
                and admitted['admission_deadline_seconds'] == phase['admission_deadline_seconds']
                == plan['design']['budgets']['phase_wall_seconds'], 'Scheduler budget differs')
        admitted_map = {Path(item['request']).name: item for item in admitted['planned']}
        require(len(admitted_map) == len(admitted['planned']) == 120, 'Duplicate admitted request')
        phase_map = {item['attempt']['original_operation_id']: item for item in phase['attempts']}
        require(len(phase_map) == len(phase['attempts']) == 120, 'Duplicate/unresolved phase attempt')
        require({path.name for path in (root / 'qualification/requests').glob('*.json')} == set(admitted_map), 'Extra/missing request file')
        require(len(list((root / 'episodes').glob('*/result.json'))) == 120, 'Extra/missing episode result')
        run_rows, keys = [], set()
        for binding in summary['bindings']:
            output = within(root, binding['relative_output'])
            result = document(output / 'result.json', binding['result_sha256'])
            attempt = document(output / 'original-attempt.json', binding['attempt_sha256'])
            key = (result['regime'], result['arm'], result['task_family'])
            require(key in expected and key not in keys, 'Extra/duplicate roster tuple')
            keys.add(key)
            operation = 'meter-v2-' + sha(canonical([summary['run_id'], *key]))[:32]
            require(operation == result['original_operation_id'] == attempt['original_operation_id'], 'Operation identity differs')
            require(attempt['result_sha256'] == binding['result_sha256']
                    and attempt['terminal_status'] == result['terminal_status'], 'Outer receipt differs')
            request_path = root / 'qualification/requests' / (operation + '.json')
            require(admitted_map[request_path.name]['sha256'] == attempt['request_sha256'], 'Admission/request pin differs')
            request = document(request_path, attempt['request_sha256'])
            original_profile = profiles[key[:2]]
            predecessor = first_by_key.get(key) if number == 2 else None
            expected_profile = {**original_profile, 'original_operation_id': operation,
                                'retry_of': predecessor['original_operation_id'] if predecessor and predecessor['terminal_status'] == 'Failed' else None,
                                'original_policy_sha256': original_profile['policy_sha256'],
                                'policy_sha256': sha(canonical({'controller': original_profile['controller'],
                                    'control_plan_sha256': original_profile['control_plan_sha256'],
                                    'diagnostic_code_manifest_sha256': manifest_pin}))}
            if predecessor:
                expected_profile['instrumentation_predecessor_operation_id'] = predecessor['original_operation_id']
            require(request['profile'] == expected_profile
                    and all(result[k] == value for k, value in expected_profile.items()), 'Frozen profile or predecessor differs')
            expected_config = {**config, 'repository_root': str(base / 'code'), 'scripts_root': str(base / 'code/scripts'),
                               'runtime_roots': [str(base / 'code') if p == config['repository_root'] else p for p in config['runtime_roots']]}
            case = cases[key[2]]
            require(request['config'] == expected_config and request['case'] == case and request['output'] == str(output)
                    and request['training'] is False, 'Request model/material/config scope differs')
            require(phase_map[operation]['attempt'] == attempt and phase_map[operation]['output'] == str(output), 'Phase original receipt differs')
            require(attempt['retry_of'] == expected_profile['retry_of'], 'Outer retry identity differs')
            model_sha = hash_file(original_profile['weights'], original_profile['model_sha256'])
            control_sha = hash_file(original_profile['control_plan'], original_profile['control_plan_sha256'])
            training_sha = hash_file(Path(original_profile['weights']).parent / 'receipt.json', original_profile['training_receipt_sha256'])
            _, packet = bound(material, case['packet'])
            require(read(output / 'public/case.json') == packet, 'Actor public packet differs')
            reference_path, reference_raw = bound(material, case['reference'])
            reference = strict(reference_raw)
            require(reference['role'] == result['split'] == 'development' and result['source_group_id'] == source
                    and reference['case_id'] == result['case_id'] == case['id'], 'Source/role/case differs')
            source_path, _ = bound(material, reference['source_image'])
            hash_file(source_path, result['source_sha256'])
            snapshots = sorted(output.glob('delivery-*/delivery.json'))
            require(bool(snapshots), 'No actual delivery')
            delivery_path = snapshots[-1]
            delivery = document(delivery_path)
            text_sha = sha(canonical(delivery['text']))
            require(text_sha == result['output_text_sha256'], 'Actual delivered text digest differs')
            image_path, image_sha = None, None
            if delivery['image'] is not None:
                image_path, _ = bound(delivery_path.parent, delivery['image'])
                image_sha = hash_file(image_path)
            require(image_sha == result['output_image_sha256'], 'Actual delivered image digest differs')
            trajectory = document(output / 'trajectory.json')
            launch = document(output / 'launch.json')
            require(len(result['actions']) <= 8 and len(trajectory['steps']) == len(result['actions']), 'Action budget/trajectory differs')
            require(launch['enforced_before_actor_exec'] and launch['launch_receipt']['no_new_privileges']
                    and launch['launch_receipt']['filesystem_default'] == 'DENY'
                    and launch['launch_receipt']['network'] == 'DENY', 'Isolation receipt is absent or changed')
            hash_file(base / 'code/scripts/ndu_real_materials/isolate.py', launch['launcher_source_sha256'])
            stdout_bytes = len(launch['stdout'].encode())
            status = result['terminal_status']
            if status == 'Failed':
                require(number == 1 and key[2] == 'preparation_required' and key[1] in {'B', 'D', 'mpc', 'mpc_hepta'}
                        and launch['limit_reason'] == 'output_limit' and launch['exit_code'] == -9
                        and stdout_bytes > 4 * 1024 * 1024, 'Unexpected failed original')
            else:
                require(launch['exit_code'] == 0 and launch['limit_reason'] is None
                        and launch['callback_error'] is None, 'Successful episode launch is inconsistent')
            host, actor_bindings, tail_wall, tail_cpu = meter_check(result, output, trajectory, number == 2)
            evaluations = sorted(output.glob('delivery-*/evaluation.json'))
            score_path, eval_wall, score_sha = None, 0.0, None
            if status == 'Failed':
                require(not evaluations and 'evaluation_meter' not in result and not (output / 'evaluation-meter.json').exists(), 'Unexpected failed scorer inventory')
            else:
                require(evaluations == [delivery_path.parent / 'evaluation.json'], 'Missing/extra terminal scorer receipt')
                score_path = evaluations[0]
                score = document(score_path)
                score_sha = hash_file(score_path)
                require(score == result['score_components'] and score['delivery_sha256'] == hash_file(delivery_path)
                        and score['reference_sha256'] == hash_file(reference_path)
                        and score['evaluator_source_sha256'] == config['evaluator_sha256']
                        and score['rubric_sha256'] == config['rubric_sha256'] and not score['confirmation_evaluated'], 'Scorer file binding differs')
                require(strict(read(score_path.parent / 'evaluation.stdout')) == score
                        and read(score_path.parent / 'evaluation.stderr') == b'', 'Scorer process output differs')
                evaluation_meter = document(output / 'evaluation-meter.json')
                require(evaluation_meter == result['evaluation_meter'], 'Evaluation meter receipt differs')
                evaluation = journal(evaluation_meter, output / 'evaluation.meter.jsonl')
                require(evaluation['complete_record'] and evaluation['envelope']['status'] == 'SUCCEEDED'
                        and evaluation['header']['operation_id'] == operation + '/external-evaluation'
                        and evaluation['header']['process_id'] == host['header']['process_id'], 'Scorer lifecycle differs')
                near(evaluation_meter['wall_seconds'], evaluation['envelope']['inclusive_wall_ns']/1e9, 'Evaluation duration differs')
                eval_wall = evaluation_meter['wall_seconds']
                deployment_end = result['deployment_meter'].get('observer_tail', {}).get('end_monotonic_ns', host['envelope']['end_monotonic_ns'])
                require(evaluation['envelope']['start_monotonic_ns'] >= deployment_end, 'Scoring overlaps deployment')
                near(result['net_latency_utility'], score['quality'] - config['latency_weight']*result['deployment_meter']['wall_seconds'], 'Latency utility excludes measured deployment')
            for field, actual in [('model_sha256', model_sha), ('source_sha256', result['source_sha256']),
                                  ('output_text_sha256', text_sha), ('output_image_sha256', image_sha),
                                  ('evaluator_sha256', None if status == 'Failed' else config['evaluator_sha256']),
                                  ('rubric_sha256', None if status == 'Failed' else config['rubric_sha256'])]:
                require(binding[field] == actual, 'Summary binding differs: ' + field)
            meter = result['deployment_meter']
            require(attempt['wall_seconds'] >= meter['wall_seconds'] + eval_wall - 1e-8, 'Outer wall does not cover nested scopes')
            link = 'initial_attempt' if number == 1 else 'explicit_failed_retry' if expected_profile['retry_of'] else 'instrumentation_revalidation'
            row = {**{k: result[k] for k in ('original_operation_id', 'regime', 'arm', 'task_family', 'terminal_status', 'fit_id', 'case_id', 'source_group_id', 'episode_group')},
                   'run_number': number, 'run_id': summary['run_id'], 'native_job_id': job, 'output_directory': str(output),
                   'result_sha256': binding['result_sha256'], 'original_attempt_sha256': binding['attempt_sha256'],
                   'request_path': str(request_path), 'request_sha256': attempt['request_sha256'],
                   'source_path': str(source_path), 'source_sha256': result['source_sha256'],
                   'model_path': original_profile['weights'], 'model_sha256': model_sha, 'training_receipt_sha256': training_sha,
                   'control_plan_sha256': control_sha, 'evaluator_source_sha256': config['evaluator_sha256'], 'rubric_sha256': config['rubric_sha256'],
                   'evaluation_path': None if score_path is None else str(score_path), 'evaluation_sha256': score_sha,
                   'delivery_path': str(delivery_path), 'delivery_sha256': hash_file(delivery_path),
                   'output_text_sha256': text_sha, 'output_image_path': None if image_path is None else str(image_path), 'output_image_sha256': image_sha,
                   'text_hash_representation': 'canonical JSON string or null in actual delivery.json',
                   'predecessor_link_type': link, 'retry_of': expected_profile['retry_of'],
                   'instrumentation_predecessor_operation_id': expected_profile.get('instrumentation_predecessor_operation_id'),
                   'predecessor_terminal_status': None if predecessor is None else predecessor['terminal_status'],
                   'deployment_wall_seconds': meter['wall_seconds'], 'deployment_observed_cpu_seconds': meter['cpu_seconds'],
                   'deployment_unknown_seconds': meter['observed_unclassified_overhead_seconds'], 'exclusive_category_wall_seconds': meter['costs'],
                   'observer_tail_wall_seconds': tail_wall, 'observer_tail_own_cpu_seconds': tail_cpu,
                   'outer_wall_seconds': attempt['wall_seconds'], 'outer_task_and_reaped_children_cpu_seconds': attempt['cpu_seconds'],
                   'external_evaluation_wall_seconds': eval_wall, 'stdout_bytes': stdout_bytes,
                   'isolation_launch_sha256': hash_file(output / 'launch.json'), 'launch_exit_code': launch['exit_code'],
                   'launch_limit_reason': launch['limit_reason'], 'deployment_journal_sha256': hash_file(output / 'deployment.meter.jsonl'),
                   'deployment_raw_spans_sha256': meter['raw_spans_sha256'], 'actor_journals': actor_bindings,
                   'observer_tail_sha256': meter.get('observer_tail_sha256'), 'external_evaluation_present': score_path is not None}
            inventory.append(row)
            run_rows.append(row)
            if number == 1:
                first_by_key[key] = row
            if len(inventory) % 40 == 0:
                print(json.dumps({'stage': 'independent_actual_file_readback', 'verified_attempts': len(inventory)}), flush=True)
        require(keys == expected and len(run_rows) == 120, 'Missing roster tuple')
        events = [strict(line) for line in read(root / 'qualification/events.jsonl').splitlines()]
        dispatched = [Path(event['request']).name for event in events if event['event'] == 'dispatched']
        terminals = [event['result']['attempt']['original_operation_id'] for event in events if event['event'] == 'terminal']
        require(len(events) == 240 and Counter(dispatched) == Counter(admitted_map.keys())
                and Counter(terminals) == Counter(phase_map.keys()), 'Actual event ledger does not close once per request')
        totals = aggregate(run_rows)
        require(totals['terminal_counts'] == summary['terminal_counts'], 'Summary terminal count differs')
        near(totals['deployment_wall_seconds'], summary['sum_episode_wall_seconds'], 'Summary wall omits attempts')
        near(totals['deployment_unknown_seconds'], summary['observed_unclassified_seconds'], 'Summary UNKNOWN differs')
        near(totals['outer_wall_seconds'], summary['sum_outer_task_wall_seconds'], 'Summary outer wall differs')
        near(totals['outer_task_and_reaped_children_cpu_seconds'], summary['sum_outer_task_process_and_reaped_children_cpu_seconds'], 'Summary outer CPU differs')
        if number == 2:
            require(summary['predecessor_result_sha256'] == SPECS[0][3]
                    and summary['predecessor_native_job_id'] == SPECS[0][1]
                    and summary['retry_of_failed_predecessor_count'] == 8
                    and summary['revalidation_predecessor_count'] == 112, 'Second-run predecessor contract differs')
        runs.append({'run_number': number, 'native_job_id': job, 'root': str(root), 'result_sha256': result_pin,
                     'code_manifest_sha256': manifest_pin, 'actual_event_ledger_sha256': hash_file(root / 'qualification/events.jsonl'),
                     'actual_phase_result_sha256': hash_file(root / 'qualification/phase-result.json'),
                     'original_qualification_status': summary['qualification_status'], 'totals': totals,
                     'by_terminal_status': {status: aggregate([row for row in run_rows if row['terminal_status'] == status]) for status in totals['terminal_counts']},
                     'by_predecessor_link_type': {link: aggregate([row for row in run_rows if row['predecessor_link_type'] == link]) for link in sorted({row['predecessor_link_type'] for row in run_rows})}})
    require(len(inventory) == len({row['original_operation_id'] for row in inventory}) == 240, 'Combined attempt denominator differs')
    require(Counter(row['terminal_status'] for row in inventory) == {'Completed': 210, 'BudgetStop': 22, 'Failed': 8}, 'Combined terminal roster differs')
    require(Counter(row['predecessor_link_type'] for row in inventory) == {'initial_attempt': 120, 'explicit_failed_retry': 8, 'instrumentation_revalidation': 112}, 'Retry/revalidation denominators differ')
    require(sum(row['external_evaluation_present'] for row in inventory) == 232, 'Scorer receipt denominator differs')
    for path, entry in FILES.items():
        require(identity(Path(path).lstat()) == entry['identity'], 'Artifact changed before final audit: ' + path)
    inventory.sort(key=lambda row: (row['run_number'], row['regime'], row['arm'], row['task_family']))
    inventory_document = {'schema': 'ndu.real.native-attempt-inventory.v1', 'attempt_count': 240, 'attempts': inventory}
    inventory_raw = (json.dumps(inventory_document, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    audit = {'schema': 'ndu.real.native-inventory-audit.v1', 'status': 'PASS_ACTUAL_FILE_INVENTORY_AND_BOUND_METER_REPLAY',
             'audited_at_utc': datetime.now(timezone.utc).isoformat(), 'audit_source_sha256': os.environ.get('NDU_AUDIT_SOURCE_SHA256'),
             'scope': 'Read-only actual file readback and pinned meter replay; no models executed and no outputs rescored.',
             'source_manifests': manifests, 'original_source_files_verified': len(plan['source_pins']),
             'original_input_pins': PINS, 'attempt_inventory_sha256': sha(inventory_raw), 'attempt_inventory_bytes': len(inventory_raw),
             'actual_regular_files_read_and_hashed': len(FILES), 'actual_total_unique_file_bytes': sum(v['bytes'] for v in FILES.values()),
             'all_read_file_identities_unchanged_at_completion': True, 'unique_meter_identities_replayed': len(SEEN_METERS),
             'runs': runs, 'totals': aggregate(inventory),
             'by_terminal_status': {status: aggregate([row for row in inventory if row['terminal_status'] == status]) for status in ('Completed', 'BudgetStop', 'Failed')},
             'by_predecessor_link_type': {link: aggregate([row for row in inventory if row['predecessor_link_type'] == link]) for link in ('initial_attempt', 'explicit_failed_retry', 'instrumentation_revalidation')},
             'scorer_receipts_verified': 232, 'scorer_receipts_absent_after_first_actor_failure': 8, 'missing_terminal_receipts': 0,
             'failed_originals_retained': 8, 'failed_originals_with_retained_actual_journals': 8,
             'same_original_model_control_plan_source_rubric_evaluator_pins_verified': True,
             'unchanged_budget_markers': {'max_actor_output_bytes': 4194304, 'maximum_actions': 8, 'episode_wall_seconds': 60, 'declared_phase_budgets': plan['design']['budgets']},
             'failure_and_retry_cost_interpretation': 'Dedicated category zero is not zero attempt cost; use Failed and explicit_failed_retry whole-attempt aggregates.',
             'one_source_group_five_workflow_variants_not_five_independent_source_families': True,
             'new_model_fits': 0, 'independent_new_scientific_units': 0, 'scientific_admission': 'HOLD',
             'confirmation_access_authorized': False, 'adoption_authorized': False, 'native_owner_authentication': 'NOT_ESTABLISHED_BY_THIS_AUDIT',
             'cell_journal_authentication': 'NOT_ESTABLISHED_BY_THIS_AUDIT', 'energy_joules': None, 'provider_charges': None,
             'full_physical_cost_complete': False, 'issues': [],
             'limitations': ['Frozen span verifier reused for raw replay; source author also reviewed integration.',
                             'File hashes and metadata checks do not authenticate a malicious host owner.',
                             'Deployment CPU is observed host and actor lower bound; outer CPU includes reaped children.',
                             'UNKNOWN remains real unclassified wall time; no monetary or energy conversion.',
                             'First run excludes observer tail from deployment; its outer envelope covers it.']}
    audit_raw = (json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    print(json.dumps({'audit_sha256': sha(audit_raw), 'inventory_sha256': sha(inventory_raw),
                      'audit_gzip_base64': base64.b64encode(gzip.compress(audit_raw, mtime=0)).decode(),
                      'inventory_gzip_base64': base64.b64encode(gzip.compress(inventory_raw, mtime=0)).decode()}, sort_keys=True), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'audit_status': 'BLOCKED', 'error_type': type(error).__name__, 'error': str(error),
                          'traceback': traceback.format_exc()}, sort_keys=True), flush=True)
        raise SystemExit(1)
