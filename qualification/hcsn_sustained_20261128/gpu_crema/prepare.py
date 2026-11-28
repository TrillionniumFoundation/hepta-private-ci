"""Prepare label-independent low-bandwidth representations of every original clip."""
import hashlib
import io
import json
import lzma
from pathlib import Path
import sys
import numpy as np


def sha(b):
    return hashlib.sha256(b).hexdigest()


def pack(source,out):
    with source.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'
    with np.load(source,allow_pickle=False) as z:
        ids=z['ids'];split=z['split'];tokens=z['tokens'];labels=z['labels']
        v=z['images'];a=z['audio'].astype('float32')
    train=split==0
    assert [np.sum(split==j) for j in range(3)]==[4984,1147,1311]
    n=len(split)
    assert v.shape==(n,12,28,28) and a.shape==(n,12,64)
    mean=a[train].mean((0,1),dtype='float64').astype('float32')
    sd=a[train].std((0,1),dtype='float64').clip(.01).astype('float32')
    v4=v.reshape(n,4,3,2,14,2,14).mean((2,4,6),dtype='float32').reshape(n,4,4)
    a4=((a-mean)/sd).reshape(n,4,3,4,16).mean((2,4),dtype='float32')
    raw=np.concatenate((v4,a4),axis=2)
    assert np.isfinite(raw).all()
    codes=np.empty(raw.shape,dtype='uint8');cuts=np.zeros((8,15),dtype='float32')
    levels=np.zeros((8,16),dtype='float32')
    for j in range(8):
        val=raw[:,:,j]
        edges=np.quantile(val[train],np.arange(1,16)/16).astype('float32')
        ix=np.searchsorted(edges,val,side='right');codes[:,:,j]=ix
        cuts[j]=edges
        for k in range(16):
            vals=val[train][ix[train]==k]
            levels[j,k]=vals.mean(dtype='float64') if len(vals) else np.quantile(val[train],(k+.5)/16)
    flat=codes.reshape(n,-1)
    packed=(flat[:,::2]<<4)|flat[:,1::2]
    arrays={'nibbles':packed,'ids':ids,'split':split,'labels':labels,'tokens':tokens,'levels':levels,
            'edges':cuts,'audio_train_mean':mean,'audio_train_sd':sd}
    b=io.BytesIO();np.savez(b,**arrays);blob=lzma.compress(b.getvalue(),preset=9)
    out.mkdir(exist_ok=True,parents=True)
    (out/'all.xz').write_bytes(blob)
    meta={'source_sha':'18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad',
          'sha':sha(blob),'bytes':len(blob),'source_samples':n,
          'arrays':{k:{'sha':sha(v.tobytes()),'shape':list(v.shape),'dtype':str(v.dtype)} for k,v in arrays.items()}}
    (out/'data_identity.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(len(blob),meta['sha'],flush=True)


if __name__=='__main__':
    pack(Path(sys.argv[1]),Path(sys.argv[2]))
