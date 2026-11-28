"""Retrieve the authors' fixed raw archive, verifying each HTTP range and final published SHA."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import requests
import sys
import time
import urllib.parse
ROOT=Path(sys.argv[1]).resolve()
ROOT.mkdir(exist_ok=True,parents=True)
NAME='MELD.Raw.tar.gz'
BASE='https://huggingface.co'
meta=requests.get(BASE+'/api/datasets/declare-lab/MELD/tree/main',params=dict(expand='true'),timeout=40);meta.raise_for_status()
entry=next(e for e in meta.json() if e['path']==NAME)
digest=entry['lfs']['oid'];size=entry['size']
assert len(digest)==64 and size==10878146150
u=BASE+'/datasets/declare-lab/MELD/resolve/main/'+NAME
sizepart=16*1024*1024;parts=ROOT/'parts';parts.mkdir(exist_ok=True)
def get(i):
    first=i*sizepart;last=min(size-1,first+sizepart-1);p=parts/f'{i:04d}.part'
    if p.exists() and p.stat().st_size==last-first+1:return
    failures=[]
    for k in range(7):
        try:
            # Distinct range URLs prevent reuse of an intermediary's cached partial entity.
            url=u+'?download=true&range='+str(i)
            with requests.get(url,headers={'Range':f'bytes={first}-{last}','Accept-Encoding':'identity'},stream=True,timeout=(30,140)) as r:
                r.raise_for_status()
                assert r.status_code==206 and r.headers['Content-Range']==f'bytes {first}-{last}/{size}',(r.status_code,r.headers.get('Content-Range'))
                tmp=p.with_suffix('.partial')
                with tmp.open('wb') as f:
                    for block in r.iter_content(524288):f.write(block)
                assert tmp.stat().st_size==last-first+1
                os.replace(tmp,p)
            return
        except Exception as exc:
            failures.append(str(exc)[:140]);time.sleep(min(35,2*(k+1)))
    raise RuntimeError((i,failures))
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
dest=ROOT/NAME
if not dest.exists():
    start=time.perf_counter();indices=list(range((size+sizepart-1)//sizepart))
    with concurrent.futures.ThreadPoolExecutor(4) as ex:
        for n,_ in enumerate(ex.map(get,indices),1):
            if n==1 or n%20==0:print('complete ranges',n,len(indices),'seconds',time.perf_counter()-start,flush=True)
    trial=dest.with_suffix('.staging')
    import shutil
    with trial.open('wb') as f:
        for i in indices:
            with (parts/f'{i:04d}.part').open('rb') as piece:shutil.copyfileobj(piece,f,1024*1024)
    assert trial.stat().st_size==size and sha(trial)==digest
    os.replace(trial,dest)
    for i in indices:(parts/f'{i:04d}.part').unlink()
assert dest.stat().st_size==size and sha(dest)==digest
(ROOT/'ACQUIRED.json').write_text(json.dumps(dict(source=u,bytes=size,sha256=digest,complete_at=time.time()),indent=2)+'\n')
print('verified archive',digest,size,flush=True)
