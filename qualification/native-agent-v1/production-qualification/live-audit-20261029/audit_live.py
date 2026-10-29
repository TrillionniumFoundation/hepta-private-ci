#!/usr/bin/env python3
"""Independent read-only audit of the frozen representative live captures."""
import collections
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw'
OUT = ROOT / 'derived'
GROUPS = ('representative-live-matched-v1', 'representative-live-individual-v1', 'representative-long-output-v4')


def wire(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_bytes())


def rel(path):
    return str(path.relative_to(RAW))


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def response(path):
    text = path.read_text()
    events, block = [], []
    for line in text.splitlines() + ['']:
        if not line:
            if block:
                data = '\n'.join(block)
                if data != '[DONE]':
                    events.append(json.loads(data))
                block = []
        elif line.startswith('data:'):
            block.append(line[5:].lstrip())
    terminal = [x for x in events if x.get('type') in ('response.completed', 'response.incomplete', 'response.failed')]
    value = terminal[-1].get('response', {}) if terminal else {}
    done = [x['item'] for x in events if x.get('type') == 'response.output_item.done']
    output = value.get('output', done)
    calls = []
    for item in output:
        if item.get('type') == 'function_call':
            arguments = item.get('arguments')
            try:
                decoded = json.loads(arguments) if isinstance(arguments, str) else arguments
                decode_error = None
            except Exception as error:
                decoded, decode_error = None, str(error)
            calls.append({'call_id': item.get('call_id'), 'name': item.get('name'), 'arguments': decoded,
                          'arguments_raw': arguments, 'arguments_decode_error': decode_error})
    return {'path': rel(path), 'sha256': digest(path.read_bytes()), 'bytes': path.stat().st_size,
            'terminal_events': [x.get('type') for x in terminal], 'status': value.get('status'),
            'id': value.get('id'), 'model': value.get('model'), 'usage': value.get('usage'),
            'incomplete_details': value.get('incomplete_details'), 'error': value.get('error'),
            'calls': calls, 'event_types': dict(collections.Counter(x.get('type') for x in events))}


def feedback_item(item):
    output = item.get('output')
    if isinstance(output, list):
        assert len(output) == 1 and output[0].get('type') == 'input_text'
        output = output[0]['text']
    value = json.loads(output)
    assert isinstance(value, dict) and type(value.get('exit_code')) is int
    assert isinstance(value.get('stdout'), str) and isinstance(value.get('stderr'), str)
    return value


def messages(request):
    result = []
    for item in request.get('input', []):
        if item.get('role') not in ('user', 'system', 'developer'):
            continue
        content = item.get('content')
        texts = [content] if isinstance(content, str) else [p.get('text', '') for p in content or [] if isinstance(p, dict)]
        result.append({'role': item.get('role'), 'type': item.get('type'), 'texts': texts,
                       'text_bytes': sum(len(x.encode()) for x in texts), 'content_shape': type(content).__name__})
    return result


def first_input(path, request):
    tools = request.get('tools', [])
    normalized_tools = [{k: v for k, v in tool.items() if k != 'strict'} for tool in tools]
    return {'path': rel(path), 'bytes': path.stat().st_size, 'sha256': digest(path.read_bytes()),
            'top_keys': sorted(request), 'instructions': request.get('instructions'),
            'messages': messages(request), 'tool_names': [x.get('name') for x in tools],
            'tools_sha256': digest(canonical(tools)), 'tools_without_strict_sha256': digest(canonical(normalized_tools)),
            'tool_strict': [x.get('strict') for x in tools],
            'parallel_tool_calls': request.get('parallel_tool_calls'), 'store': request.get('store'),
            'reasoning': request.get('reasoning'), 'include': request.get('include'),
            'max_output_tokens_raw': request.get('max_output_tokens'),
            'prompt_cache_key_present': 'prompt_cache_key' in request,
            'client_metadata_keys': sorted(request.get('client_metadata', {})),
            'temperature_present': 'temperature' in request, 'seed_present': 'seed' in request,
            'http_headers_capture': 'not recorded by the original gateway'}


