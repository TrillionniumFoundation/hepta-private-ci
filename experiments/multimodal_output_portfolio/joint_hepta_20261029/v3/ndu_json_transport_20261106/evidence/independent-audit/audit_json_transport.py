"""Audit the new development run without invoking a model, SQL, or source tool."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import traceback
from unittest.mock import patch

from receipt_checks import (REL, LOCAL, UPSTREAM, PUBLIC_KEYS, canonical, command_configs,
                            decode_reference, digest, model_response, near, need, public_prompt,
                            read, sha, utc, verify_model, verify_runtime)


def pair_checks(intent, terminal, context, config, payload, kind, deadline, protocol):
    need(intent['phase'] == 'intent' and terminal['phase'] == 'terminal', 'Ordered durable intent/terminal')
    need(intent['request_id'] == terminal['request_id'] and terminal['intent_sha256'] == digest(intent), 'Intent pairing/hash')
    need(intent['kind'] == terminal['kind'] == kind and intent['status'] == 'pending', 'Expected request kind')
    copied = {key: value for key, value in intent.items() if key not in ('status', 'phase', 'prepared_at', 'prepared_monotonic')}
    need(all(type(terminal[k]) is type(v) and terminal[k] == v for k, v in copied.items()), 'Full copied intent bindings')
    need(all(intent[k] == value and terminal[k] == value for k, value in context.items()), 'Request context')
    need(intent['request_sha256'] == digest(payload), 'Independent public request reconstruction')
    need(intent['transport_sha256'] == digest(config) and intent['expected_identity_sha256'] == digest(config['identity']), 'Command/identity binding')
    timeout = protocol['request_deadline_seconds' if kind == 'model' else 'tool_deadline_seconds']
    need(intent['timeout_seconds'] == timeout and near(intent['deadline_monotonic'], min(intent['prepared_monotonic']+timeout, deadline)), 'Request deadline')
    need(terminal['started_monotonic'] == intent['prepared_monotonic'] and
         intent['prepared_monotonic'] <= terminal['intent_finished_monotonic'] <= terminal['finished_monotonic'], 'Intent/terminal clock order')
    need(near(terminal['wall_seconds'], terminal['finished_monotonic']-intent['prepared_monotonic']), 'Request wall accounting')
    need(abs((utc(terminal['finished_at'])-utc(terminal['started_at'])).total_seconds()-terminal['wall_seconds']) < .01, 'UTC/monotonic request agreement')
    if terminal['dispatched']:
        need(terminal['intent_finished_monotonic'] <= terminal['dispatch_monotonic'] <= terminal['finished_monotonic']
             and terminal['dispatch_monotonic'] < deadline, 'Dispatch admission after durable intent')
    else:
        need(terminal['dispatch_monotonic'] is None and not terminal['response_received'] and terminal['status'] in ('timeout', 'failure'), 'Nondispatched accounting')
    if terminal['status'] == 'ok':
        need(terminal['dispatched'] and terminal['response_received'] and terminal['returncode'] == 0 and terminal['error_type'] is None
             and terminal['finished_monotonic'] <= terminal['deadline_monotonic'], 'Successful bounded real command')
    need(all(terminal[k] is None for k in ('actual_amount', 'reported_amount', 'reported_currency')) and
         terminal['reconciliation_status'] == 'pending', 'Unknown money and reconciliation retained')


def response_hash(value):
    return hashlib.sha256((json.dumps(value, sort_keys=True, allow_nan=False)+'\n').encode()).hexdigest()


def verify_run(folder, qualification, schedule, protocol, frozen, source, manifest, parameter, tokenizer, args):
    result, entries = read(folder/'result.json'), [json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
    files = {str(p.relative_to(folder)): sha(p) for p in folder.rglob('*') if p.is_file() and p != folder/'result.json'}
    need(files == result['artifacts_sha256'], 'Exact result artifact inventory')
    need(result['schema'] == 'ndu.json-transport-development-result.v1' and result['freeze'] == frozen, 'Result source freeze')
    need(result['qualification_only'] is qualification and len(result['episodes']) == len(schedule), 'Fixed run/episode inventory')
    need(result['protocol_sha256'] == digest(protocol) and result['worker_protocol_sha256'] == protocol['worker_protocol_sha256'], 'Distinct worker/procedure protocols')
    need(result['source_and_tasks_unchanged'] and result['independent_confirmation'] is False and result['external_paid_model_calls'] == 0
         and result['actual_host_currency_cost'] is None and result['scope'] == protocol['gain_claim'], 'Scope and cost declarations')
    model_config, workers = command_configs(args.recorded_workspace, folder.name, manifest,
        sha(source/'evidence/acquisition/materialized-model.json'), protocol, args.runner_python)
    response_files = list((folder/'model_responses').glob('*.json'))
    need(not any(p.name.startswith('failure-') for p in response_files), 'Worker-failure receipt needs an explicit unresolved audit disposition')
    responses = {hashlib.sha256(read(p)['provider_request_id'].encode()).hexdigest(): p for p in response_files}
    need(len(responses) == len(response_files) == result['real_model_responses'], 'Unique model receipt inventory')
    caps = dict(model=1 if qualification else 24, tool=0 if qualification else 8, verifier=0 if qualification else 16)
    need(result['caps'] == caps, 'Registered hard caps')
    counts, used, request_ids, audited, position, previous_finish = Counter(), set(), set(), [], 0, -math.inf
    for index, (task, arm, expected) in enumerate(schedule):
        row = read(folder/f'episode-{index:02}.json')
        context = dict(task_id=task['task_id'], arm=arm, repeat=0, episode_id=f'episode-{index:02}', protocol_sha256=digest(protocol))
        need(row == result['episodes'][index] and row['context'] == context and row['source_cluster'] == task['source_cluster'], 'Episode/order/public task binding')
        pairs = []
        while position < len(entries) and entries[position]['phase'] == 'intent':
            need(position+1 < len(entries), 'No dangling intent')
            pairs.append((entries[position], entries[position+1])); position += 2
        need(position < len(entries), 'Episode host meter present')
        meter = entries[position]; position += 1
        need(meter['phase'] == 'meter' and meter['kind'] == 'host_envelope' and
             all(meter[k] == v for k, v in context.items()), 'Unique episode host envelope')
        need(meter['request_id'] not in request_ids, 'Unique host meter id'); request_ids.add(meter['request_id'])
        start, end, deadline = meter['started_monotonic'], meter['finished_monotonic'], row['episode_deadline_monotonic']
        need(start >= previous_finish and end >= start and near(meter['wall_seconds'], end-start), 'Serial episode wall meter')
        need(meter['actual_amount'] is None and row['actual_host_currency_cost'] is None and row['children_cpu_seconds'] >= 0, 'Episode resource accounting')
        need(meter['wall_seconds'] <= row['wall_seconds'] and math.isfinite(row['wall_seconds']), 'Cleanup included in episode wall')
        need(deadline <= start+protocol['episode_deadline_seconds']+1e-6, 'Episode time cap')
        global_bound = start-(utc(meter['started_at'])-utc(result['started_at_utc'])).total_seconds()+protocol['global_deadline_seconds']
        need(abs(deadline-min(start+protocol['episode_deadline_seconds'], global_bound)) < .01, 'Global/episode effective deadline')
        state = 'qualification' if qualification else 'plan' if arm == 'one_model_selected_tool' else 'direct'
        stage, decoded, expected_failure, expected_answer, observation = state, [], None, None, None
        previous_request, model_audits, kind_counts = start, [], Counter()
        for intent, terminal in pairs:
            need(expected_failure is None and state != 'complete', 'No calls after failure/completion')
            if state == 'tool':
                role = 'sql' if task['family'] == 'sqlite_query' else 'source'
                kind, config, payload = 'tool', workers[role], dict(task=task, payload=decoded[-1]['value'])
            elif state == 'verifier':
                kind, config, payload = 'verifier', workers['verifier'], dict(task=task, answer=expected_answer)
            else:
                kind, config = 'model', model_config
                text = protocol['qualification_prompt'] if qualification else public_prompt(task, state, observation)
                payload = dict(prompt=text); stage = state
            need(counts[kind] < caps[kind], 'Admission respects remaining global budget')
            pair_checks(intent, terminal, context, config, payload, kind, deadline, protocol)
            need(intent['request_id'] not in request_ids, 'No duplicate/reused request ids'); request_ids.add(intent['request_id'])
            need(previous_request <= intent['prepared_monotonic'] <= terminal['finished_monotonic'] <= end, 'Serial request interval coverage')
            previous_request = terminal['finished_monotonic']; counts[kind] += 1; kind_counts[kind] += 1
            if kind == 'model':
                provider = terminal['provider_request_sha256']
                need(terminal['status'] != 'ok' or provider is not None, 'Successful model response has provider receipt')
                if provider is not None:
                    need(provider in responses and provider not in used, 'Model receipt paired exactly once'); used.add(provider)
                    raw, checked = model_response(responses[provider], terminal, payload, source, manifest, parameter, protocol, tokenizer)
                    model_audits.append(checked)
            if terminal['status'] != 'ok':
                expected_failure = kind+'_failure'; continue
            if kind == 'tool':
                observation = row['tool_observation']
                need(terminal['response_sha256'] == response_hash(observation), 'Exact real tool stdout binding')
                state = 'answer'
            elif kind == 'verifier':
                quality = float(json.dumps(expected_answer, sort_keys=True, allow_nan=False) == json.dumps(expected, sort_keys=True, allow_nan=False))
                need(terminal['verified_quality'] == quality and terminal['response_sha256'] == response_hash(dict(quality=quality)), 'Independent exact-answer verifier reconstruction')
                state = 'complete'
            else:
                schema = ('qualification' if qualification else ('sql_query' if task['family'] == 'sqlite_query' else 'source_read') if state == 'plan'
                          else 'rows_answer' if task['family'] == 'sqlite_query' else 'strings_answer')
                decoded.append(decode_reference(raw, schema, state))
                if decoded[-1]['status'] == 'rejected':
                    code = decoded[-1]['rejection_code']
                    expected_failure = ('parameter_failure' if state == 'plan' else 'answer_schema_failure') if code == 'schema_mismatch' else 'format_failure'
                    need(row['failure'] == dict(stage=state, type='DecodeError', message=code), 'Independent decoder rejection')
                elif state == 'plan':
                    need(row['legal_payload'] is True and row['selected_payload'] == decoded[-1]['value'], 'Unchanged legal payload/plan binding')
                    state = 'tool'
                else:
                    expected_answer = decoded[-1]['value']; state = 'complete' if qualification else 'verifier'
        need(row['decodings'] == decoded and row['answer'] == expected_answer, 'All decode records and answer preserved')
        need(row['request_ids'] == [i['request_id'] for i, _ in pairs], 'Complete episode request roster')
        need(row['prompt_sha256'] == [i['request_sha256'] for i, _ in pairs if i['kind'] == 'model'], 'Complete public prompt roster')
        for kind in caps:
            need(row[kind+'_calls'] == kind_counts[kind] and row[kind+'_dispatches'] == sum(t['dispatched'] for i, t in pairs if i['kind'] == kind), 'Admitted versus dispatched counts')
        if expected_failure is None and state == 'complete' and row['failure_category'] is None:
            need(previous_request <= row['completion_monotonic'] <= deadline and row['completion_monotonic'] <= end, 'Actual completion before deadline')
            need(row['status'] == ('qualified' if qualification else 'delivered') and row['quality'] == (None if qualification else quality), 'Delivery distinct from correctness')
        else:
            if expected_failure is None:
                expected_failure = row['failure_category']
                need(expected_failure in ('deadline_failure', 'budget_failure'), 'No unexplained missing call/completion')
                if expected_failure == 'deadline_failure':
                    need(end >= deadline, 'Observed deadline exhaustion')
                else:
                    next_kind = 'tool' if state == 'tool' else 'verifier' if state == 'verifier' else 'model'
                    need(counts[next_kind] >= caps[next_kind], 'Observed budget exhaustion')
            need(row['failure_category'] == expected_failure and row['status'] == 'not_delivered' and row['quality'] == 0
                 and row['completion_monotonic'] is None, 'Failure remains failure')
        need(sum(x['worker_cpu_seconds'] for x in model_audits) <= row['children_cpu_seconds'], 'All model CPU included in child CPU')
        audited.append(dict(episode_id=context['episode_id'], task_id=task['task_id'], arm=arm, status=row['status'], quality=row['quality'],
                            failure_category=row['failure_category'], calls=dict(kind_counts), model_requests=model_audits,
                            decoder_outcomes=[d['envelope'] if d['status'] == 'accepted' else d['rejection_code'] for d in decoded]))
        previous_finish = start+row['wall_seconds']
    need(position == len(entries) and used == set(responses), 'No extra ledger/response records')
    need(dict(counts) == {k: v for k, v in result['counts'].items() if v} and all(counts[k] <= caps[k] for k in caps), 'Complete aggregate request budget')
    need(sum(row['wall_seconds'] for row in result['episodes']) <= result['outer_wall_seconds'], 'Outer wall includes all episodes')
    need(abs((utc(result['finished_at_utc'])-utc(result['started_at_utc'])).total_seconds()-result['outer_wall_seconds']) < .01, 'Outer UTC/wall agreement')
    if qualification:
        need(result['arms'] == {} and result['qualification_passed'] == (result['episodes'][0]['status'] == 'qualified')
             and result['task_episodes_not_started'] == 16 and result['qualification_result_sha256'] is None, 'Separate qualification accounting')
    else:
        summaries = {}
        for arm in protocol['arms']:
            group = [row for row in result['episodes'] if row['context']['arm'] == arm]
            summaries[arm] = dict(episodes=len(group), delivered=sum(x['status'] == 'delivered' for x in group), correct=sum(x['quality'] for x in group),
                legal_plans=sum(x['legal_payload'] is True for x in group), failures=dict(Counter(x['failure_category'] for x in group if x['failure_category'])),
                decoder_outcomes=dict(Counter(d['envelope'] if d['status'] == 'accepted' else d['rejection_code'] for x in group for d in x['decodings'])),
                wall_seconds=sum(x['wall_seconds'] for x in group), children_cpu_seconds=sum(x['children_cpu_seconds'] for x in group))
            for kind in caps:
                for suffix in ('_calls', '_dispatches'):
                    summaries[arm][kind+suffix] = sum(x[kind+suffix] for x in group)
        need(summaries == result['arms'] and result['qualification_passed'] is None and result['task_episodes_not_started'] == 0, 'Independent full arm summaries')
    requests = [request for row in audited for request in row['model_requests']]
    return dict(episodes=audited, counts=result['counts'], arms=result['arms'], ledger_entries=len(entries),
                actual_model_responses=len(responses), input_tokens=sum(x['input_tokens'] for x in requests), output_tokens=sum(x['output_tokens'] for x in requests),
                outer_wall_seconds=result['outer_wall_seconds'], outer_self_cpu_seconds=result['outer_self_cpu_seconds'],
                children_cpu_seconds=sum(x['children_cpu_seconds'] for x in result['episodes']),
                started_at_utc=result['started_at_utc'], finished_at_utc=result['finished_at_utc'],
                artifact_sha256={**files, 'result.json': sha(folder/'result.json')})


def audit(args):
    current, source = args.repo/REL/LOCAL, args.repo/REL/UPSTREAM
    frozen, protocol, worker, anchor = read(current/'freeze.json'), read(current/'protocol.json'), read(source/'protocol.json'), read(args.anchor)
    paths = read(current/'required-inputs.json')['paths']
    need(len(paths) == len(set(paths)) == 34 and set(paths) == set(frozen['source_sha256']), 'Exact 34-input source freeze')
    need(all(sha(args.repo/name) == hashed for name, hashed in frozen['source_sha256'].items()), 'All current frozen sources unchanged')
    need(frozen['before_candidate_inference'] and not frozen['external_preregistration'] and frozen['procedure_protocol_sha256'] == sha(current/'protocol.json'), 'Prospective development freeze')
    need(len(protocol['shared_worker_keys']) == 18 and all(protocol[k] == worker[k] for k in protocol['shared_worker_keys']), 'Shared worker fields')
    need(protocol['worker_protocol_sha256'] == sha(source/'protocol.json') and protocol['adapter_sha256'] == sha(current/'adapter.py'), 'Separate source identities')
    need(anchor['freeze_content'].encode() == (current/'freeze.json').read_bytes() and anchor['all_remote_bytes_equal_local'], 'Remote freeze bytes')
    need(len(anchor['source_files']) == 35 and {x['path'] for x in anchor['source_files']} == set(paths)|{str((current/'freeze.json').relative_to(args.repo))}, 'Complete remote source roster')
    for row in anchor['source_files']:
        raw = (args.repo/row['path']).read_bytes()
        need(hashlib.sha256(raw).hexdigest() == row['sha256'] and hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == row['remote_git_blob'], 'Remote source byte identity')
    folders = [args.qualification]+([args.pilot] if args.pilot else [])
    historical = [args.resources/name for name in ('qualification-v1', 'pilot-v1', 'followup-qualification-v1', 'followup-pilot-v1')]
    inputs = [args.repo/name for name in paths]+[current/'freeze.json', args.anchor, Path(__file__), Path(__file__).with_name('receipt_checks.py')]
    inputs += [p for folder in folders+historical for p in folder.rglob('*') if p.is_file()]+list((args.runtime/'model').iterdir())
    before = {str(p): sha(p) for p in inputs}
    manifest, model_files, parameter = verify_model(source, args.runtime); runtime = verify_runtime(source)
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[name] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.runtime/'model', local_files_only=True, trust_remote_code=False)
    private = read(args.repo/REL/'ndu_llm_confirmation/external_smoke/tasks.json')['tasks']
    need(len(private) == protocol['task_count'] == 8 and len({x['source_cluster'] for x in private}) == 2, 'Fixed disclosed task inventory')
    schedule = []
    for index, task in enumerate(private):
        public = {k: task[k] for k in PUBLIC_KEYS}
        for arm in protocol['arms'] if index % 2 == 0 else list(reversed(protocol['arms'])):
            schedule.append((public, arm, task['expected']))
    with patch('subprocess.Popen', side_effect=AssertionError('Audit must not launch any model or tool')):
        qualification = verify_run(args.qualification, True, [(dict(task_id='execution/qualification', source_cluster='execution'), 'qualification', [1])],
            protocol, frozen, source, manifest, parameter, tokenizer, args)
        raw_qualification = read(args.qualification/'result.json')
        runs = {args.qualification.name: qualification}
        if args.pilot:
            need(raw_qualification['qualification_passed'] is True and raw_qualification['counts'] == dict(model=1, tool=0, verifier=0)
                 and raw_qualification['real_model_responses'] == 1, 'Actual passing single-response qualification gate')
            need(read(args.pilot/'result.json')['qualification_result_sha256'] == sha(args.qualification/'result.json'), 'Task run bound to exact qualification result')
            runs[args.pilot.name] = verify_run(args.pilot, False, schedule, protocol, frozen, source, manifest, parameter, tokenizer, args)
    times = [utc(frozen['frozen_at_utc']), utc(anchor['commit_committer_date']), utc(anchor['pr_created_at']),
             utc(qualification['started_at_utc']), utc(qualification['finished_at_utc'])]
    if args.pilot:
        times += [utc(runs[args.pilot.name]['started_at_utc']), utc(runs[args.pilot.name]['finished_at_utc'])]
    need(times == sorted(times), 'Published freeze before unique qualification and task execution')
    need({str(p): sha(p) for p in inputs} == before, 'All new/old inputs unchanged by audit')
    return dict(schema='ndu.json-transport-independent-receipt-audit.v1', audited_at_utc=datetime.now(timezone.utc).isoformat(),
        status='PASS', auditor='/root/json_audit; separate internal reviewer, not external review', new_model_forwards=0,
        replayed_model_or_tool_calls=0, inputs_unchanged=True, remote_source_files_verified=35, source_sha256=frozen['source_sha256'],
        remote_anchor_sha256=sha(args.anchor), model_files=model_files, parameter_fingerprint=parameter, runtime_metadata=runtime,
        recorded_runner_python=args.runner_python, runs=runs, input_sha256=before,
        actual_host_currency_cost=None, external_paid_model_calls=0, scientific_confirmation=False,
        limitations=['No independent host/clock attestation or guarantee about activity outside recorded runners.',
                     'Public prompt and exact verifier are independently reconstructed; tool stdout is bound to its real command receipt, without tool replay.',
                     'Tokenizer/parameter checks load data only. Runtime version/RECORD metadata do not attest compiled binaries.',
                     'Earlier audit BF16 expansion method is reused explicitly; this is separate internal receipt review, not external scientific review.',
                     'All tasks are previously disclosed development cases. No NDU candidate, positive net-gain or untouched confirmation claim.',
                     'Host, worker and generation time are nested resource measurements and must not be added as separate currency charges.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'resources', 'runtime', 'qualification', 'anchor', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--pilot', type=Path)
    parser.add_argument('--recorded-workspace', type=Path, default=Path('/workspace/scratch/3f6a885bb83c'))
    parser.add_argument('--runner-python', required=True)
    args = parser.parse_args()
    try:
        report = audit(args)
    except Exception as error:
        report = dict(schema='ndu.json-transport-independent-receipt-audit.v1', status='FAIL',
                      exception=type(error).__name__, message=str(error), traceback=traceback.format_exc(),
                      audited_at_utc=datetime.now(timezone.utc).isoformat(), audit_script_sha256=sha(Path(__file__)))
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False); stream.write('\n')
    print(json.dumps({k: report[k] for k in ('status', 'message', 'new_model_forwards', 'inputs_unchanged') if k in report}))
    raise SystemExit(report['status'] != 'PASS')
