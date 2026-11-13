from pathlib import Path
import ast
import base64
import hashlib
import json

HERE=Path('/tmp/hepta-36fa-root-history-stage-core-review-v1')
CANDIDATE=Path('/tmp/hepta-36fa-source65a-transported-originals-hold-v1')
JOB='1a1d52e0d88-392-784'

def pin(data):
    return {'bytes':len(data),'git_blob':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),'sha256':hashlib.sha256(data).hexdigest()}

def pairs(items):
    result={}
    for key,value in items:
        assert key not in result,('duplicate key',key)
        result[key]=value
    return result

def parse(raw):return json.loads(raw,object_pairs_hook=pairs)

def sdk(name):
    raw=(HERE/name).read_bytes()
    outer=parse(raw)
    assert outer['isError'] is False and outer['structuredContent'] is None
    assert len(outer['content'])==1 and outer['content'][0]['type']=='text'
    return parse(outer['content'][0]['text']),pin(raw)

expected_input_pins={
 'SUPERVISOR.original.json':'af805a3230601013eb94afd5e40e9ea3e83c61d4',
 'STAGING_READBACK.original.json':'17d4ea78bc34facc9129c6a634fe750105d75bc4',
 'STREAMS.original.json':'6589454e33ed79a198a144220a0d8afe251c42da',
 'STAGING_READBACK.BINARY_READ.original.json':'b41b0af4a506c67049358a0b6a44cfa78cabdbda',
}
for name,sha in expected_input_pins.items():assert pin((HERE/name).read_bytes())['git_blob']==sha
normal,normal_pin=sdk('SUPERVISOR.original.json')
assert normal['job_id']==JOB and normal['state']=='succeeded' and normal['exit_code']==0
for key in ('audit_recorded','output_complete','output_durable','terminal_publication_confirmed'):assert normal[key] is True
for key in ('automatic_retry','cancelled','timed_out'):assert normal[key] is False
assert normal['terminal_publication_protocol']==1
for lane,length in [('stdout',268),('stderr',0)]:
    assert normal['log_bytes'][lane]=={'seen':length,'stored':length}
    assert normal['log_synced'][lane] is True and normal['log_truncated'][lane] is False
    assert normal['log_errors'][lane] is None
streams,stream_pin=sdk('STREAMS.original.json')
assert streams['job_id']==JOB and streams['audit_recorded'] is True
outputs={}
for lane,length in [('stdout',268),('stderr',0)]:
    s=streams[lane];raw=bytes.fromhex(s['bytes_hex'])
    assert s['offset']==0 and s['next_offset']==s['size']==len(raw)==length and s['eof'] is True
    outputs[lane]=raw
assert outputs['stderr']==b''
event=parse(outputs['stdout'])
assert event=={'event':'closed_history_transport_staging_complete','control':'/home/qian-qi/hepta-utility-36fa-evidence/final-qualification-b608-transported-originals-v1','historical_original_count':55,'source_writes':False,'main_dispatched':False,'qualification':False}
receipt_raw=(HERE/'STAGING_READBACK.original.json').read_bytes();receipt=parse(receipt_raw)
binary,binary_pin=sdk('STAGING_READBACK.BINARY_READ.original.json')
decoded=base64.b64decode(binary['data_base64'],validate=True)
assert decoded==receipt_raw and binary['offset']==0 and binary['eof'] is True
assert binary['size']==binary['next_offset']==len(decoded)==26573
assert binary['chunk_sha256']==hashlib.sha256(decoded).hexdigest()
assert binary['path']==event['control']+'/STAGING_READBACK.json'
version=tuple(int(x) for x in binary['version'].split(':'))
assert len(version)==5 and version[2]==26573
assert version[3:]==(1794577930394483386,1794577930394483386)
guard_raw=(CANDIDATE/'review-candidate-v1/qualification-admission.HOLD.py').read_bytes()
assert pin(guard_raw)['git_blob']=='299c3d79987abcde03e83c271bee91c568e0a5ab'
constants={}
for node in ast.parse(guard_raw.decode()).body:
    if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name) and node.targets[0].id.startswith('HISTORY_'):
        constants[node.targets[0].id]=ast.literal_eval(node.value)