def guard_events(case_root, known, limit):
    seen, result = set(), []
    admitted_count = 0
    for envelope in jsonl(case_root / 'executor.jsonl'):
        message = envelope['message']
        if message.get('method') != 'item/tool/call':
            continue
        params = message['params']
        cid = params.get('callId')
        flags = []
        if 'id' not in message:
            flags.append('missing_rpc_id')
        if not isinstance(cid, str) or not cid:
            flags.append('invalid_call_id')
        if params.get('tool') not in known:
            flags.append('unknown_tool')
        if cid in seen:
            flags.append('duplicate_call_id')
        if admitted_count >= limit:
            flags.append('tool_budget_exhausted')
        result.append({'ordinal': admitted_count + 1, 'received_ns': envelope['received_ns'],
                       'call_id': cid, 'name': params.get('tool'), 'arguments': params.get('arguments'),
                       'rpc_id': message.get('id'), 'thread_id': params.get('threadId'),
                       'turn_id': params.get('turnId'), 'guard_flags': flags})
        if flags:
            break
        admitted_count += 1
        seen.add(cid)
    return result


def render_failed_calls(cases):
    lines = ['# P1 live 失败逐调用附录', '',
             '由 `audit_live.py` 从原始 SSE、admission、backend 和后续模型请求生成。', '',
             '本附录只包含 10 个 live 失败，不含 long-output replay。已注册工具名、新 call ID、可解码参数不保证目标路径获准或操作会成功；此处 budget rejection 与工具本身 exit=1 分开。', '',
             '每条 call 的原 SSE 路径/哈希、admission 路径/哈希、完整参数、反馈内容与哈希见 [CALL_LEDGER.json](derived/CALL_LEDGER.json)。表中 model feedback 表示后续真实请求里出现了该反馈；没有下一轮请求时，backend 仍可能已经完成。', '']
    for case in cases:
        if case['cost']['mode'] != 'live' or case['reported_result']['status'] == 'passed':
            continue
        lines += [f"## {case['group']} / {case['lane']} / {case['case']}", '',
                  f"原件目录：`raw/{case['root']}`。", '',
                  '| 次序 | 模型响应轮 | 工具 | 参数 | call ID | owner admission | exit / 后续模型反馈 |',
                  '|---:|---:|---|---|---|---|---|']
        for call in case['calls']:
            arguments = json.dumps(call['arguments'], ensure_ascii=False, separators=(',', ':')).replace('|', '\\|').replace('`', '\\`')
            code = call.get('exit_code', call.get('backend_exit_code'))
            feedback = '已观察' if call['feedback_observed'] else '未进入后续请求'
            terminal = f'exit={code}' if code is not None else '未 admission'
            lines.append(f"| {call['ordinal']} | {call['response_number']} | `{call['name']}` | `{arguments}` | `{call['call_id']}` | {'是' if call['owner_admitted'] else '否'} | {terminal}；{feedback} |")
        rejected = [call for call in case['calls'] if not call['owner_admitted']]
        assert len(rejected) == 1 and rejected[0]['ordinal'] == 6
        lines += ['', '结论：已有 5 次 admission，第 6 次 call ID 新且工具名已注册；拒绝原因为工具预算耗尽。']
        if case['dynamic_guard_events']:
            last = case['dynamic_guard_events'][-1]
            lines += [f"动态 guard 独立重建：`{json.dumps(last['guard_flags'])}`；RPC ID `{last['rpc_id']}`。"]
        else:
            lines += ['native 原结果：`tool call budget exhausted before admission`。']
        lines += ['', '模型响应原件：', '']
        for path in sorted({c['response_path'] for c in case['calls']}):
            lines.append(f'- `raw/{path}`')
        lines += ['']
    (ROOT / 'FAILED_CALLS.md').write_text('\n'.join(lines) + '\n')


