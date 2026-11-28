"""Reproduce paired speaker results from logits alone; attach measured cold and adaptation clocks."""
import argparse
import json
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.special import softmax
def content(p):return json.loads(p.read_text())
def data(p):
    with np.load(p) as f:return dict(f)
def run(a):
    seeds=(271,577,911);archs=('literal','smooth');groups=('old','A','B','C')
    methods=('keep','joint','receiver','bp','lora','ridge','wrong','lm_joint','lm_receiver','lbfgs');rungs=(3,15,60)
    reference=data(a.cold/'targets.npz');agg={};val={};timing={};choices={};macro={};mic={}
    wpre=content(a.prior/'data.json')['wall_seconds'];fresh=content(a.fresh/'preparation.json')['splits']
    for arch in archs:
        for seed in seeds:
            root=a.models/f'{arch}_{seed}';pred=data(a.cold/f'{arch}_{seed}.npz');timer=content(a.cold/f'{arch}_{seed}.json');parent=content(root/'parent.json')
            for m in methods:
                params=None if m=='keep' else content(root/(m+'.json'))['picks']
                for b in rungs:
                    ident=f'{m}_{0 if m=="keep" else b}';key=(arch,seed,m,b)
                    choices[key]=None if params is None else params[str(b)]['selection']
                    elapsed=0 if params is None else params[str(b)]['wall_upper']
                    tm=timer[ident]['both'][1]+elapsed
                    timing[key]=dict(all_three_cold_s=timer[ident]['all_three'][1]+elapsed+parent['study_prep']['wall']+parent['parent_fit']['wall']+wpre+sum(fresh[g]['wall'] for g in ('A','B'))+content(a.fresh/'third.json')['extraction_and_features_wall'],adaptation_wall_upper_s=elapsed, warm_parent_both_evaluations_s=tm+parent['study_prep']['wall'],
                                     full_from_waveform_s=tm+parent['study_prep']['wall']+parent['parent_fit']['wall']+wpre+sum(fresh[g]['wall'] for g in ('A','B')))
                    for g in groups:
                        z=pred[ident+'_'+g]; y=reference[g+'_y']; s=reference[g+'_speaker']
                        correctness=z.argmax(1)==y
                        by=np.array([correctness[s==sp].mean() for sp in np.unique(s)])
                        agg[key+(g,)]=by
                        val[key+(g,)]=float(by.mean());mic[key+(g,)]=float(correctness.mean());macro[key+(g,)]=float(np.mean([correctness[y==label].mean() for label in range(10)]))
    @lru_cache(maxsize=8)
    def draws(n):
        return np.random.default_rng(440334).integers(n,size=(10000,n),dtype=np.int32)
    def boot(v):
        idx=draws(v.shape[-1])
        # Conditional on fixed parent models; resample independent speaker clusters.
        diff=v.mean(0)
        return dict(mean=float(diff.mean()),ci=np.quantile(diff[idx].mean(1),[.025,.975]).tolist())
    summary=[]
    for arch in archs:
        for m in methods:
            for b in rungs:
                keys=[(arch,s,m,b) for s in seeds]
                def arr(h,g,arch0=arch):return np.array([agg[(arch0,s,h,b,g)] for s in seeds])
                checks=[];contrasts={}
                for g in groups:
                    M=arr(m,g);K=arr('keep',g)
                    contrasts[g]={'vs_keep':boot(M-K),'vs_bp':boot(M-arr('bp',g)),'vs_other_law':boot(M-arr(m,g,'smooth' if arch=='literal' else 'literal')),
                                  'vs_receiver':boot(M-arr('receiver',g)),'vs_lm_receiver':boot(M-arr('lm_receiver',g)),'vs_lbfgs':boot(M-arr('lbfgs',g)),
                                  'vs_lora':boot(M-arr('lora',g)),'vs_ridge':boot(M-arr('ridge',g))}
                for s in seeds:
                    delta={g:val[(arch,s,m,b,g)]-val[(arch,s,'keep',b,g)] for g in groups}
                    checks.append(delta['old']>=-.02-1e-12 and min(delta['A'],delta['B'])>=.02-1e-12)
                cells={g:[val[k+(g,)] for k in keys] for g in groups}
                times={k:[timing[x][k] for x in keys] for k in timing[keys[0]]}
                summary.append(dict(arch=arch,method=m,rung=b,seed_accuracies=cells,avg={g:float(np.mean(v)) for g,v in cells.items()},contrasts=contrasts,
                                    third_domain_gate=(min(val[(arch,s,m,b,'C')]-val[(arch,s,'keep',b,'C')] for s in seeds)>=.02-1e-12 and contrasts['C']['vs_keep']['ci'][0]>0),third_equal_class=[macro[k+('C',)] for k in keys],third_micro=[mic[k+('C',)] for k in keys],passes=int(sum(checks)),quality_gate=all(checks) and all(contrasts[g]['vs_keep']['ci'][0]>0 for g in ('A','B')),
                                    dev_picks=[choices[k] for k in keys],times=times,median_cold_s=float(np.median(times['full_from_waveform_s']))))
    (a.out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    frontiers=[]
    for arch in archs:
        for active in ('joint','lm_joint','receiver','lm_receiver','ridge','lora'):
            for comparator in ('bp','lbfgs'):
                selected=[]
                for method in (active,comparator):
                    candidates=[r for r in summary if r['arch']==arch and r['method']==method and r['quality_gate']]
                    selected.append(min(candidates,key=lambda r:r['rung']) if candidates else None)
                c,b=selected
                stats=dict(arch=arch,method=active,comparator=comparator,editor_rung=c['rung'] if c else None,comparator_rung=b['rung'] if b else None)
                if c and b:
                    paired={}
                    for g in groups:
                        v=np.array([agg[(arch,s,active,c['rung'],g)]-agg[(arch,s,comparator,b['rung'],g)] for s in seeds])
                        paired[g]=boot(v)
                    ratio=c['median_cold_s']/b['median_cold_s']
                    noninferior=all(paired[g]['ci'][0]>=-.02 for g in ('A','B'))
                    stats.update(cold_ratio=ratio,seconds=[c['median_cold_s'],b['median_cold_s']],paired=paired,
                                 additional_common_seconds_before_20pct_limit=4*b['median_cold_s']-5*c['median_cold_s'],
                                 warm_ratio=float(np.median(c['times']['warm_parent_both_evaluations_s'])/np.median(b['times']['warm_parent_both_evaluations_s'])),
                                 supported=bool(noninferior and ratio<=.8))
                else:stats.update(supported=False,reason='at least one arm has no qualifying rung')
                frontiers.append(stats)
    (a.out/'matched.json').write_text(json.dumps(frontiers,indent=2,allow_nan=False)+'\n')
    for row in summary:
        if row['rung']==60:print(row['arch'],row['method'],row['avg'],row['passes'],flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('models','prior','fresh','cold','out'):p.add_argument(n,type=Path)
    a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True);run(a)
