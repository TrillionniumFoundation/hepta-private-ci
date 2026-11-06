#!/usr/bin/env python3
"""Restore only saved bytes; no network or test execution."""
from pathlib import Path,PurePosixPath
import base64,gzip,hashlib,io,json,sys,tarfile,zipfile,stat
manifest=Path(sys.argv[1]);parts=Path(sys.argv[2]);dest=Path(sys.argv[3])
m=json.loads(manifest.read_bytes())
def ident(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
assert not dest.exists() or not list(dest.iterdir())
dest.mkdir(parents=True,exist_ok=True)
chunks=[]
for p in m['parts']:
 b=(parts/p['file']).read_bytes();assert ident(b)==p['encoded_identity']
 raw=base64.b64decode(b,validate=True);assert ident(raw)==p['decoded_identity'];chunks.append(raw)
archive=b''.join(chunks);assert ident(archive)==m['archive']
expected={x['path']:x for x in m['members']};seen=set()
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:gz') as t:
 for member in t:
  p=PurePosixPath(member.name);assert not p.is_absolute() and '..' not in p.parts and member.isfile()
  assert member.name in expected and member.name not in seen;seen.add(member.name)
  b=t.extractfile(member).read();assert ident(b)==expected[member.name]['identity']
  out=dest.joinpath(*p.parts);out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(b)
assert seen==set(expected)
expanded=0
for item in m['nested_archives']:
 zpath=dest/item['archive_path'];outroot=dest/item['expanded_root'];expected={x['path']:x for x in item['members']};seen=set()
 with zipfile.ZipFile(zpath) as z:
  assert z.testzip() is None
  for info in z.infolist():
   p=PurePosixPath(info.filename);assert not p.is_absolute() and '..' not in p.parts and not stat.S_ISLNK(info.external_attr>>16)
   if info.is_dir():continue
   assert info.filename in expected and info.filename not in seen;seen.add(info.filename)
   b=z.read(info);assert ident(b)==expected[info.filename]['identity']
   q=outroot.joinpath(*p.parts);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b);expanded+=1
  assert seen==set(expected)
print(json.dumps({'schema':'hepta-main92-lossless-restore-v1','archive':m['archive'],'archive_members':len(m['members']),'nested_original_zip_members':expanded,'total_restored_files':len(m['members'])+expanded,'all_bytes_equal':True},indent=2))

