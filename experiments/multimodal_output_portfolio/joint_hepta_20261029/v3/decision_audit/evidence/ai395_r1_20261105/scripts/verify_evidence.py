"""Audit the retained R1 evidence; evidence consistency is not semantic acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import time

BASE = '975e1a264c14ed3da02dcee23a64327825387e42'
TREE = 'cb612abe0d02afaf711d37f5d8575a577da5524e'
HISTORICAL_TEXT = 'e868d31e1cdee549254b25203d775363f10b19ab97a01ba7f19e60873caf52d6'

def load(path):
    return json.loads(path.read_text())

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(root, source=None):
    start = time.process_time(), time.perf_counter()
    listing = load(root/'FILES.json')
    expected = {item['path'] for item in listing['files']}
    present = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and str(p.relative_to(root)) not in {'FILES.json', 'VALIDATION.json'}}
    assert expected == present, 'Publication inventory is incomplete or has an extra file'
    for item in listing['files']:
        raw_path = root/item['path']
        path = raw_path.resolve()
        assert path.is_relative_to(root) and not raw_path.is_symlink()
        assert path.stat().st_size == item['size'] and sha(path) == item['sha256'], item['path']
    manifest = load(root/'native/RETAINED_FILE_MANIFEST.json')
    assert manifest['source_sha'] == BASE and manifest['status'] == 'completed'
    owner_files = {item['path']: item for item in manifest['files']}
    for path in (root/'native').rglob('*'):
        relative = str(path.relative_to(root/'native'))
        if path.is_file() and relative in owner_files:
            assert sha(path) == owner_files[relative]['sha256'], relative
    source_manifest = load(root/'SOURCE_SUBSET.json')
    assert source_manifest['source_sha'] == BASE and source_manifest['tree'] == TREE
    for script,receipt,key in [('capture_actual_tensors.py','native/evidence/raw-capture/EXECUTION.json','observer_sha256'),('replay_historical_prompts.py','native/evidence/legacy-probes/EXECUTION.json','observer_sha256'),('inventory_retained_evidence.py','native/RETAINED_FILE_MANIFEST.json','generator_sha256')]:
        assert sha(root/'scripts'/script) == load(root/receipt)[key], script
    if source is not None:
        for entry in source_manifest['files']:
            assert sha(source/entry['path']) == entry['sha256'], entry['path']
    rows = {}
    for group, pattern, count in [('neutral', 'native/evidence/diagnostics/*/TRACE.json', 6), ('capture', 'native/evidence/raw-capture/diagnostics/*/TRACE.json', 6), ('legacy', 'native/evidence/legacy-probes/*/TRACE.json', 11), ('actions', 'actions/artifact/diagnostics/*/TRACE.json', 6)]:
        paths = sorted(root.glob(pattern));assert len(paths) == count, group
        rows[group] = [load(path) for path in paths]
        for path,row in zip(paths,rows[group]):
            assert row['status'] == 'completed' and row['model_generate_calls'] == 1
            assert hashlib.sha256(row['output'].encode()).hexdigest() == row['output_sha256']
            assert len(row['input_token_ids']) == row['input_tokens']
            assert len(row['output_token_ids']) == row['output_tokens']
            assert row['vision_outputs'] and all(v['finite'] for v in row['vision_outputs'])
            assert row['backend']['models']['vlm']['revision'] == '067788b187b95ebe7b2e040b3e4299e342e5b8fd'
            if group in {'capture','legacy'}:
                base = 'evidence/raw-capture' if group == 'capture' else 'evidence/legacy-probes'
                for value in [*row['inputs'].values(),*row['vision_outputs']]:
                    remote = owner_files[base+'/'+value['artifact_relative_path']]
                    assert remote['sha256'] == value['artifact_sha256'] and remote['size'] == value['artifact_bytes']
    neutral = rows['neutral']
    assert {(r['image'],r['instruction']) for r in neutral} == {(i,p) for i in ('original','generated','blank') for p in ('caption','object')}
    assert len({r['inputs']['pixel_values']['sha256'] for r in neutral}) == 3
    assert len({r['inputs']['input_ids']['sha256'] for r in neutral}) == 2
    assert len({v['sha256'] for r in neutral for v in r['vision_outputs']}) == 3
    assert len({r['output_sha256'] for r in neutral}) == 6
    fields = ['input_token_ids','output_token_ids','output','output_sha256','stop_reason']
    for original,capture,actions in zip(neutral,rows['capture'],rows['actions']):
        for key in fields:
            assert original[key] == capture[key] == actions[key], key
        for key,value in original['inputs'].items():
            assert all(capture['inputs'][key][k] == v for k,v in value.items())
        assert original['inputs'] == actions['inputs']
        assert original['vision_outputs'] == actions['vision_outputs']
        assert all(captured[k] == value for a,captured in zip(original['vision_outputs'],capture['vision_outputs']) for k,value in a.items())
        assert original['stop_reason'] == 'eos'
    legacy = rows['legacy']
    assert all(r['role']=='historical_input_replay' and r['output_sha256']==HISTORICAL_TEXT and r['output_tokens']==80 and r['stop_reason']=='max_new_tokens' and not r['last_token_is_eos'] for r in legacy[:9])
    assert legacy[9]['image_sha256'] == legacy[10]['image_sha256']
    assert legacy[9]['inputs']['pixel_values']['sha256'] == legacy[10]['inputs']['pixel_values']['sha256']
    assert legacy[9]['vision_outputs'] == legacy[10]['vision_outputs']
    assert legacy[9]['output_sha256'] != legacy[10]['output_sha256']
    receipts = {'original-six':'1a1aa61b4a7-fc05-4217','raw-capture':'1a1aa6bab03-fc05-42cf','legacy-probes':'1a1aa7162ff-fc05-4330','inventory':'1a1aa7f38b5-fc05-43aa'}
    for name,job in receipts.items():
        value = load(root/f'native/receipts/{name}.json')
        assert value['job_id'] == job and value['state']=='succeeded' and value['exit_code']==0
        assert value['output_complete'] and value['output_durable'] and value['terminal_publication_confirmed']
        assert not value['timed_out'] and not value['cancelled'] and not any(value['log_truncated'].values())
    tensor_rows = [r for r in manifest['files'] if r['path'].startswith('evidence/') and r['path'].endswith('.safetensors')]
    assert len(tensor_rows) == manifest['tensor_files'] == len(manifest['tensor_verification']) == 29
    assert sum(r['size'] for r in tensor_rows) == manifest['tensor_bytes'] == 26239504
    numeric = {r['path']:r for r in manifest['tensor_verification']}
    assert all(numeric[r['path']]['raw_tensor_sha256']==Path(r['path']).stem for r in tensor_rows)
    actions = load(root/'actions/RECEIPTS.json')
    assert actions['run']['head_sha'] == BASE and actions['run']['conclusion']=='success'
    assert actions['jobs']['total_count']==1 and actions['jobs']['jobs'][0]['conclusion']=='success'
    assert load(root/'actions/ARTIFACT_RECEIPT.json')['actual_sha256']=='d84b6451b4b70e2dcc25b01c72ed5553357c0a9081c96d2f8ebd5248a0cca7aa'
    assert (root/'actions/artifact/environment.txt').read_bytes() == (root/'native/evidence/freeze.log').read_bytes()
    r2 = load(root/'r2/PARTIAL_FREEZE.json')
    frozen = json.dumps(r2['frozen'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    assert hashlib.sha256(frozen).hexdigest()==r2['frozen_fields_sha256']
    assert not r2['fully_sealed'] and not r2['r2_training_performed'] and not r2['r2_test_opened'] and r2['no_update']
    costs = load(root/'COST_LEDGER.json')
    assert costs['native_model_generate_calls']==23
    assert abs(costs['native_three_batch_cpu_seconds']-183.559997686)<1e-9
    result = {'schema':'hepta.r1-evidence-readback.v1','status':'consistent','source_sha':BASE,'source_tree':TREE,'native_model_calls':23,'original_actions_model_calls_separately':6,'historical_text_matches':9,'negative_controls':2,'tensor_files_reverified_on_owner':29,'tensor_bodies_downloaded_here':False,'tensor_bytes_retained':26239504,'publication_files':len(expected),'semantic_acceptance':False,'production_qualified':False,'r2_executed':False,'no_update':True,'cpu_seconds':time.process_time()-start[0],'wall_seconds':time.perf_counter()-start[1]}
    return result

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--source',type=Path);parser.add_argument('--receipt',type=Path)
    args=parser.parse_args();result=verify(args.root.resolve(),args.source.resolve() if args.source else None)
    text=json.dumps(result,indent=2,allow_nan=False)+'\n'
    if args.receipt:args.receipt.write_text(text)
    print(text,end='')
