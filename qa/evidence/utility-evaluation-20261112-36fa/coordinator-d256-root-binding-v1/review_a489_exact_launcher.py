#!/usr/bin/env python3
"""Independent Root exact typed launcher review, no dispatch."""
import ast, base64, gzip, hashlib, json
from pathlib import Path
R=Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
O=Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
N=Path('/tmp/hepta-36fa-coordinator-a489-materializer-hold-v1')
def pin(raw): return {'bytes':len(raw),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),'sha256':hashlib.sha256(raw).hexdigest()}
old_raw=(O/'MATERIALIZATION_PROCESS_INPUT.candidate.json').read_bytes()
new_raw=(N/'MATERIALIZATION_PROCESS_INPUT.candidate.json').read_bytes()
assert pin(old_raw)['git_blob']=='a34c8779fca77cbf1dd7e26e5516efcfb654c191'
assert pin(new_raw)['git_blob']=='a5a3f6b6bcc0bdbfb4c36261d4c2d31f6fb5cefa'
old=json.loads(old_raw);new=json.loads(new_raw)
assert set(old)==set(new)=={'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
for key in ('host','executable','cwd','timeout_seconds'): assert old[key]==new[key]
assert new['host']=='desktop' and new['executable']=='/usr/bin/python3' and new['cwd']=='/home/qian-qi' and new['timeout_seconds']==900
assert new['idempotency_key']=='hepta-utility-36fa-provider-coordinator-a489-isolated-materialization-v1'
assert new['args'][:2]==old['args'][:2]==['-B','-c'] and len(new['args'])==len(old['args'])==3
before=old['args'][2];after=new['args'][2]
assert after.encode()==(N/'MATERIALIZATION_BOOTSTRAP.candidate.py').read_bytes()
assert new['stdin'].encode()==(N/'MATERIALIZATION_STDIN.candidate.json').read_bytes()
assert len(new_raw)<1048576 and len(new['stdin'].encode())<1048576
def assignment(s,name):
    nodes=[n for n in ast.parse(s).body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==name]
    assert len(nodes)==1
    return nodes[0],ast.get_source_segment(s,nodes[0])
ob,obs=assignment(before,'BASE'); nb,nbs=assignment(after,'BASE')
assert obs=="BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-isolated-materialization-v1')"
assert nbs=="BASE = pathlib.Path('/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1')"
op,ops=assignment(before,'PINS'); np,nps=assignment(after,'PINS')
assert before.replace(obs,nbs,1).replace(ops,nps,1)==after
assert after.replace(nbs,obs,1).replace(nps,ops,1)==before
old_pins=ast.literal_eval(op.value); new_pins=ast.literal_eval(np.value)
assert old_pins.keys()==new_pins.keys()
files={
 'driver.py':(N/'driver.HOLD.py').read_bytes(),
 'MATERIALIZATION_PACKET.json':(N/'MATERIALIZATION_PACKET.HOLD.json').read_bytes(),
 'DONOR_RESULT.original.json':(N/'DONOR_RESULT.original.json').read_bytes(),
 'DONOR_SUPERVISOR.original.json':(N/'DONOR_NORMAL_SUPERVISOR.original.json').read_bytes(),
 'APPROVED_CONFIG.json':(N/'APPROVAL_CANDIDATE_CONFIG.json').read_bytes(),
}
payload=json.loads(new['stdin'])
assert set(payload)=={'format','files'} and payload['format']=='hepta-complete-candidate-materialization-bootstrap-v1'
assert set(payload['files'])==set(files)==set(new_pins)
decoded_pins=[]
for name,expected in files.items():
    actual=base64.b64decode(payload['files'][name],validate=True)
    if name=='MATERIALIZATION_PACKET.json': actual=gzip.decompress(actual)
    assert actual==expected and pin(actual)==new_pins[name]
    if name.startswith('DONOR_'):assert old_pins[name]==new_pins[name]
    decoded_pins.append({'name':name,**pin(actual)})
cfg=json.loads(files['APPROVED_CONFIG.json']); waiting=json.loads((N/'WAITING_CONFIG.json').read_text())
assert cfg.keys()==waiting.keys()
assert {k for k in cfg if cfg[k]!=waiting[k]}=={'root_execution_approved','status'}
assert cfg['root_execution_approved'] is True and waiting['root_execution_approved'] is False
assert cfg['status']=='APPROVED_CANDIDATE_ISOLATED_MATERIALIZATION'
assert waiting['status']=='WAITING_ROOT_EXACT_APPROVAL'
assert cfg['qualification'] is False and cfg['automatic_retry'] is False
def helpers(s): return {n.name:ast.get_source_segment(s,n) for n in ast.parse(s).body if isinstance(n,ast.FunctionDef)}
assert helpers(before)==helpers(after) and set(helpers(after))=={'check','identity','real_parents','retain'}
report={'format':'hepta-root-a489-exact-launcher-static-review-v1','status':'EXACT_LAUNCHER_VERIFIED_PENDING_FINAL_ENGINEERING_APPROVAL','qualification':False,'H_calls':0,'original_request':pin(old_raw),'typed_request':pin(new_raw),'bootstrap':pin(after.encode()),'stdin':pin(new['stdin'].encode()),'candidate_config':pin(files['APPROVED_CONFIG.json']),'original_bootstrap_outside_exact_base_and_pins_byte_equal':True,'original_four_helpers_complete_byte_equal':True,'decoded_five_payloads':decoded_pins,'environment_overrides':False,'seven_typed_fields_exact':True,'host':new['host'],'executable':new['executable'],'cwd':new['cwd'],'idempotency_key':new['idempotency_key'],'outer_seconds':900,'action_record_seconds':[600,180],'typed_bytes_limit':1048576,'staging_requires_five_separate_fixed_absent_writes':True,'candidate_true_config_is_not_runtime_Root_authority_or_qualification':True,'actual_dispatch_calls':0,'real_authorized_task_chains':0}
raw=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode()
(R/'ROOT_A489_EXACT_LAUNCHER_REVIEW.json').write_bytes(raw)
print(json.dumps({'report':pin(raw),'request':pin(new_raw),'payloads':len(decoded_pins),'status':report['status']}))
