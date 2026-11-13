#!/usr/bin/env python3
"""Cloud-only exact successor preparation. No native calls or source writes."""
import ast
import difflib
import hashlib
import json
import pathlib

OUT = pathlib.Path('/tmp/hepta-36fa-coordinator-a489-maintenance-successor-v1')
OLD = pathlib.Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1')
REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1'
MATERIALIZATION = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1/run'
HEAD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
TREE = 'a489b394666b8141840275128a780605b024cde0'
NATIVE = {'bytes':3543409,'git_blob':'7647480c5ed06525e1661ac451d0ac0ff2b23ea7','sha256':'69cab8dc5e68f6c9ebd8e8bd98ee54565fbbf112f1a1c61113c3413b77e3173b'}
FULL = {'bytes':5631947,'filesystem_entries':15243,'git_blob':'f1e2d72f99093581403a2dcc91b55da22a33f905','sha256':'0463522b45970d8ae9dbf5f4560e1b15e61768ec7c9ec164848019009c4643f0','tracked_entries':15243}

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def write(name,b):
    p=OUT/name
    if p.exists():
        assert p.read_bytes()==b, name
    else:
        with p.open('xb') as f:f.write(b)
    return {'name':name,**pin(b)}

def jbytes(x):
    return (json.dumps(x,indent=2,ensure_ascii=False)+'\n').encode()

old=(OLD/'driver-maintenance.HOLD.py').read_bytes()
assert pin(old)=={'bytes':68496,'sha256':'d47231764a8d85cf60bba499411a08b316798ac6835ae8e7eae95967a79d5259','git_blob':'3a0f6dec8127aa9587129d6e0f24bad55837ca13'}
original=old.decode()
replacements=[
 ('REPO=pathlib.Path("/home/qian-qi/hepta-utility-36fa-provider-0c59-isolated-v1")','REPO=pathlib.Path('+json.dumps(REPO)+')'),
 ('EVIDENCE=pathlib.Path("/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-maintenance-v1")','EVIDENCE=pathlib.Path('+json.dumps(CONTROL)+')'),
 ('HEAD="0c59aaca0b4932507f068c723f73da2f96729b3d"','HEAD='+json.dumps(HEAD)),
 ('TREE="4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09"','TREE='+json.dumps(TREE)),
 ('NATIVE_INVENTORY={"bytes":3541985,"git_blob":"68342846200b9ba15f0483d89e28bfcf4c499a44","sha256":"686c516814839ce12a3de6a8907a8efd5f27d4d39d9d4b14e380137698faa1f4"}','NATIVE_INVENTORY='+json.dumps(NATIVE,separators=(',',':'))),
 ('SUCCESSOR_INVENTORY={"bytes":5629701,"filesystem_entries":15237,"git_blob":"a596ae68859e3263a9ee58e2b5d7334ac9314c34","sha256":"affce692432a4fa61521561e6717a84984f679f3535190b6b88c92cb0f725f44","tracked_entries":15237}','SUCCESSOR_INVENTORY='+json.dumps(FULL,separators=(',',':'))),
 ('LEAVES=15237','LEAVES=15243'),
 ('observed.get("new_objects_fully_verified")==16652','observed.get("new_objects_fully_verified")==16661'),
]
source=original
for before,after in replacements:
    assert source.count(before)==1, before
    source=source.replace(before,after)
inverse=source
for before,after in reversed(replacements):
    assert inverse.count(after)==1
    inverse=inverse.replace(after,before)
