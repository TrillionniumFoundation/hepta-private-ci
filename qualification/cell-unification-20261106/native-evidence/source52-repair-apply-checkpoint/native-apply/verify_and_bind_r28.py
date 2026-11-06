from pathlib import Path, PurePosixPath
import ast
import difflib
import hashlib
import json

ROOT = Path('/workspace/scratch/08f5efd48967')
OUT = Path(__file__).parent
E = '/home/alex/work/hepta-cell-unified-20261106-a/evidence/'
S = '/home/alex/work/hepta-cell-unified-20261106-a/source'
TREE = '211f15baff19095e8c98bcea2b0ed99ca2270ade'
COMMIT = '1e0910becc37383e6d17ecf861ea844fd07d8862'
LEAF = 'codex-rs/network-proxy/src/runtime.rs'


def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def save(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(raw)


def dump(value):
    return (json.dumps(value, indent=2, ensure_ascii=False)+'\n').encode()


payload=json.loads((OUT/'transfer-payload.json').read_bytes())
raws={}
records=[]
for row in payload['files']:
    assert row['eof'] is True and row['path'].startswith(E)
    name=row['path'][len(E):]
    p=PurePosixPath(name)
    assert not p.is_absolute() and '..' not in p.parts and name not in raws
    raw=row['text'].encode()
    actual=pin(raw)
    assert actual['bytes']==row['size'] and actual['sha256']==row['sha256']
    raws[name]=raw
    records.append({'path':name,**actual,'native_version':row['version']})
assert len(raws)==25
terminal_name='native-source52-apply-terminal-process-status.json'
terminal=json.loads(raws[terminal_name])
assert terminal['job_id']==payload['job_id']=='1a1b1e474a3-fc05-7b5b'
assert terminal['state']=='succeeded' and terminal['exit_code']==0
assert all(terminal[k] is True for k in ['audit_recorded','output_complete','output_durable','terminal_publication_confirmed'])
assert all(terminal[k] is False for k in ['automatic_retry','cancelled','timed_out'])
assert not any(terminal['log_truncated'].values())
complete_name='native-source52-apply/complete.json'
complete=json.loads(raws[complete_name])
post=json.loads(raws['native-source52-apply/post-apply-source-guard.json'])
manifest=json.loads(raws['native-candidate-r28-source.json'])
assert complete['source_commit']==COMMIT and complete['source_tree']==TREE
assert complete['actual_changed_file_count']==195 and complete['prior_changed_file_count']==194
assert complete['source_guards_pass'] is True and post['pass'] is True
assert post['actual_tree']==TREE and post['actual_changed_file_count']==195
assert complete['changed_from_source51_paths']==post['changed_from_source51_paths']==[LEAF]
assert complete['source51_original_changed_manifest_rows_unchanged'] is True
assert complete['before_existing_repo_leaf_not_in_prior_changed_manifest'] is True
assert complete['dependency_inputs_changed_paths']==post['dependency_inputs_changed_paths']==[]
assert complete['native_git_head']==post['native_head']=='bef6fa7645df9df12b69fda499e97eed25de6c75'
assert not any(complete[k] for k in ['bazel_lock_update_executed','rust_executed','fix_fmt_executed'])
for k in ['source_manifest','delta_manifest','source_postguard']:
    p=complete[k]
    assert pin(raws[p['path']])=={name:p[name] for name in ['bytes','sha256','git_blob']}
assert raws['native-candidate-r28-source.json']==(ROOT/'source52-preparation/native-candidate-r28-source.json').read_bytes()
assert raws['native-source52-apply/input/delta-manifest.json']==(ROOT/'source52-preparation/source52-actual-delta-manifest.json').read_bytes()
assert len(manifest['changed_files'])==195
for name in ['pre-apply-source-guard.json','immediately-before-apply-source-guard.json']:
    guard=json.loads(raws['native-source52-apply/'+name])
    assert guard['pass'] is True and guard['actual_tree']=='763c8d2b4089f6e9806c3bbb68fa247bc2f6af36' and guard['actual_changed_file_count']==194
prestage=json.loads(raws['native-source52-apply/prestage-source-guard.json'])
assert prestage['pass'] is True and prestage['unstaged_paths']==[LEAF]
phases=[]
for phase,args in [('apply-check',['git','apply','--check',E+'native-source52-apply/input/candidate.patch']),('apply',['git','apply',E+'native-source52-apply/input/candidate.patch']),('stage-exact-paths',['git','add','--',LEAF])]:
    prefix='native-source52-apply/'+phase+'-'
    raw=json.loads(raws[prefix+'raw-process-result.json'])
    receipt=json.loads(raws[prefix+'receipt.json'])
    started=json.loads(raws[prefix+'started.json'])
    assert raw['exit_code']==receipt['exit_code']==0 and raw['wait_exception'] is None
    assert raw['command']==receipt['command']==started['command']==args
    assert raw['cwd']==receipt['cwd']==S
    assert all(receipt[k]==v for k,v in raw.items())
    for stream in ['stdout','stderr']:
        assert receipt[stream]==pin(raws[prefix+stream+'.log'])
        assert raws[prefix+stream+'.log']==b''
    phases.append({'phase':phase,'command':args,'exit_code':0,'elapsed_seconds':raw['elapsed_seconds'],'raw_process_result':pin(raws[prefix+'raw-process-result.json'])})
for k in ['cargo_lock_sha256','bazel_lock_sha256']:
    assert complete[k]==post[k]==manifest[k]

for name,raw in raws.items():
    save(OUT/'evidence'/name,raw)
controllers=[]
for row in payload['controllers']:
    raw=row['text'].encode();save(OUT/'controller'/row['name'],raw)
    controllers.append({'path':'controller/'+row['name'],**pin(raw)})
save(OUT/'native-source52-apply.py',payload['runner']['text'].encode())
review={'schema':'hepta.source52-apply-native-readback.v1','status':'PASS_APPLY_ONLY_NO_RUST',
        'source_commit':COMMIT,'source_tree':TREE,'native_git_head':complete['native_git_head'],
        'job_id':payload['job_id'],'outer_exit_code':0,'original_git_commands':phases,
        'raw_originals':records,'controller_originals':controllers,'actual_changed_file_count':195,
        'only_changed_from_source51_path':LEAF,'prior194_unchanged':True,'dual_locks_unchanged':True,
        'actual_manifest_equals_root_frozen_bytes':True,'rust_bazel_fix_fmt_executed':False}
review_raw=dump(review);save(OUT/'LOCAL-READBACK.json',review_raw)

B=ROOT/'native-validation-results/r28-bound-input';B.mkdir(parents=True,exist_ok=False)
template=(ROOT/'source52-native-gates-preparation/native-run-r28-template.py').read_bytes()
assert len(template)==53959 and hashlib.sha256(template).hexdigest()=='2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb'
delta_name=complete['delta_manifest']['path']
bindings={
 'EXPECTED_COMMIT':COMMIT,'EXPECTED_TREE':TREE,'EXPECTED_CHANGED_COUNT':195,
 'SOURCE_MANIFEST_NAME':'native-candidate-r28-source.json','SOURCE_MANIFEST_SHA256':pin(raws['native-candidate-r28-source.json'])['sha256'],
 'APPLY_COMPLETE_NAME':complete_name,'APPLY_COMPLETE_SHA256':pin(raws[complete_name])['sha256'],'APPLY_COMPLETE_BYTES':len(raws[complete_name]),
 'APPLY_TERMINAL_NAME':terminal_name,'APPLY_TERMINAL_SHA256':pin(raws[terminal_name])['sha256'],'APPLY_TERMINAL_BYTES':len(raws[terminal_name]),
 'APPLY_JOB_ID':payload['job_id'],
 'DELTA_MANIFEST_NAME':delta_name,'DELTA_MANIFEST_SHA256':pin(raws[delta_name])['sha256'],'DELTA_MANIFEST_BYTES':len(raws[delta_name])}
text=template.decode(); tree=ast.parse(text)
none={n.targets[0].id for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant) and n.value.value is None}
assert none==set(bindings) and len(bindings)==15
bound=text
for k,v in bindings.items():
    old=k+' = None';assert bound.count(old)==1
    bound=bound.replace(old,k+' = '+repr(v),1)
