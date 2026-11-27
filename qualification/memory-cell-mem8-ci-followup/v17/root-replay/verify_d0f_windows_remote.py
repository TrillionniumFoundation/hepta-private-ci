"""Replay original Windows evidence without running any recorded native command."""
from pathlib import Path,PurePosixPath
import base64
import hashlib
import json
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent
REMOTE=HERE/'d0f-windows-remote'
PREFIX='qualification/memory-cell-mem8-ci-followup/v17/'
def pin(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def read(p):return json.loads(p.read_bytes())
def unwrap(v):
    if 'structuredContent' in v:return unwrap(v['structuredContent'])
    if isinstance(v.get('content'),str):return unwrap(json.loads(v['content']))
    return v
rows=read(HERE/'D0F_WINDOWS_STAGE_OBJECTS.json')
api=read(HERE/'D0F_WINDOWS_API_READBACK.json')
assert api['commit']['sha']=='3328cd562dacf3d4d17b6754778e805356cd508b'
assert api['commit']['tree']['sha']=='a040d50a6b476c2c8c93ec4dea331c5f080488a6'
assert [p['sha'] for p in api['commit']['parents']]==['dc2bc426a057b1128d4e5d50a20368f679afcae1']
verified=[]
for row in rows:
    p=REMOTE/row['path'][len(PREFIX):]
    if row['binary']:
        encoded=Path(str(p)+'.b64').read_text()
        assert set(encoded)<=set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n\t ')
        raw=base64.b64decode(''.join(c for c in encoded if c not in '\r\n\t '),validate=True)
        if p.exists():assert p.read_bytes()==raw
        else:
            with p.open('xb') as stream:stream.write(raw)
    else:raw=p.read_bytes()
    assert pin(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    assert raw==Path(row['local']).read_bytes()
    verified.append({'path':row['path'],**pin(raw),'full_remote_bytes_equal':True})
base=REMOTE/'windows-current-d0f'
pub=read(base/'DELIVERY_PUBLICATION.json')
archive=base/'D0F_WINDOWS_CURRENT_ORIGINAL_COMPLETE.tar.xz'
assert pin(archive.read_bytes())==pub['archive_index']['archive']
out=base/'root-extracted';out.mkdir(exist_ok=True)
manifest={r['path']:r for r in pub['member_manifest']}
with tarfile.open(archive,'r:xz') as tf:
    members=tf.getmembers()
    assert len(members)==len({m.name for m in members})==len(manifest)==41
    assert set(manifest)=={m.name for m in members}
    for m in members:
        p=PurePosixPath(m.name)
        assert m.isfile() and not p.is_absolute() and '..' not in p.parts and '\\' not in m.name
        raw=tf.extractfile(m).read()
        assert pin(raw)=={k:manifest[m.name][k] for k in ('bytes','sha256','git_blob')}
        dest=out/p;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():assert dest.read_bytes()==raw
        else:
            with dest.open('xb') as stream:stream.write(raw)
root_api=read(base/'ROOT_ORIGINAL_API.json')
assert root_api['jobs']==unwrap(read(out/'FULL_TERMINAL_JOBS_API.json'))
captured=unwrap(read(out/'ARTIFACTS_API.json'))['artifacts']
actual=root_api['artifacts']['artifacts']
assert len(captured)==len(actual)==root_api['artifacts']['total_count']==1
for observed, original in zip(actual,captured,strict=True):
    assert all(key in observed and observed[key]==value for key,value in original.items())
assert (out/'records/verify_original.py').read_bytes()==(base/'verify_original.py').read_bytes()
assert pin((out/'records/verify_original.py').read_bytes())==pub['reader']
run=subprocess.run([sys.executable,'-B',str(out/'records/verify_original.py'),str(out/'records')],capture_output=True,timeout=60)
assert run.returncode==0,run.stderr.decode()
assert run.stdout==(out/'AUDIT.json').read_bytes()==(base/'AUDIT.json').read_bytes()
audit=json.loads(run.stdout)
assert audit['job_conclusion']=='cancelled' and audit['terminal_counts']=={'FAIL':1,'PASS':123}
assert audit['terminal_distinct_original_case_ids']==124 and audit['no_observed_terminal_case_count']==43
assert audit['completed_group_receipts']==13 and audit['strict_passing_groups']==12
assert audit['original_final_receipt'] is None and audit['source_after_observation']=='UNOBSERVED_NO_FINAL_RECEIPT'
lock=(HERE/'v10-completed-remote/native-two-preparation/root-extracted-v3/source/codex-rs/Cargo.lock').read_bytes()
assert pin(lock)['git_blob']=='025813e20504f31d12dae2092a0807a1a4066419' and b'\r' not in lock
crlf=lock.replace(b'\n',b'\r\n')
assert pin(crlf)['sha256']==audit['source_before']['cargoLockSha256']
with (base/'ROOT_REMOTE_OFFLINE_REPLAY.json').open('xb') as stream:stream.write(run.stdout)
proof={'schema':'mem8.v17.d0f-windows-current-root-remote-replay.v1','immutable_commit':api['commit']['sha'],'objects':verified,
       'complete_archive':pin(archive.read_bytes()),'complete_members':41,'original_ZIP_members':len(audit['members']),
       'original_ZIP':audit['archive'],'original_full_raw':audit['raw'],'unchanged_reader_exit':run.returncode,
       'full_original_result_bytes_equal':True,'all_original_API_job_steps_and_captured_artifact_fields_equal':True,
       'raw_API_additional_artifact_total_count_and_node_id_retained':True,
       'Cargo_lock_before_checksum':{'source_LF':pin(lock),'derived_CRLF':pin(crlf),'original_Windows_lock_bytes_archived':False,'before_only_no_after_stability_claim':True},
       'original_result':{'job':'cancelled','pass':123,'fail':1,'leak':0,'unobserved_terminals':43,'declared':167,
                          'completed_groups':13,'strict_passing_groups':12,'source_after':'UNOBSERVED_NO_FINAL_RECEIPT'},
       'source':audit['head'],'tree':audit['tree'],'new_native_or_model_executions':0}
(HERE/'ROOT_D0F_WINDOWS_COMPLETE_REMOTE_REPLAY.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'objects':len(verified),'package_members':41,'original_ZIP_members':len(audit['members']),'replay':'PASS_FULL_ORIGINAL_BYTES_UNCHANGED_READER','native_result':proof['original_result']}))
