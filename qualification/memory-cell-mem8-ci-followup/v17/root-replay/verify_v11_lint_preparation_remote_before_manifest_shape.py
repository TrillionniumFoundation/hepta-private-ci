"""Restore immutable preparation bytes and execute its reviewed offline reader."""
from pathlib import Path,PurePosixPath
import base64
import hashlib
import json
import subprocess
import sys
import tarfile

HERE=Path(__file__).resolve().parent
REMOTE=HERE/'v11-lint-prep-remote'
PREFIX='qualification/memory-cell-mem8-ci-followup/v17/'
def pin(raw):return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}
def read(p):return json.loads(p.read_bytes())
rows=read(HERE/'V11_LINT_PREPARATION_STAGE_OBJECTS.json')
api=read(HERE/'V11_LINT_PREP_API_READBACK.json')
assert api['commit']['sha']=='dc2bc426a057b1128d4e5d50a20368f679afcae1'
assert api['commit']['tree']['sha']=='2d5d815a7cd457eb03bcc01a880d156fcd0272df'
assert [r['sha'] for r in api['commit']['parents']]==['b5c5c0fbc594e7aa31b979b1f1c35eb690fedee1']
verified=[]
for row in rows:
    path=REMOTE/row['path'][len(PREFIX):]
    if row['binary']:
        encoded=Path(str(path)+'.b64').read_text()
        assert set(encoded)<=set('ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n\t ')
        raw=base64.b64decode(''.join(c for c in encoded if c not in '\r\n\t '),validate=True)
        with path.open('xb') as stream:stream.write(raw)
    else:raw=path.read_bytes()
    assert pin(raw)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    assert raw==Path(row['local']).read_bytes()
    verified.append({'path':row['path'],**pin(raw),'full_remote_bytes_equal':True})
base=REMOTE/'windows-fix-v11-preparation'
pub=read(base/'ACTUAL_PUBLICATION.json')
raw=b''.join((base/r['name']).read_bytes() for r in pub['parts'])
assert pin(raw)=={'bytes':pub['archive']['bytes'],'sha256':pub['archive']['sha256'],'git_blob':pub['archive']['git_blob_computed_only']}
archive=base/'ROOT_RECONSTRUCTED.tar.xz'
with archive.open('xb') as stream:stream.write(raw)
out=base/'root-extracted';out.mkdir(exist_ok=False)
manifest=read(base/'PACKAGE_MEMBER_MANIFEST.json')
entries=manifest['members'] if isinstance(manifest,dict) else manifest
by_path={r['path']:r for r in entries}
with tarfile.open(archive,'r:xz') as tf:
    members=tf.getmembers()
    assert len(members)==67 and len({m.name for m in members})==67
    assert {m.name for m in members}==set(by_path)
    for member in members:
        path=PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts and '\\' not in member.name
        data=tf.extractfile(member).read()
        assert pin(data)=={k:by_path[member.name][k] for k in ('bytes','sha256','git_blob')}
        dest=out/path;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as stream:stream.write(data)
assert (out/'verify_preparation.py').read_bytes()==(base/'verify_preparation.py').read_bytes()
result=subprocess.run([sys.executable,'-B',str(out/'verify_preparation.py'),str(out)],capture_output=True,timeout=60)
assert result.returncode==0,result.stderr.decode()
assert result.stdout==(base/'OFFLINE_PREPARATION_AUDIT.json').read_bytes()
with (base/'ROOT_REMOTE_OFFLINE_REPLAY.json').open('xb') as stream:stream.write(result.stdout)
spec=read(out/'FINAL_FOUR_OBJECT_SPEC.json')
commit=read(out/'HARNESS_COMMIT_READBACK.json')
assert commit['sha']=='fe824cce50037071ff559e1aabdf36f9d5954908' and commit['tree']['sha']==spec['expected_harness_tree']=='ac382f3fc9989017ad77ed64e07b02e1e42cb5cc'
assert [p['sha'] for p in commit['parents']]==['ceadcb3b11dbd94a9d07afb7e6301555e4ff3f80']
for entry in spec['tree_elements']:
    assert (out/'rendered'/entry['path']).read_bytes()==(out/'root-remote'/entry['path']).read_bytes()
    assert pin((out/'rendered'/entry['path']).read_bytes())['git_blob']==entry['sha']
proof={'schema':'mem8.v17.v11-lint-preparation-root-remote-replay.v1','immutable_commit':api['commit']['sha'],'objects':verified,
       'archive':pin(raw),'complete_members':67,'original_reader_exit':0,'full_original_reader_result_bytes_equal':True,
       'all_20_full_source_dependencies_inside_and_verified':True,'nine_provisional_members_and_final_delta_preserved':True,
       'root_single_actual_admission_and_full_remote_harness_bytes_recovered':True,'harness':commit['sha'],'harness_tree':commit['tree']['sha'],
       'source':spec['source_head'],'source_tree':spec['source_tree'],'preparation_result':json.loads(result.stdout),
       'original_lint_run_results_included':False,'new_native_or_model_executions':0}
(HERE/'ROOT_V11_LINT_PREPARATION_REMOTE_REPLAY.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'objects':len(verified),'complete_members':67,'result':'PASS_COMPLETE_REMOTE_PREPARATION_REPLAY','new_native_or_model_executions':0}))
