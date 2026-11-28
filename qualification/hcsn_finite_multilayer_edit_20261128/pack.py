"""Losslessly archive immutable evidence, split for ordinary Git, and verify each byte before extraction."""
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path
def digest(data):return hashlib.sha256(data).hexdigest()
def create(root,parts,pattern):
    parts.mkdir(parents=True,exist_ok=True)
    paths=sorted(f for f in root.rglob(pattern) if f.is_file())
    if not paths:raise ValueError('empty evidence directory')
    members={};buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for f in paths:
            name=f.relative_to(root).as_posix();blob=f.read_bytes()
            member=zipfile.ZipInfo(name,(2026,11,28,0,0,0));member.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(member,blob);members[name]=[len(blob),digest(blob)]
    contents=buf.getvalue();items=[]
    for off in range(0,len(contents),262144):
        data=contents[off:off+262144];name=f'{len(items):04d}.part';(parts/name).write_bytes(data);items.append([name,len(data),digest(data)])
    info=dict(archive_bytes=len(contents),archive_sha256=digest(contents),members=members,parts=items)
    (parts/'manifest.json').write_text(json.dumps(info,indent=2,sort_keys=True)+'\n');return info
def restore(parts,dest):
    meta=json.loads((parts/'manifest.json').read_text());payload=bytearray()
    if dest.exists() and any(dest.iterdir()):raise FileExistsError(dest)
    for name,n,h in meta['parts']:
        if Path(name).name!=name:raise ValueError(name)
        buf=(parts/name).read_bytes();assert len(buf)==n and digest(buf)==h;payload+=buf
    assert len(payload)==meta['archive_bytes'] and digest(payload)==meta['archive_sha256']
    with zipfile.ZipFile(io.BytesIO(payload)) as f:
        assert set(f.namelist())==set(meta['members'])
        for name,(size,h) in meta['members'].items():
            path=Path(name);assert not path.is_absolute() and '..' not in path.parts
            data=f.read(name);assert len(data)==size and digest(data)==h
            out=dest/path;out.parent.mkdir(exist_ok=True,parents=True);out.write_bytes(data)
    return meta
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['create','restore']);p.add_argument('source',type=Path);p.add_argument('dest',type=Path);p.add_argument('--pattern',default='*');a=p.parse_args()
    m=create(a.source,a.dest,a.pattern) if a.action=='create' else restore(a.source,a.dest);print(len(m['members']),len(m['parts']),m['archive_bytes'],m['archive_sha256'])
