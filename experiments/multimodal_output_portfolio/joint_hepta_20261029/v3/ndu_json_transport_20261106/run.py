"""Prospective development runner; reuse the frozen Qwen worker and actual tools."""
import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import time

from ..ndu_frozen_lm_followup_20261106 import run as upstream
from ..ndu_frozen_lm_followup_20261106.prompts import legal_payload, prompt
from ..ndu_llm_confirmation.contracts import digest
from ..ndu_llm_confirmation.transport import call, host_envelope
from .adapter import DecodeError, Schema, decode

ROOT, REPO, tools = Path(__file__).resolve().parent, upstream.REPO, upstream.tools
SHARED = ('system_prompt', 'cpu_threads', 'dtype', 'sampling', 'max_input_tokens', 'max_output_tokens',
          'request_deadline_seconds', 'episode_deadline_seconds', 'tool_deadline_seconds',
          'global_deadline_seconds', 'maximum_model_requests', 'maximum_tool_requests',
          'task_count', 'source_clusters', 'arms', 'order', 'repeats', 'model_load_policy')
LOCAL_INPUTS = ('adapter.py', 'test_adapter.py', 'prospective-protocol.json', 'README.md', 'validation.json',
                'frozen-source-boundary.json', 'manifest.json', 'run.py', 'RUNNING.md', 'protocol.json',
                'check_wiring.py', 'required-inputs.json')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def configuration(runtime, output):
    procedure, worker = load(ROOT/'protocol.json'), load(upstream.ROOT/'protocol.json')
    if tuple(procedure['shared_worker_keys']) != SHARED or digest({k: procedure[k] for k in SHARED}) != digest({k: worker[k] for k in SHARED}):
        raise ValueError('Shared worker generation/time/task parameters differ')
    if sha(upstream.ROOT/'protocol.json') != procedure['worker_protocol_sha256'] or str(runtime.resolve()) != procedure['runtime_path']:
        raise ValueError('Original worker protocol or fixed runtime differs')
    if sha(ROOT/'adapter.py') != procedure['adapter_sha256'] or sha(ROOT/'prospective-protocol.json') != procedure['prospective_protocol_sha256']:
        raise ValueError('Published adapter or prospective contract differs')
    model = load(upstream.ROOT/'model_manifest.json')
    if (model['model_id'], model['revision']) != (procedure['model_id'], procedure['model_revision']):
        raise ValueError('Fixed Qwen identity differs')
    old = upstream.freeze_matches()
    required = set(old['source_sha256']) | {str((upstream.ROOT/'freeze.json').relative_to(REPO))}
    required.update(str(ROOT.relative_to(REPO)/name) for name in LOCAL_INPUTS)
    for folder in (ROOT, upstream.ROOT, Path(tools.__file__).parent):
        for parent in (folder, *folder.parents):
            if parent == REPO.parent:
                break
            if (parent/'__init__.py').is_file():
                required.add(str((parent/'__init__.py').relative_to(REPO)))
    listed = load(ROOT/'required-inputs.json')['paths']
    if set(listed) != required or len(listed) != len(required) or not all((REPO/name).is_file() for name in required):
        raise ValueError('Exact future-freeze input inventory differs')
    if sha(Path(tools.__file__).parent/'tasks.json') != procedure['task_bank_sha256']:
        raise ValueError('Disclosed task bank differs')
    model_config, workers = upstream.configs(runtime, output, worker)
    return procedure, model_config, workers, sorted(required)


def freeze_matches(required):
    frozen = load(ROOT/'freeze.json')
    if (frozen.get('schema') != 'ndu.json-transport-source-freeze.v1' or
            frozen.get('before_candidate_inference') is not True or frozen.get('external_preregistration') is not False or
            frozen.get('procedure_protocol_sha256') != sha(ROOT/'protocol.json')):
        raise ValueError('A separate prospective procedure freeze is required')
    if frozen['source_sha256'] != {name: sha(REPO/name) for name in required}:
        raise ValueError('Complete source freeze mismatch')
    return frozen


