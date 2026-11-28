"""Fetch versioned RSICD/UCM inputs and reproduce the historical RSICD pixel roster directly."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib,io,json,os,re,time
from pathlib import Path
import urllib.request

import numpy as np
from PIL import Image
import pyarrow.parquet as pq

RSBASE='https://huggingface.co/datasets/arampacha/rsicd/resolve/820466c8716e3ccdacde5cb2eb15a2f0f11ccdfe/data'
RSCAP='https://raw.githubusercontent.com/201528014227051/RSICD_optimal/fc33b4555e4baa4d2f05ff0449479c89da2eeac2/dataset_rsicd.json'
UCBASE='https://huggingface.co/datasets/caglarmert/UCM-captions/resolve/393e3704f8b004c6878407280e24e3e09632005b/data'
RSHASH={'train':'637ce48273746c9a9bc7ea65f84bdcc0173257243f5ab6ae3258e013b58f8310','valid':'06ef6d6a455a0c80667e93e490a0e9603ded172c45106c67bcaa4997fa865b91','test':'e707fd90b59fe22a9a222d48b969226715f3eccf78e2b0f382f0a5565a98acda'}
UCHASH={'train':'bb9884ae4a0aadeaf3a244f7ef4d7f290544415b7b085d7e07020584d3242fca','validation':'331019cc6bdb1288c466da204bfeef80edabec0f7d120de48894056b736adc45','test':'2bfc7b1c1d38fdfc6b6c6b8b8435c570b6b3b39e678855e5281e32c7b1822da9'}
AUTH='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede'
EXPECTED={'rows.json':'80c9f4256fef2cf37031660858dd90f07d1bb554535a0545a46e744d00f508d2','pixels32.npy':'d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1'}


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def get(item):
    path,url,want=item;path.parent.mkdir(exist_ok=True,parents=True)
    if path.is_file() and digest(path)==want:return
    for i in range(3):
        tmp=path.with_suffix(path.suffix+'.partial')
        try:
            with urllib.request.urlopen(url,timeout=60) as server,tmp.open('wb') as f:
                while b:=server.read(1<<20):f.write(b)
            assert digest(tmp)==want
            os.replace(tmp,path);return
        except (OSError,AssertionError):
            if i==2:raise
            time.sleep(1+i)


def norm(s):
    return ' '.join(re.findall(r'[a-z0-9]+',s.lower()))


def key(s):
    return hashlib.sha256(s.encode()).hexdigest()


def prepare(rs):
    raw=rs/'raw';out=rs/'data';out.mkdir(exist_ok=True,parents=True);t0=time.perf_counter()
    for s,d in RSHASH.items():assert digest(raw/(s+'.parquet'))==d
    assert digest(raw/'original.json')==AUTH
    lookup={x['filename']:x for x in json.loads((raw/'original.json').read_bytes())['images']}
    names=set();caps=set();hashes=set();meta=[];photos=[];drops=Counter();counts=Counter()
    for stage,split in enumerate(('train','valid','test')):
        local=[]
        for batch in pq.ParquetFile(raw/(split+'.parquet')).iter_batches(batch_size=96):
            for row in batch.to_pylist():
                name=Path(row['filename']).name;author=lookup[name]
                assert author['split']=={'valid':'val'}.get(split,split)
                official=sorted({norm(s['raw']) for s in author['sentences'] if norm(s['raw'])})
                assert {norm(s) for s in row['captions']} & set(official)
                cap=min(official,key=lambda s:key(row['filename']+'|'+s))
                with Image.open(io.BytesIO(row['image']['bytes'])) as im:px=np.array(im.convert('RGB').resize((32,32),Image.Resampling.BILINEAR))
                local.append((name,cap,px))
        for name,cap,px in sorted(local,key=lambda x:x[0]):
            h=hashlib.sha256(px.tobytes()).digest()
            if name in names or cap in caps or h in hashes:drops[split]+=1;continue
            names.add(name);caps.add(cap);hashes.add(h);photos.append(px);counts[split]+=1
            meta.append({'filename':name,'caption_sha':key(cap),'split':stage,'category':re.sub(r'[_-]?[0-9]+$','',Path(name).stem)})
    np.save(out/'pixels32.npy',np.stack(photos));(out/'rows.json').write_text(json.dumps(meta))
    achieved={p:digest(out/p) for p in EXPECTED};assert achieved==EXPECTED
    receipt={'sha256':achieved,'retained':dict(counts),'earliest_duplicate_removed':dict(drops),'source_cache_rebuild_s':time.perf_counter()-t0}
    (out/'rebuild.json').write_text(json.dumps(receipt,indent=2)+'\n');print(receipt,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('rs',type=Path);p.add_argument('ucm',type=Path);p.add_argument('--local-rs-only',action='store_true');a=p.parse_args()
    if not a.local_rs_only:
        urls=[(a.rs/'raw'/'original.json',RSCAP,AUTH)]
        for base,path,checks in [(RSBASE,a.rs/'raw',RSHASH),(UCBASE,a.ucm,UCHASH)]:
            urls.extend((path/(s+'.parquet'),base+'/'+s+'-00000-of-00001.parquet?download=true',d) for s,d in checks.items())
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(get,urls))
    prepare(a.rs)
