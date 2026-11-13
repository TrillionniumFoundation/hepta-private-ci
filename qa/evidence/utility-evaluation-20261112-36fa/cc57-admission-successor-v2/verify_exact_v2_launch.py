import ast
import base64
import hashlib
import json
from pathlib import Path

ROOT=Path('/tmp/hepta-36fa-cc57-admission-successor-v2')
NEW=Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v2')
OLD=Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v1')

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def only_pin(x):return {k:x[k] for k in ('bytes','sha256','git_blob')}

def assignments(source):
    module=ast.parse(source)
    out={n.targets[0].id:(n,ast.get_source_segment(source,n)) for n in module.body
         if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
         and n.targets[0].id in ('BASE','PINS')}
    assert set(out)=={'BASE','PINS'}
    return module,out

def differences(old,new,path=()):
    assert type(old) is type(new),path
    if isinstance(old,dict):
        assert old.keys()==new.keys(),path
        return [x for key in old for x in differences(old[key],new[key],path+(key,))]
    if isinstance(old,list):
        assert len(old)==len(new),path
        return [x for i in range(len(old)) for x in differences(old[i],new[i],path+(str(i),))]
    return [] if old==new else [{'path':'.'.join(path),'old':old,'new':new}]

request_raw=(NEW/'SOURCE_PROCESS_INPUT.candidate.json').read_bytes()
request=json.loads(request_raw);old=json.loads((OLD/'SOURCE_PROCESS_INPUT.candidate.json').read_bytes())
assert pin(request_raw)=={'bytes':131345,'sha256':'55c9acefda3fe004b6b29e407256e89a1e99fd5e372b2ca04bf4b27a6f7687f4','git_blob':'3ebc2777182d88bcec1e0a3ad8546af93d5b25f0'}
assert list(request)==list(old)==['host','executable','args','cwd','stdin','idempotency_key','timeout_seconds']
for key in ('host','executable','cwd','timeout_seconds'):assert request[key]==old[key]
assert request['host']=='desktop' and request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert request['timeout_seconds']==7200 and request['idempotency_key']=='hepta-utility-36fa-final-source-gates-cc57-v2'
code=(NEW/'SOURCE_BOOTSTRAP.candidate.py').read_bytes();stdin=(NEW/'SOURCE_STDIN.candidate.json').read_bytes()
assert request['args']==['-B','-c',code.decode()] and request['stdin'].encode()==stdin and len(stdin)<=1048576
old_code=(OLD/'SOURCE_BOOTSTRAP.candidate.py').read_text()
new_ast,new_values=assignments(code.decode());old_ast,old_values=assignments(old_code)
inverse=code.decode()
for name in ('BASE','PINS'):
    assert inverse.count(new_values[name][1])==1
    inverse=inverse.replace(new_values[name][1],old_values[name][1],1)
assert inverse==old_code
assert ast.literal_eval(new_values['BASE'][0].value.args[0])=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v2'
pins=ast.literal_eval(new_values['PINS'][0].value);old_pins=ast.literal_eval(old_values['PINS'][0].value)
packet=json.loads(stdin);old_packet=json.loads(old['stdin'])
assert set(packet)=={'format','files'} and packet['format']==old_packet['format']=='hepta-final-source-qualification-bootstrap-v1'
assert set(packet['files'])==set(pins)==set(old_pins) and len(pins)==8
manifest=json.loads((NEW/'EXACT_SOURCE_LAUNCH_MANIFEST.candidate.json').read_bytes())
assert manifest['eight_input_pins']==pins
bound={'qualification-admission.py':ROOT/'qualification-admission.cc57.HOLD.py',
       'APPROVED_QUALIFICATION_INPUT.json':ROOT/'QUALIFICATION_INPUT.cc57-v2.HOLD.json',
       'APPROVED_SOURCE_GATES_CONFIG.json':ROOT/'SOURCE_GATES_CONFIG.cc57-v2.HOLD.json'}
for name,value in packet['files'].items():
    data=base64.b64decode(value,validate=True)
    assert pin(data)==pins[name]
    assert data==(NEW/'inputs'/name).read_bytes()
    if name in bound:assert data==bound[name].read_bytes()
    else:assert data==base64.b64decode(old_packet['files'][name],validate=True) and pins[name]==old_pins[name]
