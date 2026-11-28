"""Retrieve pinned public LFS media with bounded concurrency and keep decoded original tensors."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import threading
import time
import traceback
import zipfile
import io
import numpy as np
import requests
import prepare_original as original
from reference import stages

WHEEL='c7e46fcec401dd990405049d2e2f475e2b397779df2519b544b8aab515195282'
FFMPEG='e7e7fb30477f717e6f55f9180a70386c62677ef8a4d4d1a5d948f4098aa3eb99'
client=threading.local()

def sha(x):return hashlib.sha256(x).hexdigest()

def fetch(url, timeout=22):
    if not hasattr(client,'http'):client.http=requests.Session()
    for attempt in range(2):
        try:
            resp=client.http.get(url,timeout=(7,timeout));resp.raise_for_status();return resp.content
        except (requests.Timeout,requests.ConnectionError):
            if attempt:raise
        except requests.HTTPError as exc:
            if attempt or exc.response.status_code not in (502,503,504):raise
        time.sleep(1)

def decoder(path):
    try:
        import imageio_ffmpeg
        installed=Path(imageio_ffmpeg.get_ffmpeg_exe())
        if sha(installed.read_bytes())==FFMPEG:
            path.symlink_to(installed);return 'preinstalled exact digest'
    except (ImportError,OSError):pass
    meta=json.loads(fetch('https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json'))
    wheel=next(r for r in meta['urls'] if r['digests']['sha256']==WHEEL)
    raw=fetch(wheel['url'],45);assert sha(raw)==WHEEL
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name=next(i for i in z.namelist() if i.startswith('imageio_ffmpeg/binaries/ffmpeg-linux'))
        b=z.read(name)
    assert sha(b)==FFMPEG;path.write_bytes(b);path.chmod(0o700)
    return 'pinned public wheel'

def persist(path,obj):
    p=path.with_suffix('.tmp');p.write_text(json.dumps(obj,allow_nan=False));p.replace(path)

def main(root):
    start=time.perf_counter();dest=root/'ingress.json';rep={'entries':[],'tiers':[],'elapsed_s':0,'errors':{},'complete':False}
    def save():rep.update(elapsed_s=time.perf_counter()-start);persist(dest,rep)
    save()
    try:
        (root/'env').mkdir();(root/'data/raw').mkdir(parents=True);(root/'data/clips').mkdir()
        rep['decoder']=decoder(root/'env/ffmpeg');save();original.download=fetch
        with np.load(root/'meta.npz',allow_pickle=False) as a: names=a['ids'];fold=a['split']
        tiers=stages(fold);ptrs=(root/'pointers.bin').read_bytes()
        assert len(ptrs)==len(tiers[-2])*20
        pointers={int(j):ptrs[20*i:20*i+20].hex() for i,j in enumerate(tiers[-2])}
        seen=set();done=set();ref=json.loads((root/'reference.json').read_text())
        for lev,ix in enumerate(tiers):
            if lev==len(tiers)-1:
                tree=json.loads(fetch(f'https://api.github.com/repos/{original.REPO}/git/trees/{original.REV}?recursive=1'))
                rows=sorted((x for x in tree['tree'] if x['path'].startswith('VideoFlash/') and x['path'].endswith('.flv')),key=lambda r:r['path']);assert len(rows)==len(names) and not tree['truncated']
                full={j:r['sha'] for j,r in enumerate(rows) if r['path']=='VideoFlash/'+names[j]+'.flv'};assert len(full)==len(names) and all(full[j]==p for j,p in pointers.items());pointers=full
            task_ids=[int(i) for i in ix if int(i) not in seen];seen.update(task_ids)
            def one(j):
                e={'path':'VideoFlash/'+str(names[j])+'.flv','sha':pointers[j]}
                return original.extract_one((root,j,e))
            with ThreadPoolExecutor(max_workers=8) as pool:
                tasks={pool.submit(one,j):j for j in task_ids}
                for future in as_completed(tasks):
                    j=tasks[future]
                    try:
                        _,digest,samples,frames=future.result()
                        p=root/'data/clips'/(str(names[j])+'.npz')
                        with np.load(p,allow_pickle=False) as q:
                            vc=sha(q['video'].tobytes());ac=sha(q['audio'].tobytes())
                        d={'index':j,'id':str(names[j]),'media_sha256':digest,'image_sha256':vc,'audio_sha256':ac,'samples':samples,'frames':frames};done.add(j)
                        if d['id'] in ref['first48']:d['match_reference']=(ref['first48'][d['id']]=={'image_sha256':vc,'audio_sha256':ac})
                        rep['entries'].append(d)
                        (root/'data/raw'/(str(names[j])+'.flv')).unlink(missing_ok=True)
                    except Exception as exc:rep['errors'][str(j)]=[type(exc).__name__,str(exc)[:320]]
                    if (len(done)+len(rep['errors']))%8==0:save()
            required=set(map(int,ix));cr={'n':len(ix),'decoded':len(required&done),'verified':False}
            if required<=done:
                vhash=hashlib.sha256();ahash=hashlib.sha256()
                for j in ix:
                    with np.load(root/'data/clips'/(str(names[j])+'.npz'),allow_pickle=False) as q:
                        vhash.update(q['video'].tobytes());ahash.update(q['audio'].tobytes())
                cr.update(ids=sha(names[ix].tobytes()),images=vhash.hexdigest(),audio=ahash.hexdigest());cr['verified']=all(cr[k]==ref['tiers'][lev][k] for k in ('ids','images','audio'))
            rep['tiers'].append(cr);save()
            if not cr['verified']:break
        rep['complete']=True;save()
    except Exception:
        rep['error']=traceback.format_exc()[-2500:];save()

if __name__=='__main__':main(Path(sys.argv[1]))
