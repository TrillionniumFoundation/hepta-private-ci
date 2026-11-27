"""Evaluate the registered comparisons by resampling paired seeds and held-out images."""
from pathlib import Path
import math
import time

import numpy as np
from fit import ARMS, CONFIRM, ROOT, SRC, json_file, sha, write_json


def values(arm,seed,assignment,tune,sealed,split='test'):
    from fit import run_path
    d=run_path('confirm',arm,seed,tune['rates'][arm])
    frozen=sealed['assignments'][d.name]
    rec=frozen['assignment'].get(assignment)
    if rec is None:return None
    cold=json_file(d/'cold.json')
    assert cold['seal']==sha(ROOT/'evaluation_seal.json') and cold['references'][assignment]==rec['state']
    name='cold-'+rec['state'][:16]+'.npz'
    assert sha(d/name)==cold['arrays'][name]
    with np.load(d/name,allow_pickle=False) as z:
        return dict(loss=z[split+'_sum'].copy(),gain=z[split+'_swapped']-z[split+'_sum'],counts=z[split+'_counts'].copy(),
                    ids=z[split+'_ids'].copy(),seconds=rec['seconds'],steps=rec['steps'],tokens=rec['tokens'],stage=rec['stage'])


def summarize_candidate(arm,assignment,tune,sealed):
    all_seeds={s:values(arm,s,assignment,tune,sealed) for s in CONFIRM}
    present=[s for s,v in all_seeds.items() if v is not None]
    if not present:return {'attained':0,'censored':list(CONFIRM)}
    n=all_seeds[present[0]]['counts']
    stats={str(s):{'nll':float(all_seeds[s]['loss'].sum()/n.sum()),'gain':float(all_seeds[s]['gain'].sum()/n.sum()),
        'seconds':all_seeds[s]['seconds'],'stage':all_seeds[s]['stage'],'steps':all_seeds[s]['steps'],'tokens':all_seeds[s]['tokens']} for s in present}
    return {'attained':len(present),'censored':[s for s in CONFIRM if s not in present],
            'test_nll':float(np.mean([r['nll'] for r in stats.values()])),'conditioning_gain':float(np.mean([r['gain'] for r in stats.values()])),
            'per_seed':stats}


def paired(control,assignment,tune,sealed):
    treated=[];baseline=[];seeds=[]
    for seed in CONFIRM:
        a=values('grouped_hcsn',seed,assignment,tune,sealed)
        b=values(control,seed,assignment,tune,sealed)
        if a is None or b is None:continue
        assert np.array_equal(a['counts'],b['counts']) and np.array_equal(a['ids'],b['ids'])
        if treated:assert np.array_equal(a['ids'],treated[0]['ids']) and np.array_equal(a['counts'],treated[0]['counts'])
        treated.append(a);baseline.append(b);seeds.append(seed)
    out={'paired_n':len(seeds),'censored_pair_seeds':[s for s in CONFIRM if s not in seeds],'paired_seeds':seeds}
    if not seeds:return out
    n=treated[0]['counts']
    assert len(n)==800
    gap=np.stack([a['loss']-b['loss'] for a,b in zip(treated,baseline)])
    benefit=np.stack([a['gain'] for a in treated])
    log_speed=np.asarray([math.log(b['seconds']/a['seconds']) for a,b in zip(treated,baseline)])
    rng=np.random.default_rng(2026112719)
    resampled=[]; gain_samples=[]; ratios=[]
    for _ in range(50):
        seed_ix=rng.integers(len(seeds),size=(100,len(seeds)))
        image_ix=rng.integers(len(n),size=(100,len(n)))
        loss_set=gap[seed_ix].mean(axis=1)
        gain_set=benefit[seed_ix].mean(axis=1)
        denom=n[image_ix].sum(axis=1)
        resampled.extend(np.take_along_axis(loss_set,image_ix,axis=1).sum(axis=1)/denom)
        gain_samples.extend(np.take_along_axis(gain_set,image_ix,axis=1).sum(axis=1)/denom)
        ratios.extend(np.exp(log_speed[seed_ix].mean(axis=1)))
    out.update(nll_difference=float(gap.mean(axis=0).sum()/n.sum()),
        paired_nll_95=np.quantile(resampled,[.025,.975]).tolist(),
        conditioning_gain=float(benefit.mean(axis=0).sum()/n.sum()), conditioning_95=np.quantile(gain_samples,[.025,.975]).tolist(),
        comparator_over_grouped_first_observed=float(np.exp(log_speed.mean())),
        time_ratio_seed_95=np.quantile(ratios,[.025,.975]).tolist())
    return out


def main():
    tick=time.perf_counter()
    tuning=json_file(ROOT/'tuning_seal.json')
    seal=json_file(ROOT/'evaluation_seal.json')
    assert len(seal['assignments'])==72 and seal['tuning']==sha(ROOT/'tuning_seal.json')
    for k,h in seal['sources'].items():assert sha(SRC/k)==h
    axes=('best','0','1','2')
    arms={arm:{a:summarize_candidate(arm,a,tuning,seal) for a in axes} for arm in ARMS}
    contrasts={c:{a:paired(c,a,tuning,seal) for a in axes} for c in ARMS if c!='grouped_hcsn'}
    main_result=contrasts[tuning['control']]['0']
    criteria={'attained_in_both_at_least_10':main_result['paired_n']>=10,
          'heldout_noninferiority':bool(main_result.get('paired_nll_95',[0,math.inf])[1]<=.02),
          'speed_lower_above_one':bool(main_result.get('time_ratio_seed_95',[0])[0]>1),
          'speed_point_at_least_one_tenth_faster':main_result.get('comparator_over_grouped_first_observed',0)>=1.10,
          'positive_conditioning':main_result.get('conditioning_gain',0)>0}
    write_json(ROOT/'final.json',{'arms':arms,'contrasts':contrasts,'primary':main_result,'criteria':criteria,'passes':all(criteria.values()),
               'tuning':tuning,'seal':sha(ROOT/'evaluation_seal.json'),'cohort':sha(ROOT/'gallery/manifest.json'),
               'tuning_jobs':36,'confirmation_fits':72,'test_images':800,'development_images':320,'analysis_seconds':time.perf_counter()-tick})
    print('primary',criteria,main_result,flush=True)


if __name__=='__main__':
    main()
