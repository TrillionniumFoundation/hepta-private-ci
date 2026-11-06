"""Deterministic connection checks with synthetic transport; no worker is launched."""
import argparse
from collections import Counter
import itertools
import json
from pathlib import Path
from unittest.mock import patch

from . import run


def simulate(protocol, arm, family, replies, deadline=1000., model_cap=24, reject_legal=False):
    task = {'task_id': 'synthetic/task', 'family': family, 'source_cluster': 'synthetic',
            'question': 'Return the supplied synthetic value.', 'answer_format': 'JSON array of rows' if family == 'sqlite_query' else 'JSON array of strings'}
    calls, remaining = [], list(replies)
    workers = {role: {'role': role} for role in ('sql', 'source', 'verifier')}
    def fake_call(config, payload, context, ledger, timeout, kind, absolute_deadline):
        expected, status, value = remaining.pop(0)
        assert kind == expected
        assert set(payload) == ({'prompt'} if kind == 'model' else {'task', 'answer'} if kind == 'verifier' else {'task', 'payload'})
        if kind != 'model':
            assert payload['task'] == task
        calls.append({'kind': kind, 'role': config.get('role'), 'payload': payload})
        return {'request_id': f'synthetic-{len(calls)}', 'status': status, 'dispatched': True}, value
    caps, budget = {'model': model_cap, 'tool': 8, 'verifier': 16}, {'model': 0, 'tool': 0, 'verifier': 0}
    legal = run.legal_payload
    with patch.object(run, 'call', fake_call), patch.object(run, 'host_envelope', lambda *args: None), \
         patch.object(run.time, 'perf_counter', side_effect=lambda: next(clock)/1000), \
         patch.object(run, 'legal_payload', side_effect=(lambda *args: False) if reject_legal else legal), \
         patch('subprocess.Popen', side_effect=AssertionError('No real worker may launch')):
        clock = itertools.count()
        row = run.episode(task, arm, 0, {'role': 'model'}, workers, protocol, Path('/unused/synthetic-ledger'), deadline, budget, caps)
    assert not remaining
    return row, calls


def main(runtime):
    output = run.ROOT/'must-not-be-created-by-check'
    assert not output.exists() and not (run.ROOT/'freeze.json').exists()
    protocol, model, workers, required = run.configuration(runtime, output)
    assert Path(model['argv'][1]) == run.upstream.ROOT/'worker.py'
    assert model['argv'][0] == str(runtime/'venv/bin/python')
    assert model['argv'][3] == str(runtime/'model')
    assert model['decoding'] == {'do_sample': False, 'max_new_tokens': 96}
    assert set(workers) == {'sql', 'source', 'verifier'}
    assert all(workers[role]['argv'][-1] == role for role in workers)
    try:
        run.freeze_matches(required)
        raise AssertionError('Execution must require the future freeze')
    except FileNotFoundError:
        pass
    schedule = run.planned_schedule(protocol)
    assert len(schedule) == 16 and Counter(arm for _, arm in schedule) == {'direct': 8, 'one_model_selected_tool': 8}
    assert all(set(task) == {'task_id', 'family', 'source_cluster', 'question', 'answer_format'} for task, _ in schedule)
    plans = [{'task_id': task['task_id'], 'arm': arm, 'prompt_sha256': run.digest({'prompt': run.prompt(task, 'plan' if arm == 'one_model_selected_tool' else 'direct')})} for task, arm in schedule]
    examples = [
        ('qualification', 'sqlite_query', [('model', 'ok', '```json\n[1]\n```')], 'qualified', None),
        ('direct', 'sqlite_query', [('model', 'ok', '[[1]]'), ('verifier', 'ok', {'quality': 0.})], 'delivered', None),
        ('one_model_selected_tool', 'sqlite_query', [('model', 'ok', '```json\n{"query":"SELECT 1"}\n```'), ('tool', 'ok', {'rows': [[1]]}),
         ('model', 'ok', '```json\n[[1]]\n```'), ('verifier', 'ok', {'quality': 1.})], 'delivered', None),
        ('one_model_selected_tool', 'source_inspection', [('model', 'ok', '{"needle":"synthetic"}'), ('tool', 'ok', {'matches': []}),
         ('model', 'ok', '["synthetic"]'), ('verifier', 'ok', {'quality': 1.})], 'delivered', None),
        ('one_model_selected_tool', 'sqlite_query', [('model', 'ok', 'Explanation: {"query":"SELECT 1"}')], 'not_delivered', 'format_failure'),
        ('one_model_selected_tool', 'source_inspection', [('model', 'ok', '{"start_line":true,"line_count":1}')], 'not_delivered', 'parameter_failure'),
        ('one_model_selected_tool', 'sqlite_query', [('model', 'ok', '{"query":"SELECT 1"}'), ('tool', 'failure', None)], 'not_delivered', 'tool_failure'),
    ]
    statuses = []
    for arm, family, replies, status, category in examples:
        row, calls = simulate(protocol, arm, family, replies)
        assert row['status'] == status and row['failure_category'] == category
        assert row['model_calls']+row['tool_calls']+row['verifier_calls'] == len(calls)
        if arm == 'qualification':
            assert row['answer'] == [1] and row['quality'] is None and len(calls) == 1
        elif category is None:
            summary = run.summarize([row])
            assert summary['delivered'] == 1 and summary['correct'] == row['quality']
        if any(call['kind'] == 'tool' for call in calls):
            assert calls[1]['role'] == ('sql' if family == 'sqlite_query' else 'source')
            assert calls[1]['payload']['payload'] == row['selected_payload']
        statuses.append({'arm': arm, 'family': family, 'status': status, 'failure_category': category})
    for settings, category in (({'deadline': -1.}, 'deadline_failure'), ({'model_cap': 0}, 'budget_failure')):
        row, calls = simulate(protocol, 'direct', 'sqlite_query', [], **settings)
        assert not calls and row['failure_category'] == category
    row, calls = simulate(protocol, 'one_model_selected_tool', 'sqlite_query', [('model', 'ok', '{"query":"SELECT 1"}')], reject_legal=True)
    assert len(calls) == 1 and row['failure_category'] == 'parameter_failure'
    assert not output.exists() and not (run.ROOT/'freeze.json').exists()
    report = {'schema': 'ndu.json-transport-wiring-check.v1', 'status': 'PASS', 'synthetic_scenarios': 10,
              'worker_protocol_sha256': protocol['worker_protocol_sha256'], 'shared_keys_equal': list(run.SHARED),
              'planned_task_episodes': plans, 'synthetic_outcomes': statuses, 'required_freeze_inputs': required,
              'source_sha256': {name: run.sha(run.REPO/name) for name in required},
              'model_forwards': 0, 'actual_tool_calls': 0, 'old_response_replays': 0, 'freeze_created': False}
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    main(parser.parse_args().runtime)
