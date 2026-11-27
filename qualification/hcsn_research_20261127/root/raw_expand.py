"""Grow the pre-registered true COCO training sample without retaining extra original media."""
import concurrent.futures,hashlib,io,json,os,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent;C=ROOT/'cache';OUT=ROOT/'raw4096_inputs'
def records(path):
    dec=json.JSONDecoder()
    with path.open(encoding='utf8') as f:
        buf=''
        while True:
            part=f.read(1<<20)
            buf+=part
            while True:
                buf=buf.lstrip(' ,\r\n\t[')
                if not buf or buf[0]==']':break
                try:obj,idx=dec.raw_decode(buf)
                except json.JSONDecodeError:break
                yield obj;buf=buf[idx:]
            if not part:break
def key(name):
    return hashlib.sha256(('hepta-hcsn-coco-20261127-v1:'+name).encode()).digest()
def roster():
    dest=ROOT/'raw4096_roster.json'
    if dest.is_file():return json.loads(dest.read_bytes())
    base=json.loads((C/'selected.json').read_bytes())
    seen={r['image'].rsplit('/',1)[-1] for r in records(C/'train.json')}
    ordered=sorted(seen,key=key)[:4096];chosen=set(ordered);items={}
    for r in records(C/'train.json'):
        name=r['image'].rsplit('/',1)[-1]
        if name in chosen:
            slot=items.setdefault(name,{'file':name,'path':r['image'],'captions':[]})
            if len(slot['captions'])<5 and r['caption'] not in slot['captions']:slot['captions'].append(r['caption'])
    assert ordered[:1024]==[r['file'] for r in base['train']]
    for s in ('val','test'):assert not chosen.intersection(r['file'] for r in base[s])
    d={'train':[items[n] for n in ordered],'val':base['val'],'test':base['test']}
    dest.write_text(json.dumps(d,ensure_ascii=False));return d
def one(row):
    name=row['file'];base=ROOT/'raw_inputs/decoded'/(name+'.npy');target=OUT/'decoded'/(name+'.npy')
    receipt=OUT/'receipts'/(name+'.json')
    if target.is_file() and receipt.is_file():return json.loads(receipt.read_bytes())
    orig=C/'images'/name
    if base.is_file() and orig.is_file():
        if not target.is_file():os.link(base,target)
        b=orig.read_bytes()
    else:
        u='https://s3.amazonaws.com/images.cocodataset.org/'+row['path']
        for attempt in range(5):
            try:
                with urlopen(Request(u,headers={'User-Agent':'Hepta COCO extension'}),timeout=45) as f:b=f.read()
                with Image.open(io.BytesIO(b)) as im:image=np.asarray(im.convert('RGB').resize((32,32),Image.Resampling.BICUBIC))
                with target.with_suffix('.tmp').open('wb') as f:np.save(f,image)
                target.with_suffix('.tmp').replace(target);break
            except Exception:
                if attempt==4:raise
                time.sleep(1+attempt)
    rec={'name':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'decoded_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    receipt.write_text(json.dumps(rec));return rec
def main():
    from raw_prepare import main as prepare
    OUT.mkdir(exist_ok=True);(OUT/'decoded').mkdir(exist_ok=True);(OUT/'receipts').mkdir(exist_ok=True)
    d=roster();rows=[r for vs in d.values() for r in vs];start=time.perf_counter();errors=[]
    with concurrent.futures.ThreadPoolExecutor(10) as ex:
        futures={ex.submit(one,row):row['file'] for row in rows}
        for nc,f in enumerate(concurrent.futures.as_completed(futures),1):
            try:f.result()
            except Exception as e:errors.append([futures[f],str(e)])
            if nc%256==0:print('images',nc,'errors',len(errors),flush=True)
    if errors:raise ValueError(errors[:8])
    sys.argv=[sys.argv[0],'--roster',str(ROOT/'raw4096_roster.json'),'--out',str(OUT)]
    prepare()
    print('complete retrieval and decoding wall time',time.perf_counter()-start,flush=True)
if __name__=='__main__':main()
