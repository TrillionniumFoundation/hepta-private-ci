"""Deduplicate identical inference arrays and reconstruct the original per-parent NumPy archives byte for byte."""
import argparse
import hashlib
import io
import json
import shutil
from pathlib import Path
import numpy as np


def digest(bytes_):
    return hashlib.sha256(bytes_).hexdigest()


def pack(source,dest):
    dest.mkdir(parents=True,exist_ok=True)
    values=dest/'arrays';values.mkdir(exist_ok=True)
    entries={};aliases=0
    for f in sorted(source.iterdir()):
        if not f.is_file():continue
        encoded=f.read_bytes()
        if f.suffix!='.npz':
            if f.suffix=='.json':
                shutil.copyfile(f,dest/f.name)
                entries[f.name]={'sha':digest(encoded),'copied':True}
            continue
        members=[]
        with np.load(f,allow_pickle=False) as obs:
            for name in obs.files:
                buf=io.BytesIO();np.save(buf,obs[name],allow_pickle=False);v=buf.getvalue();key=digest(v)
                part=values/(key+'.npy')
                if not part.exists():part.write_bytes(v)
                else:aliases+=1
                members.append([name,key])
        entries[f.name]={'sha':digest(encoded),'members':members}
    (dest/'schema.json').write_text(json.dumps({'entries':entries,'duplicate_arrays':aliases,'version':np.__version__},indent=1)+'\n')


def restore(encoded,dest):
    if dest.exists() and list(dest.iterdir()):raise FileExistsError(dest)
    dest.mkdir(parents=True,exist_ok=True)
    meta=json.loads((encoded/'schema.json').read_text())
    for name,rec in meta['entries'].items():
        if Path(name).name!=name:raise ValueError(name)
        target=dest/name
        if rec.get('copied'):
            shutil.copyfile(encoded/name,target)
        else:
            record={}
            for key,value in rec['members']:
                v=(encoded/'arrays'/(value+'.npy')).read_bytes()
                assert digest(v)==value
                record[key]=np.load(io.BytesIO(v),allow_pickle=False)
            np.savez_compressed(target,**record)
        assert digest(target.read_bytes())==rec['sha'],name


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('pack','restore'))
    p.add_argument('source',type=Path);p.add_argument('dest',type=Path)
    a=p.parse_args();(pack if a.mode=='pack' else restore)(a.source,a.dest)
