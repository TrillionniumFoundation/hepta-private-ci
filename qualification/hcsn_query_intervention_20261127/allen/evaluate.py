"""Cold donor- and horizon-disjoint scoring with paired-cell uncertainty."""
import argparse
from pathlib import Path
import json
import time
import numpy as np
from estimate import collect,add_base_features,pred,IDX_NEW,HORIZONS,mean_log,digest
from model import score

def run(data,cache,trained,out):
    out.mkdir(parents=True,exist_ok=True);seal=json.loads((trained/'SEAL.json').read_text())
    assert digest(data/'roster.json')==seal['roster_sha256'];test=seal['ids'][16:]; assert len(test)==8
    for i in test:assert digest(data/f'{i}.npz')==seal['source_sha256'][str(i)] and digest(cache/f'{i}.json')==seal['features_sha256'][str(i)]
    t=time.monotonic();rs=collect(data,cache,test);add_base_features(rs,seal['pre'])
    forecasts={};times={}
    for m,choice in seal['selected'].items():
        tic=time.monotonic();forecasts[m]=pred(rs,m,choice);times[m]=time.monotonic()-tic
    outputs={};rng=np.random.default_rng(855917);bootstrap=rng.integers(0,8,(10000,8));names=list(forecasts)
    def donor_scores(typ):
        ids=[j for j,r in enumerate(rs) if r['slot'][0]==typ]
        donor={};per_h={}
        for m in names:
            vals=[];detail=[]
            for sid in test:
                rows=[j for j in ids if rs[j]['sid']==sid];parts=[score(forecasts[m][j],rs[j]['future']) for j in rows]
                detail.append(np.mean([[ll.mean(0),bb.mean(0)] for ll,bb in parts],0))
                vals.append(np.mean([[ll[:,IDX_NEW].mean(),bb[:,IDX_NEW].mean()] for ll,bb in parts],0))
            donor[m]=np.asarray(vals);per_h[m]=np.mean(detail,0).tolist()
        return donor,per_h
    for ty in ('1','2'):
        donor,per_h=donor_scores(ty)
        report={'scores':{},'literal_augmentation_vs':{},'per_horizon':per_h}
        for m,val in donor.items():
            report['scores'][m]={'mean_nll_brier':val.mean(0).tolist(),'by_specimen':dict(zip(map(str,test),val.tolist()))}
            d=donor['hazard+literal']-val
            report['literal_augmentation_vs'][m]={'mean_nll_brier_delta':d.mean(0).tolist(),'paired_donor_95':np.quantile(d[bootstrap].mean(1),[.025,.975],axis=0).tolist(),
                                                   'cells_lower_nll':int((d[:,0]<0).sum())}
        outputs[ty]=report
    for k,r in enumerate(rs):
        # Binary outcomes suffice for these one-trial sweeps; pack IEEE-FP32 probabilities unchanged.
        np.savez_compressed(out/f"{r['sid']}-{r['slot']}.npz",anchors=r['anchors'],targets=r['future'].astype(np.uint8),
                            horizons=HORIZONS,**{m:forecasts[m][k] for m in names})
    primary=outputs['2']['literal_augmentation_vs']
    broad=all(primary[m]['paired_donor_95'][1][0]<0 and primary[m]['mean_nll_brier_delta'][1]<0 for m in ('hazard','hazard+free','hazard+fixed','hazard+tangent'))
    result={'seal_sha256':digest(trained/'SEAL.json'),'cells':test,'outputs':outputs,'broad_gate':broad,'total_cold_wall_s':time.monotonic()-t,'readout_times':times}
    (out/'results.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print('primary',broad,{m:q['mean_nll_brier'] for m,q in outputs['2']['scores'].items()})
if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for k in ('data','cache','trained','out'):ap.add_argument('--'+k,type=Path,required=True)
    a=ap.parse_args();run(a.data,a.cache,a.trained,a.out)
