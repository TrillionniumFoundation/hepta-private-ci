#!/usr/bin/env python3
"""Apply Root's four authorized configuration edits to an immutable candidate.
This program only derives reviewable bytes; it never invokes staged controls.
"""
import ast,base64,difflib,hashlib,json
from pathlib import Path
ROOT=Path('/tmp/hepta-36fa-provider-0c59-maintenance-successor-v1')
OUT=ROOT/'execution-candidate-v1'
OUT.mkdir(exist_ok=True)

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}

def jbytes(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()

def save(name,b):
    p=OUT/name
    if p.exists():assert p.read_bytes()==b,'never overwrite fixed candidate: '+name
    else:p.write_bytes(b)
    return {'name':name,'path':str(p),**pin(b)}

def replace_pin(code,name,replacement,tuples):
    node=next(n for n in ast.parse(code).body if isinstance(n,ast.Assign) and
              any(isinstance(t,ast.Name) and t.id=='PINS' for t in n.targets))
    original=ast.literal_eval(node.value)
    changed=dict(original)
    changed[name]=tuple(replacement[k] for k in ('bytes','sha256','git_blob')) if tuples else replacement
    before=ast.get_source_segment(code,node)
    after=('PINS=' if tuples else 'PINS = ')+repr(changed)
    assert code.count(before)==1
    code=code.replace(before,after,1)
    ast.parse(code);compile(code,name,'exec')
    assert {k:v for k,v in original.items() if k!=name}=={k:v for k,v in changed.items() if k!=name}
    return code

before=json.loads((ROOT/'MAINTENANCE_CONFIG.HOLD.json').read_bytes())
cfg=dict(before)
authorized={
 'status':'ROOT_APPROVED_TO_EXECUTE',
 'root_execution_approved':True,
 'formal_approved_config_created':True,
 'waiting_for_actual_records':'Frozen execution-candidate bytes pending the separate exact Root engineering approval. Actual 0c59 materialization and separate archive-restoration proofs are bound. One original scoped fix and one original c0f fmt may run only under that approval after complete create-only staging readback and all original live prerequisites. No maintenance success, test qualification or real task-chain completion is supplied by this configuration.'}
cfg.update(authorized)
assert {k for k in cfg if cfg[k]!=before[k]}==set(authorized)
config_bytes=jbytes(cfg);config_pin=pin(config_bytes)
rows=[save('MAINTENANCE_CONFIG.execution-candidate.json',config_bytes)]
changes=[{'field':key,'before':before[key],'after':cfg[key]} for key in authorized]
rows.append(save('CONFIG_FOUR_AUTHORIZED_FIELDS.json',jbytes(changes)))
rows.append(save('CONFIG_HOLD_TO_CANDIDATE.diff',''.join(difflib.unified_diff(
 (ROOT/'MAINTENANCE_CONFIG.HOLD.json').read_text().splitlines(True),config_bytes.decode().splitlines(True),
 fromfile='HOLD/MAINTENANCE_CONFIG.json',tofile='execution-candidate/MAINTENANCE_CONFIG.json')).encode()))
launcher_before=(ROOT/'LAUNCHER.HOLD.py').read_text()
launcher=replace_pin(launcher_before,'APPROVED_MAINTENANCE_CONFIG.json',config_pin,True)
rows.append(save('LAUNCHER.execution-candidate.py',launcher.encode()))
main=json.loads((ROOT/'PROCESS_INPUT.HOLD.json').read_bytes())
assert main['args']==['-B','-c',launcher_before]
main['args']=['-B','-c',launcher]
rows.append(save('PROCESS_INPUT.execution-candidate.json',jbytes(main)))
stage_before=(ROOT/'STAGING_BOOTSTRAP.HOLD.py').read_text()
stage=replace_pin(stage_before,'APPROVED_MAINTENANCE_CONFIG.json',config_pin,False)
rows.append(save('STAGING_BOOTSTRAP.execution-candidate.py',stage.encode()))
payload=json.loads((ROOT/'STAGING_PAYLOAD.HOLD.json').read_bytes())
payload['files']['APPROVED_MAINTENANCE_CONFIG.json']=base64.b64encode(config_bytes).decode()
payload_bytes=jbytes(payload)
rows.append(save('STAGING_PAYLOAD.execution-candidate.json',payload_bytes))
request=json.loads((ROOT/'STAGING_REQUEST.HOLD.json').read_bytes())
assert request['args']==['-B','-c',stage_before]
request['args']=['-B','-c',stage];request['stdin']=payload_bytes.decode()
rows.append(save('STAGING_REQUEST.execution-candidate.json',jbytes(request)))
for name,before_code,after_code in [('LAUNCHER',launcher_before,launcher),('STAGING',stage_before,stage)]:
    rows.append(save(name+'_HOLD_TO_CANDIDATE.diff',''.join(difflib.unified_diff(
     before_code.splitlines(True),after_code.splitlines(True),fromfile=name+'.HOLD.py',
     tofile=name+'.execution-candidate.py')).encode()))

stage_pins=ast.literal_eval(next(n.value for n in ast.parse(stage).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='PINS' for t in n.targets)))
assert set(payload['files'])==set(stage_pins) and len(stage_pins)==6
for name,value in payload['files'].items():assert pin(base64.b64decode(value,validate=True))==stage_pins[name]
assert json.loads(base64.b64decode(payload['files']['APPROVED_MAINTENANCE_CONFIG.json'],validate=True))==cfg
assert set(main)=={'host','executable','args','cwd','idempotency_key','timeout_seconds'} and main['timeout_seconds']==9300
assert set(request)==set(main)|{'stdin'} and request['timeout_seconds']==900
review={
 'format':'hepta-maintenance-exact-execution-candidate-review-v1',
 'status':'PENDING_SEPARATE_EXACT_ROOT_ENGINEERING_APPROVAL',
 'root_authorized_candidate_only_four_fields':changes,'all_other_config_values_equal':True,
 'driver_unchanged':pin((ROOT/'driver-maintenance.HOLD.py').read_bytes()),
 'all_main_launcher_bytes_except_config_pin_equal':True,
 'all_stage_bootstrap_bytes_except_config_pin_equal':True,
 'all_payloads_except_exact_config_equal':True,'six_payloads_strictly_decoded_and_full_identity_equal':True,
 'main_request_shape':sorted(main),'staging_request_shape':sorted(request),
 'ordered_conditional_operations':[
   {'ordinal':1,'request':'STAGING_REQUEST.execution-candidate.json',
    'effect':'Create-only six external control files; no source operation or main execution',
    'required_actual_readback_before_ordinal_2':'Same-job normal exit0, complete durable output; complete STAGING_READBACK.json and all six stored file pins must match this exact reviewed payload; original staging launcher/payload retained; no BOOTSTRAP_FAILURE/partial-state replacement.'},
   {'ordinal':2,'request':'PROCESS_INPUT.execution-candidate.json',
    'effect':'Original EX launcher on the same actual inode; original one fix7200 and at most one fmt900 after all original live prerequisites',
    'requires_separate_root_engineering_approval':True}],
 'unknown_policy':'Retain original result and reconcile the exact key/bytes. Never resubmit a different operation to bypass an existing control/run or unobserved terminal.',
 'scope':{'staging_outer':900,'maintenance_outer':9300,'fix':7200,'fmt':900,'preflight':600,'records':300,
          'environment_override_in_requests':False,'source_refs_or_tests_authorized':False},
 'actual_staging_or_main_started':False,'h_calls':0,'qualification':False,'artifacts':rows}
rows.append(save('EXACT_CANDIDATE_REVIEW.json',jbytes(review)))
save('FILE_INDEX.json',jbytes(rows))
print(json.dumps({'artifacts':rows},indent=2))