assert {name for name in pins if pins[name]!=old_pins[name]}==set(bound)
assert only_pin(manifest['typed_request'])==pin(request_raw)
assert only_pin(manifest['bootstrap'])==pin(code) and only_pin(manifest['stdin'])==pin(stdin)
assert manifest['outer_seconds']==7200 and manifest['idempotency_key']==request['idempotency_key']
last=new_ast.body[-1]
assert isinstance(last,ast.Expr) and isinstance(last.value,ast.Call) and isinstance(last.value.func,ast.Name) and last.value.func.id=='exec'
assert all(last not in list(ast.walk(n)) for n in new_ast.body if isinstance(n,ast.Try))
cfg=json.loads(bound['APPROVED_QUALIFICATION_INPUT.json'].read_bytes())
old_cfg=json.loads(base64.b64decode(old_packet['files']['APPROVED_QUALIFICATION_INPUT.json']))
cfg_changes=differences(old_cfg,cfg)
allowed={'admission_path','admission_pin.git_blob','admission_pin.sha256','native_driver_path','plan_path',
         'records','root_parent','run_identity','source_gates_config_path','source_gates_config_pin.git_blob',
         'source_gates_config_pin.sha256','source_gates_handoff_records','canonical_alignment.supervisor_path'}
assert {x['path'] for x in cfg_changes}==allowed
source_cfg=json.loads(bound['APPROVED_SOURCE_GATES_CONFIG.json'].read_bytes())
old_source_cfg=json.loads(base64.b64decode(old_packet['files']['APPROVED_SOURCE_GATES_CONFIG.json']))
source_changes=differences(old_source_cfg,source_cfg)
assert {x['path'] for x in source_changes}=={'source_checkout','records','run_identity'}
assert cfg['runtime_guard']==old_cfg['runtime_guard'] and cfg['source']==old_cfg['source']=='cc57c7198db6293ccca562253c42fffbe2a04633'
assert cfg['tree']==old_cfg['tree']=='b7b357c07b5539769a068c6b9b009629f5612d1e'
assert source_cfg['budgets_seconds']=={'source-closure':600,'self-test':300,'verify':4800}
successor=json.loads((ROOT/'SUCCESSOR_REVIEW.json').read_bytes())
assert successor['new_admission']==pins['qualification-admission.py']
assert len(successor['exact_three_ast_constant_changes'])==3 and successor['inverse_three_replacements_restores_full_original_bytes'] is True
assert successor['original_predicate_rejects_actual_1c98'] is True and successor['successor_predicate_accepts_actual_1c98'] is True
assert len(successor['synthetic_negative_predicate_probes'])==12 and all(x['predicate_returned'] is False for x in successor['synthetic_negative_predicate_probes'])
review={'format':'hepta-root-cc57-v2-exact-source-launch-review-v1','status':'EXACT_BYTES_VERIFIED_PEER_REVIEW_AND_ROOT_FINAL_APPROVAL_REQUIRED',
        'source':cfg['source'],'tree':cfg['tree'],'request':pin(request_raw),'bootstrap':pin(code),'stdin':pin(stdin),
        'idempotency_key':request['idempotency_key'],'outer_seconds':7200,
        'exact_eight_input_pins':pins,'exact_bootstrap_inverse_restores_v1_bytes':True,
        'five_fixed_inputs_full_byte_identical':True,'exec_outside_staging_try':True,
        'qualification_cfg_exact_whitelisted_changes':cfg_changes,'source_cfg_exact_whitelisted_changes':source_changes,
        'runtime_guard_and_source_identity_unchanged':True,'admission_successor_review':pin((ROOT/'SUCCESSOR_REVIEW.json').read_bytes()),
        'old_attempt':{'job':'1a1d2325df6-2564-1cae','wrapper_status':'unknown','source_driver_main_entered':False,'retained':True},
        'H_or_main_dispatched':False,'native_main_approved':False,'qualification':False,'real_qualified_task_chains':0}
raw=(json.dumps(review,sort_keys=True,indent=2)+'\n').encode();out=ROOT/'ROOT_EXACT_V2_PREFLIGHT_REVIEW.json'
if out.exists():assert out.read_bytes()==raw
else:out.write_bytes(raw)
print(json.dumps({'preflight_review':pin(raw),'exact_request':pin(request_raw),'status':review['status']},sort_keys=True))
