"""Shared train-only PCA whitening followed by regularized paired CCA."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from scipy import sparse
from score import score_embeddings


def image_features(pixels):
    y=pixels.reshape(-1,8,4,8,4,3).astype(np.float32)/255
    return np.concatenate([y.mean((2,4)).reshape(len(y),-1),y.std((2,4)).reshape(len(y),-1)],axis=1)


def bow(tokens,v):
    a=tokens.reshape(-1,tokens.shape[-1]);mask=a>0;i,j=np.nonzero(mask)
    c=sparse.csr_matrix((np.ones(len(i),np.float32),(i,a[i,j])),shape=(len(a),v))
    c.data=np.log1p(c.data);return c


def unit(x):
    return x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-10)


def project(model,images,tokens):
    x=(image_features(images)-model['mx'])@model['a']
    y=(bow(tokens,int(model['v']))@model['b'])-model['y0']
    return unit(x),unit(y)


def run(work):
    t0=time.perf_counter();c0=time.process_time()
    with np.load(work/'input.npz') as data:
        splits=data['split']; ix=np.flatnonzero(splits==0); dev=np.flatnonzero(splits==1)
        images=data['images'];t=data['tokens'];v=int(data['vocab']);g=data['groups']
    x=image_features(images[ix]);mx=x.mean(0);x=x-mx
    all_y=bow(t[ix],v);f=np.asarray(all_y.mean(0)).ravel()
    n=len(ix)
    # Identical image on all five caption rows. Compute each caption's covariance in full.
    cx=(x.T@x/n).astype(np.float64)
    cy=((all_y.T@all_y).toarray()/(5*n)-np.outer(f,f)).astype(np.float64)
    cxy=np.zeros((x.shape[1],v))
    for k in range(5):cxy+=(all_y[k::5].T@x).T/(5*n)
    lx,ux=np.linalg.eigh(cx);ly,uy=np.linalg.eigh(cy)
    ax=ux[:,lx>1e-9];lx=lx[lx>1e-9];ay=uy[:,ly>1e-9];ly=ly[ly>1e-9]
    cross=ax.T@cxy@ay
    best=None;records=[]
    for ridge in (.01,.1,1.0):
        wx=1/np.sqrt(lx+ridge*np.mean(lx));wy=1/np.sqrt(ly+ridge*np.mean(ly))
        u,sv,vt=np.linalg.svd(wx[:,None]*cross*wy[None,:],full_matrices=False)
        for rank in (16,32,64):
            a=(ax*wx)@u[:,:rank];b=(ay*wy)@vt[:rank].T
            model=dict(mx=mx,a=a.astype(np.float32),b=b.astype(np.float32),y0=(f@b).astype(np.float32),v=np.array(v))
            im,tx=project(model,images[dev],t[dev,0]);sc=score_embeddings(im,tx,g[dev,0])[:,:,0].mean()
            records.append(dict(ridge=ridge,rank=rank,dev_concordance=float(sc)))
            if best is None or sc>best[0]:best=(sc,model,records[-1])
    path=work/'linear.npz';np.savez_compressed(path,**best[1])
    receipt=dict(selected=best[2],candidates=records,wall_s=time.perf_counter()-t0,cpu_s=time.process_time()-c0,sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    (work/'linear.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(receipt['selected'],receipt['wall_s'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('work',type=Path);run(p.parse_args().work)
