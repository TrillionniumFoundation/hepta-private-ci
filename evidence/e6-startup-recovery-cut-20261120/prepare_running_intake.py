"""Index already saved start/peer receipts; do not poll the running owner."""
import collections
import importlib.util
import json
from pathlib import Path

ROOT = Path('/workspace/scratch/e9e051ab0825')
D = ROOT / 'metrics_integration/execution-readout-intake-diagnostic-6'
spec = importlib.util.spec_from_file_location('intake_helpers', D / 'prepare_input_index.py')
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
OUT = D / 'input-index-preparation-4'


def dump(n, value):
    with (OUT / n).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def main():
    OUT.mkdir(exist_ok=False)
    old = []
    parents = []
    for name in ['input-index-preparation-1/CURRENT_INPUT_INDEX.json',
                 'input-index-preparation-2/ADDITIONAL_INPUT_INDEX.json',
                 'input-index-preparation-3/ADDITIONAL_STATIC_INPUT_INDEX.json']:
        j, p = h.get_json(D / name)
        old.extend(j['files'])
        parents.append(p)
    assert len(old) == 558
    by_key = collections.defaultdict(list)
    for row in old:
        by_key[h.key(row)].append(row)
    rows = []

    def add(p, role, expected=None):
        _, pin = h.read_file(p)
        if expected:
            assert all(pin[k] == expected[k] for k in ['bytes','sha256'])
        prior = by_key.get(h.key(pin))
        if prior:
            other = sorted(prior, key=lambda x:x['workspace_path'])[0]
            _, observed = h.read_file(ROOT / other['workspace_path'])
            assert h.same_identity(pin, observed)
            storage = {'kind':'previous_preparatory_index_exact_body',
                       'prior_workspace_path':other['workspace_path']}
        else:
            storage = {'kind':'new_local_original_body_not_yet_archived',
                       'body_id':pin['sha256'], 'future_repository_path':None}
        rows.append({**pin,'roles':[role],'storage':storage})

    peer = ROOT / 'e6_material_resume_peer_2'
    manifest, peer_pin = h.get_json(peer / 'MANIFEST.json')
    assert peer_pin['sha256'] == '4fa3d7b684b118cf9fe5c19c6ec37ede45502df96b5c8bb5ce6b43a0c3aa940e'
    add(peer / 'MANIFEST.json','frozen_successor_peer')
    for row in manifest['files']:
        rel = Path(row['path'])
        assert not rel.is_absolute() and '..' not in rel.parts
        add(peer / rel,'frozen_successor_peer_member',row)
    add(peer / 'ROOT_READBACK.json','root_successor_peer_readback')
    resume = ROOT / 'e6_owner_work/historical_startup_recovery/material_resume_2'
    for n in ['ROOT_MATERIAL_EXECUTION_REVIEW.json','OWNER_START.json']:
        add(resume / n,'material_owner2_exact_authorization_or_start_not_terminal')
    add(ROOT / 'metrics_integration/AUTOMATION_MATERIAL_RESUME2_RUNNING_HOLD.json',
        'retained_root_hold_update_no_scheduling_by_this_reviewer')
    add(ROOT / 'e6_owner_work/historical_startup_compile/rev1/INPUT_CONTRACT.json',
        'static_compile_input_contract_no_executable_payload_or_actual_compile')
    owner, owner_pin = h.get_json(resume / 'OWNER_START.json')
    status = json.loads(owner['content'][0]['text'])
    assert status['session_id'] == 'dpty-1ff0aada969cb9ec4ef726e177ebab6aa31af70f59c70ed2ce1676e68cd0814c'
    assert status['status']['state'] == 'running' and status['reused'] is False
    assert status['status']['output_complete'] is False
    approval, approval_pin = h.get_json(resume / 'ROOT_MATERIAL_EXECUTION_REVIEW.json')
    assert approval['execution_authorized'] is True and approval['automatic_followup_authorized'] is False
    assert approval['new_compiler_native_model_runs_authorized'] == 0
    before_paths = {x['workspace_path'] for x in old}
    assert len(rows) == len({x['workspace_path'] for x in rows})
    assert not before_paths.intersection(x['workspace_path'] for x in rows)
    composition = {'parent_indexes':parents,'previous_logical_file_count':558,
                   'additional_rows':len(rows),'composed_logical_file_count':558+len(rows),
                   'uploaded_repository_paths_remain557_distinct_measure':True}
    dump('ADDITIONAL_START_INPUT_INDEX.json',{
        'status':'START_AND_STATIC_RECEIPTS_ONLY_NOT_MATERIAL_SUCCESS',
        'composition':composition,'files':sorted(rows,key=lambda x:x['workspace_path']),
        'host_network_git_test_build_native_model_actions':0,'pack_executed':False,
    })
    dump('RUNNING_STATE_INTAKE.json',{
        'status':'ACTUAL_OWNER_STARTED_RESULT_UNKNOWN',
        'source':'1a9799686243c2be0ee393ba364e091029cfb944',
        'owner_start_pin':owner_pin,'root_authorization':approval_pin,
        'owner':status['session_id'],'created_unix_ms':status['status']['created_unix_ms'],
        'owner_pid':status['status']['owner_pid'],'worker_pid':status['status']['pid'],
        'reused':False,'actual_terminal_result':None,'actual_new_gets':None,
        'actual_new_body_bytes':None,'actual_material_seal':None,
        'source_after':None,'actual_format':None,'actual_compile':None,
        'peer_manifest':peer_pin,'peer_members_verified':len(manifest['files']),
        'peer_scope':'Both former blockers closed statically; no runtime success is inherited.',
        'host_polling_by_this_reviewer':0,
        'scope':'This is the already saved start observation, not a fresh live process query.',
    })
    print(json.dumps({'output':str(OUT),'additional_rows':len(rows),
                     'composed_logical_file_count':558+len(rows)},ensure_ascii=False))


if __name__ == '__main__':
    main()
