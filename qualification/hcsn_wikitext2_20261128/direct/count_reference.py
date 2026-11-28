"""Train-only unigram and fixed-.75 absolute-discount continuation bigram references."""
import argparse
import json
from pathlib import Path
import time
import numpy as np


def run(root):
    t=time.perf_counter();v=json.loads((root/'data.json').read_text())['vocab']
    ref=np.load(root/'train.npy').astype(np.int64)
    left,right=ref[:-1],ref[1:];offset=left*v+right
    pairs,freq=np.unique(offset,return_counts=True)
    ctx=np.bincount(left,minlength=v)
    distinct=np.bincount(pairs//v,minlength=v)
    cont=np.bincount(pairs%v,minlength=v)+.1;cont/=cont.sum()
    uni=np.bincount(right,minlength=v)+.1;uni/=uni.sum()
    elapsed=time.perf_counter()-t
    report={}
    for spl in ('valid','test'):
        data=np.load(root/(spl+'.npy')).astype(np.int64);i,j=data[:-1],data[1:];keys=i*v+j
        idx=np.minimum(np.searchsorted(pairs,keys),len(pairs)-1)
        f=freq[idx]*(pairs[idx]==keys)
        p=(np.maximum(f-.75,0)+.75*distinct[i]*cont[j])/np.maximum(ctx[i],1)
        p=np.where(ctx[i]>0,p,cont[j])
        def score(x):
            nll=-float(np.log(x).mean());return dict(nll=nll,ppl=np.exp(nll))
        report[spl]=dict(targets=len(i),bigram=score(p),unigram=score(uni[j]))
    return dict(discount=.75,unigram_and_continuation_pseudocount=.1,training_targets=len(left),
                distinct_train_bigrams=len(pairs),train_seconds=elapsed,splits=report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);z=p.parse_args()
    (z.root/'direct'/'count_reference.json').write_text(json.dumps(run(z.root),indent=2)+'\n')
