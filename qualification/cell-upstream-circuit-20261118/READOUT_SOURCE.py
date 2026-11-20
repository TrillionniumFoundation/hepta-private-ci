"""Validate every retained primary/setup receipt without model or verifier calls."""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/home/qian-qi/work/hepta-e4-matched-upstream-20261118-2e9b/candidate-41d273d')
RUN = ROOT / 'run-1'
sys.path.insert(0, str(ROOT / 'source/scripts'))
from cell_experiments import data
from cell_experiments.circuit_receipts_v3 import business_evidence
from cell_experiments.online_v4.onpolicy_feedback import feedback

MODELS = {
    'F': '46c1a35887fc0639050210a19ec2a3a421e1bdb3d5e58cff394a1e54879f29f2',
    'T': '430f4051d47672d121a5d790aca0e489804b0d8419c101e3c1171b3d17157786',
    'C': '518f2839f00fab5dfb2dfa386c8abb679465a2379b3335cc535eff1f3a33ee03',
}
PARAMETERS = {
    'F': 'f9c23acb0dcc56fce2f5466e727751737daf9dd87104164848431cb80229d529',
    'T': 'e5da16c3256c27f06f42ecac69880ce8802a0eb3a87c05830d11c09477aa817f',
    'C': 'e268d2763aae2ecba6d145c1db16b1c7f817c4a9167e9baa945d09ffdc16eb53',
}


def read(path):
    return data._parse(path.read_bytes())


def business(output, verification):
    return business_evidence({'semantic_receipt': verification,
        'semantic_receipt_sha256': verification['receipt_sha256'],
        'raw_answer': output['answer'], 'success': verification['success']})


