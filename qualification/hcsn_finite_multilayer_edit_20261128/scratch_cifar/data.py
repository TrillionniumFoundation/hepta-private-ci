"""Recover literal CIFAR100 RGB arrays from the verified author archive; fix all cohorts by image hash."""
import argparse
import hashlib
import io
import json
import pickle
import tarfile
import time
import urllib.request
from pathlib import Path
import numpy as np


URL='https://cave.cs.toronto.edu/kriz/cifar-100-python.tar.gz'
SIZE=169001437
EXPECTED='85cd44d02ba6437773c5bbd22e183051d648de2e7d6b014e1ef29b855ba677a7'


def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def load_source(out):
    archive=out/'cifar100-author.tar.gz'
    if not archive.exists():
        temp=archive.with_suffix('.partial')
        step=8*1024*1024
        with temp.open('wb') as f:
            for start in range(0,SIZE,step):
                end=min(SIZE,start+step)-1
                for i in range(5):
                    try:
                        req=urllib.request.Request(URL+f'?edit_block={start}',headers={'Range':f'bytes={start}-{end}'})
                        with urllib.request.urlopen(req,timeout=60) as s:
                            assert s.status==206 and s.headers['Content-Range']==f'bytes {start}-{end}/{SIZE}'
                            data=s.read()
                        assert len(data)==end-start+1
                        f.write(data);break
                    except Exception:
                        if i==4:raise
                        time.sleep(2**i)
        assert sha(temp)==EXPECTED
        temp.replace(archive)
    assert sha(archive)==EXPECTED
    return archive


def main(out):
    wall=time.perf_counter();cpu=time.process_time()
    out.mkdir(exist_ok=True,parents=True)
    if (out/'data.json').exists():return
    archive=load_source(out)
    seen=set();rows={};ident={};duplicate=[];counts={}
    source=tarfile.open(archive,'r:gz')
    for group in ('train','test'):
        # Pickle is decoded only after checking the complete original source digest.
        obj=pickle.loads(source.extractfile('cifar-100-python/'+group).read(),encoding='bytes')
        pix=obj[b'data'].reshape(-1,3,32,32).transpose(0,2,3,1).copy()
        y=np.array(obj[b'fine_labels'],dtype=np.uint8)
        c=np.array(obj[b'coarse_labels'],dtype=np.uint8)
        names=[v.decode('ascii') for v in obj[b'filenames']]
        keep=[];hashes=[]
        for i,p in enumerate(pix):
            h=hashlib.sha256(p.tobytes()).hexdigest()
            if h in seen:
                duplicate.append((group,i,h));continue
            seen.add(h);keep.append(i);hashes.append(h)
        if group=='train':
            by_label=[sorted((j for j,i in enumerate(keep) if y[i]==cl),key=lambda j:hashes[j]) for cl in range(100)]
            subsets={'dev':[j for l in by_label for j in l[:25]],
                     'train':[j for l in by_label for j in l[25:]]}
        else:subsets={'test':list(range(len(keep)))}
        for name,idx in subsets.items():
            pos=np.asarray(keep)[idx]
            p=out/(name+'_pixels.npy')
            np.save(p,pix[pos])
            np.savez_compressed(out/(name+'_targets.npz'),fine=y[pos],coarse=c[pos],original=pos,
                                filename=np.array(names)[pos],rgb_sha=np.array(hashes)[idx])
            counts[name]=dict(n=len(pos),fine=np.bincount(y[pos],minlength=100).tolist(),coarse=np.bincount(c[pos],minlength=20).tolist(),
                              pixels=sha(p),targets=sha(out/(name+'_targets.npz')))
    source.close()
    train=np.load(out/'train_pixels.npy',mmap_mode='r')
    sums=train.sum(axis=(0,1,2),dtype=np.uint64)
    mu=sums/(len(train)*1024*255)
    meta=dict(url=URL,source_sha256=sha(archive),splits=counts,duplicate=duplicate,train_rgb_mean=mu.tolist(),
              wall=time.perf_counter()-wall,cpu=time.process_time()-cpu)
    (out/'data.json').write_text(json.dumps(meta,indent=1)+'\n')
    print({key:v['n'] for key,v in counts.items()},'duplicates',len(duplicate),flush=True)
    archive.unlink()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);main(p.parse_args().out)
