"""Prepare two training corpora and independent report-only test galleries."""
import argparse
from collections import Counter,defaultdict
import hashlib
import io
import json
from pathlib import Path
import sys
import time
from zipfile import ZipFile

import numpy as np
from PIL import Image
import pyarrow.parquet as pq
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare import digest,hashes,words


class Duplicates:
    def __init__(self):self.raw=set();self.k=defaultdict(set)
    def candidates(self,h):
        return ((j,(h>>(13*j))&8191) for j in range(5))
    def matches(self,sig,h):
        if sig in self.raw:return 'exact'
        for k in self.candidates(h):
            if any((j^h).bit_count()<=4 for j in self.k.get(k,())):return 'near'
        return ''
    def add(self,sig,hs):
        self.raw.add(sig)
        for h in hs:
            for k in self.candidates(h):self.k[k].add(h)


def parquet_rows(paths):
    for p in sorted(paths):
        for batch in pq.ParquetFile(p).iter_batches(batch_size=32):
            for r in batch.to_pylist():
                with Image.open(io.BytesIO(r['image']['bytes'])) as im:
                    px=np.asarray(im.convert('RGB').resize((32,32),Image.Resampling.BOX))
                yield r['file_name'],px,[r['caption_'+str(k)] or '' for k in range(1,6)]


def run(rs,uc,corps,out):
    t0=time.perf_counter();out.mkdir(exist_ok=True,parents=True)
    refhash={'rsicd_author':digest(rs/'raw/original.json'),'rsicd_pixels':digest(rs/'data/pixels32.npy'),'rsicd_roster':digest(rs/'data/rows.json')}
    assert refhash['rsicd_author']=='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede'
    assert refhash['rsicd_pixels']=='d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1'
    idx=Duplicates();raw=[];removed=Counter()
    def consume(label,source,rows,test=False):
        local=Duplicates() if test else idx
        for name,px,caps in sorted(rows,key=lambda a:a[0]):
            norm=[' '.join(words(c)) for c in caps]
            if not norm or not norm[0]:removed[label+'/missing_primary']+=1;continue
            valid=[c for c in norm if c]
            h=hashes(px);sig=hashlib.sha256(px.tobytes()).digest()
            reason=idx.matches(sig,h[0])
            if not reason and test:reason=local.matches(sig,h[0])
            if reason:removed[label+'/'+reason]+=1;continue
            local.add(sig,h);raw.append((source,label,name,px,valid))
    maps=json.loads((rs/'data/rows.json').read_text());px=np.load(rs/'data/pixels32.npy',mmap_mode='r');auth=json.loads((rs/'raw/original.json').read_text())
    c={row['filename']:[s['raw'] for s in row['sentences']][:5] for row in auth['images']}
    nw=corps/'nwpu';nwremote=json.loads((nw/'remote.json').read_text())
    for f in nw.glob('*.parquet'):
        refhash['NWPU/'+f.name]=digest(f);assert refhash['NWPU/'+f.name]==nwremote['data/'+f.name]['lfs']['oid']
    for ix,g,nprefix in [(0,'train','train'),(1,'dev','validation'),(2,'test','test')]:
        rsrows=[(m['filename'],px[j],c[m['filename']]) for j,m in enumerate(maps) if m['split']==ix]
        consume('rs_'+g,'rs',rsrows,test=ix==2)
        consume('nw_'+g,'nw',parquet_rows(nw.glob(nprefix+'-*.parquet')),test=ix==2)
    for f in sorted(uc.glob('*.parquet')):refhash['UCM/'+f.name]=digest(f)
    consume('ucm','ucm',parquet_rows(uc.glob('*.parquet')),test=True)
    sz=corps/'sydney'/'Sydney_captions.zip';refhash['sydney']=digest(sz)
    assert refhash['sydney']==json.loads((corps/'sydney/remote.json').read_text())[sz.name]['lfs']['oid']
    with ZipFile(sz) as z:
        sydney=json.loads(z.read('dataset.json'));tmp=[]
        for row in sydney['images']:
            name=row.get('filename',str(row['imgid']+1)+'.tif')
            with Image.open(io.BytesIO(z.read('images/'+name))) as im:
                x=np.asarray(im.convert('RGB').resize((32,32),Image.Resampling.BOX))
            tmp.append((name,x,[s['raw'] for s in row['sentences']][:5]))
        consume('sydney','sydney',tmp,test=True)
    freq=Counter(w for _,g,_,_,cs in raw if g.endswith('_train') for cap in cs for w in cap.split())
    voc={w:j+2 for j,w in enumerate(sorted(freq,key=lambda k:(-freq[k],k))[:4094])}
    z=np.zeros((len(raw),5,24),np.int16);label=np.zeros((len(raw),5),np.int32);caps_id={};oov=Counter();tot=Counter()
    for j,(_,g,_,_,ca) in enumerate(raw):
        for k in range(5):
            cap=ca[k%len(ca)];v=[voc.get(w,1) for w in cap.split()[:24]];z[j,k,:len(v)]=v;label[j,k]=caps_id.setdefault(cap,len(caps_id));oov[g]+=v.count(1);tot[g]+=len(v)
    for name,dat in dict(pixels=np.stack([r[3] for r in raw]),tokens=z,groups=label,splits=np.array([r[1] for r in raw]),ids=np.array([r[0]+'/'+r[2] for r in raw])).items():
        np.save(out/(name+'.npy'),dat)
    receipt=dict(counts=dict(Counter(r[1] for r in raw)),exclusions=dict(removed),oov={g:oov[g]/tot[g] for g in tot},vocab=len(voc)+2,raw_files=refhash,arrays={p.name:digest(p) for p in sorted(out.glob('*.npy'))},elapsed_s=time.perf_counter()-t0)
    (out/'data.json').write_text(json.dumps(receipt,indent=2)+'\n');print(receipt,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for arg in ('rs','uc','corpora','out'):ap.add_argument(arg,type=Path)
    a=ap.parse_args();run(a.rs,a.uc,a.corpora,a.out)
