"""Prepare genuine decoded photo patches and training-only word IDs for scratch retrieval."""
import argparse, collections, hashlib, json, re, time
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent
def words(x):
    return re.findall(r"[a-z0-9]+(?:'[a-z0-9]+)?",x.lower())
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--roster',type=Path,default=ROOT/'cache'/'selected.json')
    p.add_argument('--image-dir',type=Path,default=ROOT/'cache'/'images')
    p.add_argument('--out',type=Path,default=ROOT/'raw_inputs')
    a=p.parse_args()
    start=time.perf_counter();a.out.mkdir(exist_ok=True,parents=True)
    d=json.loads(a.roster.read_bytes())
    counts=collections.Counter(w for row in d['train'] for c in row['captions'] for w in words(c))
    vocab={v:i+2 for i,v in enumerate(sorted(counts,key=lambda v:(-counts[v],v))[:4094])}
    (a.out/'vocab.json').write_text(json.dumps(vocab,sort_keys=True))
    info={}
    for s,rows in d.items():
        pix=[];tokens=[];owners=[];hashed=[]
        pixdir=a.out/'decoded';pixdir.mkdir(exist_ok=True)
        for i,r in enumerate(rows):
            pp=pixdir/(r['file']+'.npy')
            if not pp.is_file():
                with Image.open(a.image_dir/r['file']) as im:
                    decoded=np.asarray(im.convert('RGB').resize((32,32),Image.Resampling.BICUBIC),dtype=np.uint8)
                with pp.with_suffix('.tmp').open('wb') as f:np.save(f,decoded)
                pp.with_suffix('.tmp').replace(pp)
            pix.append(np.load(pp))
            if i%160==0:print('raw',s,i,flush=True)
            for cap in r['captions']:
                w=words(cap)
                ids=[vocab.get(v,1) for v in w[:16]] or [1]
                tokens.append(ids+[0]*(16-len(ids)));owners.append(i)
                bag=np.zeros(512,np.int16)
                for token in w:
                    idx=int.from_bytes(hashlib.sha256(token.encode()).digest()[:4],'big')
                    bag[idx%512]+=1 if idx&(1<<16) else -1
                hashed.append(bag)
        f=a.out/f'{s}.npz'
        np.savez_compressed(f,rgb=pix,token=np.asarray(tokens,dtype=np.int16),owner=np.asarray(owners,dtype=np.int32),bow=hashed)
        info[s]={'photos':len(pix),'captions':len(tokens),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
    info['vocab_sha256']=hashlib.sha256((a.out/'vocab.json').read_bytes()).hexdigest()
    info['elapsed_seconds']=time.perf_counter()-start
    (a.out/'manifest.json').write_text(json.dumps(info,indent=2))
if __name__=='__main__':main()
