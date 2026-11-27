"""Independent equal-exposure and simultaneous-seed timing summaries from saved per-image costs."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np

ARMS=('physical','smooth','mean','dense')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def point(a,n):return float(a.sum()/n.sum())
def interval(x,n,indices):
    per=x.sum(1);tokens=n.sum(1)
    b=per[indices].sum(1)/tokens[indices].sum(1)
    return [point(x,n),*np.quantile(b,[.025,.975]).tolist()]
def main(base,replay,out):
    seal=json.loads((base/'seal.json').read_text());scores=json.loads((base/'result.json').read_text())
    agg=json.loads((replay/'replay.json').read_text())
    assert sha(base/'seal.json')==scores['seal']==agg['original_seal_sha256']
    with np.load(base/'predictions.npz') as p:counts=p['tokens'].copy()
    idx=np.random.default_rng(650037).integers(0,len(counts),(4000,len(counts)))
    whole={'device':agg['device'],'accepted_cells':agg['successful'],'source':sha(replay/'replay.json'),'size':{}}
    for width in sorted(set(k.split('-')[0] for k in agg['matrix'])):
        ranked={};timed={}
        seeds=sorted({int(k.split('-')[1]) for k in agg['matrix']})
        for label in [f'{t}{r}' for t in ('time','equal') for r in seal['caps']]:
            per={};payload={}
            for arm in ARMS:
                cells=[];swapped=[];tokens=[];st=[];timepaid=[]
                for sd in seeds:
                    key=f'{width}-{sd}-{arm}';m=agg['matrix'][key]
                    p=replay/(key+'.npz');assert m['predictions_sha256']==sha(p)
                    if not m['valid']:continue
                    inf=m['by_rung'][label];tokens.append(inf['nonpadding_training_tokens']);st.append(inf['step'])
                    with np.load(p) as data:
                        assert np.array_equal(data['tokens'],counts);cells.append(data[label]);swapped.append(data[label+'-shuffled'])
                    if label.startswith('time'):
                        rung=int(label[4:]);orig=seal['models'][key]
                        a=next(y for y in orig['history'] if y['requested_s']==rung)
                        cost=scores['per_model_times'][key]
                        timepaid.append(dict(optimizer=a['optimizer_wall_s'],fit_to_observed=a['elapsed_fit_wall_s'],
                                             single_setup_fit_and_cold=seal['setup_wall_s']+a['elapsed_fit_wall_s']+cost['cold_load_and_hash_s']+cost['aligned_s']))
                if not cells:continue
                cold=np.stack(cells);wrong=np.stack(swapped);per[arm]=cold.mean(0)
                payload[arm]=dict(valid_seeds=len(cells),selected_group_seeds=seeds if len(cells)==len(seeds) else None,
                    per_seed_nll=[point(c,counts) for c in cold],per_seed_fit_tokens=tokens,per_seed_steps=st,
                    nll=interval(per[arm],counts,idx),grounding_gain=interval((wrong-cold).mean(0),counts,idx),timepaid=timepaid)
                if label.startswith('time'):timed.setdefault(arm,[]).append((rung,payload[arm]))
            if label.startswith('equal') and all(a in payload and payload[a]['valid_seeds']==len(seeds) for a in ARMS):
                assert len({tuple(payload[a]['per_seed_fit_tokens']) for a in ARMS})==1
            for arm in ARMS:
                if arm in per and 'physical' in per and all(payload[a]['valid_seeds']==len(seeds) for a in (arm,'physical')):
                    payload[arm]['physical_minus_arm_nll']=interval(per['physical']-per[arm],counts,idx)
            ranked[label]=payload
        result={}
        for arm,values in timed.items():
            result[arm]={}
            for t in (1,.85,.70,.60):
                first=next(((r,rec) for r,rec in values if rec['valid_seeds']==len(seeds) and max(rec['per_seed_nll'])<=t),None)
                result[arm][str(t)]=dict(first_observed_rung=first[0],per_seed_time=first[1]['timepaid']) if first else dict(right_censored=True,last_observed_rung=values[-1][0])
        whole['size'][width]={'curves':ranked,'all_seed_test_levels':result}
    out.write_text(json.dumps(whole,indent=2)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('base','replay','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();main(a.base,a.replay,a.out)
