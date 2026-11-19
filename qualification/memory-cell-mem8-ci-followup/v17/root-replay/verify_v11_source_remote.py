"""Recover the complete remotely retained V11 original and run only offline readers."""
from pathlib import Path,PurePosixPath
import base64
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile

HERE=Path(__file__).resolve().parent
REMOTE=HERE/'v11-source-remote'
PREFIX='qualification/memory-cell-mem8-ci-followup/v17/'

def pin(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def load(p): return json.loads(p.read_bytes())

rows=load(HERE/'V11_SOURCE_STAGE_OBJECTS.json')
api=load(HERE/'V11_SOURCE_API_READBACK.json')
assert api['commit']['sha']=='b5c5c0fbc594e7aa31b979b1f1c35eb690fedee1'
assert api['commit']['tree']['sha']=='3f4fe9126172e1f30fd303dbcd41a783887736bc'
assert [r['sha'] for r in api['commit']['parents']]==['8e0b0f9524a7fb037c59a590f871fdeae03d7552']
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
source=REMOTE/'source-v11'
pub=load(source/'DELIVERY_PUBLICATION.json')
pieces=pub['actual_part_publication']['parts']
raw=b''
for row in pieces:
    assert row['offset']==len(raw)
    part=(source/row['path']).read_bytes()
    assert pin(part)=={k:row[k] for k in ('bytes','sha256','git_blob')}
    raw+=part
assert len(pieces)==13 and pin(raw)==pub['archive_index']['archive']
archive=source/'ROOT_RECONSTRUCTED.tar.xz'
with archive.open('xb') as stream:stream.write(raw)
out=source/'root-extracted'
out.mkdir(exist_ok=False)
with tarfile.open(archive,'r:xz') as tf:
    members=tf.getmembers()
    assert len(members)==62 and len({m.name for m in members})==62
    manifest={r['path']:r for r in pub['member_manifest']}
    assert set(manifest)=={m.name for m in members}
    for member in members:
        path=PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts and '\\' not in member.name
        data=tf.extractfile(member).read()
        assert pin(data)=={k:manifest[member.name][k] for k in ('bytes','sha256','git_blob')}
        dest=out/path;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as stream:stream.write(data)
for name in ('materialize_original.py','verify_source_records_v11.py'):
    assert (out/name).read_bytes()==(source/name).read_bytes()
    assert pin((out/name).read_bytes())==pub['reader_identities'][name]
assert pin((out/'ORIGINAL_ARTIFACT.zip').read_bytes())==pub['archive_index']['original_zip']
assert (source/'root/ROOT_SOURCE_GATE_AUDIT.json').read_bytes()==(HERE.parent/'mem8-source-v11-preparation/ROOT_SOURCE_GATE_AUDIT.json').read_bytes()
with tempfile.TemporaryDirectory(prefix='mem-v11-remote-root-') as tmp:
    materialized=Path(tmp)/'readback'
    first=subprocess.run([sys.executable,'-B',str(out/'materialize_original.py'),'--zip',str(out/'ORIGINAL_ARTIFACT.zip'),'--output',str(materialized)],capture_output=True,timeout=60)
    assert first.returncode==0,first.stderr.decode()
    canonical=materialized/'canonical-original'
    second=subprocess.run([sys.executable,'-B',str(out/'verify_source_records_v11.py'),str(canonical)],capture_output=True,timeout=60)
    assert second.returncode==0,second.stderr.decode()
    replay=(canonical/'OFFLINE_VERIFICATION.json').read_bytes()
    assert replay==(out/'readback/canonical-original/OFFLINE_VERIFICATION.json').read_bytes()==(source/'ROOT_REMOTE_OFFLINE_VERIFICATION.json').read_bytes()
    archive_info=load(canonical/'ARCHIVE_INFO.json')
    zip_audit=load(materialized/'ZIP_FULL_MEMBER_AUDIT.json')
    tar_audit=load(materialized/'CANONICAL_ARCHIVE_MATERIALIZATION.json')
    assert zip_audit['member_count']==386 and tar_audit['tar_members']==387
    assert len(tar_audit['direct_zip_omitted_paths'])==9
    result=json.loads(replay)
    assert result['formatter_changed_paths']==[] and result['source_after_status']==''
    assert result['source_python_actual_pass']==18 and result['rust_files_scanned']==6204
    assert result['formatted_tree']=='27651abb15e269c427c75f28f92a3bd1cd9d191f'
    with (source/'ROOT_COMPLETE_REMOTE_REPLAY.json').open('xb') as stream:stream.write(replay)
proof={'schema':'mem8.v17.v11-source-root-full-remote-replay.v1','immutable_commit':api['commit']['sha'],
       'objects':verified,'complete_archive':pin(raw),'complete_package_members':62,'parts':13,
       'original_ZIP':pub['archive_index']['original_zip'],'original_ZIP_members':386,
       'canonical_tar':archive_info,'canonical_manifest_rows':386,'expanded_hidden_members_restored_from_original_tar':9,
       'materializer_exit':first.returncode,'unchanged_verifier_exit':second.returncode,
       'full_original_result_bytes_equal':True,'source':result['source_head_unchanged'],'tree':result['formatted_tree'],
       'source_after_clean':True,'formatter_changed_paths':[],'native_tests_or_model_executions':0}
(HERE/'ROOT_V11_SOURCE_COMPLETE_REMOTE_REPLAY.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'objects':len(verified),'members':62,'source_gate':'PASS_FULL_COMPLETE_REMOTE_REPLAY','native_or_model_executions':0}))