assert inverse==original
ast.parse(source)
def definitions(s):
    lines=s.splitlines(keepends=True)
    return {n.name:''.join(lines[n.lineno-1:n.end_lineno]) for n in ast.parse(s).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
beforedefs=definitions(original);afterdefs=definitions(source)
assert beforedefs.keys()==afterdefs.keys()
changed=[k for k in beforedefs if beforedefs[k]!=afterdefs[k]]
assert changed==['validate_materialization']
assert afterdefs['validate_materialization'].replace('==16661','==16652')==beforedefs['validate_materialization']
driver=write('driver-maintenance.HOLD.py',source.encode())
write('DRIVER_3A0F6.original.py',old)
write('FROM_3A0F6.diff',''.join(difflib.unified_diff(original.splitlines(keepends=True),source.splitlines(keepends=True),fromfile='3a0f6-original',tofile='a489-HOLD')).encode())
cfgraw=(OLD/'execution-candidate-v1/MAINTENANCE_CONFIG.execution-candidate.json').read_bytes()
assert pin(cfgraw)=={'bytes':13768,'sha256':'ccf92346644f428bc66e634c8e4aebe871ed6dcaac354538c1e35862ea83aacf','git_blob':'d27dd8ee763c75eb5a0f195bb034fc9ca32b727e'}
cfg=json.loads(cfgraw)
cfg.update(status='HOLD_ACTUAL_MATERIALIZATION_AND_ROOT_EXACT_REVIEW_REQUIRED',root_execution_approved=False,
           driver_sha256=driver['sha256'],driver_git_blob=driver['git_blob'],source_repo=REPO,
           source_commit=HEAD,source_tree=TREE,source_inventory=FULL,formal_approved_config_created=False)
cfg['materialization']={'job_id':None,'result_path':MATERIALIZATION+'/RESULT.json','result':None,
                       'supervisor_path':CONTROL+'/MATERIALIZATION_SUPERVISOR.original.json','supervisor':None,
                       'git_state':None,'index':None,'git_metadata':None,'git_metadata_gzip':None,
                       'records':{k:None for k in ('command_records','mutation_records','input_records','artifact_records')}}
cfg['coordination_lock']={k:v for k,v in cfg['coordination_lock'].items() if k!='stat'}
cfg['coordination_lock']['stat']=None
cfg['archive_restoration']['supervisor_path']=CONTROL+'/V8_RESTORATION_SUPERVISOR.original.json'
cfg['waiting_for_actual_records']='HOLD. The d256 materialization original job must reach normal terminal and provide complete RESULT, four original records, raw index/Git metadata, coordination and all three final audits. Exact staging and maintenance require separate Root approval. No source qualification is inherited.'
cfg['source_inventory_observation']='Expected source inventory and native projection only at this preparation snapshot; no actual d256 success is claimed. Future configuration must bind the original materialization complete actual pins, and maintenance must reread all current bytes and actual Git-file stat before any fix/fmt.'
config=write('WAITING_CONFIG.json',jbytes(cfg))
write('CONFIG_FROM_D27DD8.diff',''.join(difflib.unified_diff(cfgraw.decode().splitlines(keepends=True),jbytes(cfg).decode().splitlines(keepends=True),fromfile='d27dd8-original',tofile='a489-HOLD')).encode())
report={'format':'hepta-a489-maintenance-preparation-byte-review-v1','status':'HOLD_NOT_EXECUTED','original_driver':pin(old),'driver':driver,'config':config,
        'exact_replacements':[{'before':a,'after':b} for a,b in replacements], 'inverse_full_bytes_equal':True,
        'top_level_definition_count':len(beforedefs),'byte_identical_definitions':[k for k in beforedefs if k not in changed],
        'changed_definitions':changed,'sole_function_change':'Exact observed new object union count 16652 to 16661; original predicate and all remaining bytes unchanged.',
        'original_budgets':{'fix':7200,'fmt':900,'preflight':600,'records':300,'outer':9300},
        'original_fix_argv':cfg['fix_argv'],'original_fmt_argv':cfg['fmt_argv'],
        'actual_materialization_proofs':None,'maintenance_dispatch_authorized':False,'H_calls':0,'source_writes':0,
        'historical_results_preserved':{'0c59_fix_job':'1a1d3eccd3a-392-231','fix_returncode':101,'fix_consumed':True,'old_apply4_fmt_job':'1a1d41eb3ef-392-2b2','not_reclassified':True},
        'lock_design':'Reuse the exact original EX launcher; it alone holds an inheritable EX descriptor. The original 3a0f6 main does not take a second flock.',
        'next':'Bind only actual terminal proof to a new config after complete materialization, then freeze exact six-file create-only stage and original EX main requests for Root/peer review. No invocation from this preparation.'}
review=write('STATIC_BYTE_REVIEW.json',jbytes(report))
print(json.dumps({'driver':driver,'config':config,'review':review,'definition_count':len(beforedefs),'byte_identical_count':len(beforedefs)-1,'replacement_count':len(replacements)}))
