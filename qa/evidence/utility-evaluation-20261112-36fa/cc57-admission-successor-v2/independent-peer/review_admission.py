"""Read-only exact admission-expression review. No imports of gate modules or main calls."""
from pathlib import Path
import ast,copy,datetime,hashlib,json,re,types

OUT=Path(__file__).resolve().parent
P=Path('/tmp/hepta-36fa-cc57-admission-successor-v2')
OLD=Path('/tmp/hepta-36fa-final-qualification-hold-v1/qualification-admission.HOLD.py')
OLD_CFG=Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def read(p):return json.loads(p.read_bytes())
def same_pin(p,expected):
    actual=pin(p.read_bytes())
    assert all(expected.get(k)==v for k,v in actual.items()),str(p)
    return actual
def diffs(a,b,path=''):
    assert type(a) is type(b),(path,'type changed')
    if isinstance(a,dict):
        assert a.keys()==b.keys(),(path,'keys changed')
        return [r for k in sorted(a) for r in diffs(a[k],b[k],path+'/'+k)]
    if isinstance(a,list):
        assert len(a)==len(b),(path,'list length changed')
        return [r for i,(x,y) in enumerate(zip(a,b)) for r in diffs(x,y,path+'/'+str(i))]
    return [] if a==b else [{'path':path,'before':a,'after':b}]

old=OLD.read_bytes();new=(P/'qualification-admission.cc57.HOLD.py').read_bytes()
assert pin(old)['git_blob']=='5208cfa83a1f279c7fb76c4536adfa41c1df5f6f'
assert pin(new)['git_blob']=='a8be08b6cb00536817e2d68c42fa4b90d1e9ff72'
oa=ast.parse(old);na=ast.parse(new);nodes0=list(ast.walk(oa));nodes1=list(ast.walk(na));assert len(nodes0)==len(nodes1)
changes=[]
for a,b in zip(nodes0,nodes1):
    assert type(a) is type(b)
    if isinstance(a,ast.Constant) and a.value!=b.value:
        changes.append({'line':b.lineno,'before':a.value,'after':b.value});b.value=a.value
assert len(changes)==3 and ast.dump(oa)==ast.dump(na)
restored=new.decode()
for before,after in [
("final_format['source_commit'] == '9c4a11f61d30e9cc352bf44d56c98909d202a55d'","final_format['source_commit'] == '246d8cb614770252ee42029a5c014f2a4904176a'"),
("final_format['source_tree'] == 'ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'","final_format['source_tree'] == 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087'"),
("final_format['parents'] == ['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']","final_format['parents'] == ['9c4a11f61d30e9cc352bf44d56c98909d202a55d']")]:
    assert restored.count(after)==1;restored=restored.replace(after,before,1)
assert restored.encode()==old

cfg=read(P/'QUALIFICATION_INPUT.cc57-v2.HOLD.json');oldcfg=read(OLD_CFG/'APPROVED_FINAL_QUALIFICATION_INPUT.json')
sc=read(P/'SOURCE_GATES_CONFIG.cc57-v2.HOLD.json');oldsc=read(OLD_CFG/'APPROVED_FINAL_SOURCE_GATES_CONFIG.json')
cfgdiff=diffs(oldcfg,cfg);scdiff=diffs(oldsc,sc)
allowed={'/admission_path','/admission_pin/git_blob','/admission_pin/sha256','/canonical_alignment/supervisor_path',
 '/native_driver_path','/plan_path','/records','/root_parent','/run_identity','/source_gates_config_path',
 '/source_gates_config_pin/git_blob','/source_gates_config_pin/sha256','/source_gates_handoff_records'}
assert {x['path'] for x in cfgdiff}==allowed and len(cfgdiff)==13
assert {x['path'] for x in scdiff}=={'/records','/run_identity','/source_checkout'}
for k in ['runtime_guard','source','tree','parents','full_physical_inventory','expected_inventory_sha256',
          'final_format','coordination_lock','positive_eval_cases','expected_file_count','native_driver_pin','plan_pin']:
    assert cfg[k]==oldcfg[k],k
assert sc['budgets_seconds']==oldsc['budgets_seconds']=={'source-closure':600,'self-test':300,'verify':4800}
assert cfg['admission_pin']==pin(new)
same_pin(P/'SOURCE_GATES_CONFIG.cc57-v2.HOLD.json',cfg['source_gates_config_pin'])