def decode_stage(text, schema, stage, row):
    record = {'stage': stage, 'schema': schema.value, 'raw_sha256': None, 'body_sha256': None, 'envelope': None}
    row['decodings'].append(record)
    try:
        record['raw_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    except (AttributeError, UnicodeEncodeError):
        pass
    try:
        result = decode(text, schema=schema)
    except DecodeError as exc:
        record.update(status='rejected', rejection_code=exc.code)
        raise
    record.update(asdict(result), status='accepted')
    return result.value


class EpisodeFailure(RuntimeError):
    def __init__(self, category, detail):
        self.category = category
        super().__init__(detail)


def episode(task, arm, index, model_config, workers, protocol, ledger, deadline, budget, caps):
    started, started_at, before = time.perf_counter(), datetime.now(timezone.utc).isoformat(), resource.getrusage(resource.RUSAGE_CHILDREN)
    context = {'task_id': task['task_id'], 'arm': arm, 'repeat': 0, 'episode_id': f'episode-{index:02}', 'protocol_sha256': digest(protocol)}
    deadline = min(deadline, started+protocol['episode_deadline_seconds'])
    row = {'context': context, 'source_cluster': task['source_cluster'], 'status': 'not_delivered', 'quality': 0.,
           'answer': None, 'request_ids': [], 'prompt_sha256': [], 'decodings': [], 'legal_payload': None,
           'failure_category': None, 'episode_deadline_monotonic': deadline, 'completion_monotonic': None}
    row.update({kind+suffix: 0 for kind in ('model', 'tool', 'verifier') for suffix in ('_calls', '_dispatches')})
    stage = 'qualification' if arm == 'qualification' else 'plan' if arm == 'one_model_selected_tool' else 'direct'

    def invoke(config, payload, kind, timeout):
        if time.perf_counter() >= deadline:
            raise EpisodeFailure('deadline_failure', 'Episode/global admission deadline exhausted')
        if budget[kind] >= caps[kind]:
            raise EpisodeFailure('budget_failure', kind+' request cap exhausted')
        event, answer = call(config, payload, context, ledger, timeout, kind, deadline)
        budget[kind] += 1
        row[kind+'_calls'] += 1
        row[kind+'_dispatches'] += int(event['dispatched'])
        row['request_ids'].append(event['request_id'])
        if kind == 'model':
            row['prompt_sha256'].append(digest(payload))
        if event['status'] != 'ok':
            raise EpisodeFailure(kind+'_failure', event['status'])
        return answer

    def complete(status, quality):
        completed = time.perf_counter()
        if completed > deadline:
            raise EpisodeFailure('deadline_failure', 'Delivery deadline exhausted')
        row.update(status=status, quality=quality, completion_monotonic=completed)

    try:
        observation = None
        if arm == 'qualification':
            text = invoke(model_config, {'prompt': protocol['qualification_prompt']}, 'model', protocol['request_deadline_seconds'])
            row['answer'] = decode_stage(text, Schema.QUALIFICATION, stage, row)
            complete('qualified', None)
        else:
            if arm == 'one_model_selected_tool':
                text = invoke(model_config, {'prompt': prompt(task, 'plan')}, 'model', protocol['request_deadline_seconds'])
                schema = Schema.SQL_QUERY if task['family'] == 'sqlite_query' else Schema.SOURCE_READ
                selected = decode_stage(text, schema, stage, row)
                row['legal_payload'] = legal_payload(task, selected)
                row['selected_payload'] = selected
                if not row['legal_payload']:
                    raise EpisodeFailure('parameter_failure', 'Original legal_payload rejected decoded plan')
                role = 'sql' if task['family'] == 'sqlite_query' else 'source'
                observation = invoke(workers[role], {'task': task, 'payload': selected}, 'tool', protocol['tool_deadline_seconds'])
                row['tool_observation'] = observation
                stage = 'answer'
            text = invoke(model_config, {'prompt': prompt(task, stage, observation)}, 'model', protocol['request_deadline_seconds'])
            schema = Schema.ROWS_ANSWER if task['family'] == 'sqlite_query' else Schema.STRINGS_ANSWER
            row['answer'] = decode_stage(text, schema, stage, row)
            checked = invoke(workers['verifier'], {'task': task, 'answer': row['answer']}, 'verifier', protocol['tool_deadline_seconds'])
            complete('delivered', checked['quality'])
    except (DecodeError, EpisodeFailure) as exc:
        category = (('parameter_failure' if stage == 'plan' else 'answer_schema_failure') if exc.code == 'schema_mismatch'
                    else 'format_failure') if isinstance(exc, DecodeError) else exc.category
        row.update(failure_category=category, failure={'stage': stage, 'type': type(exc).__name__, 'message': str(exc)})
    finally:
        host_envelope(context, ledger, started_at, started)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        row.update(wall_seconds=time.perf_counter()-started, actual_host_currency_cost=None,
                   children_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime)
    return row


def summarize(rows):
    return {'episodes': len(rows), 'delivered': sum(x['status'] == 'delivered' for x in rows),
            'correct': sum(x['quality'] for x in rows), 'legal_plans': sum(x['legal_payload'] is True for x in rows),
            'failures': dict(Counter(x['failure_category'] for x in rows if x['failure_category'])),
            'decoder_outcomes': dict(Counter((d['envelope'] if d['status'] == 'accepted' else d['rejection_code']) for x in rows for d in x['decodings'])),
            **{kind+suffix: sum(x[kind+suffix] for x in rows) for kind in ('model', 'tool', 'verifier') for suffix in ('_calls', '_dispatches')},
            'wall_seconds': sum(x['wall_seconds'] for x in rows), 'children_cpu_seconds': sum(x['children_cpu_seconds'] for x in rows)}


def planned_schedule(protocol):
    tasks = [tools.public_task(task) for task in tools.bank()['tasks']]
    if len(tasks) != protocol['task_count'] or len({t['source_cluster'] for t in tasks}) != protocol['source_clusters']:
        raise ValueError('Fixed task inventory differs')
    return [(task, arm) for index, task in enumerate(tasks) for arm in
            (protocol['arms'] if index % 2 == 0 else list(reversed(protocol['arms'])))]


def main(runtime, output, qualification, qualification_result):
    if output.exists():
        raise ValueError('Refusing to overwrite an existing attempt')
    protocol, model_config, workers, required = configuration(runtime, output)
    frozen = freeze_matches(required)
    gate_sha = None
    if not qualification:
        gate = load(qualification_result) if qualification_result else {}
        if not (gate.get('qualification_only') is True and gate.get('qualification_passed') is True and gate.get('freeze') == frozen and
                gate.get('protocol_sha256') == digest(protocol) and gate.get('source_and_tasks_unchanged') is True and
                gate.get('counts') == {'model': 1, 'tool': 0, 'verifier': 0} and gate.get('real_model_responses') == 1):
            raise ValueError('This exact development freeze requires its own successful qualification')
        if any(sha(qualification_result.parent/name) != value for name, value in gate['artifacts_sha256'].items()):
            raise ValueError('Qualification artifacts changed')
        gate_sha = sha(qualification_result)
    schedule = planned_schedule(protocol)
    if qualification:
        schedule = [({'task_id': 'execution/qualification', 'source_cluster': 'execution'}, 'qualification')]
    output.mkdir(parents=True)
    started, cpu, start_at = time.perf_counter(), time.process_time(), datetime.now(timezone.utc).isoformat()
    caps = {'model': 1 if qualification else protocol['maximum_model_requests'],
            'tool': 0 if qualification else protocol['maximum_tool_requests'], 'verifier': 0 if qualification else protocol['maximum_verifier_requests']}
    budget, rows = dict.fromkeys(caps, 0), []
    for index, (task, arm) in enumerate(schedule):
        row = episode(task, arm, index, model_config, workers, protocol, output/'requests.jsonl', started+protocol['global_deadline_seconds'], budget, caps)
        rows.append(row)
        save(output/f'episode-{index:02}.json', row)
    unchanged = freeze_matches(required) == frozen
    responses = [load(p) for p in (output/'model_responses').glob('*.json') if not p.name.startswith('failure-')]
    if any(x['local_evidence']['parameter_sha256_before'] != x['local_evidence']['parameter_sha256_after'] for x in responses):
        raise ValueError('Frozen parameter invariant failed')
    report = {'schema': 'ndu.json-transport-development-result.v1', 'started_at_utc': start_at,
              'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'protocol_sha256': digest(protocol),
              'worker_protocol_sha256': protocol['worker_protocol_sha256'], 'freeze': frozen, 'source_and_tasks_unchanged': unchanged,
              'qualification_only': qualification, 'qualification_passed': rows[0]['status'] == 'qualified' if qualification else None,
              'qualification_result_sha256': gate_sha, 'task_episodes_not_started': 16 if qualification else 0,
              'episodes': rows, 'real_model_responses': len(responses), 'counts': budget, 'caps': caps,
              'actual_host_currency_cost': None, 'external_paid_model_calls': 0, 'independent_confirmation': False,
              'outer_wall_seconds': time.perf_counter()-started, 'outer_self_cpu_seconds': time.process_time()-cpu,
              'arms': {} if qualification else {arm: summarize([x for x in rows if x['context']['arm'] == arm]) for arm in protocol['arms']},
              'scope': protocol['gain_claim']}
    report['artifacts_sha256'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    save(output/'result.json', report)
    print(json.dumps({key: report[key] for key in ('qualification_only', 'qualification_passed', 'real_model_responses', 'arms')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--qualification', action='store_true')
    parser.add_argument('--qualification-result', type=Path)
    args = parser.parse_args()
    main(args.runtime, args.output, args.qualification, args.qualification_result)
