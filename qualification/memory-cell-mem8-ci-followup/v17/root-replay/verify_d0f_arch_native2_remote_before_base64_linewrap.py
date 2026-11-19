"""Verify complete remote packets and replay reviewed offline readers only."""
from pathlib import Path, PurePosixPath
import base64
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
REMOTE = HERE / 'd0f-arch-native2-remote'
PREFIX = 'qualification/memory-cell-mem8-ci-followup/v17/'
HEAD = '8e0b0f9524a7fb037c59a590f871fdeae03d7552'

def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def load(path):
    return json.loads(path.read_bytes())

def dump(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')

def unwrap(obj):
    if 'structuredContent' in obj:
        return unwrap(obj['structuredContent'])
    if isinstance(obj.get('content'),str):
        return unwrap(json.loads(obj['content']))
    return obj

def subset(full, old):
    if isinstance(old,dict):
        for key,value in old.items():
            if key == 'logs_url':
                assert value is None and key not in full
            else:
                assert key in full
                subset(full[key],value)
    elif isinstance(old,list):
        assert len(full)==len(old)
        for a,b in zip(full,old,strict=True): subset(a,b)
    else:
        assert full==old

rows=load(HERE/'D0F_ARCH_NATIVE2_STAGE_OBJECTS.json')
api=load(HERE/'D0F_ARCH_NATIVE2_API_READBACK.json')
assert api['commit']['sha']==HEAD
assert api['commit']['tree']['sha']=='7bd5cebfeb454f0ed772db72da65d22147d35e83'
assert [x['sha'] for x in api['commit']['parents']]==['1eee8836f06b53e185c7dbb1f135ea64001144ba']
verified=[]
for row in rows:
    path=REMOTE/row['path'][len(PREFIX):]
    if row['binary']:
        raw=base64.b64decode(Path(str(path)+'.b64').read_text().strip(),validate=True)
        with path.open('xb') as stream: stream.write(raw)
    else: raw=path.read_bytes()
    assert identity(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    assert raw==Path(row['local']).read_bytes()
    verified.append({'path':row['path'],**identity(raw),'full_remote_bytes_equal':True})

arch=REMOTE/'architecture-d0f'
pub=load(arch/'ACTUAL_PUBLICATION.json')
raw=b''.join((arch/r['path']).read_bytes() for r in pub['parts'])
assert identity(raw)=={k:pub['archive'][k] for k in ('bytes','sha256','git_blob')}
archive=arch/'ROOT_RECONSTRUCTED.tar.xz'
with archive.open('xb') as stream: stream.write(raw)
with tarfile.open(archive,'r:xz') as tf:
    payload={m.name:tf.extractfile(m).read() for m in tf if m.isfile()}
    assert len(payload)==28
    root_api=load(arch/'ROOT_ORIGINAL_API.json')
    assert root_api['jobs']==unwrap(json.loads(payload['ARCH_JOBS_TERMINAL.json']))
    archived_meta=[json.loads(payload[f'artifacts/{a}/MANIFEST.json'])['artifact'] for a in (13873952864,13877116867)]
    actual={a['id']:a for a in root_api['artifacts']['artifacts']}
    for a in archived_meta: subset(actual[a['id']],a)
    for name in ('verify_arch_package.py','audit_arch_complete_original.py','audit_command_receipts.py','audit_completed_records.py','audit_arch_candidate_preflight.py','tree_identity.py'):
        assert payload[name]==(HERE.parent/'mem-ci-d0f-memarch-original'/name).read_bytes()
result=subprocess.run([sys.executable,'-B',str(arch/'verify_arch_package.py'),str(archive)],capture_output=True,timeout=90)
assert result.returncode==0,result.stderr.decode()
assert result.stdout==(arch/'OFFLINE_PACKAGE_REPLAY.json').read_bytes()
with (arch/'ROOT_REMOTE_OFFLINE_REPLAY.json').open('xb') as stream: stream.write(result.stdout)

two=REMOTE/'native-two-d0f'
pub2=load(two/'DELIVERY_PUBLICATION.json')
archive2=two/'TWO_NATIVE_ORIGINAL_COMPLETE.tar.xz'
assert identity(archive2.read_bytes())=={k:pub2['archive'][k] for k in ('bytes','sha256','git_blob')}
work=two/'root-recovery'
extract=work/'original'
extract.mkdir(parents=True,exist_ok=False)
with tarfile.open(archive2,'r:xz') as tf:
    members=tf.getmembers()
    assert len(members)==52 and len({m.name for m in members})==52
    manifest={r['path']:r for r in pub2['members']}
    assert set(manifest)=={m.name for m in members}
    for member in members:
        path=PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts and '\\' not in member.name
        raw=tf.extractfile(member).read()
        assert identity(raw)=={k:manifest[member.name][k] for k in ('bytes','sha256','git_blob')}
        dest=extract/path
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as stream: stream.write(raw)
prereq=HERE/'v10-completed-remote/native-two-preparation/root-extracted-v3/preparation/rendered-d0f6507'
prereq_rows=[]
for path in ['.github/scripts/mem_native_subagent.py','.github/scripts/mem_native_subagent_support.py','.github/workflows/hepta-mem-native-subagent.yml','.github/fixtures/mem-native-subagent-plan.json']:
    raw=(prereq/path).read_bytes()
    assert raw==(HERE.parent/'mem-two-native-harness-preparation/rendered-d0f6507'/path).read_bytes()
    dest=work/'mem-two-native-harness-preparation/rendered-d0f6507'/path
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open('xb') as stream: stream.write(raw)
    prereq_rows.append({'path':path,**identity(raw),'origin':'v17/native-two-preparation original frozen complete archive, prior root full remote replay'})
assert (extract/'FROZEN_PLAN.json').read_bytes()==(prereq/'.github/fixtures/mem-native-subagent-plan.json').read_bytes()
root_api=load(two/'ROOT_ORIGINAL_API.json')
subset(root_api['jobs'],unwrap(load(extract/'TERMINAL_JOBS.json')))
subset(root_api['artifacts'],unwrap(load(extract/'ARTIFACT_METADATA.json')))
assert root_api['jobs']['jobs'][0]['head_sha']=='ca9ab8c0d07d1a236ef3c4b76a22f0a131d409ae'
assert root_api['jobs']['jobs'][0]['conclusion']=='success'
for name in ['audit_original.py','audit_snapshot_proofs_v2.py']:
    assert (extract/name).read_bytes()==(two/name).read_bytes()
out=extract/'root-replay'
cmd=[sys.executable,'-B',str(extract/'audit_original.py'),'--zip',str(extract/'ORIGINAL_ARTIFACT.zip'),'--output',str(out)]
result2=subprocess.run(cmd,capture_output=True,timeout=60)
assert result2.returncode==0,result2.stderr.decode()
old=load(extract/'readback/INDEPENDENT_AUDIT.json')
new=load(out/'INDEPENDENT_AUDIT.json')
old_observed=old.pop('observed_at'); new_observed=new.pop('observed_at')
assert old==new and new['qualification']=='PASS_TWO_NATIVE_AND_ONE_CLEAN_FIX'
assert (out/'ZIP_MEMBER_AUDIT.json').read_bytes()==(extract/'readback/ZIP_MEMBER_AUDIT.json').read_bytes()
snapshot=extract/'ROOT_SOURCE_SNAPSHOT_REPLAY.json'
result3=subprocess.run([sys.executable,'-B',str(extract/'audit_snapshot_proofs_v2.py'),'--files',str(out/'files'),'--output',str(snapshot)],capture_output=True,timeout=60)
assert result3.returncode==0,result3.stderr.decode()
assert snapshot.read_bytes()==(extract/'SOURCE_SNAPSHOT_AUDIT_V2.json').read_bytes()
summary={'schema':'mem8.v17.d0f-architecture-native-two-root-remote-replay.v1','immutable_commit':HEAD,'objects':verified,
         'architecture':{'complete_members':28,'original_reader_exit':result.returncode,'full_original_result_bytes_equal':True,'result':json.loads(result.stdout),'full_original_API_and_artifact_fields_bound':True},
         'native_two':{'complete_members':52,'original_reader_exit':result2.returncode,'original_qualification':new['qualification'],
                       'all_original_result_fields_equal_except_observer_timestamp':True,'old_observed_at':old_observed,'new_observed_at':new_observed,
                       'original_ZIP_audit_byte_equal':True,'all_73_snapshot_checks_and_result_bytes_equal':True,
                       'source':new['source_head'],'tree':new['source_tree'],'cases':new['independently_qualified_native_cases'],
                       'clean_lint_packages':new['clean_scoped_fix_packages'],'restored_unchanged_frozen_harness_dependencies':prereq_rows,
                       'API_normalized_projection_boundary':'All captured fields compare; tool-only logs_url:null is explicitly not a raw GitHub field.'},
         'new_native_or_model_executions':0}
dump(HERE/'ROOT_D0F_ARCH_NATIVE2_REMOTE_REPLAY.json',summary)
print(json.dumps({'objects':len(verified),'architecture':summary['architecture']['result']['status'],'two_native':new['qualification'],'snapshot_checks':len(load(snapshot)['checks'])}))