def case_audit(group, row):
    case_root = RAW / 'runs' / group / row['lane'] / f"{row['repeat']:02}-{row['case']}"
    frozen = read(case_root / 'FROZEN.json')
    budgets = frozen['budgets']
    backend = jsonl(case_root / 'backend.jsonl')
    ready = next(x['message'] for x in backend if x['message'].get('ready'))
    known = {x['name'] for x in ready['tools']}
    paths = sorted((case_root / 'model').glob('*.request.json'))
    requests = [read(p) for p in paths]
    response_paths = sorted((case_root / 'model').glob('*.response.sse'))
    responses = [response(p) for p in response_paths]
    records = sorted(jsonl(case_root / 'model/model_requests.jsonl'), key=lambda x: x['call'])
    assert len(requests) == len(responses) == len(records), str(case_root)
    calls, feedback, first_seen, request_audit = [], {}, {}, []
    usage = collections.Counter()
    for index, (p, request, reply, record) in enumerate(zip(paths, requests, responses, records)):
        assert digest(p.read_bytes()) == record['request_sha256']
        assert p.stat().st_size == record['request_bytes']
        assert record['response_bytes'] == reply['bytes']
        effective = dict(request)
        effective['max_output_tokens'] = min(int(effective.get('max_output_tokens', budgets['output_tokens'])), budgets['output_tokens'])
        effective_bytes = wire(effective)
        assert digest(effective_bytes) == record['effective_sha256']
        assert len(effective_bytes) == record['effective_bytes']
        request_audit.append({'request_path': rel(p), 'response_path': reply['path'],
                              'request_sha256': record['request_sha256'], 'effective_sha256': record['effective_sha256'],
                              'request_bytes': record['request_bytes'], 'effective_bytes': len(effective_bytes),
                              'max_output_tokens': effective['max_output_tokens'],
                              'http_status': record.get('http_status'), 'gateway_error': record.get('error'),
                              'started_ns': record['started_ns'], 'finished_ns': record['finished_ns'],
                              'gateway_elapsed_ms': (record['finished_ns'] - record['started_ns']) / 1e6,
                              'parallel_tool_calls': request.get('parallel_tool_calls')})
        for item in request.get('input', []):
            if item.get('type') == 'function_call_output':
                cid, value = item['call_id'], feedback_item(item)
                if cid in feedback:
                    assert value == feedback[cid], 'rewritten feedback'
                feedback[cid] = value
                first_seen.setdefault(cid, index + 1)
        for proposal in reply['calls']:
            calls.append({**proposal, 'ordinal': len(calls) + 1, 'response_number': index + 1,
                          'response_path': reply['path'], 'response_sha256': reply['sha256']})
        item = reply['usage']
        assert isinstance(item, dict), 'missing actual or declared replay usage'
        assert all(type(item[k]) is int and item[k] >= 0 for k in ('input_tokens', 'output_tokens', 'total_tokens'))
        assert item['total_tokens'] == item['input_tokens'] + item['output_tokens']
        for name in ('input_tokens', 'output_tokens', 'total_tokens'):
            usage[name] += item[name]
        cached = item.get('input_tokens_details', {}).get('cached_tokens', 0)
        assert type(cached) is int and 0 <= cached <= item['input_tokens']
        usage['cached_input_tokens'] += cached
    admission_paths = sorted((case_root / 'sessions').rglob('tool-*.json'))
    admissions = {}
    for p in admission_paths:
        value = read(p)
        cid = value['call']['call_id']
        assert cid not in admissions
        admissions[cid] = (p, value)
    backend_terminals = {}
    for envelope in backend:
        message = envelope['message']
        if message.get('status') != 'completed' or 'output' not in message:
            continue
        cid = message.get('session', '').rsplit(':', 1)[-1]
        if cid not in admissions:
            continue
        assert cid not in backend_terminals
        backend_terminals[cid] = (envelope, feedback_item(message))
    seen = set()
    for call in calls:
        cid = call['call_id']
        call['unknown_name'] = call['name'] not in known
        call['reused_call_id'] = cid in seen
        seen.add(cid)
        call['owner_admitted'] = cid in admissions
        call['feedback_observed'] = cid in feedback
        if cid in admissions:
            p, value = admissions[cid]
            owner_call = value['call']
            assert owner_call['name'] == call['name']
            assert json.loads(owner_call['arguments']) == call['arguments']
            call['admission_path'] = rel(p)
            call['admission_sha256'] = digest(p.read_bytes())
            call['idempotency_key'] = value['params'].get('idempotency_key')
        if cid in backend_terminals:
            envelope, value = backend_terminals[cid]
            call['backend_terminal_observed'] = True
            call['backend_terminal_received_ns'] = envelope['received_ns']
            call['backend_exit_code'] = value['exit_code']
            call['backend_stdout_sha256'] = digest(value['stdout'].encode())
            call['backend_stderr_sha256'] = digest(value['stderr'].encode())
            if cid in feedback:
                assert value == feedback[cid], 'backend output differs from model feedback'
        if cid in feedback:
            value = feedback[cid]
            assert first_seen[cid] > call['response_number']
            call['feedback_first_request'] = first_seen[cid]
            call['exit_code'] = value['exit_code']
            call['stdout_bytes'] = len(value['stdout'].encode())
            call['stderr_bytes'] = len(value['stderr'].encode())
            call['stdout_sha256'] = digest(value['stdout'].encode())
            call['stderr_sha256'] = digest(value['stderr'].encode())
            call['stdout'] = value['stdout']
            call['stderr'] = value['stderr']
    guards = guard_events(case_root, known, budgets['tool_calls'])
    for event in guards:
        originals = [call for call in calls if call['call_id'] == event['call_id']]
        assert len(originals) == 1
        original = originals[0]
        assert original['name'] == event['name'] and original['arguments'] == event['arguments']
    workspace = read(case_root / 'workspace.json')
    immutable = {name: digest((case_root / 'workspace' / name).read_bytes()) == sha for name, sha in workspace['readonly'].items()}
    assert all(immutable.values())
    runtime_jobs = []
    for p in sorted((case_root / 'remote/jobs').glob('*/exit.json')):
        terminal = read(p)
        out, err = p.parent / 'stdout.log', p.parent / 'stderr.log'
        entry = {'terminal_path': rel(p), 'terminal': terminal,
                 'stdout_bytes': out.stat().st_size, 'stdout_sha256': digest(out.read_bytes()),
                 'stderr_bytes': err.stat().st_size, 'stderr_sha256': digest(err.read_bytes())}
        for name in ('started.json', 'child.json', 'request.json', 'launch.json', 'owner-intent.json'):
            q = p.parent / name
            if q.is_file():
                entry[name] = read(q)
        runtime_jobs.append(entry)
    category = 'passed_original_gate'
    if row['status'] != 'passed':
        if guards and guards[-1]['guard_flags'] == ['tool_budget_exhausted']:
            category = 'sixth_valid_dynamic_tool_rejected_after_five_admissions'
        elif (row.get('result') or {}).get('error') == 'tool call budget exhausted before admission':
            assert len(admissions) == 5 and len(calls) >= 6
            assert all(not x['unknown_name'] and not x['reused_call_id'] for x in calls)
            category = 'native_sixth_valid_proposal_rejected_after_five_admissions'
        elif row['case'] == 'long_output':
            last_backend = backend[-1]['message']
            assert last_backend.get('status') == 'pending_tool'
            assert last_backend.get('cancel_requested') is True or last_backend.get('last_error') == 'tool timed out or cancelled; terminal observation required'
            assert len(runtime_jobs) == 1 and runtime_jobs[0]['terminal']['exit_code'] == 0
            assert runtime_jobs[0]['terminal']['output_complete'] and runtime_jobs[0]['terminal']['output_durable']
            category = 'pending_tool_with_cancel_or_timeout_marker_after_original_job_completed'
        else:
            category = 'requires_manual_review'
    cost = {'group': group, 'lane': row['lane'], 'case': row['case'], 'status': row['status'],
            'mode': frozen['mode'], 'startup_ms': row.get('startup_ms'), 'task_wall_ms': row.get('wall_ms'),
            'model_requests_captured': len(requests), 'provider_proposals': len(calls), 'owner_tool_admissions': len(admissions),
            'model_gateway_sum_ms': sum(x['gateway_elapsed_ms'] for x in request_audit),
            'request_bytes': sum(x['request_bytes'] for x in request_audit),
            'effective_bytes': sum(x['effective_bytes'] for x in request_audit),
            'response_sse_bytes': sum(x['bytes'] for x in responses), **dict(usage),
            'uncached_input_tokens': usage['input_tokens'] - usage['cached_input_tokens'],
            'max_request_bytes': max((x['request_bytes'] for x in request_audit), default=0),
            'max_output_tokens_used': max((x['usage']['output_tokens'] for x in responses), default=0),
            'max_complete_tool_stream_bytes': max((x['stdout_bytes'] + x['stderr_bytes'] for x in runtime_jobs), default=0)}
    return {'group': group, 'lane': row['lane'], 'case': row['case'], 'root': rel(case_root),
            'reported_result': row, 'budgets': budgets, 'failure_category': category, 'calls': calls,
            'dynamic_guard_events': guards, 'responses': responses, 'requests': request_audit,
            'initial_input': first_input(paths[0], requests[0]), 'cost': cost,
            'known_tools': sorted(known), 'all_immutable_workspace_files_unchanged': all(immutable.values()),
            'runtime_jobs': runtime_jobs,
            'backend_results': [x for x in backend if not x['message'].get('ready')],
            'limits': {'client_http_headers_captured': False, 'failed_task_wall_ms_available': row.get('wall_ms') is not None}}


