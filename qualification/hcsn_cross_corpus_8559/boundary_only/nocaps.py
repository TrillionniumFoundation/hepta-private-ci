"""A selection- and score-independent 512-photo natural-image gallery."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib,io,json,os
from pathlib import Path
import sys,time
import urllib.request

import numpy as np
from PIL import Image

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from external import vocab_and_check
from prepare import digest,hashes,words

AUTHOR='https://drive.usercontent.google.com/download?id=1zrsLhT94nazJ5h-LleHsU4AojHBqpcA0&export=download&confirm=t'


def run(w,source,author):
    public=w/'public';ann=public/'nocaps-authors.json'
    if not ann.exists():
        with urllib.request.urlopen(AUTHOR,timeout=60) as f:ann.write_bytes(f.read())
    labels=json.loads(ann.read_text());assert len(labels['images'])==4500 and len(labels['annotations'])==45000
    chosen=sorted(labels['images'],key=lambda x:hashlib.sha256(('hcsn-nocaps-8559|'+x['open_images_id']).encode()).digest())[:512]
    desc={}
    for a in labels['annotations']:desc.setdefault(a['image_id'],' '.join(words(a['caption'])))
    imgs=public/'nocaps-raw';imgs.mkdir(exist_ok=True)
    def get(row):
        file=row['file_name'];fp=imgs/file
        url='https://open-images-dataset.s3.amazonaws.com/validation/'+file
        for attempt in range(3):
            try:
                if not fp.exists():
                    req=urllib.request.Request(url,headers={'User-Agent':'HCSN natural-image transport research'})
                    with urllib.request.urlopen(req,timeout=30) as conn:raw=conn.read()
                else:raw=fp.read_bytes()
                with Image.open(io.BytesIO(raw)) as p:
                    p=p.convert('RGB');px=np.asarray(p.resize((32,32),Image.Resampling.BOX));sz=p.size
                if not fp.exists():
                    tmp=fp.with_suffix('.part');tmp.write_bytes(raw);os.replace(tmp,fp)
                return row,px,{'id':row['open_images_id'],'domain':row.get('domain'),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'url':url,'dimensions':list(sz),'metadata_dimensions':[row['width'],row['height']]}
            except Exception as e:
                if attempt==2:return row,None,{'id':row['open_images_id'],'error':type(e).__name__+': '+str(e)[:180],'url':url}
                time.sleep(1+attempt)
    with ThreadPoolExecutor(max_workers=6) as ex:loaded=list(ex.map(get,chosen))
    with np.load(source) as z:vocab=vocab_and_check(z,author);prior=z['images']
    with np.load(w/'rsitmd.npz') as r:prior=np.concatenate((prior,r['pixels']))
    ref=np.array([hashes(p) for p in prior],dtype=np.uint64);exacts={hashlib.sha256(p.tobytes()).digest() for p in prior}
    accepted=[];history=[];fps=[];seen=set()
    for row,pix,rec in loaded:
        if pix is None:history.append(rec);continue
        h=np.asarray(hashes(pix),np.uint64);sig=hashlib.sha256(pix.tobytes()).digest()
        dist=int(np.bitwise_count(ref^h[0]).min())
        if fps:dist=min(dist,int(np.bitwise_count(np.asarray(fps)^h[0]).min()))
        rec['min_hamming']=dist;rec['accepted']=dist>4 and sig not in exacts and sig not in seen
        if rec['accepted']:
            cap=desc[row['id']];assert cap
            accepted.append((row,pix,cap));fps.append(h);seen.add(sig)
        history.append(rec)
    assert len(accepted)>0
    cap=[r[2] for r in accepted];_,g=np.unique(cap,return_inverse=True);t=np.stack([vocab(c) for c in cap]);p=w/'nocaps.npz'
    np.savez_compressed(p,pixels=np.stack([x[1] for x in accepted]),ids=np.array([x[0]['open_images_id'] for x in accepted]),tokens=t,groups=g,caps=np.array(cap),domain=np.array([x[0].get('domain','') for x in accepted]))
    rec=dict(author_url=AUTHOR,annotation_sha256=digest(ann),public_source='Open Images V4 publication objects matched by the author-provided 16-digit image ID',requested=512,loaded=sum(x[1] is not None for x in loaded),accepted=len(accepted),domains=dict(Counter(x[0].get('domain') for x in accepted)),oov_fraction=float((t==1).sum()/(t!=0).sum()),derived_sha256=digest(p),rows=history)
    (w/'NOCAPS_ROSTER.json').write_text(json.dumps(rec,indent=2)+'\n');print({k:v for k,v in rec.items() if k!='rows'},flush=True)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('work',type=Path);a.add_argument('source',type=Path);a.add_argument('author',type=Path);p=a.parse_args();run(p.work,p.source,p.author)