fmt_path=Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/RESULT.original.json')
aligned_path=Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/RESULT.json')
fmt=read(fmt_path);aligned=read(aligned_path)
same_pin(fmt_path,cfg['final_format']['result']);same_pin(aligned_path,cfg['canonical_alignment']['result'])
normal_paths={'final_format':Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/STATUS_01.original.json'),
 'canonical_alignment':Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/STATUS_01.original.json')}
normals=[]
for key,path in normal_paths.items():
    same_pin(path,cfg[key]['supervisor']);outer=read(path)
    assert outer['isError'] is False and len(outer['content'])==1 and outer['content'][0]['type']=='text'
    terminal=json.loads(outer['content'][0]['text']);assert terminal['job_id']==cfg[key]['job_id']
    assert terminal['state']=='succeeded' and terminal['exit_code']==0 and terminal['timed_out'] is False
    assert terminal['cancelled'] is False and terminal['automatic_retry'] is False
    assert terminal['output_complete'] is True and terminal['output_durable'] is True and terminal['terminal_publication_confirmed'] is True
    assert not any(terminal['log_truncated'].values())
    normals.append({'proof':key,'job_id':terminal['job_id'],'exact_complete_normal_terminal':True,'identity':pin(path.read_bytes())})

inventory_path=Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1/CANONICAL_CLEAN_INVENTORY.expected.json')
inv_raw=inventory_path.read_bytes();same_pin(inventory_path,cfg['full_physical_inventory']);inv=json.loads(inv_raw)
assert inv['source']=={'head':cfg['source'],'tree':cfg['tree'],'status':''}
assert len(inv['files'])==inv['tracked_entries']==cfg['expected_file_count']==15188
plan_path=Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v1/inputs/PLAN.original.json')
same_pin(plan_path,cfg['plan_pin']);plan=read(plan_path)
source_pins=[];file_rows={r['path']:r for r in inv['files']}
for item in plan['unchanged_original_controls']['reviewed_source_pins']['files']:
    row=file_rows[item['path']]
    assert row['bytes']==item['bytes'] and row['sha256']==item['sha256']
    assert row['index_blob']==item['git_blob'] and row['stable'] is True
    source_pins.append({'path':item['path'],'git_blob':item['git_blob'],'exact_canonical_inventory_row_matches':True})

tree=ast.parse(new);fn=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='acquire_and_validate')
checks=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check']
def environment(ff,al):return {'__builtins__':{},'cfg':cfg,'plan':plan,'final_format':ff,'aligned':al,
 'complete':ff['actual_final_source'],'stage':ff['stages'][0],'after':al['after'],
 'self':types.SimpleNamespace(initial_raw=inv_raw),'C0F':'c0f78493f815780f68b9bf5e390a21314d79311f',
 'all':all,'len':len,'str':str,'list':list,'isinstance':isinstance,'json':json,'re':re}
def evaluate(node,ff=fmt,al=aligned,key=None):
    e=environment(ff,al)
    if key is not None:e['key']=key
    return bool(eval(compile(ast.Expression(node.args[0]),'<exact-admission-data-expression>','eval'),e,e))
pure=[];by_reason={}
for n in sorted(checks,key=lambda x:x.lineno):
    if isinstance(n.args[1],ast.BinOp):
        for key in ['source','tree']:
            assert evaluate(n,key=key);pure.append({'line':n.lineno,'reason':'actual final '+key,'accepted_actual':True})
        continue
    reason=n.args[1].value
    if reason=='actual exact canonical raw Git state':continue
    assert evaluate(n),reason
    pure.append({'line':n.lineno,'reason':reason,'accepted_actual':True});by_reason[reason]=n
assert len(pure)==19
oldnode=next(n for n in ast.walk(ast.parse(old)) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='check' and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value=='actual final original format prerequisite')
assert evaluate(oldnode) is False

# One-field corruptions are only offline data-predicate checks, not new source
# executions or qualification tests. They do not modify any original record.
negatives=[]
def corrupt(which,path,value,reason):
    ff=copy.deepcopy(fmt);al=copy.deepcopy(aligned);target=ff if which=='fmt' else al
    for k in path[:-1]:target=target[k]
    target[path[-1]]=value
    assert evaluate(by_reason[reason],ff,al) is False,(which,path,reason)
    negatives.append({'record':which,'field':path,'guard':reason,'rejected':True})
for field,value in [('source_commit','9c4a11f61d30e9cc352bf44d56c98909d202a55d'),('source_tree','ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7'),('parents',['86dd56a930277e0d1aef3e475e35c2b5d60b43b7']),('format','unknown'),('status','failed'),('source_repo','/unapproved'),('qualification',True),('fix_dispatched',True),('test_commands_dispatched',1),('attempted_commands',['fix','fmt']),('not_run_commands',['fmt']),('source_ref_updates',True)]:
    corrupt('fmt',[field],value,'actual final original format prerequisite')
for path,value,reason in [
 (['actual_final_source','complete'],False,'actual final-format physical tree is the canonical qualification subject'),
 (['git_metadata_unchanged'],False,'actual final-format physical tree is the canonical qualification subject'),
 (['actual_final_source','postimages','all_actual_physical_tree'],'0'*40,'actual final-format physical tree is the canonical qualification subject'),
 (['actual_final_source','postimages','all_actual_physical_leaf_count'],15187,'actual final-format physical tree is the canonical qualification subject'),
 (['stages',0,'argv'],['just','fmt'],'unchanged final-format command and budget'),
 (['stages',0,'timeout_seconds'],901,'unchanged final-format command and budget'),
 (['stages',0,'execution','returncode'],1,'actual final fmt normal command terminal'),
 (['stages',0,'execution','timed_out'],True,'actual final fmt normal command terminal'),
 (['stages',0,'execution','output_limit_exceeded'],True,'actual final fmt normal command terminal'),
 (['final_audits',0,'status'],'unknown','complete actual final-format audits'),
 (['formatter_changed_paths'],['unexpected.rs'],'actual final formatter postimages individually reviewed')]:corrupt('fmt',path,value,reason)
