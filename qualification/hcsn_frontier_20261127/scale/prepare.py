"""Prepare an offline, compact public UCM-Captions subset for the GPU qualification."""
import argparse
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
import re

import numpy as np
import pyarrow.parquet as pq
from PIL import Image


def sha(raw):return hashlib.sha256(raw).hexdigest()
def tokens(text):return re.findall(r"[a-z0-9]+(?:'[a-z]+)?",text.lower())


def main(directory,out):
    rows=[];known=set(); removed=[];seen_names=set();rawfiles={}
    for split,part in enumerate(('train','validation','test')):
        f=directory/(part+'.parquet');rawfiles[part]=sha(f.read_bytes())
        for batch in pq.ParquetFile(f).iter_batches(batch_size=50):
            for a in batch.to_pylist():
                img=Image.open(io.BytesIO(a['image']['bytes'])).convert('RGB')
                sig=sha(img.tobytes());name=a['file_name']
                if sig in known or name in seen_names:
                    removed.append((name,split));continue
                known.add(sig);seen_names.add(name)
                px=np.asarray(img.resize((8,8),Image.Resampling.BOX),np.uint8)
                pic=(px[:,:,0]&224)|((px[:,:,1]>>3)&28)|(px[:,:,2]>>6)
                gr=np.asarray(img.resize((9,8),Image.Resampling.BOX).convert('L')).astype(int)
                dh=int.from_bytes(np.packbits(gr[:,1:]>gr[:,:-1]).tobytes(),'big')
                caps=[tokens(a['caption_'+str(i)]) for i in range(1,4)]
                rows.append([name,split,pic,caps,sig,dh])
    vocabulary=Counter(t for _,s,_,caps,_,_ in rows if s==0 for c in caps for t in c)
    words=sorted(vocabulary,key=lambda t:(-vocabulary[t],t))[:1020]
    ids={t:j+4 for j,t in enumerate(words)}
    text=np.zeros((len(rows),3,22),np.uint16);oov=Counter();tot=Counter();near=[]
    for j,(n,s,_,caps,_,d) in enumerate(rows):
        for k,c in enumerate(caps):
            v=[ids.get(t,1) for t in c[:20]]
            text[j,k,:len(v)+2]=[2,*v,3];oov[s]+=v.count(1);tot[s]+=len(v)
        for m in range(j):
            if rows[m][1]!=s and (d^rows[m][-1]).bit_count()<=2:near.append([rows[m][0],n])
    images=np.array([a[2] for a in rows]);splits=np.array([a[1] for a in rows],np.uint8)
    # Exclude OOD photos with very similar 64-bit hashes to any earlier split.
    hurt=set(v for _,v in near); mask=np.array([a[0] not in hurt for a in rows])
    out.mkdir(exist_ok=True,parents=True);pack=out/'pack.npz'
    np.savez_compressed(pack,images=images[mask],split=splits[mask],captions=text[mask],vocab_size=np.array(len(words)+4))
    manifest=dict(source_sha256=rawfiles,ids=[a[0] for i,a in enumerate(rows) if mask[i]],
                  split_counts=np.bincount(splits[mask]).tolist(),source_unknown_count=dict(oov),source_tokens=dict(tot),close_cross_split=near,exact_removed=removed,vocab=words,sha256=sha(pack.read_bytes()),payload_bytes=pack.stat().st_size)
    (out/'data.json').write_text(json.dumps(manifest)+'\n');print(len(rows),manifest['split_counts'],pack.stat().st_size,len(near),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('out',type=Path)
    a=p.parse_args();main(a.source,a.out)
