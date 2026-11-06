"""Freeze complete retained format-failure evidence plus independent review, losslessly."""
from pathlib import Path
import base64
import hashlib
import io
import json
import lzma
import subprocess
import sys
import tarfile

E=Path(__file__).resolve().parent
C=E/'fmt-candidate-127779715942'
I=E.parent/'holdout-fmt-independent-20261106'
D=E/'fmt-evidence-delivery'
D.mkdir(exist_ok=False)
def identity(b):
    return {'bytes':len(b),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),'sha256':hashlib.sha256(b).hexdigest()}
def dump(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
members={}
f=json.loads((C/'FREEZE.json').read_bytes())
for row in f['files']:
    b=(C/row['path']).read_bytes()
    assert identity(b)=={k:row[k] for k in ['bytes','git_blob','sha256']}
    members['author/candidate/'+row['path']]=b
members['author/candidate/FREEZE.json']=(C/'FREEZE.json').read_bytes()
for name in ['build_fmt_candidate.py','fmt-build-01.stdout.json','fmt-build-01.stderr.txt']:
    members['author/'+name]=(E/name).read_bytes()
f=json.loads((I/'DELIVERY-MANIFEST.json').read_bytes())
for row in f['files']:
    b=(I/row['path']).read_bytes()
    assert identity(b)=={k:row[k] for k in ['bytes','git_blob','sha256']}
    members['independent/'+row['path']]=b
members['independent/DELIVERY-MANIFEST.json']=(I/'DELIVERY-MANIFEST.json').read_bytes()
for name in ['blocking-42180997764-jobs-sixth.original.json','head-2d1137-runs-third.original.json']:
    members['ci-increment/'+name]=(E/name).read_bytes()
member_manifest={name:identity(b) for name,b in sorted(members.items())}
stream=io.BytesIO()
with tarfile.open(fileobj=stream,mode='w',format=tarfile.PAX_FORMAT) as archive:
    for name,b in sorted(members.items()):
        info=tarfile.TarInfo(name);info.size=len(b);info.mode=0o644;info.mtime=0;info.uid=info.gid=0;info.uname=info.gname=''
        archive.addfile(info,io.BytesIO(b))
tarbytes=stream.getvalue()
packed=lzma.compress(tarbytes,format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,preset=6)
(D/'evidence.original.tar.xz').write_bytes(packed)
partdir=D/'parts';partdir.mkdir()
encoded=base64.b64encode(packed)
parts=[]
for i,start in enumerate(range(0,len(encoded),60000)):
    b=encoded[start:start+60000]+b'\n';name=f'parts/archive.part-{i:03d}.base64.txt';(D/name).write_bytes(b)
    parts.append({'path':name,**identity(b)})
assert lzma.decompress(base64.b64decode(b''.join((D/p['path']).read_bytes().strip() for p in parts),validate=True))==tarbytes
restored=D/'portable-restored';restored.mkdir()
with tarfile.open(fileobj=io.BytesIO(packed),mode='r:xz') as archive:
    assert len(archive.getmembers())==len(members)
    for m in archive:
        assert m.isfile() and m.name in members
        b=archive.extractfile(m).read();assert b==members[m.name]
        p=restored/m.name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
run=subprocess.run([sys.executable,str(restored/'independent/verify_candidate.py'),str(restored/'author/candidate')],
    stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
(D/'portable-replay.stdout.json').write_bytes(run.stdout)
(D/'portable-replay.stderr.txt').write_bytes(run.stderr)
assert run.returncode==0 and not run.stderr and run.stdout==members['independent/replay-01.stdout.json']
manifest={'schema':'holdout-native-fmt-complete-evidence-archive-v1','archive':identity(packed),'tar':identity(tarbytes),
          'format':'tar.xz, lossless XZ CRC64; deterministic tar headers','member_count':len(members),
          'member_bytes':sum(len(b) for b in members.values()),'members':member_manifest,'parts':parts,
          'independent_review_actual_blob':'7ea9cb737a8c57a215cbf473b2ad100c25ab668b',
          'candidate_tree':'c3e9ddc1799f470ac7c80e117ee953a7232847e0',
          'original_failed_source':'a0cb0f33661e199674012e3302b0602407c91a8d',
          'original_job':127779715942,'original_job_conclusion':'failure',
          'portable_replay':{'exit':run.returncode,'stdout':identity(run.stdout),'stderr':identity(run.stderr),'all_stdout_bytes_equal':True},
          'qualification':'Only exact original formatter whitespace candidate accepted. No product/Rust/native/format success transferred.'}
dump(D/'archive-manifest.json',manifest)
dump(D/'PORTABLE_VERIFICATION.json',{'archive':identity(packed),'all_member_bytes_equal':True,'members':len(members),
    'all_original_author_and_independent_freeze_members_included':True,'independent_replay':manifest['portable_replay'],
    'no_Rust_native_CI_or_ref_operation':True})
print(json.dumps({k:v for k,v in manifest.items() if k not in ['members','parts']},ensure_ascii=False,indent=2))
