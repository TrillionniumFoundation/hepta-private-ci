"""Verify every development substitution metric from retained per-photo losses."""
from hashlib import sha256
import json
from pathlib import Path
import numpy as np


def main():
    here=Path(__file__).resolve().parent;r=json.loads((here/'frozen_results.json').read_text());p=here/'per_image.npz'
    assert sha256(p.read_bytes()).hexdigest()==r['array_sha256']
    assert r['source']==sha256((here/'frozen_diagnostic.py').read_bytes()).hexdigest()
    with np.load(p,allow_pickle=False) as z:
        c=z['counts'];assert len(c)==256 and len(set(z['ids']))==256 and c.sum()==r['tokens'] and (c>0).all()
        seeds=sorted(map(int,r['weights']));base=np.stack([z[f'{s}_1_correct'] for s in seeds]).mean(0)
        ix=np.random.default_rng(20261127191).integers(len(c),size=(5000,len(c)))
        for n in [1,2,4]:
            loss=[];sft=[]
            for seed in seeds:
                key=f'{seed}_{n}';a=z[key+'_correct'];b=z[key+'_shifted'];assert np.isfinite(a).all() and np.isfinite(b).all()
                assert abs(a.sum()/c.sum()-r['per_model'][key]['nll'])<1e-12
                assert abs((b-a).sum()/c.sum()-r['per_model'][key]['conditioning_gain'])<1e-12
                loss.append(a);sft.append(b)
            a=np.mean(loss,0);b=np.mean(sft,0);delta=a-base;s=r['summary'][str(n)]
            assert max(abs(a.sum()/c.sum()-s['nll']),abs((b-a).sum()/c.sum()-s['conditioning_gain']),abs(delta.sum()/c.sum()-s['minus_n1']))<1e-12
            ci=np.quantile(delta[ix].sum(1)/c[ix].sum(1),[.025,.975]);assert np.allclose(ci,s['paired_image_95'],atol=1e-12,rtol=0)
    print('9 fixed models and all paired bootstrap summaries agree;',r['tokens'],'caption tokens')


if __name__=='__main__':main()
