"""Build a cross-corpus gallery with source-author captions and transform-aware deduplication."""
import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image
import pyarrow.parquet as pq
from scipy.fft import dctn


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(4 << 20),b''):h.update(block)
    return h.hexdigest()


def words(text):
    return re.findall("[a-z0-9]+(?:'[a-z]+)?",text.lower())


def hashes(image):
    grey=np.sum(image*np.array([.299,.587,.114]),axis=2)
    transforms=[np.rot90(grey,k) for k in range(4)]+[np.rot90(grey[:,::-1],k) for k in range(4)]
    out=[]
    for v in transforms:
        fft=dctn(v,norm='ortho')[:8,:8].ravel()
        bits=fft>np.median(fft[1:]);bits[0]=False
        out.append(int.from_bytes(np.packbits(bits).tobytes(),'little'))
    return out


class Index:
    def __init__(self):
        self.parts=defaultdict(set)
        self.exact=set()
    def keys(self,h):
        return ((k,(h>>(13*k))&8191) for k in range(5))
    def admit(self,image):
        raw=hashlib.sha256(image.tobytes()).digest()
        if raw in self.exact:return 'exact'
        hs=hashes(image)
        for key in self.keys(hs[0]):
            if any((other^hs[0]).bit_count()<=4 for other in self.parts[key]):return 'near'
        self.exact.add(raw)
        for h in hs:
            for key in self.keys(h):self.parts[key].add(h)
        return ''


def main(root,ucm,out):
    start=time.perf_counter(); files={}
    for f in [root/'data/pixels32.npy',root/'data/rows.json',root/'raw/original.json',*(ucm/(s+'.parquet') for s in ('train','validation','test'))]:
        files[str(f.relative_to(root) if f.is_relative_to(root) else 'ucm/'+f.name)]=digest(f)
    assert files['data/pixels32.npy']=='d79c414bb32c3ffb88f1714c20b6bdb531a68a7a95999370c86aea7367b768b1'
    assert files['raw/original.json']=='5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede'
    desc={r['filename']:[' '.join(words(s['raw'])) for s in r['sentences']][:5] for r in json.loads((root/'raw/original.json').read_text())['images']}
    rp=np.load(root/'data/pixels32.npy',mmap_mode='r');meta=json.loads((root/'data/rows.json').read_text())
    rs=defaultdict(list)
    for i,m in enumerate(meta):
        name=m['filename'];rs[m['split']].append((name,np.asarray(rp[i]),desc[name]))
    u=[]
    for s in ('train','validation','test'):
        for batch in pq.ParquetFile(ucm/(s+'.parquet')).iter_batches(batch_size=16):
            for rec in batch.to_pylist():
                with Image.open(io.BytesIO(rec['image']['bytes'])) as img:
                    px=np.asarray(img.convert('RGB').resize((32,32),Image.Resampling.BOX))
                u.append((rec['file_name'],px,[' '.join(words(rec['caption_'+str(j)])) for j in range(1,6)]))
    import copy
    rows=[];exclusions=Counter();idx=Index()
    for group,cohort in enumerate([rs[0],rs[1],rs[2],u]):
        if group==2:before=copy.deepcopy(idx)
        if group==3:idx=before
        for name,image,caps in sorted(cohort,key=lambda r:r[0]):
            if not caps or not caps[0]:
                exclusions[f'{group}/missing_primary_caption']+=1;continue
            missing=sum(not cap for cap in caps)
            if missing:exclusions[f'{group}/empty_nonprimary_caption_fields']+=missing
            caps=[cap for cap in caps if cap]
            reason=idx.admit(image)
            if reason:exclusions[f'{group}/{reason}']+=1;continue
            assert len(caps)>0 and all(caps)
            rows.append((group,name,image,caps))
    cnt=Counter(w for g,n,im,cs in rows if g==0 for cap in cs for w in cap.split())
    vocab={w:j+2 for j,w in enumerate(sorted(cnt,key=lambda w:(-cnt[w],w))[:2046])}
    names=[];pixels=[];tokens=np.zeros((len(rows),5,24),np.int16);split=[];classnames=[];groups=[];all_group={}
    oovs=Counter();nwords=Counter()
    for i,(g,n,im,cs) in enumerate(rows):
        names.append(n);pixels.append(im);split.append(g);rowg=[]
        for k in range(5):
            cap=cs[k%len(cs)];lab=all_group.setdefault(cap,len(all_group));rowg.append(lab)
            v=[vocab.get(w,1) for w in cap.split()[:24]];tokens[i,k,:len(v)]=v;oovs[g]+=v.count(1);nwords[g]+=len(v)
        groups.append(rowg)
    out.mkdir(exist_ok=True,parents=True)
    np.savez(out/'input.npz',images=np.stack(pixels),tokens=tokens,split=np.asarray(split),groups=np.asarray(groups),vocab=np.array(len(vocab)+2),names=np.asarray(names))
    traintext={c for g,n,im,cs in rows if g==0 for c in cs}
    report=dict(source_files=files,input_sha256=digest(out/'input.npz'),counts=np.bincount(split).tolist(),exclusions=dict(exclusions),oov_rate={g:oovs[g]/nwords[g] for g in range(4)},source_training_captions_reused_by_external_primary=sum(cs[0] in traintext for g,n,im,cs in rows if g==3),vocab=len(vocab)+2,prep_wall_s=time.perf_counter()-start,
    sources=['https://github.com/201528014227051/RSICD_optimal/blob/fc33b4555e4baa4d2f05ff0449479c89da2eeac2/dataset_rsicd.json','https://huggingface.co/datasets/arampacha/rsicd','https://huggingface.co/datasets/caglarmert/UCM-Captions'])
    (out/'data.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for key in ('rsicd','ucm','out'):p.add_argument(key,type=Path)
    a=p.parse_args();main(a.rsicd,a.ucm,a.out)
