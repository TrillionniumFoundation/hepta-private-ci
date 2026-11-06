"""Read-only receipt audit; no model loading, generation, tools, or result repair."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys


REL = Path('experiments/multimodal_output_portfolio/joint_hepta_20261029/v3')
PILOT = 'ndu_frozen_lm_followup_20261106'
PUBLIC_KEYS = ('task_id', 'family', 'source_cluster', 'question', 'answer_format')
SCHEMA = ('Artist(ArtistId,Name); Album(AlbumId,Title,ArtistId); '
          'Genre(GenreId,Name); Track(TrackId,Name,AlbumId,GenreId,Milliseconds); '
          'Invoice(InvoiceId,BillingCountry,Total).')


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            value.update(chunk)
    return value.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def require(condition, name):
    if not condition:
        raise AssertionError(name)


def near(first, second):
    return math.isclose(first, second, rel_tol=1e-10, abs_tol=1e-6)


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def strict_parse(text):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    def finite(value):
        raise ValueError('Nonfinite JSON')
    return json.loads(text, object_pairs_hook=unique, parse_constant=finite)


def public_prompt(task, arm):
    text = task['question']+'\nRequired answer format: '+task['answer_format']+'.'
    if task['family'] == 'sqlite_query':
        text += '\nPublic SQLite schema: '+SCHEMA
    if arm == 'one_model_selected_tool':
        instruction = ('Return only a JSON object with exactly one key "query" whose value is one read-only SQLite SELECT statement.'
                       if task['family'] == 'sqlite_query' else
                       'Return only a JSON object for a source search, either {"needle":"literal search text"} or {"start_line":1,"line_count":20}.')
        return text+'\nYou may make exactly one tool call on the pinned source. '+instruction
    return text+'\nReturn only the requested JSON answer. Do not include Markdown, prose or a tool call.'


def parameter_fingerprint(path):
    """Hash float32 parameter bytes by exact BF16 bit expansion, without a model."""
    import numpy as np
    result = hashlib.sha256()
    with path.open('rb') as stream:
        header_size = int.from_bytes(stream.read(8), 'little')
        header = json.loads(stream.read(header_size))
        tensors = {k: v for k, v in header.items() if k != '__metadata__'}
        count = 0
        intervals = []
        for name, spec in sorted(tensors.items()):
            require(spec['dtype'] == 'BF16', 'Expected frozen BF16 tensor storage')
            start, end = spec['data_offsets']
            size = math.prod(spec['shape'])
            require(end-start == 2*size, 'Tensor storage size')
            count += size
            intervals.append((start, end))
            result.update(json.dumps([name, spec['shape'], 'torch.float32']).encode())
            stream.seek(8+header_size+start)
            remaining = end-start
            while remaining:
                block = stream.read(min(1048576, remaining))
                require(bool(block), 'Complete tensor storage')
                words = np.frombuffer(block, dtype='<u2').astype('<u4')
                result.update((words << 16).astype('<u4', copy=False).tobytes())
                remaining -= len(block)
        intervals.sort()
        require(intervals[0][0] == 0, 'Tensor data begins at zero')
        require(all(a[1] == b[0] for a, b in zip(intervals, intervals[1:])), 'No tensor gaps or overlaps')
        require(8+header_size+intervals[-1][1] == path.stat().st_size, 'Complete weight file accounting')
    return {'sha256': result.hexdigest(), 'parameters': count, 'tensor_count': len(tensors),
            'method': 'Sorted safetensors names and shapes; exact BF16-to-float32 bit expansion; no model instantiated.'}


def verify_model(source, runtime):
    declared = read(source/'model_manifest.json')
    actual = read(source/'evidence/acquisition/materialized-model.json')
    require(actual['manifest_sha256'] == sha(source/'model_manifest.json'), 'Materialization binding')
    require(all(actual[k] == declared[k] for k in ('model_id', 'revision')), 'Model identity')
    files = {x['name']: x for x in actual['files']}
    expected = {x['name'] for x in declared['files']}
    require(set(files) == expected, 'Materialized inventory')
    require({p.name for p in (runtime/'model').iterdir()} == expected, 'Exact physical model inventory')
    observed = {}
    for item in declared['files']:
        path = runtime/'model'/item['name']
        value = sha(path)
        require(not path.is_symlink() and path.stat().st_size == item['bytes'] == files[item['name']]['bytes'], 'Model file size')
        require(value == files[item['name']]['sha256'], 'Materialized file digest')
        if 'sha256' in item:
            require(value == item['sha256'], 'Published weight digest')
        else:
            data = path.read_bytes()
            blob = hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            require(blob == item['git_blob'], 'Published configuration/tokenizer Git blob')
        observed[item['name']] = {'sha256': value, 'bytes': path.stat().st_size}
    return declared, observed, parameter_fingerprint(runtime/'model/model.safetensors')


def verify_runtime(source):
    manifest = read(source/'evidence/acquisition/runtime-manifest.json')
    require(sys.version == manifest['python'] and platform.platform() == manifest['platform'], 'Python and platform metadata')
    for row in manifest['packages']:
        package = importlib.metadata.distribution(row['name'])
        require(package.version == row['version'], 'Installed package version: '+row['name'])
        require(hashlib.sha256(package.read_text('RECORD').encode()).hexdigest() == row['record_sha256'],
                'Installed package RECORD: '+row['name'])
    return {'packages_matched': len(manifest['packages']), 'python': manifest['python'],
            'scope': 'Reused runtime: version and RECORD-file digest checks, not independent binary/runtime attestation.'}


def transport_config(recorded, output_name, declared, materialized_sha, protocol):
    source = recorded/'hepta-research'/REL/PILOT
    runtime = recorded/'round3_resources/followup_lm'
    identity = {'kind': 'frozen_llm', 'model_id': declared['model_id'], 'revision': declared['revision'],
                'evidence_sha256': materialized_sha}
    config = {'kind': 'command', 'identity': identity,
              'decoding': {'do_sample': False, 'max_new_tokens': protocol['max_output_tokens']},
              'argv': [str(runtime/'venv/bin/python'), str(source/'worker.py'),
                       '--model-directory', str(runtime/'model'), '--materialized',
                       str(source/'evidence/acquisition/materialized-model.json'), '--receipts',
                       str(recorded/'round3_resources'/output_name/'model_responses')]}
    return config


def verify_run(folder, prompts, protocol, frozen, config, declared, parameter, source, tokenizer):
    result = read(folder/'result.json')
    entries = [json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
    qualification = folder.name == 'followup-qualification-v1'
    expected_count = 1 if qualification else 16
    require(len(entries) == 3*expected_count, 'Ledger inventory')
    require(len(result['episodes']) == result['real_model_responses'] == expected_count, 'Result inventory')
    require(result['qualification_only'] == qualification and result['freeze'] == frozen, 'Run identity and source freeze')
    require(result['source_and_tasks_unchanged'] and not result['independent_confirmation'], 'Run scope')
    files = {str(p.relative_to(folder)): sha(p) for p in folder.rglob('*') if p.is_file() and p.name != 'result.json'}
    require(files == result['artifacts_sha256'], 'Exact artifact inventory and hashes')
    response_files = list((folder/'model_responses').glob('*.json'))
    responses = {hashlib.sha256(read(p)['provider_request_id'].encode()).hexdigest(): (p, read(p)) for p in response_files}
    require(len(responses) == len(response_files) == expected_count, 'No duplicate or extra responses')
    require(all(p.stem == value['provider_request_id'] for p, value in responses.values()), 'Response filenames')
    used, request_ids, audits = set(), set(), []
    previous_finish = -math.inf
    for index in range(expected_count):
        intent, terminal, meter = entries[3*index:3*index+3]
        require([(x['kind'], x['phase']) for x in (intent, terminal, meter)] ==
                [('model', 'intent'), ('model', 'terminal'), ('host_envelope', 'meter')], 'No hidden tool/verifier ledger entries')
        require(intent['request_id'] == terminal['request_id'] and intent['request_id'] not in request_ids, 'Unique paired model request')
        require(meter['request_id'] not in request_ids and meter['request_id'] != intent['request_id'], 'Unique host meter')
        request_ids.update((intent['request_id'], meter['request_id']))
        require(digest(intent) == terminal['intent_sha256'], 'Durable intent binding')
        context, prompt = prompts[index]
        require(all(all(event[key] == value for key, value in context.items()) for event in (intent, terminal, meter)), 'Exact public task and arm order')
        require(intent['request_sha256'] == terminal['request_sha256'] == digest({'prompt': prompt}), 'Public-only request reconstruction')
        require(intent['transport_sha256'] == terminal['transport_sha256'] == digest(config), 'Frozen command transport')
        require(intent['expected_identity_sha256'] == terminal['expected_identity_sha256'] == digest(config['identity']), 'Expected model identity')
        provider = terminal['provider_request_sha256']
        require(provider in responses and provider not in used, 'One response per launched request')
        used.add(provider)
        path, response = responses[provider]
        evidence = response['local_evidence']
        require(sha(path) == terminal['response_sha256'], 'Exact stdout and receipt bytes')
        require(all(response[key] == declared[key] for key in ('model_id', 'revision')), 'Observed model identity')
        require(terminal['observed_identity_sha256'] == digest({k: response[k] for k in ('model_id', 'revision')}), 'Observed identity digest')
        require(terminal['status'] == 'ok' and terminal['identity_status'] == 'match' and terminal['error_type'] is None and
                terminal['returncode'] == 0 and terminal['dispatched'] and terminal['response_received'], 'Successful real worker response')
        require(evidence['parameter_sha256_before'] == evidence['parameter_sha256_after'] == parameter['sha256'], 'Frozen parameters match raw weights')
        require(evidence['parameters'] == parameter['parameters'], 'Parameter count')
        for key, name in (('worker_sha256', 'worker.py'), ('protocol_sha256', 'protocol.json'),
                          ('model_manifest_sha256', 'model_manifest.json'),
                          ('materialized_manifest_sha256', 'evidence/acquisition/materialized-model.json')):
            require(evidence[key] == sha(source/name), 'Response source binding: '+key)
        require(evidence['device'] == 'cpu' and evidence['dtype'] == protocol['dtype'] and
                evidence['threads'] == protocol['cpu_threads'] and evidence['torch'] == importlib.metadata.version('torch'), 'Frozen CPU configuration')
        messages = [{'role': 'system', 'content': protocol['system_prompt']}, {'role': 'user', 'content': prompt}]
        input_ids = tokenizer.apply_chat_template(messages, add_generation_prompt=True,
                                                  tokenize=True, return_dict=True)['input_ids']
        tokens = evidence['output_token_ids']
        require(response['usage'] == terminal['usage'] == {'input_tokens': len(input_ids), 'output_tokens': len(tokens), 'cached_input_tokens': 0}, 'Independent token accounting')
        require(tokenizer.decode(tokens, skip_special_tokens=True) == response['text'], 'Exact output token decoding')
        require(len(input_ids) <= protocol['max_input_tokens'] and 0 < len(tokens) <= protocol['max_output_tokens'], 'Token limits')
        clocks = [meter['started_monotonic'], intent['prepared_monotonic'], terminal['intent_finished_monotonic'],
                  terminal['dispatch_monotonic'], terminal['finished_monotonic'], meter['finished_monotonic']]
        require(clocks == sorted(clocks) and clocks[0] >= previous_finish, 'Serial clock order and envelope coverage')
        previous_finish = clocks[-1]
        require(near(terminal['started_monotonic'], clocks[1]) and near(terminal['wall_seconds'], clocks[4]-clocks[1]), 'Request wall meter')
        require(near(meter['wall_seconds'], clocks[-1]-clocks[0]), 'Host wall meter')
        require(near(intent['deadline_monotonic'], clocks[1]+protocol['request_deadline_seconds']) and
                terminal['deadline_monotonic'] == intent['deadline_monotonic'] and clocks[4] <= intent['deadline_monotonic'], 'Request deadline')
        require(0 <= evidence['generation_seconds'] <= evidence['worker_wall_seconds'] <= terminal['wall_seconds'], 'Generation and worker wall inclusion')
        require(abs((utc(terminal['finished_at'])-utc(terminal['started_at'])).total_seconds()-terminal['wall_seconds']) < .01, 'UTC and monotonic agreement')
        require(all(terminal[k] is None for k in ('actual_amount', 'reported_amount', 'reported_currency')) and
                meter['actual_amount'] is None and evidence['actual_host_currency_cost'] is None and
                evidence['external_paid_model_calls'] == 0, 'Unknown currency costs preserved')
        if qualification:
            require(result['episodes'][0] == {'event': terminal, 'text': response['text']}, 'Qualification result binding')
            try:
                parsed = strict_parse(response['text'])
                failure = None if parsed == [1] else {'type': 'WrongQualificationValue', 'message': 'Not [1]'}
            except ValueError as error:
                failure = {'type': type(error).__name__, 'message': str(error)}
        else:
            episode = read(folder/f'episode-{index:02}.json')
            require(episode == result['episodes'][index] and episode['context'] == context, 'Episode result binding')
            require(episode['request_ids'] == [intent['request_id']] and episode['prompt_sha256'] == [digest({'prompt': prompt})], 'Episode request binding')
            try:
                selected = strict_parse(response['text'])
                if context['arm'] == 'one_model_selected_tool':
                    sql = 'Public SQLite schema:' in prompt
                    legal = isinstance(selected, dict)
                    if legal and sql:
                        legal = (set(selected) == {'query'} and isinstance(selected['query'], str)
                                 and 1 <= len(selected['query']) <= 4000)
                    elif legal and set(selected) == {'needle'}:
                        legal = isinstance(selected['needle'], str) and 1 <= len(selected['needle']) <= 128
                    elif legal:
                        legal = (set(selected) == {'start_line', 'line_count'}
                                 and type(selected['start_line']) is int and type(selected['line_count']) is int
                                 and selected['start_line'] >= 1 and 1 <= selected['line_count'] <= 120)
                    if not legal:
                        raise ValueError('Model selected an invalid tool payload')
                raise AssertionError('Unexpected passing delivery checkpoint in frozen failed episode')
            except ValueError as error:
                failure = {'type': type(error).__name__, 'message': str(error)}
            require(failure == episode['failure'], 'Independent strict parse reproduces failure')
            require(episode['quality'] == 0 and episode['status'] == 'not_delivered' and episode['answer'] is None and
                    episode['model_calls'] == 1 and episode['tool_calls'] == 0, 'Failure retained without rescue')
            require(episode['actual_host_currency_cost'] is None and meter['wall_seconds'] <= episode['wall_seconds'] <= protocol['episode_deadline_seconds'], 'Episode wall and unknown cost')
            require(evidence['worker_cpu_seconds'] <= episode['children_cpu_seconds'], 'Worker CPU included in child CPU')
        audits.append({'episode_id': context['episode_id'], 'task_id': context['task_id'], 'arm': context['arm'],
                       'request_id': intent['request_id'], 'response_file': path.name, 'response_sha256': sha(path),
                       'request_sha256': intent['request_sha256'], 'input_tokens': len(input_ids), 'output_tokens': len(tokens),
                       'strict_parse_failure': failure, 'response_prefix': response['text'].splitlines()[0],
                       'request_wall_seconds': terminal['wall_seconds'], 'worker_wall_seconds': evidence['worker_wall_seconds'],
                       'generation_seconds': evidence['generation_seconds'], 'worker_cpu_seconds': evidence['worker_cpu_seconds'],
                       'all_bindings_verified': True})
    require(used == set(responses), 'No orphan response files')
    require(result['actual_host_currency_cost'] is None and result['external_paid_model_calls'] == 0, 'No invented currency total')
    require(result['outer_wall_seconds'] < protocol['global_deadline_seconds'], 'Observed run within global bound')
    require(abs((utc(result['finished_at_utc'])-utc(result['started_at_utc'])).total_seconds()-result['outer_wall_seconds']) < .01, 'Run UTC and monotonic agreement')
    if not qualification:
        arms = {}
        for arm in protocol['arms']:
            group = [row for row in result['episodes'] if row['context']['arm'] == arm]
            arms[arm] = {'episodes': len(group), 'correct': sum(x['quality'] for x in group),
                         'delivered': sum(x['status'] == 'delivered' for x in group),
                         'model_calls': sum(x['model_calls'] for x in group), 'tool_calls': sum(x['tool_calls'] for x in group),
                         'wall_seconds': sum(x['wall_seconds'] for x in group),
                         'children_cpu_seconds': sum(x['children_cpu_seconds'] for x in group)}
        require(arms == result['arms'], 'Independent arm summaries')
        require(sum(x['model_calls'] for x in result['episodes']) <= protocol['maximum_model_requests'], 'Model request budget')
        require(sum(x['wall_seconds'] for x in result['episodes']) <= result['outer_wall_seconds'], 'Run envelope includes episodes')
    return {'requests': audits, 'ledger_entries': len(entries), 'response_count': expected_count,
            'input_tokens': sum(x['input_tokens'] for x in audits), 'output_tokens': sum(x['output_tokens'] for x in audits),
            'worker_cpu_seconds': sum(x['worker_cpu_seconds'] for x in audits),
            'outer_wall_seconds': result['outer_wall_seconds'], 'outer_self_cpu_seconds': result['outer_self_cpu_seconds'],
            'worker_wall_seconds': sum(x['worker_wall_seconds'] for x in audits),
            'started_at_utc': result['started_at_utc'], 'finished_at_utc': result['finished_at_utc'],
            'arms': result.get('arms'), 'artifact_sha256': {**files, 'result.json': sha(folder/'result.json')}}


def main(args):
    source = args.repo/REL/PILOT
    runtime = args.resources/'followup_lm'
    frozen, protocol = read(source/'freeze.json'), read(source/'protocol.json')
    source_files = [args.repo/name for name in frozen['source_sha256']]+[source/'freeze.json']
    inputs = source_files+[p for name in ('followup-qualification-v1', 'followup-pilot-v1') for p in (args.resources/name).rglob('*') if p.is_file()]
    inputs += list((runtime/'model').iterdir())+[args.anchor]
    before = {str(path): sha(path) for path in inputs}
    require(all(sha(args.repo/name) == value for name, value in frozen['source_sha256'].items()), 'Complete frozen source inventory')
    anchor = read(args.anchor)
    require(anchor['freeze_content'].encode() == (source/'freeze.json').read_bytes(), 'Remote and local freeze bytes')
    data = anchor['freeze_content'].encode()
    require(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest() == anchor['freeze_git_blob'], 'Remote freeze Git blob')
    declared, model_files, parameter = verify_model(source, runtime)
    installed = verify_runtime(source)
    for name in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[name] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(runtime/'model', local_files_only=True, trust_remote_code=False)
    tasks = [{key: item[key] for key in PUBLIC_KEYS} for item in read(args.repo/REL/'ndu_llm_confirmation/external_smoke/tasks.json')['tasks']]
    require(len(tasks) == protocol['task_count'] and len({x['source_cluster'] for x in tasks}) == protocol['source_clusters'], 'Task and source cluster inventory')
    prompts = []
    for index, task in enumerate(tasks):
        for arm in protocol['arms'] if index % 2 == 0 else list(reversed(protocol['arms'])):
            context = {'task_id': task['task_id'], 'arm': arm, 'repeat': 0,
                       'episode_id': f'episode-{len(prompts):02}', 'protocol_sha256': digest(protocol)}
            prompts.append((context, public_prompt(task, arm)))
    qualification = [({'task_id': 'execution/qualification', 'arm': 'qualification', 'repeat': 0,
                       'episode_id': 'qualification', 'protocol_sha256': digest(protocol)}, frozen['qualification_prompt_separate'])]
    runs = {}
    for name, sequence in (('followup-qualification-v1', qualification), ('followup-pilot-v1', prompts)):
        config = transport_config(args.recorded_workspace, name, declared, sha(source/'evidence/acquisition/materialized-model.json'), protocol)
        runs[name] = verify_run(args.resources/name, sequence, protocol, frozen, config, declared, parameter, source, tokenizer)
    times = [utc(anchor['pr_created_at']), utc(frozen['frozen_at_utc']), utc(anchor['commit_committer_date']),
             utc(runs['followup-qualification-v1']['started_at_utc']), utc(runs['followup-qualification-v1']['finished_at_utc']),
             utc(runs['followup-pilot-v1']['started_at_utc']), utc(runs['followup-pilot-v1']['finished_at_utc'])]
    require(times == sorted(times), 'Published draft precedes both execution runs')
    require({str(path): sha(path) for path in inputs} == before, 'All input artifacts unchanged by audit')
    report = {'schema': 'ndu.followup-receipt-audit.v1',
              'audited_at_utc': datetime.now(timezone.utc).isoformat(), 'auditor': '/root; adapted existing independent audit machinery',
              'engineering_receipt_audit': 'PASS', 'task_success_gate': 'FAIL_0_OF_16_DELIVERED',
              'model_selected_tool_gate': 'NOT_DEMONSTRATED_0_TOOL_CALLS', 'scientific_confirmation': False,
              'additional_model_forwards': 0, 'input_files_unchanged': True, 'model': declared,
              'model_file_checks': model_files, 'independent_parameter_fingerprint': parameter,
              'runtime_metadata_checks': installed, 'source_sha256': frozen['source_sha256'],
              'remote_anchor': {k: v for k, v in anchor.items() if k != 'freeze_content'},
              'remote_freeze_matches': True, 'ordinary_draft_timestamp_is_external_preregistration': False,
              'qualification_counted_as_task_episode': False, 'runs': runs,
              'actual_host_currency_cost': None, 'external_paid_model_calls': 0,
              'cost_rule': 'Intent and terminal describe one request. Host, worker, and generation time are nested; never summed as separate monetary charges.',
              'limitations': ['Internal adaptation of prior receipt audit; not new independent review or host/clock attestation.',
                              'Public-only model input verified against frozen source and payload hashes; no claim of an OS access-control sandbox.',
                              'Complete recorded-run accounting does not attest to unrelated activity outside these runners.',
                              'Fifteen task failures occur at strict parsing and one at payload schema validation; no semantic verifier or actual tool was reached.',
                              'Disclosed tasks in two source clusters; no NDU gain, untouched confirmation, or monetary net-benefit claim.'],
              'input_sha256': before, 'audit_script_sha256': sha(Path(__file__))}
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({key: report[key] for key in ('engineering_receipt_audit', 'task_success_gate',
                                                'model_selected_tool_gate', 'additional_model_forwards', 'input_files_unchanged')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--anchor', type=Path, default=Path(__file__).with_name('remote-anchor.json'))
    parser.add_argument('--recorded-workspace', type=Path, default=Path('/workspace/scratch/3f6a885bb83c'))
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
