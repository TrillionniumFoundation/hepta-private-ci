"""Quantify reconstruction losses of the fixed label-free pooled representations."""
import hashlib
import io
import json
import lzma
from pathlib import Path
import sys

import numpy as np


def evaluate(raw_path,packed_path):
    with raw_path.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='18423277257e2e487521d83a8c116bc7cf5599411f4ff769e569bd849beae6ad'
    with np.load(raw_path,allow_pickle=False) as original:
        image=original['images'];audio=original['audio'];split=original['split']
    with np.load(io.BytesIO(lzma.decompress(packed_path.read_bytes()))) as p:
        raw=p['nibbles'];lev=p['levels'];mu=p['audio_train_mean'];sd=p['audio_train_sd']
    codes=np.stack((raw>>4,raw&15),axis=-1).reshape(len(raw),4,8)
    features=lev[np.arange(8)[None,None,:],codes]
    # Accumulate original scalar moments and both loss terms by source fold.
    panel={}
    for fold in (0,1,2):
        selected=np.flatnonzero(split==fold)
        sums={k:np.zeros(5,dtype=np.float64) for k in ('video','audio')}
        for start in range(0,len(selected),64):
            rows=selected[start:start+64];n=len(rows)
            v=image[rows].reshape(n,4,3,2,14,2,14).astype('float32')
            a=((audio[rows]-mu)/sd).reshape(n,4,3,4,16)
            rec_v=features[rows,:,:4].reshape(n,4,1,2,1,2,1);rec_a=features[rows,:,4:].reshape(n,4,1,4,1)
            for name,x,w,axis in (('video',v,rec_v,(2,4,6)),('audio',a,rec_a,(2,4))):
                m=x.mean(axis=axis,keepdims=True,dtype='float64')
                s=sums[name]
                s[0]+=x.size;s[1]+=x.sum(dtype='float64');s[2]+=np.square(x,dtype='float64').sum()
                s[3]+=np.square(x-m).sum();s[4]+=np.square(x-w,dtype='float64').sum()
        result={}
        for k,(count,sm,ss,pool,total) in sums.items():
            variance=ss/count-(sm/count)**2
            result[k]={'count':int(count),'input_sd':float(np.sqrt(variance)),
                'rmse_pooling_only':float(np.sqrt(pool/count)),'rmse_pooled_and_quantized':float(np.sqrt(total/count)),
                'original_variance_explained':float(1-total/(variance*count)),
                'fraction_of_squared_error_from_pooling':float(pool/total)}
        panel[str(fold)]=result
    return panel


if __name__=='__main__':
    result=evaluate(Path(sys.argv[1]),Path(sys.argv[2]))
    Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\n')
