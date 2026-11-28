"""Time-to-quality and paired held-out noninferiority at validation-selected rungs."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
ARMS=('literal','smooth','fixed','no_feedback','lif','cnn','attention')
SEEDS=(137,311,557)
RUNGS=(30,180,720,1800)
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def read(p):return json.loads(p.read_text())
def get(root,arm,seed,r):
    run=root/'runs'/f'{arm}-{seed}'/f'rung-{r}.json'
    if not run.exists():return None
    d=read(run);assert sha(run) in {m['receipt_sha256'] for m in read(root/'runs'/f'seal-{r}.json')}
    cold=root/f'cold-{r}'/f'{arm}-{seed}.json'
    return (d,read(cold)) if cold.exists() else None
def setup_time(root):
    return sum(read(root/'data'/f'{split}-data.json')['preprocessing_wall_s'] for split in ('train','test'))
def evaluate(root,out):
    prep=setup_time(root);sums={};assess={};sigs={}
    for target in (.60,.70,.80):
        times={};hit={}
        for arm in ARMS:
            records=[]
            for seed in SEEDS:
                observed=[];answer=None
                for r in RUNGS:
                    if not (root/'runs'/f'seal-{r}.json').exists():break
                    val=get(root,arm,seed,r)
                    if val is None:break
                    d,c=val;observed.append(r)
                    if d['best']['dev_macro']<target:continue
                    # The accounting starts from the original inputs. Report preprocessing separately for a warm cache.
                    current=d['fit_wall_s']+d['overhead_wall_s']+d['data_setup_wall_s']+c['input_setup_wall_s']+c['model_restore_wall_s']
                    costs=dict(fit_wall_s=d['fit_wall_s'],fit_cpu_s=d['fit_cpu_s'],selection_and_checkpoint_accounted_s=d['overhead_wall_s'],
                               training_data_setup_s=d['data_setup_wall_s'],test_data_setup_s=c['input_setup_wall_s'],restore_s=c['model_restore_wall_s'],
                               forward_natural_s=c['forward_wall_s']['natural'],test_all_views_s=sum(c['forward_wall_s'].values()),
                               prediction_write_hash_s=c.get('prediction_write_hash_wall_s'),cold_preprocessing_sum_s=prep)
                    coldfile=root/f'cold-{r}'/f'{arm}-{seed}.npz'
                    assert c['score_sha256']==sha(coldfile)
                    with np.load(coldfile) as z:
                        sign=z['natural'].argmax(1)==z['y']
                        meta=np.stack([z['row'],z['y'],z['speaker']])
                    hit[arm,seed]=(meta,sign)
                    answer=dict(seed=seed,chosen_rung=r,chosen_weights_rung=d['best']['budget'],observed_rungs=observed,
                                reported_validation=d['best']['dev_macro'],costs=costs,warm_natural_wall_s=current+c['forward_wall_s']['natural'],
                                from_original_files_natural_wall_s=prep+current+c['forward_wall_s']['natural'],
                                complete_observed_panel_wall_s=prep+current+sum(c['forward_wall_s'].values())+(c.get('prediction_write_hash_wall_s') or 0.))
                    break
                records.append(answer or dict(seed=seed,chosen_rung=None,observed_rungs=observed))
            times[arm]={'reached_all':all(r['chosen_rung'] is not None for r in records),'per_seed':records}
        for arm in ('smooth','lif','cnn','attention'):
            lhs,other=times['literal'],times[arm]
            if not(lhs['reached_all'] and other['reached_all']):continue
            dif=[]
            for seed in SEEDS:
                a,left=hit['literal',seed];b,right=hit[arm,seed];assert np.array_equal(a,b)
                dif.append(left.astype(float)-right)
            s=a[-1];per=np.mean(dif,axis=0);ids=[np.flatnonzero(s==i) for i in np.unique(s)]
            rng=np.random.default_rng(52193)
            boot=[]
            for j in range(4000):
                groups=rng.integers(len(ids),size=len(ids))
                boot.append(np.mean([per[rng.choice(ids[i],len(ids[i]),replace=True)].mean() for i in groups]))
            ci=np.quantile(boot,[.05,.95]);ratios={clock:[b[clock]/a[clock] for a,b in zip(lhs['per_seed'],other['per_seed'])] for clock in ('warm_natural_wall_s','from_original_files_natural_wall_s','complete_observed_panel_wall_s')}
            assess[f'{target}/{arm}']=dict(point_macro=float(np.mean([per[g].mean() for g in ids])),one_sided_lower95=float(ci[0]),noninferior=bool(ci[0]>-.02),
                                          baseline_wall_divided_by_literal_wall=ratios)
        sums[str(target)]=times
    out.write_text(json.dumps(dict(targets=sums,qualified_comparisons=assess,
        summary='Fixed-rung qualification. Data acquisition and queue waiting are not in these measured data-to-prediction times. The input preparation sum is sequential-equivalent if prepared concurrently. Training receipt overhead is accumulated as recorded. Uninstrumented serialization is explicitly null.'),indent=1)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('out',type=Path);a=p.parse_args();evaluate(a.root,a.out)