nodes={n.targets[0].id:n for n in ast.parse(bound).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
assert ast.literal_eval(nodes['FROZEN'].value) is False
assert {k:ast.literal_eval(nodes[k].value) for k in bindings}==bindings
reverse=bound
for k in reversed(list(bindings)):
    old=ast.get_source_segment(bound,nodes[k]);assert reverse.count(old)==1
    reverse=reverse.replace(old,k+' = None',1)
assert reverse.encode()==template
assert bound.count('FROZEN = False')==1
final=bound.replace('FROZEN = False','FROZEN = True',1);ast.parse(final)
diff=''.join(difflib.unified_diff(text.splitlines(True),bound.splitlines(True),fromfile='reviewed-template.py',tofile='bound-template.py')).encode()
freeze_diff=''.join(difflib.unified_diff(bound.splitlines(True),final.splitlines(True),fromfile='bound-template.py',tofile='expected-final.py')).encode()
save(B/'native-run-r28-bound.py',bound.encode())
save(B/'template-to-bound.patch',diff);save(B/'bound-to-expected-final.patch',freeze_diff)
save(B/'ACTUAL-BINDINGS.json',dump(bindings))
report={'schema':'hepta.source52-r28-native-bound-review.v1','status':'STATIC_CLEAR_BOUND_REMAINS_INERT',
        'reviewed_template':pin(template),'bound':pin(bound.encode()),'bindings':bindings,
        'actual_apply_local_readback':{'path':str(OUT/'LOCAL-READBACK.json'),**pin(review_raw)},
        'exact15_literal_replacements':True,'whole_file_inverse_matches_reviewed_template':True,'ast_parse':True,
        'commands_environment_and_guard_logic_unchanged':True,'frozen':False,
        'expected_final_only_frozen_flip':pin(final.encode()),'rust_executed':False}
report_raw=dump(report);save(B/'BOUND-INDEPENDENT-READBACK.json',report_raw)
print(json.dumps({'local_apply_review':pin(review_raw),'bound':report['bound'],'bound_review':pin(report_raw),'expected_final':report['expected_final_only_frozen_flip'],'job_id':payload['job_id']}))
