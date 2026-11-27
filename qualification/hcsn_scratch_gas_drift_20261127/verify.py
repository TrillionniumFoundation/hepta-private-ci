"""Recount sealed score vectors, shifted-batch calibration and end-to-end timing."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def stats(z,y,b):
    out={}
    for bid in np.unique(b):
        take=b==bid;labels=y[take];s=z[take]
        ok=s.argmax(1)==labels;pr=np.exp(5*(s-s.max(1,keepdims=True)));pr/=pr.sum(1,keepdims=True)
        conf=pr.max(1);bins=np.minimum((conf*10).astype(int),9)
        out[int(bid)]={'n':int(take.sum()),'accuracy':float(ok.mean()),'macro_recall':float(np.mean([ok[labels==j].mean() for j in np.unique(labels)])),'brier':float(np.mean(((pr-np.eye(6)[labels])**2).sum(1))),'ece10':float(sum(abs((ok[c]-conf[c]).sum()) for j in range(10) if (c:=bins==j).any())/len(ok))}
    return {'batches':out,'external_recall':float(np.mean([v['macro_recall'] for v in out.values()])),'accuracy':float((z.argmax(1)==y).mean())}


def bootstrap(correct,y,b,rep=4000):
    # Paired bootstrap of the selected seeds and late batches, then the records
    # in each true-label cell. Weight unique sampled seeds/batches by multiplicity.
    rng=np.random.default_rng(6631);batch_ids=np.unique(b);seeds=correct.shape[0]
    seed_weights=rng.multinomial(seeds,np.ones(seeds)/seeds,rep)/seeds
    batch_weights=rng.multinomial(len(batch_ids),np.ones(len(batch_ids))/len(batch_ids),rep)/len(batch_ids)
    batch_mean=[];draws=np.zeros(rep)
    for j,bid in enumerate(batch_ids):
        cols=[correct[:,(b==bid)&(y==ci)] for ci in np.unique(y[b==bid])]
        point=np.stack([v.mean(1) for v in cols]).mean(0);batch_mean.append(point)
        outcome=np.zeros(rep)
        for cell in cols:
            # All rows sharing the same joint outcome vector have identical
            # effects; multinomial counts exactly emulate replacement of rows.
            unique,n=np.unique(cell.T,axis=0,return_counts=True)
            counts=rng.multinomial(n.sum(),n/n.sum(),rep)
            outcome+=(counts@unique*seed_weights).sum(1)/(n.sum()*len(cols))
        draws+=batch_weights[:,j]*outcome
    d=np.array(batch_mean)
    loo=[v.mean()*100 for v in [np.delete(d,j,axis=0) for j in range(len(d))]]
    return {'delta_pp':float(d.mean()*100),'batch_delta_pp':(d.mean(1)*100).tolist(),'seed_delta_pp':(d.mean(0)*100).tolist(),'bootstrap95_pp':(100*np.quantile(draws,[.025,.975])).tolist(),'leave_one_batch_out_pp':[float(min(loo)),float(max(loo))]}


def main():
    q=argparse.ArgumentParser()
    for k in ('models','scores','seal','archive','output'):q.add_argument(k,type=Path)
    a=q.parse_args();seal=json.loads(a.seal.read_bytes());arms=('forward','bp','hybrid_bp','frozen','raw','fourier','fp_hcsn','fp_relu8','fp_relu32','fp_flat32','fp_shuffle');seeds=(2021,4411,6709);rungs=(1,3,8,24)
    ids0=None;rows={};oks={};score_count=0
    for arm in arms:
        for seed in seeds:
            stem=f'{arm}_{seed}';path=a.scores/(stem+'.npz');cost=json.loads(path.with_suffix('.json').read_bytes())
            fp=a.models/(stem+'.json');assert digest(fp)==seal['fits'][fp.name]
            train=json.loads(fp.read_bytes());assert digest(path)==cost['pred_sha256'] and digest(a.seal)==cost['seal_sha256']
            with np.load(path) as f:
                ids=f['feature_id'];y=f['y'];b=f['batch']
                if ids0 is None:ids0=ids.copy();y0=y.copy();b0=b.copy()
                else:assert np.array_equal(ids,ids0) and np.array_equal(b,b0) and np.array_equal(y,y0)
                for r in rungs:
                    selected=train['selected'][str(r)]
                    if selected is None:continue
                    z=f['r'+str(r)];assert z.shape==(len(y),6);score_count+=z.size
                    assert selected['fit_cpu']<=r and seal['fits'][stem+'_'+str(r)+'.npz']==selected['sha256']
                    stat=stats(z,y,b);oks[arm,seed,r]=(z.argmax(1)==y).astype(np.int16)
                    # Upper-bound selection time by the next completed development evaluation.
                    later=[v['fit_wall'] for v in train['history'] if v['fit_cpu']>r]
                    selection_wall=min(later+[train['fit_wall']])
                    cold=cost['source_and_start_wall']+cost['per_rung'][str(r)]['model_load_and_prediction_wall']
                    stat.update({'selected':selected,'common_fit_init_wall':train['common_process_wall'],'selected_candidate_wall':selected['fit_wall'],'selection_through_rung_upper_wall':selection_wall,'cold_wall':cold,'end_to_end_upper_wall':train['common_process_wall']+selection_wall+cold,'full_fit_wall':train['fit_wall']})
                    rows[arm,seed,r]=stat
    comparisons={};quality={};targets={}
    for arm in arms:
        quality[arm]={}
        for r in rungs:
            if any((arm,s,r) not in rows for s in seeds):continue
            rr=[rows[arm,s,r] for s in seeds];quality[arm][r]={'mean_external_recall':float(np.mean([v['external_recall'] for v in rr])),'seed_external_recall':[v['external_recall'] for v in rr],'mean_batch_recall':[float(np.mean([v['batches'][j]['macro_recall'] for v in rr])) for j in (8,9,10)],'mean_batch_brier':[float(np.mean([v['batches'][j]['brier'] for v in rr])) for j in (8,9,10)],'mean_batch_ece10':[float(np.mean([v['batches'][j]['ece10'] for v in rr])) for j in (8,9,10)],'mean_accuracy':float(np.mean([v['accuracy'] for v in rr])),'end_to_end_upper_wall':[v['end_to_end_upper_wall'] for v in rr],'selected_hidden_deltas':[v['selected']['hidden_deltas'] for v in rr],'selected_hidden_updates':[v['selected']['hidden_updates'] for v in rr]}
            if arm!='forward' and all(('forward',s,r) in oks for s in seeds):
                dif=np.stack([oks['forward',s,r]-oks[arm,s,r] for s in seeds])
                comparisons[f'forward_minus_{arm}_{r}']=bootstrap(dif,y0,b0)
        targets[arm]={}
        for t in (.5,.65,.8):
            eligible=[r for r in rungs if r in quality[arm] and min(quality[arm][r]['seed_external_recall'])>=t]
            if eligible:
                first=eligible[0];tt=quality[arm][first]['end_to_end_upper_wall']
                targets[arm][str(t)]={'rung':first,'mean_end_to_end_upper_wall':float(np.mean(tt)),'per_seed_wall':tt}
            else:targets[arm][str(t)]=None
    for arm in arms:
        if arm=='fp_hcsn':continue
        if all(('fp_hcsn',s,24) in oks and (arm,s,24) in oks for s in seeds):
            dif=np.stack([oks['fp_hcsn',s,24]-oks[arm,s,24] for s in seeds]);comparisons[f'fp_hcsn_minus_{arm}_24']=bootstrap(dif,y0,b0)
    from model import read_batches
    _,_,_,prior=read_batches(a.archive,range(1,8))
    overlap=np.isin(ids0,prior)
    sens={}
    if overlap.any():
        for arm in arms:
            for s in seeds:
                with np.load(a.scores/f'{arm}_{s}.npz') as f:sens[f'{arm}_{s}']=stats(f['r24'][~overlap],y0[~overlap],b0[~overlap])
    result={'model_milestones':len(rows),'score_entries':score_count,'unique_late_feature_ids':len(set(ids0)),'late_rows':len(y0),'late_batch_sizes':{str(k):int((b0==k).sum()) for k in np.unique(b0)},'late_rows_duplicated_with_train_or_dev':int(overlap.sum()),'sensitivity_excluding_leaked_features':sens,'seal_sha256':digest(a.seal),'bootstrap_draws':4000,'quality':quality,'same_quality_targets':targets,'paired_comparisons':comparisons,'all_models':{'_'.join(map(str,k)):v for k,v in rows.items()}}
    a.output.write_text(json.dumps(result,sort_keys=True,indent=1,allow_nan=False)+'\n')
    print(len(rows),'milestones;',score_count,'cold scores;',int(overlap.sum()),'cross-split feature duplicates')


if __name__=='__main__':main()
