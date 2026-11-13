from pathlib import Path
import hashlib
import json

HERE=Path('/tmp/hepta-36fa-root-history-stage-core-review-v1')
REQUEST=Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1/execution-candidate-v1/STAGING_PROCESS_INPUT.execution-candidate.json')
def pin(b):return {'bytes':len(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'sha256':hashlib.sha256(b).hexdigest()}
def pairs(items):
    result={}
    for k,v in items:
        assert k not in result
        result[k]=v
    return result
def parse(b):return json.loads(b,object_pairs_hook=pairs)
def native(name):
    raw=(HERE/name).read_bytes();value=parse(raw)
    assert value['isError'] is False and value['structuredContent'] is None
    assert len(value['content'])==1 and value['content'][0]['type']=='text'
    return parse(value['content'][0]['text']),pin(raw)
request_raw=REQUEST.read_bytes();request=parse(request_raw)
assert pin(request_raw)=={'bytes':168712,'git_blob':'e944fa3dd289d28901cc216e4e05cce26e636a38','sha256':'4e9fc5f534ba18ad30ef73efa4c25aa65f11e48bad7f26fcedb2d3db1d3ace4f'}
intent_raw=(HERE/'STAGE_DISPATCH_INTENT.original.json').read_bytes();intent=parse(intent_raw)
assert pin(intent_raw)['git_blob']=='27696a998b71d7671338f8b8943becf45d4f47a8'
assert intent['approval']=='75003db540da7000de0b350b5fa53ac0b61c6644'
assert intent['request']==pin(request_raw) and intent['dispatch_limit']==1
assert intent['stage_only'] is True and intent['source_or_native_gate_authorized'] is False
assert intent['observed_admission'] is None
assert set(request)=={'host','executable','args','cwd','stdin','idempotency_key','timeout_seconds'}
assert request['timeout_seconds']==intent['timeout_seconds']==900
assert request['host']==intent['host']=='desktop'
assert request['idempotency_key']==intent['idempotency_key']=='hepta-utility-36fa-final-b608-transported-originals-staging-v1'
assert request['executable']=='/usr/bin/python3' and request['cwd']=='/home/qian-qi'
assert len(request['args'])==3 and request['args'][:2]==['-B','-c']
assert pin(request['args'][2].encode())['git_blob']=='0837bd70dd0e20a208fd8f59eec6017910cb9076'
assert pin(request['stdin'].encode())['git_blob']=='f8efb445171e1eb74dc289cd5c15ab89f8940e4f'
admission,admission_pin=native('STAGE_ADMISSION.original.json')
assert admission_pin['git_blob']=='97d700fa05cc4c6b9a7455376cc35878fe37dfaf'
assert admission['audit_recorded'] is True and admission['reused'] is False and admission['local_record_pending'] is False
job=admission['job'];assert job['id']=='1a1d52e0d88-392-784'
echo=['host','executable','args','cwd','idempotency_key']
for field in echo:assert job[field]==request[field],field
assert job['env_keys']==[] and job['ssh_target']=='desktop-ts' and job['execution_mode']=='operator'
assert job['system_jobctl'] is False and job['launch_state']=='launched' and job['launch_error'] is None
assert admission['launch']['ok'] is True and admission['launch']['unit']==job['unit']=='hepta-runtime-job-'+job['id']
assert len(job['request_digest'])==64 and int(job['request_digest'],16)>0
assert type(job['request_fingerprint']) is int and job['request_fingerprint']==12393409941603592577
assert job['request_fingerprint']==int(job['request_digest'][:16],16)
normal,normal_pin=native('SUPERVISOR.original.json')
assert normal['job_id']==job['id'] and normal['at_unix_ms']>=job['created_unix_ms']
assert normal['state']=='succeeded' and normal['exit_code']==0
report={'format':'hepta-root-stage-dispatch-binding-review-v1','job_id':job['id'],'status':'EXACT_SAVED_REQUEST_AND_ALL_ECHOED_ADMISSION_FIELDS_BOUND_TO_ACTUAL_NORMAL_JOB','intent':pin(intent_raw),'approved_request':pin(request_raw),'admission':admission_pin,'supervisor':normal_pin,'echoed_fields_equal':echo,'args_include_exact_approved_17939_byte_program':True,'saved_request_stdin':pin(request['stdin'].encode()),'saved_request_timeout_seconds':900,'actual_admission_env_keys':[],'actual_request_digest':job['request_digest'],'actual_request_fingerprint_decimal':str(job['request_fingerprint']),'reused':False,'normal_success':True,'full_61_file_readback_verified_by_this_review':False,'H_calls':0,'qualification':False,'real_qualified_task_chains':0,'limits':['The admission record echoes command, arguments, cwd, key and host, not the full stdin or timeout. The exact saved typed request retains those two fields; actual payload-file readback is part of the separate 61-file closure.','The worker request digest and fingerprint are preserved as observed. Prefix correspondence is checked; the worker canonical request-digest algorithm is not reconstructed here.','The pre-dispatch intent records 17 writes and 82 successful chunks plus one retained helper read failure. This report does not independently replay all part SDKs.','This is no source/native gate approval or deployed utility outcome.']}
raw=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'DISPATCH_BINDING_REVIEW.json').open('xb') as f:f.write(raw)
print(json.dumps({'report':pin(raw),'job_id':job['id'],'full61_verified':False,'qualification':False},sort_keys=True))