assert receipt['format']=='hepta-closed-history-transport-readback-v1'
assert receipt['control']==constants['HISTORY_TRANSPORT_CONTROL']==event['control']
assert receipt['historical_original_count']==55
for field,key in [('manifest','HISTORY_MANIFEST_PIN'),('packet','HISTORY_PACKET_PIN'),('compressed_packet','HISTORY_GZIP_PIN'),('part_inputs','HISTORY_PART_INPUTS')]:assert receipt[field]==constants[key]
for field in ('automatic_retry','main_dispatched','old_path_writes','qualification','source_writes'):assert receipt[field] is False
manifest_raw=(CANDIDATE/'review-candidate-v1/TRANSPORT_MANIFEST.HOLD.json').read_bytes()
assert pin(manifest_raw)==constants['HISTORY_MANIFEST_PIN']
manifest=parse(manifest_raw);assert len(manifest['rows'])==55
expected={e['transport_path']:e['pin'] for e in manifest['rows']}
payload_raw=(CANDIDATE/'execution-candidate-v1/STAGING_INPUT.execution-candidate.json').read_bytes()
assert pin(payload_raw)['git_blob']=='f8efb445171e1eb74dc289cd5c15ab89f8940e4f'
expected.update({constants['HISTORY_MANIFEST_PATH']:constants['HISTORY_MANIFEST_PIN'],constants['HISTORY_RUNTIME_GUARD_PATH']:constants['HISTORY_RUNTIME_GUARD_PIN'],receipt['control']+'/ACTUAL_TRANSPORT_BOOTSTRAP.py':constants['HISTORY_STAGER_PIN'],receipt['control']+'/ACTUAL_TRANSPORT_ARGV.json':constants['HISTORY_STAGER_ARGV_PIN'],receipt['control']+'/ACTUAL_TRANSPORT_PAYLOAD.json':pin(payload_raw)})
assert len(expected)==60 and len(receipt['files'])==60
actual={}
for e in receipt['files']:
    assert set(e)=={'path','bytes','git_blob','sha256'} and e['path'] not in actual
    actual[e['path']]={k:e[k] for k in ('bytes','git_blob','sha256')}
assert actual==expected
report={'format':'hepta-root-history-stage-core-review-v1','job_id':JOB,'status':'NORMAL_SUPERVISOR_AND_COMPLETE_DECLARED_RECEIPT_VERIFIED_FILE_READBACK_STILL_PENDING','inputs':{n:pin((HERE/n).read_bytes()) for n in expected_input_pins},'normal_success':True,'complete_durable_streams':True,'stdout':pin(outputs['stdout']),'stderr':pin(outputs['stderr']),'receipt_binary_full_native_readback':True,'receipt_native_version_exact':binary['version'],'declared_files_match_frozen_exact_map':60,'declared_originals':55,'declared_parts_match':17,'approved_payload':pin(payload_raw),'full_61_file_readback_verified_by_this_review':False,'actual_request_to_job_admission_binding_verified_by_this_review':False,'source_or_native_main_dispatched_by_this_review':False,'H_calls':0,'qualification':False,'real_qualified_task_chains':0,'limits':['This checks supervisor, streams and one complete native receipt readback. It does not certify the other 60 file readbacks.','Receipt source/old-path/main flags are the exact approved stager receipt; this review is not a fresh source inventory.','The job admission and actual request original SDK remain a separate required binding.','Native version nanosecond fields are parsed and compared as exact Python integers; raw originals remain unchanged.']}
out=(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (HERE/'REVIEW.json').open('xb') as f:f.write(out)
print(json.dumps({'review':pin(out),'job_id':JOB,'normal_success':True,'receipt_readback':True,'declared_files':60,'full61_verified':False,'qualification':False},sort_keys=True))
