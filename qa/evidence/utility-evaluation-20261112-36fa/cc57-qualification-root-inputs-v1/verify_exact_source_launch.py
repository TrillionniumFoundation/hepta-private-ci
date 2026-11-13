import ast
import base64
import hashlib
import json
from pathlib import Path

ROOT=Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
CAND=Path('/tmp/hepta-36fa-source-qualification-cc57-candidate-v1')
OLD=Path('/tmp/hepta-36fa-final-source-qualification-launch-v1')

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def only_pin(value):
    return {k:value[k] for k in ('bytes','sha256','git_blob')}

def assignments(source):
    module=ast.parse(source)
    values={}
    for node in module.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            if node.targets[0].id in ('BASE','PINS'):
                values[node.targets[0].id]=(node,ast.get_source_segment(source,node))
    assert set(values)=={'BASE','PINS'}
    return module,values

request_raw=(CAND/'SOURCE_PROCESS_INPUT.candidate.json').read_bytes()
request=json.loads(request_raw)
old_request=json.loads((OLD/'ACTUAL_SOURCE_PROCESS_INPUT.json').read_bytes())
assert pin(request_raw)=={'bytes':131345,'sha256':'a75a1c40a743997daf2b374cd6a10e75846cc25698af84a5472e9c965923d190','git_blob':'2153b3aba2bfcaaa44123e53ec370004c22d66dd'}
assert list(request)==list(old_request)==['host','executable','args','cwd','stdin','idempotency_key','timeout_seconds']
assert request['host']=='desktop' and request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert request['timeout_seconds']==old_request['timeout_seconds']==7200
assert request['idempotency_key']=='hepta-utility-36fa-final-source-gates-cc57-v1'
assert request['args'][:2]==['-B','-c'] and len(request['args'])==3
code=(CAND/'SOURCE_BOOTSTRAP.candidate.py').read_bytes()
stdin=(CAND/'SOURCE_STDIN.candidate.json').read_bytes()
assert request['args'][2].encode()==code and request['stdin'].encode()==stdin and len(stdin)<=1048576
assert pin(code)['git_blob']=='0c317ffdb1f76b027c4eeabd0a61e561929d93e3'
assert pin(stdin)['git_blob']=='30e5ccddc28853a19eb8b0cebf2811ce8ef3da00'
old_code=(OLD/'ACTUAL_SOURCE_BOOTSTRAP.py').read_text()
assert pin(old_code.encode())['git_blob']=='d6b2df2a5753c2703242ef036fc8088b3333dd5b'
new_code=code.decode()
new_ast,new_values=assignments(new_code)
old_ast,old_values=assignments(old_code)
inverse=new_code
for name in ('BASE','PINS'):
    assert inverse.count(new_values[name][1])==1
    inverse=inverse.replace(new_values[name][1],old_values[name][1],1)
