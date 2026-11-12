import base64, gzip, hashlib, json, re, struct
from pathlib import Path
R=Path('/tmp/hepta-36fa-checkpoint1867-recovery')
N=Path('/tmp/hepta-36fa-maintenance-terminal-20261112')
A=Path('/tmp/hepta-36fa-git-index-stat-audit-v1/actual-index-analysis-v1')
def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def read(n): return json.loads((N/n).read_bytes())
result=read('RESULT.json'); term=read('NORMAL_TERMINAL.original.json'); fix=read('fix.terminal.json')
assert pin((N/'RESULT.json').read_bytes())=={'bytes':5114,'sha256':'c13be4e53eba55593d17a43ec9acdfb97060a55866eb52fc684700bf2df0236c','git_blob':'30300f4cf4743e3fb80ccf404f7e7be4d8b81ac6'}
assert result['status']=='UNKNOWN' and result['attempted_commands']==['fix'] and result['not_run_commands']==['fmt']
assert result['test_commands_dispatched']==0 and result['stages']==[fix]
assert term['job_id']=='1a1d10d8ad0-2564-1bff' and term['exit_code']==1
assert term['output_complete'] and term['output_durable'] and not term['timed_out'] and not term['cancelled']
assert fix['execution']['returncode']==101 and fix['execution_outcome']=='failed'
assert not fix['execution']['timed_out'] and not fix['execution']['output_limit_exceeded']
raw=(N/'fix.raw.log').read_bytes(); stdout=(N/'SUPERVISOR.stdout.log').read_bytes()
assert pin(raw)=={'bytes':116897,'sha256':'e30ead233ff190511d27e06d3465d25aa162bc1f075f50a6114102243b81af93','git_blob':'e3595315f3e98e4232dfac34d82cbec9032b997c'}
assert pin(stdout)=={'bytes':118168,'sha256':'869dd733aac2f9980ee3f1b03d594bd31d2326f8796f1f61df097b89f5125fb1','git_blob':'b94991a16d66bea3f0d633bb49d0391af3ed5cbf'}
assert raw in stdout and term['log_bytes']['stdout']=={'seen':len(stdout),'stored':len(stdout)}
assert term['log_bytes']['stderr']=={'seen':0,'stored':0}
def unwrap(x):
    if isinstance(x,dict) and isinstance(x.get('content'),list):
        texts=[v['text'] for v in x['content'] if v.get('type')=='text']
        if len(texts)==1:
            try:return json.loads(texts[0])
            except ValueError: pass
    return x
fix_chunks=[]
for name in ['FIX_RAW_FIRST_BINARY_READ_NATIVE_SDK.original.json','FIX_RAW_SECOND_BINARY_READ_NATIVE_SDK.original.json']:
    j=unwrap(read(name)); b=base64.b64decode(j['data_base64'],validate=True)
    assert hashlib.sha256(b).hexdigest()==j['chunk_sha256']
    assert j['next_offset']==j['offset']+len(b) and j['size']==len(raw)
    assert raw[j['offset']:j['next_offset']]==b
    fix_chunks.append((j['offset'],j['next_offset'],j['version'],j['eof']))
assert fix_chunks[0][0]==0 and fix_chunks[0][1]==fix_chunks[1][0] and fix_chunks[1][1]==len(raw) and fix_chunks[1][3]
assert fix_chunks[0][2]==fix_chunks[1][2]
covered=bytearray(len(stdout)); intervals=[]
def inspect_stdout(j,name):
    j=unwrap(j)
    if not isinstance(j,dict) or j.get('job_id')!=term['job_id'] or not isinstance(j.get('stdout'),dict):return
    d=j['stdout']
    if 'bytes_hex' not in d:return
    b=bytes.fromhex(d['bytes_hex']); a=d['offset']; z=d['next_offset']
    assert b==d['text'].encode() and z==a+len(b) and stdout[a:z]==b
    covered[a:z]=b'\1'*len(b); intervals.append({'record':name,'offset':a,'next_offset':z,'size_at_observation':d['size'],'eof_at_observation':d['eof']})
for p in N.glob('*.json'):
    try:inspect_stdout(json.loads(p.read_bytes()),p.name)
    except (UnicodeDecodeError,json.JSONDecodeError):pass