for field,value in [('format','unknown'),('status','failed'),('source_repo','/unapproved'),('physical_source_writes_dispatched',1),('cargo_or_formatter_started',True),('test_commands_dispatched',1),('source_branch_refs_updated',True),('remote_ref_updates',True),('automatic_retry',True)]:
    corrupt('aligned',[field],value,'actual clean canonical alignment only')
for path,value,reason in [
 (['final_audits',0,'status'],'unknown','complete actual alignment audits'),
 (['after','commit'],'0'*40,'actual canonical SHA/tree/parents'),
 (['after','tree'],'0'*40,'actual canonical SHA/tree/parents'),
 (['after','parents'],['0'*40],'actual canonical SHA/tree/parents'),
 (['after','inventory','sha256'],'0'*64,'actual final canonical full inventory identity'),
 (['final_format','job_id'],'different','canonical proof refers to this exact actual final fmt'),
 (['final_format','result','git_blob'],'0'*40,'canonical proof refers to this exact actual final fmt'),
 (['final_format','supervisor','git_blob'],'0'*40,'canonical proof refers to this exact actual final fmt')]:corrupt('aligned',path,value,reason)
for field in ['physical_bytes_unchanged','physical_modes_unchanged','complete_source_clean','detached','index_equals_tree','normal_stat_refresh_verified']:
    corrupt('aligned',['actual',field],False,'actual complete physical source and normal canonical index')

sha_constants=[{'value':n.value,'line':n.lineno} for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and re.fullmatch('[0-9a-f]{40}',n.value)]
assert not any(x['value'] in ['ee42ec7e6289e0ccdbe03a5af0b39216a5a6dab7','86dd56a930277e0d1aef3e475e35c2b5d60b43b7'] for x in sha_constants)
assert [x['line'] for x in sha_constants if x['value']=='9c4a11f61d30e9cc352bf44d56c98909d202a55d']==[123]
report={'format':'hepta-cc57-admission-successor-independent-peer-v2','status':'NO_BLOCKING_DATA_PREDICATE_OR_CHANGE_SCOPE_ISSUE',
 'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'original_admission':pin(old),'successor_admission':pin(new),
 'only_three_AST_constant_changes':changes,'inverse_three_replacements_restore_entire_original_bytes':True,
 'qualification_cfg_exact_whitelist_diff':cfgdiff,'source_cfg_exact_whitelist_diff':scdiff,
 'runtime_guards_and_complete_original_proofs_unchanged':True,'actual_normal_proofs':normals,
 'actual_format_result':pin(fmt_path.read_bytes()),'actual_canonical_result':pin(aligned_path.read_bytes()),
 'all_data_only_admission_checks':pure,'old_first_predicate_rejects_actual_format':True,
 'negative_data_predicate_probes':negatives,'negative_probe_count':len(negatives),
 'source_control_pins_match_recovered_actual_canonical_inventory':source_pins,
 'full_inventory':pin(inv_raw),'native_compact_expected_digest_unchanged_projection_only':cfg['expected_inventory_sha256'],
 'remaining_historical_anchors':sha_constants,
 'historical_anchor_interpretation':'Only the exact actual fmt parent9c4 remains; old9c4/ee42/[86dd] formatter tuple is removed. C0F is the intentionally retained fmt base. V5/inventory/plan pins identify unchanged original control modules.',
 'not_executed_or_claimed':['No Admission constructor, acquire_and_validate, finish, wrapper main, H, source gate, native gate, Git command, source/ref write.',
 'No new live lock/Git/physical/tool/environment observation. Actual runtime still must reacquire the original lock, read current full source/raw Git, and enforce all original checks.',
 'Recovered13d3 bytes match actual aligned RESULT; they are not a second native full read or actual native compact snapshot.'],
 'prior_failure_and_review_scope':'Prior cc57 v1 actual Unknown and secondary error remain unchanged. Bootstrap-only peer16f0 correctly bounded byte differences but did not test the retained admission ancestry. This review adds the missing actual-format and canonical-data seam checks; no old PASS is relabeled.',
 'budgets_unchanged':{'source-closure':600,'self-test':300,'verify':4800,'source_outer':7200,'native_outer':45000},
 'actual_qualified_task_chains_proved':0,'qualification':False}
raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode()
with (OUT/'REVIEW.json').open('xb') as f:f.write(raw)
print(json.dumps({'review':str(OUT/'REVIEW.json'),**pin(raw),'pure_checks':len(pure),'negative_probes':len(negatives),'source_pins':len(source_pins)}))
