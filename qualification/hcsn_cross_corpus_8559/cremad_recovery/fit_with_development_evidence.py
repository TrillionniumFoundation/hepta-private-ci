"""Run the unchanged original optimizer while preserving its exact aligned development logits."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np


def main(root,arm,width,seed):
    import torch
    sys.path.insert(0,str(root/'src'))
    import run as original
    assert hashlib.sha256((root/'src/run.py').read_bytes()).hexdigest()=='d76c1583d81c130c2ba3a0f9cc0070b4fc88817f09fa42d2b7abab599cb7632c'
    torch.set_num_threads(1);factual=original.inference
    dest=root/'recovery-8559'/'dev'/f'{width}-{seed}-{arm}';dest.mkdir(parents=True,exist_ok=True)
    events=[]
    def observe(net,d,ids,variants=False):
        values=factual(net,d,ids,variants)
        scores=values['aligned'];y=d.y[ids].cpu().numpy();keys=d.key[ids]
        short=keys=='1076_MTI_NEU_XX';assert short.sum()==1
        x=scores.astype(np.float64);mx=x.max(1)
        loss=mx+np.log(np.exp(x-mx[:,None]).sum(1))-x[np.arange(len(y)),y]
        i=len(events);path=dest/f'dev-{i}.npz'
        with path.with_suffix('.part').open('wb') as out:np.savez_compressed(out,scores=scores,labels=y,keys=keys)
        os.replace(path.with_suffix('.part'),path)
        events.append({'i':i,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'n':len(y),'nll':float(loss.mean()),'nll_without_short':float(loss[~short].mean()),'short_nll':float(loss[short].item())})
        original.dump(dest/'observations.json',events)
        return values
    original.inference=observe
    original.fit(root,arm,width,seed)
    record=json.loads((root/'fits'/f'{width}-{seed}-{arm}'/'fit.json').read_text())
    assert len(record['history'])==len(events)
    for e,r in zip(events,record['history']):
        assert abs(e['nll']-r['nll'])<1e-4
        e.update(steps=r['steps'],tags=r['tags'])
    original.dump(dest/'sensitivity.json',{'observations':events,'original_selected_steps':record['chosen']['steps'],
                 'without_short_selected_steps':min(events,key=lambda e:(e['nll_without_short'],e['steps']))['steps'],'wrapper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    print('complete with exact sensitivity',width,seed,arm,flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);ap.add_argument('arm');ap.add_argument('width',type=int);ap.add_argument('seed',type=int);a=ap.parse_args();main(a.root.resolve(),a.arm,a.width,a.seed)