for p in (R/'native68-blobs').glob('*.response.json'):
    wrapper=json.loads(p.read_bytes())
    try:inspect_stdout(json.loads(wrapper['content']),p.name)
    except (KeyError,TypeError,json.JSONDecodeError):pass
assert all(covered),[(m.start(),m.end()) for m in re.finditer(b'\0+',covered)]
errors=re.findall(rb'^error\[(E\d+)\]: (.+)$',raw,re.M)
assert errors==[(b'E0425',b'cannot find function `recovered_peer` in module `training_ports`')],errors
before=read('SOURCE_GIT_STATE.before.json'); after=read('final.git-state.json')
assert read('fix.after.git-state.json')==before
assert [k for k in before if before[k]!=after[k]]==['index_sha256']
assert read('fix.after.postimages.json')['changes']==[] and fix['retention']['complete']
idx_after=(N/'index.actual.bin').read_bytes(); idx_before=(A/'index.before.exactly_recovered.bin').read_bytes()
assert pin(idx_after)['bytes']==before['index_bytes']==after['index_bytes']==len(idx_before)==2072488
assert pin(idx_after)['sha256']==after['index_sha256']
assert pin(idx_before)['sha256']==before['index_sha256']
assert gzip.decompress((N/'index.actual.bin.gz').read_bytes())==idx_after
assert idx_before[:12]==idx_after[:12] and idx_after[:4]==b'DIRC'
assert hashlib.sha1(idx_after[:-20]).digest()==idx_after[-20:]
assert hashlib.sha1(idx_before[:-20]).digest()==idx_before[-20:]
_,count=struct.unpack('>II',idx_after[4:12]); assert count==15188
offset=12; changed_stat_fields=0
for i in range(count):
    start=offset
    for k in range(10):
        a=idx_after[offset+k*4:offset+k*4+4]; b=idx_before[offset+k*4:offset+k*4+4]
        if k==6:assert a==b
        else:
            assert b==b'\0'*4
            changed_stat_fields+=a!=b
    flags=int.from_bytes(idx_after[offset+60:offset+62],'big');assert flags&0x4000==0
    nul=idx_after.index(b'\0',offset+62); end=start+((nul-start+1+7)//8)*8
    assert idx_before[offset+40:end]==idx_after[offset+40:end]
    offset=end
assert offset==2003612 and idx_before[offset:-20]==idx_after[offset:-20]
report={'format':'hepta-root-maintenance-terminal-and-index-review-v1','qualification':False,'native_job':term['job_id'],'original_maintenance_result_status':'UNKNOWN','known_fix_returncode':101,'fmt':'NOT_RUN','tests_dispatched':0,'full_original_result':pin((N/'RESULT.json').read_bytes()),'complete_fix_log':pin(raw),'complete_supervisor_stdout':pin(stdout),'all_stdout_bytes_matched_original_observed_hex_and_text':True,'stdout_observation_intervals':intervals,'fix_log_fixed_version_chunks':fix_chunks,'compiler_errors':[{'code':c.decode(),'message':m.decode()} for c,m in errors],'zero_actual_source_postimages':True,'fix_after_inventory':fix['retention']['inventory'],'git_fields_changed':['index_sha256'],'index_before':pin(idx_before),'index_after':pin(idx_after),'index_entry_count':count,'changed_stat_fields':changed_stat_fields,'only_nine_standard_stat_fields_and_final_sha1_differ':True,'mode_oid_path_flags_stage_padding_and_all_extension_bytes_unchanged':True,'before_index_direct_native_read':False,'before_index_recovery':'Exact complete hash anchored by the original independent before record; one zero-stat candidate, recomputed footer. Root independently compared every changed and invariant byte.','actual_index_writer_identity':'Unknown; command timing and documented Git behavior support an inference, not direct observation.','native_git_version':'Unknown','old_unknown_reclassified':False,'minimal_control_revision':'Set diff.autoRefreshIndex=false only for archive diff; retain original raw Git-state equality gate.','source_ref_updated':False,'maintenance_replayed':False}
(R/'ROOT_MAINTENANCE_FAILURE_AND_INDEX_REVIEW.json').write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
print(json.dumps({'report':pin((R/'ROOT_MAINTENANCE_FAILURE_AND_INDEX_REVIEW.json').read_bytes()),'stdout_intervals':len(intervals),'index_entries':count,'known_fix_returncode':101,'original_overall_status':'UNKNOWN'}))