def main():
    OUT.mkdir(exist_ok=True)
    manifest = read(RAW / 'COLLECTION_MANIFEST.json')
    for entry in manifest['files']:
        data = (RAW / entry['archive_path']).read_bytes()
        assert len(data) == entry['bytes'] and digest(data) == entry['sha256']
        assert entry['stable_stat_during_read']
    verification = {'files': len(manifest['files']), 'bytes': sum(x['bytes'] for x in manifest['files']),
                    'missing': manifest['missing'], 'all_hashes_verified': True, 'unstable_reads': 0,
                    'manifest_sha256': digest((RAW / 'COLLECTION_MANIFEST.json').read_bytes()),
                    'archive_sha256_supplied_by_root': 'd2fe31ff5c35d62d862d5afe3047973224ba5419cb61c8adf64cf8b809a438b1'}
    cases = []
    for group in GROUPS:
        report = read(RAW / 'runs' / group / 'REPORT.json')
        cases += [case_audit(group, row) for row in report['rows']]
    write('MANIFEST_VERIFICATION.json', verification)
    write('AUDIT.json', {'schema': 'hepta.p1.independent-live-audit.v1', 'manifest': verification, 'cases': cases})
    write('CALL_LEDGER.json', [{'group': x['group'], 'lane': x['lane'], 'case': x['case'],
                              'category': x['failure_category'], 'calls': x['calls'],
                              'dynamic_guard_events': x['dynamic_guard_events']} for x in cases])
    render_failed_calls(cases)
    write('INITIAL_INPUTS.json', [{'group': x['group'], 'lane': x['lane'], 'case': x['case'],
                                 **x['initial_input']} for x in cases])
    costs = [x['cost'] for x in cases]
    write('COSTS.json', costs)
    with (OUT / 'COSTS.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(costs[0]))
        writer.writeheader()
        writer.writerows(costs)
    aggregate = []
    for group in GROUPS:
        for lane in ('app-server', 'facade', 'native'):
            selected = [x for x in cases if x['group'] == group and x['lane'] == lane]
            record = {'group': group, 'lane': lane, 'passed': sum(x['reported_result']['status'] == 'passed' for x in selected),
                      'cases': len(selected), 'failed_wall_ms_missing': sum(x['cost']['task_wall_ms'] is None for x in selected)}
            for key in ('model_requests_captured', 'provider_proposals', 'owner_tool_admissions', 'model_gateway_sum_ms',
                        'request_bytes', 'effective_bytes', 'response_sse_bytes', 'input_tokens', 'output_tokens',
                        'total_tokens', 'cached_input_tokens', 'uncached_input_tokens'):
                record[key] = sum(x['cost'][key] for x in selected)
            aggregate.append(record)
    write('AGGREGATES.json', aggregate)
    print(json.dumps({'cases': len(cases), 'categories': dict(collections.Counter(x['failure_category'] for x in cases)),
                      'unknown_tool_names': sum(x['unknown_name'] for c in cases for x in c['calls']),
                      'reused_call_ids': sum(x['reused_call_id'] for c in cases for x in c['calls']),
                      'all_provider_terminal_event_types': sorted({t for c in cases for r in c['responses'] for t in r['terminal_events']}),
                      'all_provider_terminal_statuses': sorted({r['status'] for c in cases for r in c['responses']})}, indent=2))


if __name__ == '__main__':
    main()
