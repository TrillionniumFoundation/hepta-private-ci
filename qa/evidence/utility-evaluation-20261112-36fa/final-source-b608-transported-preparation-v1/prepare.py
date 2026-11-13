"""Cloud-only immutable preparation of the b608 v2 source request.

No H, native process, project code import, source mutation, or execution approval.
The already approved transport stage is completed. Source execution remains HOLD
until Root reviews the concrete execution-candidate bytes and separately approves.
"""
import ast
import base64
import copy
import difflib
import hashlib
import json
from pathlib import Path

OUT=Path('/tmp/hepta-36fa-final-source-b608-transported-preparation-v1')
OLD=Path('/tmp/hepta-36fa-final-source-qualification-b608-preparation-v1/execution-candidate-v1')
HISTORY_HOLD=Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1/review-candidate-v1')
RUNTIME=Path('/tmp/hepta-36fa-b608-history-transport-staging-runtime-v1')
ADMISSION=Path('/tmp/hepta-36fa-admission-baseline-unavailable-increment-v1/qualification-admission.after.py')
BASE='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-v2'
KEY='hepta-utility-36fa-final-source-gates-b608-v2'
JOB='1a1d52e0d88-392-784'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def jb(x):return (json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()

def retain(directory,name,b):
    p=directory/name
    with p.open('xb') as f:f.write(b)
    assert p.read_bytes()==b
    return {'name':str(p.relative_to(OUT)),'local_path':str(p),**pin(b)}

def once(text,before,after):
    assert text.count(before)==1, ('nonunique exact replacement',before[:80])
    return text.replace(before,after)

def delta(a,b,prefix=()):
    if isinstance(a,dict) and isinstance(b,dict):
        assert set(a)==set(b),('schema key set changed',prefix)
        out=[]
        for k in a:out+=delta(a[k],b[k],prefix+(k,))
        return out
    if a==b:return []
    return [{'path':list(prefix),'before':a,'after':b}]

for name in ('inputs','actual-binding-hold-v1','execution-candidate-v1'):
    (OUT/name).mkdir()
INPUTS=OUT/'inputs';HOLD=OUT/'actual-binding-hold-v1';EXEC=OUT/'execution-candidate-v1'
old_boot=(OLD/'SOURCE_BOOTSTRAP.candidate.py').read_bytes()
old_request_raw=(OLD/'SOURCE_PROCESS_INPUT.candidate.json').read_bytes()
assert pin(old_request_raw)=={'bytes':246727,'sha256':'1737f34278a277d0d3003efdf6a9539e11e63d40326544542d81da024947aa16','git_blob':'465e0eaa1f387ad6bb167a4931328e199a5bf793'}
assert pin(old_boot)['git_blob']=='f8f7d607f3e06ead370d9fa00c1fdfbb56ddbc73'
old_request=json.loads(old_request_raw);old_packet=json.loads(old_request['stdin'])
old_files={n:base64.b64decode(v,validate=True) for n,v in old_packet['files'].items()}
assert old_request['args']==['-B','-c',old_boot.decode()]
assert len(old_files)==8
base_cfg_raw=(HISTORY_HOLD/'QUALIFICATION_CONFIG.HOLD.json').read_bytes()
base_source_raw=(HISTORY_HOLD/'SOURCE_GATES_CONFIG.HOLD.json').read_bytes()
assert pin(base_cfg_raw)['git_blob']=='09cc978923c1d0a3d6f920b0e1754025107d7825'
assert pin(base_source_raw)['git_blob']=='acfa7c86f4202d6e7f15399514dc739f4bc33f82'
cfg=json.loads(base_cfg_raw);source=json.loads(base_source_raw)
assert jb(cfg)==base_cfg_raw and jb(source)==base_source_raw
admission_raw=ADMISSION.read_bytes()
assert pin(admission_raw)['git_blob']=='fd67cb043f7b6cb8cf042104ac202cb5f0842196'
assert len(admission_raw)==111588
stage_result=(RUNTIME/'STAGING_READBACK.json').read_bytes()
stage_normal=(RUNTIME/'STATUS_01.original.json').read_bytes()
stage_payload=(RUNTIME/'STAGE_STDIN.original.json').read_bytes()
closure_raw=(RUNTIME/'COMPLETE_61_READBACK_REVIEW.json').read_bytes();closure=json.loads(closure_raw)
assert pin(closure_raw)['git_blob']=='3b1c1096f1cd29805f55553ad6a51ffbbae86501'
assert closure['job_id']==JOB and closure['required_files']==61 and closure['all_complete_same_version_readback'] is True
assert pin(stage_result)['git_blob']=='17d4ea78bc34facc9129c6a634fe750105d75bc4'
assert pin(stage_normal)['git_blob']=='af805a3230601013eb94afd5e40e9ea3e83c61d4'
assert pin(stage_payload)['git_blob']=='f8efb445171e1eb74dc289cd5c15ab89f8940e4f'
terminal=json.loads(json.loads(stage_normal)['content'][0]['text'])
assert terminal['job_id']==JOB and terminal['state']=='succeeded' and terminal['exit_code']==0
assert all(terminal[k] is True for k in ('output_complete','output_durable','terminal_publication_confirmed'))
assert all(terminal[k] is False for k in ('automatic_retry','cancelled','timed_out'))

input_rows=[]
for name,b in [('SOURCE_BOOTSTRAP.65a.original.py',old_boot),('SOURCE_PROCESS_INPUT.65a.original.json',old_request_raw),
               ('QUALIFICATION_CONFIG.transport.HOLD.original.json',base_cfg_raw),('SOURCE_GATES_CONFIG.transport.HOLD.original.json',base_source_raw),
               ('qualification-admission.fd67.selected.py',admission_raw),('STAGING_READBACK.actual.json',stage_result),
               ('TRANSPORT_SUPERVISOR.actual.json',stage_normal),('TRANSPORT_PAYLOAD.actual.json',stage_payload),
               ('COMPLETE_61_READBACK_REVIEW.actual.json',closure_raw)]:
    input_rows.append(retain(INPUTS,name,b))
for name in ('source-gates-wrapper.py','native-wrapper.py','native-driver.original.py','PLAN.original.json'):
    input_rows.append(retain(INPUTS,name,old_files[name]))

bound=copy.deepcopy(cfg)
spec=bound['history_transport']
for n in ('staging_job_id','staging_result','staging_supervisor','staging_payload'):assert spec[n] is None
spec.update(staging_job_id=JOB,staging_result=pin(stage_result),staging_supervisor=pin(stage_normal),staging_payload=pin(stage_payload))
bound['admission_pin']=pin(admission_raw)
assert bound['admission_path']==BASE+'/qualification-admission.py'
assert spec['staging_supervisor_path']==BASE+'/TRANSPORT_SUPERVISOR.original.json'
assert bound['root_execution_approved'] is False and bound['state']=='HOLD_ROOT_EXACT_SOURCE_REVIEW_REQUIRED'
bound_raw=jb(bound)
reverse=copy.deepcopy(bound)
for n in ('staging_job_id','staging_result','staging_supervisor','staging_payload'):reverse['history_transport'][n]=None
reverse['admission_pin']=cfg['admission_pin']
assert jb(reverse)==base_cfg_raw
hold_cfg=retain(HOLD,'QUALIFICATION_CONFIG.HOLD.json',bound_raw)
hold_source=retain(HOLD,'SOURCE_GATES_CONFIG.HOLD.json',base_source_raw)
bound_diff=delta(cfg,bound)
allowed_bound={('admission_pin',k) for k in ('bytes','sha256','git_blob')} | {('history_transport',k) for k in ('staging_job_id','staging_result','staging_supervisor','staging_payload')}
assert {tuple(x['path']) for x in bound_diff}==allowed_bound

ready_source=copy.deepcopy(source);ready_source['state']='READY_FOR_EXACT_SOURCE_RUN'
ready_source_raw=jb(ready_source)
ready=copy.deepcopy(bound);ready['state']='READY_FOR_FINAL_SOURCE_QUALIFICATION';ready['root_execution_approved']=True
ready['source_gates_config_pin']=pin(ready_source_raw)
ready_raw=jb(ready)
reverse_ready=copy.deepcopy(ready);reverse_ready['state']=bound['state'];reverse_ready['root_execution_approved']=False;reverse_ready['source_gates_config_pin']=bound['source_gates_config_pin']
assert jb(reverse_ready)==bound_raw
reverse_source=copy.deepcopy(ready_source);reverse_source['state']=source['state'];assert jb(reverse_source)==base_source_raw
ready_delta=delta(bound,ready);source_delta=delta(source,ready_source)
assert {tuple(x['path']) for x in ready_delta}=={('state',),('root_execution_approved',),('source_gates_config_pin','bytes'),('source_gates_config_pin','sha256'),('source_gates_config_pin','git_blob')}
assert source_delta==[{'path':['state'],'before':source['state'],'after':'READY_FOR_EXACT_SOURCE_RUN'}]
ready_cfg=retain(EXEC,'QUALIFICATION_CONFIG.execution-candidate.json',ready_raw)
ready_source_row=retain(EXEC,'SOURCE_GATES_CONFIG.execution-candidate.json',ready_source_raw)

text=old_boot.decode();old_base_line=next(line for line in text.splitlines(True) if line.startswith('BASE = '));old_pins_line=next(line for line in text.splitlines(True) if line.startswith('PINS = '))
new_base_line='BASE = pathlib.Path('+repr(BASE)+')\n'
old_functions={n.name:ast.get_source_segment(text,n) for n in ast.walk(ast.parse(text)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
assert len(old_functions)==5
outputs=[]
def build_request(directory,qual_raw,src_raw,label):
    files={}
    for name,b in old_files.items():
        if name=='qualification-admission.py':b=admission_raw
        elif name=='APPROVED_QUALIFICATION_INPUT.json':b=qual_raw
        elif name=='SOURCE_GATES_CONFIG.json':b=src_raw
        elif name=='CANONICAL_SUPERVISOR.original.json':name='TRANSPORT_SUPERVISOR.original.json';b=stage_normal
        files[name]=b
    assert len(files)==8
    pins={n:pin(b) for n,b in files.items()}
    pins_line='PINS = '+repr(pins)+'\n'
    boot=once(once(text,old_base_line,new_base_line),old_pins_line,pins_line)
    assert once(once(boot,new_base_line,old_base_line),pins_line,old_pins_line)==text
    functions={n.name:ast.get_source_segment(boot,n) for n in ast.walk(ast.parse(boot)) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    assert functions==old_functions
    # Preserve the old payload's exact JSON spelling/whitespace outside the four
    # changed base64 values and the one explicit final-slot role name.
    payload=old_request['stdin']
    for old_name,new_name in [('qualification-admission.py','qualification-admission.py'),
                              ('APPROVED_QUALIFICATION_INPUT.json','APPROVED_QUALIFICATION_INPUT.json'),
                              ('SOURCE_GATES_CONFIG.json','SOURCE_GATES_CONFIG.json'),
                              ('CANONICAL_SUPERVISOR.original.json','TRANSPORT_SUPERVISOR.original.json')]:
        payload=once(payload,old_packet['files'][old_name],base64.b64encode(files[new_name]).decode('ascii'))
    payload=once(payload,'CANONICAL_SUPERVISOR.original.json','TRANSPORT_SUPERVISOR.original.json')
    parsed=json.loads(payload)
    assert parsed=={'format':old_packet['format'],'files':{n:base64.b64encode(b).decode('ascii') for n,b in files.items()}}
    request_text=old_request_raw.decode()
    replacements=[(json.dumps(old_boot.decode()),json.dumps(boot)),(json.dumps(old_request['stdin']),json.dumps(payload)),(json.dumps(old_request['idempotency_key']),json.dumps(KEY))]
    for a,b in replacements:request_text=once(request_text,a,b)
    reverse_text=request_text
    for a,b in reversed(replacements):reverse_text=once(reverse_text,b,a)
    assert reverse_text==old_request_raw.decode()
    req=json.loads(request_text)
    assert set(req)==set(old_request)=={'host','executable','args','cwd','idempotency_key','stdin','timeout_seconds'}
    assert req['host']=='desktop' and req['executable']=='/usr/bin/python3' and req['cwd']=='/home/qian-qi' and req['timeout_seconds']==7200
    assert req['args']==['-B','-c',boot] and req['stdin']==payload and req['idempotency_key']==KEY
    assert len(request_text.encode())<=1048576 and len(payload.encode())<=1048576
    rows=[retain(directory,'SOURCE_BOOTSTRAP.'+label+'.py',boot.encode()),
          retain(directory,'SOURCE_STDIN.'+label+'.json',payload.encode()),
          retain(directory,'SOURCE_PROCESS_INPUT.'+label+'.json',request_text.encode())]
    diff=''.join(difflib.unified_diff(text.splitlines(True),boot.splitlines(True),fromfile='actual65a/SOURCE_BOOTSTRAP.py',tofile=label+'/SOURCE_BOOTSTRAP.py'))
    rows.append(retain(directory,'FROM_65A_BOOTSTRAP.diff',diff.encode()))
    manifest={'schema':'hepta-b608-transported-source-exact-candidate-v1','label':label,'not_an_execution_approval':True,
              'source_execution_dispatched':False,'native_execution_dispatched':False,'qualification':False,
              'request':pin(request_text.encode()),'bootstrap':pin(boot.encode()),'stdin':pin(payload.encode()),
              'seven_fields':list(req),'key':KEY,'host':'desktop','outer_budget_seconds':7200,'no_env':True,
              'control':BASE,'inputs':pins,'input_count':8,'original_five_definitions_byte_identical':True,
              'whole_bootstrap_inverse_to_actual_65a':True,'whole_request_inverse_to_actual_65a':True,
              'execute_outside_staging_try_unchanged':True,
              'explicit_slot_change':{'removed_staging_copy':'CANONICAL_SUPERVISOR.original.json','added_actual_stage_supervisor':'TRANSPORT_SUPERVISOR.original.json',
                'canonical_receipt_still_required':'canonical.supervisor remains a fixed original in the complete 55-role history map; no canonical content or guard removed'},
              'actual_stage_job':JOB,'actual_stage_readback':pin(stage_result),'actual_stage_complete_61_review':pin(closure_raw),
              'selected_admission':pin(admission_raw),'old_65a_request':pin(old_request_raw),
              'original_controls_unchanged':{n:pin(old_files[n]) for n in ('source-gates-wrapper.py','native-wrapper.py','native-driver.original.py','PLAN.original.json')},
              'budgets':{'admission':600,'source_closure':600,'self_test':300,'verify':4800,'final':300,'source_outer':7200,'future_native_outer':45000},
              'future_native_phases':14,'root_parents':48,'e1_e2_code_not_included':True}
    rows.append(retain(directory,'EXACT_SOURCE_LAUNCH_MANIFEST.json',jb(manifest)))
    return rows

outputs+=build_request(HOLD,bound_raw,base_source_raw,'HOLD')
outputs+=build_request(EXEC,ready_raw,ready_source_raw,'candidate')
change_record={'schema':'hepta-transport-actual-binding-and-permission-delta-v1',
              'actual_bound_changes':bound_diff,'ready_qualification_changes':ready_delta,'ready_source_changes':source_delta,
              'old_hold_restored_byte_exact':True,'ready_to_bound_hold_byte_exact':True,'source_ready_to_hold_byte_exact':True,
              'new_stage_bindings_only_after_complete_actual_61_readback':True,'historical_json_modified':False,
              'admission_selected_by_root':'fd67 InitialBaselineUnavailable successor; original299c and65a unchanged',
              'not_an_execution_approval':True}
outputs.append(retain(OUT,'EXACT_BINDING_AND_PERMISSION_CHANGES.json',jb(change_record)))
outputs.append(retain(OUT,'BOUND_HOLD_TO_READY.diff',''.join(difflib.unified_diff(bound_raw.decode().splitlines(True),ready_raw.decode().splitlines(True),fromfile='actual-bound/HOLD',tofile='execution-candidate')).encode()))
report={'schema':'hepta-b608-source-preparation-static-byte-review-v1','actual_stage_job':JOB,
        'actual_stage_readback':pin(stage_result),'complete_61_review':pin(closure_raw),
        'frozen_original_input_count':len(input_rows),'original_inputs':input_rows,
        'holds':[hold_cfg,hold_source],'execution_config_candidates':[ready_cfg,ready_source_row],
        'outputs':outputs,'generator':pin((OUT/'prepare.py').read_bytes()),
        'all_whole_inverse_checks_passed':True,'all_eight_payloads_exact':True,
        'new_h_calls':0,'runtime_or_project_tests':0,'source_native_qualification':False,
        'root_exact_execution_approval_still_required':True}
row=retain(OUT,'STATIC_BYTE_REVIEW.json',jb(report))
print(json.dumps({'review':row,'hold_cfg':hold_cfg,'ready_cfg':ready_cfg,'ready_source_cfg':ready_source_row,
                  'execution_outputs':[x for x in outputs if x['name'].startswith('execution-candidate-v1/')]}))