assert inverse==old_code
assert ast.literal_eval(new_values['BASE'][0].value.args[0])=='/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-cc57-v1'
pins=ast.literal_eval(new_values['PINS'][0].value)
old_pins=ast.literal_eval(old_values['PINS'][0].value)
packet=json.loads(stdin)
assert set(packet)=={'format','files'} and packet['format']=='hepta-final-source-qualification-bootstrap-v1'
assert set(packet['files'])==set(pins)==set(old_pins) and len(pins)==8
old_packet=json.loads(old_request['stdin'])
bound={
 'APPROVED_QUALIFICATION_INPUT.json':ROOT/'APPROVED_FINAL_QUALIFICATION_INPUT.json',
 'APPROVED_SOURCE_GATES_CONFIG.json':ROOT/'APPROVED_FINAL_SOURCE_GATES_CONFIG.json',
 'CANONICAL_ALIGNMENT_NORMAL.original.json':Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1/STATUS_01.original.json')}
manifest=json.loads((CAND/'EXACT_SOURCE_LAUNCH_MANIFEST.candidate.json').read_bytes())
for name,value in packet['files'].items():
    raw=base64.b64decode(value,validate=True)
    assert pin(raw)==pins[name]==only_pin(manifest['inputs'][name])
    assert raw==(CAND/'inputs'/name).read_bytes()
    if name in bound: assert raw==bound[name].read_bytes()
    else:
        assert pins[name]==old_pins[name]
        assert raw==base64.b64decode(old_packet['files'][name],validate=True)
assert {n for n in pins if pins[n]!=old_pins[n]}==set(bound)
assert only_pin(manifest['typed_request'])==pin(request_raw)
assert only_pin(manifest['bootstrap'])==pin(code) and only_pin(manifest['stdin'])==pin(stdin)
assert manifest['outer_seconds']==7200 and manifest['idempotency_key']==request['idempotency_key']
# Exact inverse replacement verifies every function, exception path, staging
# permission and the complete post-try execution tail, not merely AST shape.
assert isinstance(new_ast.body[-1],ast.Expr) and isinstance(new_ast.body[-1].value,ast.Call)
assert isinstance(new_ast.body[-1].value.func,ast.Name) and new_ast.body[-1].value.func.id=='exec'
assert all(new_ast.body[-1] not in list(ast.walk(n)) for n in new_ast.body if isinstance(n,ast.Try))
cfg=json.loads(bound['APPROVED_QUALIFICATION_INPUT.json'].read_bytes())
source_cfg=json.loads(bound['APPROVED_SOURCE_GATES_CONFIG.json'].read_bytes())
assert cfg['source']==source_cfg['source_sha']=='cc57c7198db6293ccca562253c42fffbe2a04633'
assert cfg['tree']==source_cfg['source_tree']=='b7b357c07b5539769a068c6b9b009629f5612d1e'
assert cfg['canonical_alignment']['job_id']=='1a1d223a60b-2564-1ca3'
assert cfg['canonical_alignment']['result']['git_blob']=='c374e3029f0fa8fa4f66d6e311c6841785db63b5'
assert source_cfg['budgets_seconds']=={'source-closure':600,'self-test':300,'verify':4800}
publication=json.loads(Path('/tmp/hepta-36fa-cc57-source-publication-v1/SOURCE_PUBLICATION_REVIEW.json').read_bytes())
assert publication['published_source']==cfg['source'] and publication['draft'] is True and publication['merged'] is False
review={
 'format':'hepta-root-cc57-exact-source-launch-approval-v1',
 'decision':'APPROVE_ONLY_THIS_EXACT_SOURCE_GATE_REQUEST',
 'source':cfg['source'],'tree':cfg['tree'],'source_ref_readback_verified':True,
 'request':pin(request_raw),'bootstrap':pin(code),'stdin':pin(stdin),
 'candidate_manifest':pin((CAND/'EXACT_SOURCE_LAUNCH_MANIFEST.candidate.json').read_bytes()),
 'idempotency_key':request['idempotency_key'],'host':request['host'],'executable':request['executable'],'cwd':request['cwd'],
 'outer_seconds':7200,'original_gate_budgets_seconds':source_cfg['budgets_seconds'],
 'actual_canonical_job':cfg['canonical_alignment']['job_id'],'actual_canonical_result':cfg['canonical_alignment']['result'],
 'exact_eight_input_pins':pins,'exact_inverse_BASE_and_PINS_restores_complete_prior_bootstrap':True,
 'five_fixed_inputs_full_byte_identical':True,'source_wrapper_exec_outside_staging_try':True,
 'original_all_guards_and_failure_retention_unchanged':True,'environment_override_added':False,
 'allowed_execution':'Sole native_ci_audit executor may dispatch this exact request once and reconcile this same key/request if transport outcome is Unknown. Complete source clone/freeze and all three original gates only.',
 'native_wrapper_staged_but_not_executed_by_this_request':True,
 'separate_native_main_approval_required_after_complete_source_result':True,
 'native_or_source_commands_dispatched_by_this_offline_review':False,
 'prior_246d_failed_source_result_retained':True,'qualification':False,'real_qualified_task_chains':0}
raw=(json.dumps(review,sort_keys=True,indent=2)+'\n').encode()
p=ROOT/'ROOT_EXACT_CC57_SOURCE_LAUNCH_APPROVAL.json'
if p.exists(): assert p.read_bytes()==raw
else: p.write_bytes(raw)
print(json.dumps({'approval':pin(raw),'request':pin(request_raw),'approved':True},sort_keys=True))
