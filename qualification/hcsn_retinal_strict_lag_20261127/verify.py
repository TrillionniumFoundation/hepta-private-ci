"""Recount both retrospective endpoints without the training or neural-kernel packages."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args();d=a.directory
    result=json.loads((d/'RESULTS.json').read_bytes());seal=json.loads((d/'SEAL.json').read_bytes())
    assert sha(d/'SEAL.json')==json.loads((d/'SEAL_SHA.json').read_bytes())['sha256']==result['seal_sha256']
    assert sha(d/'strict_predictions.npz')==result['predictions_sha256']
    for arm,win in seal['selection'].items():
        v=seal['candidates'][arm];assert win==int(np.argmin([z['dev_bce'] for z in v]))
    with np.load(d/'strict_predictions.npz') as f:
        y=f['y'];rep=f['repeat'];groups=np.unique(rep);draw=np.random.default_rng(30588).integers(0,len(groups),(6000,len(groups)))
        loss=lambda v:-np.log(np.where(y,v,1-v))
        all_loss={}
        for key,s in result['metrics'].items():
            v=f[key];l=loss(v);all_loss[key]=l
            av=np.array([l[rep==j].mean() for j in groups])
            assert np.allclose(av,s['loss']['by_repeat'],atol=1e-13,rtol=0)
            assert abs(l.mean()-s['loss']['pooled'])<1e-13
            assert np.allclose(np.quantile(av[draw].mean(1),[.025,.975]),s['loss']['ci95'],atol=1e-13)
            brier=(v-y)**2;assert abs(brier.mean()-s['brier']['pooled'])<1e-13
        for key,m in result['paired'].items():
            left,right=key.split('_minus_');mode=left.split('_')[0];dif=all_loss[left]-all_loss[mode+'_'+right]
            av=np.array([dif[rep==j].mean() for j in groups]);assert np.allclose(av,m['by_repeat'],atol=1e-13)
            assert np.allclose(np.quantile(av[draw].mean(1),[.025,.975]),m['ci95'],atol=1e-13)
        for j in groups:
            s=result['trial_counts'][str(j)];assert s['events']==int((rep==j).sum()) and s['strict_positive']==int(y[rep==j].sum()) and s['original_positive']==int(f['old_y'][rep==j].sum())
    print(len(all_loss),'model/condition vectors;',len(result['paired']),'paired comparisons;',len(y)*len(all_loss),'scores verified')


if __name__=='__main__':main()