def main():
    report, freeze, retrieval = [read(RUN / name) for name in ('RESULT.json', 'FREEZE.json', 'RETRIEVAL.json')]
    owner, provider = read(ROOT / 'owned-run-1/EXIT.json'), read(RUN / 'PROVIDER_EXIT.json')
    assert owner['wait_returncode'] == provider['returncode'] == 0
    assert owner['timed_out'] is False and report['status'] == 'COMPLETE'
    assert report['freeze_digest'] == data.digest(freeze)
    assert freeze['study_extension']['receipt_digest'] == data.digest(retrieval)
    assert len(report['outcomes']) == 66
    assert freeze['launch']['planned_model_calls'] == 120
    assert len(freeze['arms']) == 11
    assert freeze['record_digests'].keys() == {'upstream'}
    assert len(freeze['record_digests']['upstream']) == 6
    groups, outputs, rows, messages, first_outputs = {}, set(), [], {}, {}
    for outcome in report['outcomes']:
        directory = RUN / outcome['path']
        graph, contract = read(directory / 'RESULT.json'), read(directory / 'CONTRACT.json')
        assert data.digest(graph) == outcome['result_digest']
        assert data.digest(contract) == graph['contract_digest']
        nodes = [node for node in graph['nodes'] if node['status'] == 'COMPLETE']
        one_call = outcome['arm'].endswith('_one_call')
        assert len(nodes) == (1 if one_call else 2)
        assert contract['message_style'] == 'native_turn_v1'
        actual = []
        for index, node in enumerate(nodes):
            path = directory / ('node-' + str(node['slot']))
            request, output, verification = [read(path / name) for name in ('REQUEST.json', 'OUTPUT.json', 'VERIFICATION.json')]
            assert data.digest(request) == node['request_digest']
            assert data.digest(output) == node['output_digest'] and output == node['output']
            assert data.digest(verification) == node['verification_digest'] and verification == node['verification']
            assert output['messages_sha256'] == data.digest(request['task']['messages'])
            cell = contract['graph']['path'][node['slot']]
            assert output['loaded_model_digest'] == MODELS[cell]
            assert output['active_adapter_sha256'] == PARAMETERS[cell]
            assert output['output_tokens'] == len(output['output_token_ids'])
            assert str(path) not in outputs
            outputs.add(str(path))
            measured = business(output, verification)
            assert type(measured['business_success']) is bool
            actual.append(measured['business_success'])
            if index == 1:
                incoming, turns = node['incoming_edges'], request['task']['messages']
                assistants = [turn['content'] for turn in turns if turn['role'] == 'assistant']
                assert assistants == ([nodes[0]['output']['answer']] if 'answer' in incoming else [])
                observed = json.loads(turns[-1]['content'])
                if 'feedback' in incoming:
                    assert observed == json.loads(feedback(nodes[0]['verification']))
                else:
                    assert 'success' not in observed and 'controls_rejected' not in observed
            if index == 0:
                messages[(outcome['task_id'], outcome['arm'])] = request['task']['messages']
                first_outputs[(outcome['task_id'], outcome['arm'])] = output['output_token_ids']
        expected_slot = next((node['slot'] for node, success in zip(nodes, actual) if success), nodes[-1]['slot'])
        assert graph['final_slot'] == expected_slot
        assert graph['success'] == any(actual) == outcome['success']
        group = groups.setdefault(outcome['arm'], collections.Counter())
        group.update(tasks=1, first=actual[0], last=actual[-1], selected=any(actual),
                     two_call_tasks=len(actual) == 2,
                     recovered=len(actual) == 2 and not actual[0] and actual[-1],
                     regressed=len(actual) == 2 and actual[0] and not actual[-1])
        group.update({key: graph['cost'][key] for key in ('model_calls', 'verifier_calls', 'input_tokens', 'output_tokens', 'business_executions', 'format_rejections')})
        rows.append({'task_id': outcome['task_id'], 'arm': outcome['arm'], 'first': actual[0],
                     'last': actual[-1], 'selected': any(actual), 'result_sha256': data.digest(graph)})
    assert len(outputs) == provider['complete_outputs_retained'] == 120
    assert {key: sum(group[key] for group in groups.values()) for key in report['cost']} == report['cost']
    task_ids = {row['task_id'] for row in rows}
    for task in task_ids:
        assert messages[(task, 'native_FF_retrieval')] == messages[(task, 'native_TF_retrieval')]
    calibration = read(RUN / 'A_SETUP_CALIBRATION/RESULT.json')
    assert calibration == freeze['provider']['matched_setup_calibration']
    assert calibration['status'] == 'COMPLETE' and calibration['select_on_B'] is False
    assert calibration['model_calls'] == calibration['verifier_calls'] == 4
    setup = collections.Counter()
    for cell in ('F', 'T'):
        directory = RUN / 'A_SETUP_CALIBRATION'
        cold = read(directory / (cell + '_COLD_OUTPUT.json'))
        pooled = read(directory / (cell + '_POOL/POOL_RESULT.json'))
        assert data.digest(cold) == calibration['pairs'][cell]['cold_output_digest']
        assert data.digest(pooled) == calibration['pairs'][cell]['pool_output_digest']
        assert cold['output_token_ids'] == pooled['output_token_ids']
        assert cold['loaded_model_digest'] == pooled['loaded_model_digest'] == MODELS[cell]
        assert pooled['active_adapter_sha256'] == PARAMETERS[cell]
        for output, verification in ((cold, read(directory / (cell + '_COLD_VERIFICATION.json'))),
                                     (pooled, read(directory / (cell + '_POOL/VERIFICATION.json')))):
            measured = business(output, verification)
            setup.update(model_calls=1, verifier_calls=1, input_tokens=output['input_tokens'], output_tokens=output['output_tokens'],
                         business_executions=measured['verifier_executed'], format_rejections=measured['format_admitted'] is False)
    assert setup['input_tokens'] == calibration['input_tokens'] and setup['output_tokens'] == calibration['output_tokens']
    assert retrieval['reference_verifier_calls'] == 6 and all(v['success'] for v in retrieval['reference_verifications'])
    reference = collections.Counter(verifier_calls=6)
    memory = [row for row in data.load_records(ROOT / 'source/qualification/cell-experiments-v3-20261116/development-old-open.records.jsonl') if row['split'] == 'train']
    assert [data.digest(row) for row in memory] == retrieval['memory_record_digests']
    for record, verification in zip(memory, retrieval['reference_verifications']):
        measured = business({'answer': record['final_answer']}, verification)
        assert measured['business_success'] is True
        reference.update(business_executions=measured['verifier_executed'], format_rejections=measured['format_admitted'] is False)
    all_cost = {key: value + setup[key] + reference[key] for key, value in report['cost'].items()}
    assert all_cost['model_calls'] == 124 and all_cost['verifier_calls'] == 130
    selected = {(row['task_id'], row['arm']): row['selected'] for row in rows}
    comparisons = {
        'TF_success_beyond_both_FF_and_TT': [task for task in sorted(task_ids) if selected[task, 'native_TF'] and not selected[task, 'native_FF'] and not selected[task, 'native_TT']],
        'TF_success_lost_without_answer': [task for task in sorted(task_ids) if selected[task, 'native_TF'] and not selected[task, 'native_TF_no_answer']],
        'TF_success_lost_without_feedback': [task for task in sorted(task_ids) if selected[task, 'native_TF'] and not selected[task, 'native_TF_no_feedback']],
        'repeated_F_first_token_outputs_equal': all(first_outputs[task, 'native_FF'] == first_outputs[task, 'native_F_one_call'] for task in task_ids),
        'repeated_T_first_token_outputs_equal': all(first_outputs[task, 'native_TT'] == first_outputs[task, 'native_T_one_call'] for task in task_ids),
    }
    deployment = read(ROOT / 'DEPLOYMENT.json')
    assert deployment['source_commit'] == '41d273d06d0138ab4a747c5dc73bb2ee2a61e9ee'
    for name, expected in deployment['files'].items():
        assert hashlib.sha256((ROOT / 'source' / name).read_bytes()).hexdigest() == expected
    artifact_root = Path('/dev/shm/hepta-cell-experiments-v3-20261116-0c078a')
    admitted = ROOT / 'ADMITTED_MANIFESTS'
    admitted.mkdir(exist_ok=False)
    for cell, identity in MODELS.items():
        original = Path(freeze['provider']['manifest_files'][cell]['path'])
        raw = original.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == freeze['provider']['manifest_files'][cell]['sha256']
        assert data.digest(data._parse(raw)) == identity
        target = admitted / cell
        target.mkdir()
        (target / 'manifest.json').write_bytes(raw)
        training = freeze['provider']['pool']['inventory']['cells'][cell]['training']
        raw = (artifact_root / training['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == training['sha256']
        assert len(raw) == training['bytes']
        (target / 'TRAINING.json').write_bytes(raw)
    retained = {str(path.relative_to(ROOT)): {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in sorted(ROOT.rglob('*')) if path.is_file() and '__pycache__' not in path.parts
                and path.name not in ('READOUT.json', 'INDEX.json', 'RAW_EVIDENCE.tar.xz', 'ARCHIVE.json', 'READOUT_STDOUT.txt', 'READOUT_STDERR.txt')}
    result = {
        'schema': 'hepta.matched-upstream-circuit-readout.v1', 'status': 'COMPLETE_ORIGINALS_VALIDATED',
        'source_commit': deployment['source_commit'], 'freeze_digest': data.digest(freeze),
        'groups': groups, 'rows': rows, 'comparisons': comparisons,
        'primary_cost': report['cost'], 'setup_cost': setup, 'reference_cost': reference, 'total_model_and_verifier_cost': all_cost,
        'additional_reference_verifier_calls': 6, 'calibration': calibration,
        'owner_exit': owner, 'provider_exit': provider, 'pool_initialization_cost': report['pool_initialization_cost'],
        'actual_run_model_loads': {'base_loads': 3, 'adapter_loads': 5, 'scope': 'two cold A calibration Predictors, then one shared base with three adapters; engineering preflight loads excluded'},
        'hash_objects': {
            'adapter_model.safetensors': 'SHA256 of complete serialized file bytes, verified against each original model manifest',
            'active_adapter_sha256': 'SHA256 of canonical normalized parameter name/dtype/shape plus contiguous loaded tensor bytes, checked against original TRAINING parameter_after',
            'different_hash_objects_do_not_imply_changed_model_bytes': True,
        },
        'readout_model_calls': 0, 'readout_verifier_calls': 0,
        'primary_matched_cells': ['F', 'T'], 'secondary_unmatched_cell': 'C',
        'retrieval_inputs_equal': True, 'exposed_development_panel': True, 'new_independent_users': 0,
        'scientific_confirmation_qualified': False, 'native_owner_adoption': False,
        'full_system_cost_known': False, 'matched_actual_cost_claim': False,
        'original_index_digest': data.digest(retained),
    }
    for name, value in (('READOUT.json', result), ('INDEX.json', retained)):
        with (ROOT / name).open('xb') as stream:
            stream.write(data.canonical(value) + b'\n')
    print(data.canonical({key: value for key, value in result.items() if key not in ('rows', 'owner_exit', 'provider_exit', 'pool_initialization_cost', 'calibration')}).decode())


if __name__ == '__main__':
    main()
