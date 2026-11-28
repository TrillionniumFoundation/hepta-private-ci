"""Covariance baseline on both training sources with equal source weight."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from linear import bow,image_features,project,unit
from train import arrays,fast_concordance,write


def run(w):
    t=time.perf_counter();c0=time.process_time();d=arrays(w/'data')
    v=json.loads((w/'data/data.json').read_text())['vocab']
    xp=384;mx=np.zeros(xp);my=np.zeros(v)
    cx=np.zeros((xp,xp));cy=np.zeros((v,v));cxy=np.zeros((xp,v))
    for name in ('rs','nw'):
        ids=np.flatnonzero(d['splits']==name+'_train');n=len(ids)
        # Chunk extraction avoids forming a large 5D float image scratch array for an entire corpus.
        x=np.concatenate([image_features(d['pixels'][z]) for z in np.array_split(ids,(n+511)//512)]).astype(np.float64)
        y=bow(d['tokens'][ids],v).astype(np.float64);mx+=x.mean(0)/2;my+=np.asarray(y.mean(0)).ravel()/2
        cx+=x.T@x/(2*n);cy+=(y.T@y).toarray()/(10*n)
        for k in range(5):cxy+=(y[k::5].T@x).T/(10*n)
    cx-=np.outer(mx,mx);cy-=np.outer(my,my);cxy-=np.outer(mx,my)
    ex,ux=np.linalg.eigh(cx);ey,uy=np.linalg.eigh(cy);X=ux[:,ex>1e-9];Y=uy[:,ey>1e-9];lx=ex[ex>1e-9];ly=ey[ey>1e-9];cross=X.T@cxy@Y
    dev={}
    for name in ('rs','nw'):
        ids=np.flatnonzero(d['splits']==name+'_dev')
        dev[name]=(image_features(d['pixels'][ids])-mx,bow(d['tokens'][ids,0],v),d['groups'][ids,0])
    records=[];best=None
    for ridge in (.01,.1,1):
        wx=1/np.sqrt(lx+ridge*lx.mean());wy=1/np.sqrt(ly+ridge*ly.mean())
        u,_,vt=np.linalg.svd(wx[:,None]*cross*wy,full_matrices=False)
        for rank in (16,32,64):
            a=((X*wx)@u[:,:rank]).astype(np.float32);b=((Y*wy)@vt[:rank].T).astype(np.float32);y0=(my@b).astype(np.float32)
            res={k:fast_concordance(unit((x@a).astype(np.float32)),unit((y@b-y0).astype(np.float32)),g) for k,(x,y,g) in dev.items()}
            row={'ridge':ridge,'rank':rank,'source_dev':res,'dev_mean':float(np.mean(list(res.values())))};records.append(row)
            if best is None or row['dev_mean']>best[0]['dev_mean']:best=(row,dict(mx=mx.astype(np.float32),a=a,b=b,y0=y0,v=np.array(v)))
    fn=w/'linear.npz';np.savez_compressed(fn,**best[1]);ob=dict(selected=best[0],candidates=records,sha256=hashlib.sha256(fn.read_bytes()).hexdigest(),wall_s=time.perf_counter()-t,cpu_s=time.process_time()-c0,numerical_note='float64 covariance/eigendecompositions, float32 factors')
    write(w/'linear.json',ob);print(ob['selected'],ob['wall_s'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);run(p.parse_args().work)
