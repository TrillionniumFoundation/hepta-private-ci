"""Decode product photographs, split connected duplicate groups, derive train-only vocabulary."""
from pathlib import Path
from collections import Counter
from PIL import Image
import pyarrow.parquet as pq
import numpy as np
import json,hashlib,re,io,time
ROOT=Path(__file__).resolve().parent/'paired_catalog'
def normal(s):return ' '.join(re.findall(r'[^\W_]+',s.lower()))
def digest(data):return hashlib.sha256(data).hexdigest()
def stable(s):return int.from_bytes(hashlib.sha256(s.encode()).digest()[:8],'big')
def main():
    start=time.perf_counter(); manifest=json.loads((ROOT/'source.json').read_bytes())
    pics=[];titles=[];ids=[];skip=0;dhash=[];pixels=[]
    for spec in manifest['shards']:
        p=ROOT/Path(spec['path']).name
        assert hashlib.sha256(p.read_bytes()).hexdigest()==spec['sha256']
        for batch in pq.ParquetFile(p).iter_batches(batch_size=256,columns=['id','image','productDisplayName']):
            for row in batch.to_pylist():
                cap=row['productDisplayName'];item=row['id'];im=row['image']
                if not isinstance(cap,str) or item is None or not normal(cap) or not im or not im.get('bytes'):skip+=1;continue
                try:
                    with Image.open(io.BytesIO(im['bytes'])) as image:
                        rgb=np.asarray(image.convert('RGB').resize((32,32),Image.Resampling.BILINEAR))
                        small=np.asarray(image.convert('L').resize((9,8),Image.Resampling.BILINEAR))
                except (OSError,ValueError):
                    skip+=1;continue
                titles.append(normal(cap));ids.append(int(item));pics.append(rgb);pixels.append(digest(rgb.tobytes()))
                dhash.append(np.packbits(small[:,1:]>small[:,:-1]).tobytes().hex())
    n=len(ids);parents=list(range(n))
    def root(i):
        while i!=parents[i]:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    for field in [titles,pixels,ids]:
        seen={}
        for j,v in enumerate(field):
            if v in seen:parents[root(j)]=root(seen[v])
            else:seen[v]=j
    grp=np.array([root(i) for i in range(n)])
    names={}
    for j,g in enumerate(grp):names[g]=min(names.get(g,ids[j]),ids[j])
    group=np.array([names[x] for x in grp],dtype='int64')
    bucket=np.array([stable('catalog-groups-9c415-'+str(g))%10000 for g in group]);split=np.where(bucket<8000,0,np.where(bucket<9000,1,2))
    for a in [0,1,2]:
        for b in range(a):
            for v in [titles,pixels,ids,group]:
                assert set(np.asarray(v)[split==a]).isdisjoint(set(np.asarray(v)[split==b]))
    train=np.flatnonzero(split==0)
    counts=Counter(word for i in train for word in titles[i].split())
    words=[w for w,k in sorted(counts.items(),key=lambda x:(-x[1],x[0])) if k>=2][:8190]
    vocab={w:j+2 for j,w in enumerate(words)}
    tok=np.zeros((n,16),dtype='int32')
    for i,t in enumerate(titles):
        v=[vocab.get(w,1) for w in t.split()[:16]];tok[i,:len(v)]=v
    _,tid=np.unique(titles,return_inverse=True)
    order=np.array([stable('catalog-gallery-9c415-'+str(v)+':'+str(j)) for j,v in enumerate(ids)],dtype=np.uint64)
    np.save(ROOT/'pixels32.npy',np.stack(pics))
    np.savez(ROOT/'catalog.npz',split=split,group=group,id=ids,title=tid,tokens=tok,order=order)
    (ROOT/'vocabulary.json').write_text(json.dumps(vocab,ensure_ascii=False))
    near={};dhash=np.array(dhash)
    np.save(ROOT/'gray_hash.npy',dhash.astype('S16'))
    for a,b in [(0,1),(0,2),(1,2)]:
        aset=set(dhash[split==a]);near[str(a)+'-'+str(b)]=int(sum(q in aset for q in dhash[split==b]))
    doc={'input':manifest,'counts':np.bincount(split,minlength=3).tolist(),'groups':[len(set(group[split==a])) for a in [0,1,2]],'train_vocab':len(vocab),'malformed':skip,'overlap_of_exact_difference_hash':near,'wall_s':time.perf_counter()-start,'digests':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in ['pixels32.npy','catalog.npz','vocabulary.json']}}
    (ROOT/'dataset.json').write_text(json.dumps(doc,indent=1));print(json.dumps(doc),flush=True)
if __name__=='__main__':main()
