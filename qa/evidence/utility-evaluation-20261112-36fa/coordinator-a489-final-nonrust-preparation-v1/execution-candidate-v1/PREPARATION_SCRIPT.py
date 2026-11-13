#!/usr/bin/env python3
"""Freeze candidate bytes after exact Root review bindings; never submit them."""
import ast
import base64
import difflib
import gzip
import hashlib
import json
from pathlib import Path

ROOT=Path('/tmp/hepta-36fa-coordinator-a489-final-nonrust-preparation-v1')
OLD=ROOT/'launch-hold-v1'
OUT=ROOT/'execution-candidate-v1'
RUNTIME=Path('/tmp/hepta-36fa-coordinator-a489-maintenance-runtime-v1')
PACKET=Path('/tmp/hepta-36fa-a489-maintenance-nonrust-apply-packet-v1/NONRUST_PACKET.json')

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def encode(value):
    return (json.dumps(value,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()

def save(path,raw):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():assert path.read_bytes()==raw
    else:
        with path.open('xb')as f:f.write(raw)
    return identity(raw)

def diff(before,after,left,right):
    return ''.join(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile=left,tofile=right)).encode()

original_cfg=(ROOT/'WAITING_INPUT_BOUND_CONFIG.json').read_bytes()
assert identity(original_cfg)['git_blob']=='92d3fa23a8894c6aed4d224b2ae9bfccfc8653e3'
old_cfg=json.loads(original_cfg)
review_bound=dict(old_cfg)
review_bound['source_peer_review']='7dce432cbecd7b349db5e8599a8e1c58a0b7f4bf'
review_bound['root_input_review']='94c9d4fa5843806a0ae8e0a08296840c4ad625d9'
review_bound['waiting_for']=['Root final exact control approval pending.']
assert review_bound['status']=='HOLD_ROOT_EXACT_REVIEW_REQUIRED' and review_bound['root_execution_approved']is False
bound_raw=encode(review_bound)
bound_pin=save(OUT/'REVIEW_BOUND_HOLD_CONFIG.json',bound_raw)
save(OUT/'REVIEW_BOUND_HOLD_FROM_92D3.diff',diff(original_cfg,bound_raw,'92d3-input-bound-HOLD.json','REVIEW_BOUND_HOLD_CONFIG.json'))
inverse=dict(review_bound)
for key in ('source_peer_review','root_input_review','waiting_for'):inverse[key]=old_cfg[key]
assert encode(inverse)==original_cfg
approved=dict(review_bound)
approved['status']='ROOT_APPROVED_TO_EXECUTE'
approved['root_execution_approved']=True
approved_raw=encode(approved)
approved_pin=save(OUT/'APPROVED_CONFIG.candidate.json',approved_raw)
save(OUT/'CONFIG_TWO_FIELD_APPROVAL.diff',diff(bound_raw,approved_raw,'REVIEW_BOUND_HOLD_CONFIG.json','APPROVED_CONFIG.candidate.json'))
inverse=dict(approved)
inverse['status']=review_bound['status'];inverse['root_execution_approved']=False
assert encode(inverse)==bound_raw
assert [key for key in approved if approved[key]!=review_bound[key]]==['root_execution_approved','status']
driver=(ROOT/'driver.HOLD.py').read_bytes()
normal=(RUNTIME/'STATUS_06.original.json').read_bytes()
packet=PACKET.read_bytes()
packet_gz=PACKET.with_name(PACKET.name+'.gz').read_bytes()
assert gzip.decompress(packet_gz)==packet
files={'driver.py':driver,'MAINTENANCE_NORMAL.original.json':normal,
       'NONRUST_PACKET.json':packet,'APPROVED_CONFIG.json':approved_raw}
pins={name:identity(raw)for name,raw in files.items()}
assert pins['driver.py']==approved['driver']
assert pins['MAINTENANCE_NORMAL.original.json']==approved['actual_prior_maintenance']['supervisor']
assert pins['NONRUST_PACKET.json']==approved['nonrust_packet']
old_bootstrap=(OLD/'ACTUAL_BOOTSTRAP.HOLD.py').read_bytes()
old_request=json.loads((OLD/'ACTUAL_PROCESS_INPUT.HOLD.json').read_bytes())
old_payload=json.loads((OLD/'ACTUAL_STDIN.HOLD.json').read_bytes())
old_pin_line=next(line for line in old_bootstrap.decode().splitlines(True)if line.startswith('PINS = '))
new_pin_line='PINS = '+repr(pins)+'\n'
bootstrap=old_bootstrap.decode().replace(old_pin_line,new_pin_line,1).encode()
assert bootstrap.decode().replace(new_pin_line,old_pin_line,1).encode()==old_bootstrap
old_pins=ast.literal_eval(ast.parse(old_pin_line).body[0].value)
assert {name:pin for name,pin in old_pins.items()if name!='APPROVED_CONFIG.json'}=={
    name:pin for name,pin in pins.items()if name!='APPROVED_CONFIG.json'}
payload=dict(old_payload);payload['files']=dict(payload['files'])
payload['files']['APPROVED_CONFIG.json']=base64.b64encode(approved_raw).decode()
stdin=encode(payload)
request=dict(old_request)
request['args']=['-B','-c',bootstrap.decode()]
request['stdin']=stdin.decode()
typed=encode(request)
assert set(request)=={'host','executable','args','cwd','stdin','timeout_seconds','idempotency_key'}
assert request['timeout_seconds']==2100
assert request['idempotency_key']=='hepta-utility-36fa-provider-coordinator-a489-final-nonrust-format-v1'
assert request['host']=='desktop' and request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert len(typed)<=1048576 and len(stdin)<=1048576
for name,pin in pins.items():
    raw=base64.b64decode(payload['files'][name],validate=True)
    if name=='NONRUST_PACKET.json':raw=gzip.decompress(raw)
    assert identity(raw)==pin and raw==files[name]
parsed_original=(ROOT/'inputs/ORIGINAL_9101_BOOTSTRAP.py').read_bytes()
origin_lines=parsed_original.decode().splitlines(True)
original_base=next(line for line in origin_lines if line.startswith('BASE = '))
original_pins=next(line for line in origin_lines if line.startswith('PINS = '))
current_base=next(line for line in bootstrap.decode().splitlines(True)if line.startswith('BASE = '))
assert bootstrap.decode().replace(current_base,original_base,1).replace(new_pin_line,original_pins,1).encode()==parsed_original
compile(bootstrap,'ACTUAL_BOOTSTRAP.candidate.py','exec')
bootstrap_pin=save(OUT/'ACTUAL_BOOTSTRAP.candidate.py',bootstrap)
stdin_pin=save(OUT/'ACTUAL_STDIN.candidate.json',stdin)
request_pin=save(OUT/'ACTUAL_PROCESS_INPUT.candidate.json',typed)
save(OUT/'BOOTSTRAP_FROM_HOLD.diff',diff(old_bootstrap,bootstrap,'cb67-bootstrap-HOLD.py','ACTUAL_BOOTSTRAP.candidate.py'))
save(OUT/'INPUT_FILES.json',encode({'format':'hepta-last-nonrust-candidate-four-inputs-v1','files':pins,
    'packet_gzip':identity(packet_gz),'actual_source_peer':review_bound['source_peer_review'],
    'actual_root_input_review':review_bound['root_input_review'],'H_calls':0,
    'not_execution_authority':'The true approval fields are candidate bytes only. An exact Root engineering decision on this request is still required.'}))
representations=[]
for name,body in [('ACTUAL_STDIN.candidate.json',stdin),('ACTUAL_PROCESS_INPUT.candidate.json',typed)]:
    compressed=gzip.compress(body,mtime=0)
    parts=[]
    for number,offset in enumerate(range(0,len(compressed),307200),1):
        chunk=compressed[offset:offset+307200];encoded=base64.b64encode(chunk)+b'\n'
        part_name=name+'.gz.part-%03d.b64'%number
        part_pin=save(OUT/part_name,encoded)
        assert part_pin['bytes']<=512000
        parts.append({'name':part_name,'decoded_offset':offset,'decoded':identity(chunk),**part_pin})
    assert gzip.decompress(b''.join(base64.b64decode((OUT/p['name']).read_bytes().rstrip(b'\n'),validate=True)for p in parts))==body
    representations.append({'name':name,'raw':identity(body),'gzip':identity(compressed),'parts':parts,
        'standalone_raw_git_get_claimed':False})
save(OUT/'ENCODING_MANIFEST.json',encode({'format':'hepta-bounded-final-nonrust-candidate-launch-v1','leaf_limit':512000,
    'members':representations,'scope':'Exact prepared request/stdin only; no actual process dispatch or observations exist.'}))
review={'format':'hepta-last-nonrust-exact-execution-candidate-byte-review-v1','status':'WAITING_ROOT_EXACT_APPROVAL',
    'original_unbound_HOLD':identity(original_cfg),'actual_review_bound_HOLD':bound_pin,'candidate_config':approved_pin,
    'review_binding_only_changes':['root_input_review','source_peer_review','waiting_for'],
    'approval_candidate_only_changes':['root_execution_approved','status'],
    'both_config_inverse_byte_equal':True,'bootstrap_from_HOLD_only_change':'Approved config pin in PINS; all other code and three input pins byte-identical.',
    'bootstrap':bootstrap_pin,'stdin':stdin_pin,'request':request_pin,'four_inputs':pins,
    'bootstrap_full_inverse_to_original_9ca752':True,
    'seven_fields':sorted(request),'no_env_field':True,'outer_seconds':2100,
    'unchanged_operation_budgets':{'preflight_apply':600,'fmt':900,'retention':300},
    'typed_bytes':len(typed),'stdin_bytes':len(stdin),'exact_four_decoded_inputs_match':True,
    'single_ex_owner':'Only the unchanged thin main; no staging EX.',
    'mode_and_scope':'Four fixed existing100644 files including one explicit original contract JSON target; full source/Git/runtime guards retained.',
    'semantic_success_claim':False,'future_final_format_result':None,'future_canonical_commit':None,
    'dispatch_authorized_by_this_preparation':False,'H_calls':0,'test_commands':0,'qualification':False}
save(OUT/'EXACT_CANDIDATE_REVIEW.json',encode(review))
print(json.dumps({'bound_HOLD':bound_pin,'config':approved_pin,'bootstrap':bootstrap_pin,'stdin':stdin_pin,
                  'typed':request_pin,'H_calls':0,'execution_authority':False},indent=2))
