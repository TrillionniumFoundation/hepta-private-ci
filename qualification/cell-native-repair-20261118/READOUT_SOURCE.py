"""Read frozen original model receipts; never invoke a model or a verifier."""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path('/home/qian-qi/work/hepta-e4-native-repair-20261118-2e9b')
RUN = ROOT / 'run-1'
sys.path.insert(0, str(ROOT / 'source/scripts'))
from cell_experiments import data
from cell_experiments.circuit_receipts_v3 import business_evidence
from cell_experiments.online_v4.onpolicy_feedback import feedback


def read(path):
    return data._parse(path.read_bytes())


def main():
    report = read(RUN / 'RESULT.json')
    freeze = read(RUN / 'FREEZE.json')
    retrieval = read(RUN / 'RETRIEVAL.json')
    owner = read(ROOT / 'owned-run-1/EXIT.json')
    provider = read(RUN / 'PROVIDER_EXIT.json')
    assert owner['wait_returncode'] == 0 and provider['returncode'] == 0
    assert report['freeze_digest'] == data.digest(freeze)
    assert freeze['study_extension']['receipt_digest'] == data.digest(retrieval)
    assert len(report['outcomes']) == 44
    groups, outputs, rows, messages = {}, set(), [], {}
    for outcome in report['outcomes']:
        directory = RUN / outcome['path']
        graph = read(directory / 'RESULT.json')
        assert data.digest(graph) == outcome['result_digest']
        contract = read(directory / 'CONTRACT.json')
        assert data.digest(contract) == graph['contract_digest']
        nodes = [node for node in graph['nodes'] if node['status'] == 'COMPLETE']
        assert len(nodes) == 2
        actual = []
        for index, node in enumerate(nodes):
            path = directory / ('node-' + str(node['slot']))
            request, output, verification = [read(path / filename) for filename in
                ('REQUEST.json', 'OUTPUT.json', 'VERIFICATION.json')]
            assert data.digest(request) == node['request_digest']
            assert data.digest(output) == node['output_digest']
            assert data.digest(verification) == node['verification_digest']
            assert output == node['output'] and verification == node['verification']
            assert output['messages_sha256'] == data.digest(request['task']['messages'])
            assert str(path) not in outputs
            outputs.add(str(path))
            actual.append(business_evidence({'semantic_receipt': verification,
                'semantic_receipt_sha256': verification['receipt_sha256'],
                'raw_answer': output['answer'], 'success': verification['success']})['business_success'])
            if index == 1 and contract.get('message_style') == 'native_turn_v1':
                incoming = node['incoming_edges']
                turns = request['task']['messages']
                assistants = [turn['content'] for turn in turns if turn['role'] == 'assistant']
                assert assistants == ([nodes[0]['output']['answer']] if 'answer' in incoming else [])
                observed = json.loads(turns[-1]['content'])
                if 'feedback' in incoming:
                    assert observed == json.loads(feedback(nodes[0]['verification']))
                else:
                    assert 'success' not in observed and 'controls_rejected' not in observed
            if index == 0:
                messages[(outcome['task_id'], outcome['arm'])] = request['task']['messages']
        expected_slot = 0 if actual[0] else 1
        assert graph['final_slot'] == expected_slot
        assert graph['success'] == any(actual) == outcome['success']
        arm = outcome['arm']
        group = groups.setdefault(arm, collections.Counter())
        group.update(tasks=1, first=actual[0], last=actual[1], selected=any(actual),
                     recovered=not actual[0] and actual[1], regressed=actual[0] and not actual[1])
        group.update({key: graph['cost'][key] for key in ('model_calls','verifier_calls',
            'input_tokens','output_tokens','business_executions','format_rejections')})
        rows.append({'task_id':outcome['task_id'], 'arm':arm, 'first':actual[0], 'last':actual[1],
                     'selected':any(actual), 'result_sha256':data.digest(graph)})
    assert len(outputs) == provider['complete_outputs_retained'] == 88
    for task in {row['task_id'] for row in rows}:
        assert messages[(task,'native_FF_retrieval')] == messages[(task,'native_TF_retrieval')]
    assert {key:sum(g[key] for g in groups.values()) for key in report['cost']} == report['cost']
    retained = {str(p.relative_to(ROOT)):{'bytes':p.stat().st_size,
        'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
        and p.name not in ('READOUT.json','INDEX.json','RAW_EVIDENCE.tar.gz')}
    result = {'schema':'hepta.native-turn-repair-readout.v1','source_commit':'ad73c100feece91c152a96ba121d2e9494f10607',
        'status':'COMPLETE_ORIGINALS_VALIDATED','freeze_digest':data.digest(freeze),
        'groups':groups,'rows':rows,'cost':report['cost'],
        'additional_reference_verifier_calls':retrieval['reference_verifier_calls'],
        'reference_preparation_wall_seconds':retrieval['wall_seconds'],
        'owner_exit':owner,'provider_exit':provider,'pool_initialization_cost':report['pool_initialization_cost'],
        'retrieval_inputs_equal':True,'readout_model_calls':0,'readout_verifier_calls':0,
        'new_independent_users':0,'scientific_confirmation_qualified':False,
        'full_system_cost_known':False,'matched_actual_cost_claim':False,
        'original_index_digest':data.digest(retained)}
    (ROOT/'READOUT.json').write_bytes(data.canonical(result)+b'\n')
    (ROOT/'INDEX.json').write_bytes(data.canonical(retained)+b'\n')
    print(data.canonical({k:v for k,v in result.items() if k not in ('rows','owner_exit','provider_exit','pool_initialization_cost')}).decode())

if __name__ == '__main__':
    main()
