"""Pack or restore immutable evidence, deduplicating byte-identical NPZ records."""
import argparse
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path


def digest(b):return hashlib.sha256(b).hexdigest()


def chunks(path,data):
    if path.suffix!='.npz':return [data]
    blocks=[]
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for item in z.infolist():
            h=item.header_offset
            nl,ex=struct.unpack_from('<HH',data,h+26)
            start=h+30+nl+ex;size=item.compress_size
            blocks.extend((data[h:start],data[start:start+size]))
            # NumPy writes local headers with known CRC/size, no stream descriptor.
            assert not item.flag_bits&8
        blocks.append(data[z.start_dir:])
    assert b''.join(blocks)==data
    return blocks


def pack(src,dst):
    unique={};files={}
    for p in sorted(src.rglob('*')):
        if not p.is_file():continue
        b=p.read_bytes();parts=[]
        for block in chunks(p,b):
            key=digest(block);parts.append(key);unique[key]=block
        files[str(p.relative_to(src))]={'sha256':digest(b),'chunks':parts}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for key,b in sorted(unique.items()):z.writestr(key,b)
    data=stream.getvalue();index={'sha256':digest(data),'files':files,'parts':[]}
    for n,start in enumerate(range(0,len(data),384*1024)):
        b=data[start:start+384*1024];name=f'gas-evidence-{n:03}.bin';(dst/name).write_bytes(b)
        index['parts'].append({'name':name,'sha256':digest(b),'bytes':len(b)})
    (dst/'gas_evidence_index.json').write_text(json.dumps(index,indent=1,sort_keys=True)+'\n')
    print(len(files),'files',len(unique),'unique chunks',len(data),'bytes',len(index['parts']),'parts',index['sha256'])


def restore(src,dst):
    if dst.exists() and any(dst.iterdir()):raise FileExistsError('choose an empty destination')
    index=json.loads((src/'gas_evidence_index.json').read_bytes());raw=[]
    for part in index['parts']:
        b=(src/part['name']).read_bytes();assert digest(b)==part['sha256'] and len(b)==part['bytes'];raw.append(b)
    stream=b''.join(raw);assert digest(stream)==index['sha256']
    with zipfile.ZipFile(io.BytesIO(stream)) as z:
        for name,meta in index['files'].items():
            p=(dst/name).resolve();assert p.is_relative_to(dst.resolve())
            b=b''.join(z.read(k) for k in meta['chunks']);assert digest(b)==meta['sha256']
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
    print('verified and reconstructed',len(index['files']),'files')


if __name__=='__main__':
    q=argparse.ArgumentParser();q.add_argument('operation',choices=('pack','restore'));q.add_argument('source',type=Path);q.add_argument('destination',type=Path);a=q.parse_args();(pack if a.operation=='pack' else restore)(a.source,a.destination)
