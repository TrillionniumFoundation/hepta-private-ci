"""Losslessly package/restore the selected model weights or independently scored evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile


def file_sha(p):
    h=hashlib.sha256()
    with p.open('rb') as fp:
        for b in iter(lambda:fp.read(2**20),b''):h.update(b)
    return h.hexdigest()


def pack(src,dest,kind,mi):
    dest.mkdir(parents=True,exist_ok=True)
    base={'SEAL.json':src/'SEAL.json','data/data.json':src/'data/data.json','data/standardization.npz':src/'data/standardization.npz','data/test.npz':src/'data/test.npz','law_check.json':src/'law_check.json','parameter_counts.json':src/'parameter_counts.json','remote_seal_receipt.json':src/'remote_seal_receipt.json'}
    if kind=='weights':paths={'models/'+p.name:p for p in (src/'models').glob('*.pt')}
    else:
        paths=base;paths.update({'result/'+p.name:p for p in (src/'result').glob('*.json')})
        paths.update({'models/'+p.name:p for p in (src/'models').glob('*.json')})
        paths.update({'cold/'+p.name:p for p in (src/'cold').iterdir() if p.is_file()})
    seal=json.loads((src/'SEAL.json').read_bytes())
    if kind=='weights':assert {p.name for p in paths.values()}==set(seal['weights'])
    index={'kind':kind,'files':{},'parts':[]}
    with tempfile.TemporaryDirectory(dir=src) as tmp:
        zfile=Path(tmp)/'payload.zip'
        with zipfile.ZipFile(zfile,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4,allowZip64=True) as z:
            for name,path in sorted(paths.items()):
                assert path.is_file();digest=file_sha(path)
                if path.name.endswith('.pt'):assert digest==seal['weights'][path.name]
                if path.parent.name=='models' and path.suffix=='.json':assert digest==seal['fits'][path.name]
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                with path.open('rb') as f,z.open(info,'w') as w:
                    for b in iter(lambda:f.read(2**20),b''):w.write(b)
                index['files'][name]={'sha256':digest,'bytes':path.stat().st_size}
        index['archive_sha256']=file_sha(zfile);index['archive_bytes']=zfile.stat().st_size
        with zfile.open('rb') as f:
            for num,part in enumerate(iter(lambda:f.read(mi*1024*1024),b'')):
                name=f'{kind}-{num:03}.bin';out=dest/name;out.write_bytes(part)
                index['parts'].append({'file':name,'bytes':len(part),'sha256':hashlib.sha256(part).hexdigest()})
    (dest/f'{kind}_index.json').write_text(json.dumps(index,indent=1,sort_keys=True)+'\n')
    print(kind,len(paths),'objects',index['archive_bytes'],'bytes',len(index['parts']),'parts',index['archive_sha256'],flush=True)


def restore(src,dest,kind):
    d=json.loads((src/f'{kind}_index.json').read_bytes());dest.mkdir(exist_ok=True,parents=True)
    with tempfile.TemporaryDirectory(dir=dest) as tmp:
        zpath=Path(tmp)/'source.zip'
        with zpath.open('wb') as t:
            for part in d['parts']:
                path=src/part['file'];assert path.stat().st_size==part['bytes'] and file_sha(path)==part['sha256']
                with path.open('rb') as f:
                    for b in iter(lambda:f.read(2**20),b''):t.write(b)
        assert zpath.stat().st_size==d['archive_bytes'] and file_sha(zpath)==d['archive_sha256']
        with zipfile.ZipFile(zpath) as z:
            assert set(z.namelist())==set(d['files'])
            for name,record in d['files'].items():
                path=(dest/name).resolve();assert path.is_relative_to(dest.resolve());path.parent.mkdir(parents=True,exist_ok=True)
                if not path.exists():
                    with z.open(name) as f,path.open('xb') as out:
                        for b in iter(lambda:f.read(2**20),b''):out.write(b)
                assert file_sha(path)==record['sha256'] and path.stat().st_size==record['bytes']
    print('restored',kind,len(d['files']),flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('cmd',choices=('pack','restore'));a.add_argument('source',type=Path);a.add_argument('destination',type=Path);a.add_argument('kind',choices=('evidence','weights'));a.add_argument('--part-mib',type=int,default=2);p=a.parse_args()
    if p.cmd=='pack':pack(p.source,p.destination,p.kind,p.part_mib)
    else:restore(p.source,p.destination,p.kind)
