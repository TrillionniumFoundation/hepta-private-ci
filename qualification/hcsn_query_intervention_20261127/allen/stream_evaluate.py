"""Identical preregistered test, scoring and storing one donor at a time."""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from estimate import collect,add_base_features,pred,IDX_NEW,HORIZONS,digest
from model import score

def run(data,cache,trained,out):
    out.mkdir(parents=True,exist_ok=True);seal=json.loads((trained/'SEAL.json').read_text());test=seal['ids'][16:]
    assert len(test)==8 and digest(data/'roster.json')==seal['roster_sha256']
    names=list(seal['selected']);all_scores={k:{n:[] for n in names} for k in '12'};all_h={k:{n:[] for n in names} for k in '12'}
    ticker={n:0. for n in names};start=time.monotonic()
    for sid in test:
        assert digest(data/f'{sid}.npz')==seal['source_sha256'][str(sid)] and digest(cache/f'{sid}.json')==seal['features_sha256'][str(sid)]
        records=collect(data,cache,[sid]);add_base_features(records,seal['pre']);outputs={}
        for m,choice in seal['selected'].items():
            t=time.monotonic();outputs[m]=pred(records,m,choice);ticker[m]+=time.monotonic()-t
        for ty in '12':
            indices=[j for j,r in enumerate(records) if r['slot'][0]==ty]
            for m in names:
                metrics=[score(outputs[m][j],records[j]['future']) for j in indices]
                all_scores[ty][m].append(np.mean([[ll[:,IDX_NEW].mean(),bb[:,IDX_NEW].mean()] for ll,bb in metrics],0))
                all_h[ty][m].append(np.mean([[ll.mean(0),bb.mean(0)] for ll,bb in metrics],0))
        for j,r in enumerate(records):
            np.savez_compressed(out/f"{sid}-{r['slot']}.npz",anchors=r['anchors'],targets=r['future'].astype(np.uint8),horizons=HORIZONS,
                                **{m:outputs[m][j] for m in names})
        print(sid,'complete',flush=True)
    rng=np.random.default_rng(855917);boot=rng.integers(0,8,(10000,8));report={}
    for ty in '12':
        sr={'scores':{},'literal_augmentation_vs':{},'per_horizon':{}}
        for m in names:
            val=np.array(all_scores[ty][m]);dd=np.array(all_scores[ty]['hazard+literal'])-val
            sr['scores'][m]={'mean_nll_brier':val.mean(0).tolist(),'by_specimen':dict(zip(map(str,test),val.tolist()))}
            sr['per_horizon'][m]=np.mean(all_h[ty][m],axis=0).tolist()
            sr['literal_augmentation_vs'][m]={'mean_nll_brier_delta':dd.mean(0).tolist(),
                'paired_donor_95':np.quantile(dd[boot].mean(1),[.025,.975],axis=0).tolist(),'cells_lower_nll':int((dd[:,0]<0).sum())}
        report[ty]=sr
    primary=report['2']['literal_augmentation_vs'];gate=all(primary[m]['paired_donor_95'][1][0]<0 and primary[m]['mean_nll_brier_delta'][1]<0 for m in ('hazard','hazard+free','hazard+fixed','hazard+tangent'))
    outp=dict(seal_sha256=digest(trained/'SEAL.json'),cells=test,outputs=report,broad_gate=gate,total_cold_wall_s=time.monotonic()-start,readout_times=ticker)
    (out/'results.json').write_text(json.dumps(outp,indent=2,allow_nan=False)+'\n')
    print('gate',gate,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for k in ('data','cache','trained','out'):p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();run(a.data,a.cache,a.trained,a.out)
