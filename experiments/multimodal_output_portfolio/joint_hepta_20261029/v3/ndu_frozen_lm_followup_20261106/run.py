"""Execute the published fixed pilot, preserving failures and all planned tasks."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

from ..ndu_llm_confirmation.contracts import digest
from ..ndu_llm_confirmation.transport import call, host_envelope
from ..ndu_llm_confirmation.external_smoke import tools
from .prompts import legal_payload, parse, prompt

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[4]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_matches():
    frozen = json.loads((ROOT/'freeze.json').read_text())
    current = {name: sha(REPO/name) for name in frozen['source_sha256']}
    if current != frozen['source_sha256']:
        raise ValueError('Source/task freeze mismatch')
    return frozen


def configs(runtime, output, protocol):
    model = json.loads((ROOT/'model_manifest.json').read_text())
    materialized = ROOT/'evidence/acquisition/materialized-model.json'
    identity = {'kind': 'frozen_llm', 'model_id': model['model_id'], 'revision': model['revision'],
                'evidence_sha256': sha(materialized)}
    model_config = {'kind': 'command', 'identity': identity, 'decoding': {
                    'do_sample': False, 'max_new_tokens': protocol['max_output_tokens']},
                    'argv': [str(runtime/'venv/bin/python'), str(ROOT/'worker.py'),
                        '--model-directory', str(runtime/'model'), '--materialized', str(materialized),
                        '--receipts', str(output/'model_responses')]}
    module = tools.__name__
    workers = {role: {'kind': 'command', 'identity': {'kind': 'tool', 'model_id': role,
                 'revision': sha(Path(tools.__file__))}, 'argv': [sys.executable, '-m', module, role]}
               for role in ('sql', 'source', 'verifier')}
    return model_config, workers


def episode(task, arm, index, model_config, workers, protocol, ledger, global_deadline):
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc).isoformat()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    context = {'task_id': task['task_id'], 'arm': arm, 'repeat': 0,
               'episode_id': f'episode-{index:02}', 'protocol_sha256': digest(protocol)}
    deadline = min(global_deadline, started+protocol['episode_deadline_seconds'])
    result = {'context': context, 'source_cluster': task['source_cluster'],
              'quality': 0., 'status': 'not_delivered', 'request_ids': [], 'model_calls': 0,
              'tool_calls': 0, 'answer': None, 'prompt_sha256': []}
    def invoke(config, payload, kind, timeout):
        if time.perf_counter() >= deadline:
            raise TimeoutError('Episode/global deadline exhausted before admission')
        event, answer = call(config, payload, context, ledger, timeout, kind, deadline)
        result['request_ids'].append(event['request_id'])
        if kind == 'model':
            result['model_calls'] += 1
            result['prompt_sha256'].append(digest(payload))
        elif kind == 'tool':
            result['tool_calls'] += 1
        if event['status'] != 'ok':
            raise RuntimeError(kind+':'+event['status'])
        return answer
    try:
        observation = None
        if arm == 'one_model_selected_tool':
            selected = parse(invoke(model_config, {'prompt': prompt(task, 'plan')},
                                   'model', protocol['request_deadline_seconds']))
            if not legal_payload(task, selected):
                raise ValueError('Model selected an invalid tool payload')
            role = 'sql' if task['family'] == 'sqlite_query' else 'source'
            observation = invoke(workers[role], {'task': task, 'payload': selected},
                                 'tool', protocol['tool_deadline_seconds'])
            result['selected_payload'] = selected
            result['tool_observation'] = observation
        text = invoke(model_config, {'prompt': prompt(task, 'answer' if observation is not None else 'direct', observation)},
                      'model', protocol['request_deadline_seconds'])
        result['answer'] = parse(text)
        checked = invoke(workers['verifier'], {'task': task, 'answer': result['answer']},
                         'verifier', protocol['tool_deadline_seconds'])
        result.update(quality=checked['quality'], status='delivered')
    except (ValueError, RuntimeError, TimeoutError) as exc:
        result['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        host_envelope(context, ledger, started_at, started)
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        result.update(wall_seconds=time.perf_counter()-started,
                      children_cpu_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
                      actual_host_currency_cost=None)
    return result


def main(runtime, output, qualification):
    if output.exists():
        raise ValueError('Refusing to overwrite an existing attempt')
    frozen = freeze_matches()
    output.mkdir(parents=True)
    protocol = json.loads((ROOT/'protocol.json').read_text())
    model_config, workers = configs(runtime, output, protocol)
    ledger = output/'requests.jsonl'
    started, cpu = time.perf_counter(), time.process_time()
    start_at = datetime.now(timezone.utc).isoformat()
    rows = []
    if qualification:
        context = {'task_id': 'execution/qualification', 'arm': 'qualification', 'repeat': 0,
                   'episode_id': 'qualification', 'protocol_sha256': digest(protocol)}
        event, text = call(model_config, {'prompt': 'Return only this JSON array: [1].'}, context, ledger,
                           protocol['request_deadline_seconds'])
        rows.append({'event': event, 'text': text})
        host_envelope(context, ledger, start_at, started)
    else:
        tasks = [tools.public_task(task) for task in tools.bank()['tasks']]
        if len(tasks) != protocol['task_count']:
            raise ValueError('Task inventory mismatch')
        global_deadline = started+protocol['global_deadline_seconds']
        for task_index, task in enumerate(tasks):
            arms = protocol['arms'] if task_index % 2 == 0 else list(reversed(protocol['arms']))
            for arm in arms:
                row = episode(task, arm, len(rows), model_config, workers, protocol, ledger, global_deadline)
                rows.append(row)
                with (output/f"episode-{len(rows)-1:02}.json").open('x') as stream:
                    json.dump(row, stream, indent=2, sort_keys=True, allow_nan=False)
                    stream.write('\n')
        if sum(x['model_calls'] for x in rows) > protocol['maximum_model_requests']:
            raise AssertionError('Registered model-call cap exceeded')
        if sum(x['tool_calls'] for x in rows) > protocol['maximum_tool_requests']:
            raise AssertionError('Registered tool-call cap exceeded')
    unchanged = freeze_matches() == frozen
    responses = list((output/'model_responses').glob('*.json')) if (output/'model_responses').exists() else []
    verified = [json.loads(p.read_text()) for p in responses if not p.name.startswith('failure-')]
    if any(x['local_evidence']['parameter_sha256_before'] != x['local_evidence']['parameter_sha256_after'] for x in verified):
        raise AssertionError('Parameter drift')
    report = {'schema': 'ndu.frozen-lm-pilot-result.v1', 'started_at_utc': start_at,
              'finished_at_utc': datetime.now(timezone.utc).isoformat(), 'qualification_only': qualification,
              'freeze': frozen, 'source_and_tasks_unchanged': unchanged, 'episodes': rows,
              'real_model_responses': len(verified), 'actual_host_currency_cost': None,
              'external_paid_model_calls': 0, 'independent_confirmation': False,
              'outer_wall_seconds': time.perf_counter()-started, 'outer_self_cpu_seconds': time.process_time()-cpu,
              'scope': 'Disclosed tasks and frozen local model engineering execution. No NDU gain, held-out confirmation or monetary net-benefit claim.'}
    if not qualification:
        report['arms'] = {arm: {'episodes': len(group), 'correct': sum(x['quality'] for x in group),
                         'delivered': sum(x['status'] == 'delivered' for x in group),
                         'model_calls': sum(x['model_calls'] for x in group),
                         'tool_calls': sum(x['tool_calls'] for x in group),
                         'wall_seconds': sum(x['wall_seconds'] for x in group),
                         'children_cpu_seconds': sum(x['children_cpu_seconds'] for x in group)}
                          for arm in protocol['arms'] if (group := [x for x in rows if x['context']['arm'] == arm])}
    report['artifacts_sha256'] = {str(p.relative_to(output)): sha(p) for p in output.rglob('*') if p.is_file()}
    with (output/'result.json').open('x') as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({key: report.get(key) for key in ('qualification_only', 'real_model_responses', 'arms', 'source_and_tasks_unchanged')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--qualification', action='store_true')
    args = parser.parse_args()
    main(args.runtime, args.output, args.qualification)
