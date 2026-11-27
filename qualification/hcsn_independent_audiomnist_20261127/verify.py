"""Recount raw scores without fitting, rerouting or choosing any checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def diagnostic(z,y,sp):
    soft=np.exp((z-z.max(1)[:,None])*5);soft/=soft.sum(1)[:,None]
    correct=z.argmax(1)==y
    return {'accuracy':float(correct.mean()),'digit_macro_accuracy':float(np.mean([correct[y==i].mean() for i in range(10)])),
            'brier':float(((soft-np.eye(10)[y])**2).sum(1).mean()),
            'by_speaker':{str(s):float(correct[sp==s].mean()) for s in sorted(set(sp))}}


def contrast(by_arm,ref_arm,draws):
    delta={}
    for split in ('old','new'):
        a=np.array([list(o[split]['by_speaker'].values()) for o in by_arm])
        b=np.array([list(o[split]['by_speaker'].values()) for o in ref_arm])
        per=a-b;paired=per.mean(0);boots=paired[draws[split]].mean(1)
        delta[split]={'delta_pp':float(100*paired.mean()),'cluster_bootstrap95_pp':(100*np.quantile(boots,[.025,.975])).tolist(),'per_parent_pp':(100*per.mean(1)).tolist()}
    return delta


def main():
    parser=argparse.ArgumentParser();parser.add_argument('models',type=Path);parser.add_argument('scores',type=Path);parser.add_argument('seal',type=Path);parser.add_argument('out',type=Path)
    a=parser.parse_args();seeds=[271,577,911];budgets=[3,15,45];arms=['direct','wrong','bp','lora']
    booked=json.loads(a.seal.read_bytes());results={};reference_ids={};fitted={}
    for seed in seeds:
        for name,budget in [('keep',0)]+[(v,b) for b in budgets for v in arms]:
            key=f'{name}_{seed}_{budget}';file=a.scores/(key+'.npz');meta=json.loads(file.with_suffix('.json').read_bytes())
            assert sha(file)==meta['pred_sha256']
            if name!='keep':
                p=a.models/(key+'.json');assert sha(p)==booked['fits'][p.name];history=json.loads(p.read_bytes())
                assert history['selected'] is None or history['history'][history['selected']]['cpu']<=budget
                fitted[key]={'cpu':history['cpu'],'wall':history['wall'],'selected':history['selected'],'changed':history['changed'],'development_evaluations':len(history['history']),'admissible':history['admissible']}
            with np.load(file) as f:
                item={}
                for split in ('old','new'):
                    y=f[split+'_label'];sp=f[split+'_speaker'];rec=f[split+'_record'];z=f[split+'_scores']
                    if split not in reference_ids:reference_ids[split]=(y,sp,rec)
                    assert all(np.array_equal(q,r) for q,r in zip((y,sp,rec),reference_ids[split]))
                    assert len(set(rec))==len(y) and z.shape==(len(y),10)
                    item[split]=diagnostic(z,y,sp)
                item['cold_cpu']=meta['cpu_seconds'];item['cold_wall']=meta['wall_seconds'];results[key]=item
    rng=np.random.default_rng(12089);draws={}
    for split,(y,sp,rec) in reference_ids.items():
        n=len(set(sp));draws[split]=rng.integers(n,size=(20000,n))
    contrasts={};against_keep={}
    keep=[results[f'keep_{seed}_0'] for seed in seeds]
    for budget in budgets:
        cand={arm:[results[f'{arm}_{s}_{budget}'] for s in seeds] for arm in arms}
        for arm in arms:
            v=contrast(cand[arm],keep,draws)
            v['passes_both_by_parent']=[bool(n>=2.-1e-10 and o>=-2.-1e-10) for n,o in zip(v['new']['per_parent_pp'],v['old']['per_parent_pp'])]
            v['confirmatory_all_parents']=all(v['passes_both_by_parent'])
            against_keep[f'{arm}_{budget}']=v
        for op in ('bp','lora','wrong'):
            contrasts[f'direct_minus_{op}_{budget}']=contrast(cand['direct'],cand[op],draws)
    out={'seal_sha256':sha(a.seal),'new_unique_recordings':len(reference_ids['new'][0]),'old_unique_recordings':len(reference_ids['old'][0]),'seeds':seeds,'budgets':budgets,'cold_fits':len(results),'total_class_scores':len(results)*10*sum(len(v[0]) for v in reference_ids.values()),'per_model':results,'vs_keep':against_keep,'paired_arms':contrasts,'calibration_costs':fitted,'bootstrap_seed':12089,'bootstrap_repetitions':20000}
    a.out.write_text(json.dumps(out,indent=2,sort_keys=True,allow_nan=False)+'\n')
    print('cold models',len(results),'score entries',out['total_class_scores'])


if __name__=='__main__':main()
