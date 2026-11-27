"""Seal-gated evaluation of matched budgets, fee effects, paired week intervals and time to quality."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
import torch

from fit import ARMS, RUNGS, SEEDS, Data, analog, digest, make_table, model, predict, save_json


def boot(values,weeks,seed=574382):
    _, group=np.unique(weeks,return_inverse=True)
    sums=np.bincount(group,weights=values);n=np.bincount(group)
    rng=np.random.default_rng(seed)
    ids=rng.integers(0,len(n),(5000,len(n)))
    draws=sums[ids].sum(1)/n[ids].sum(1)
    return [float(values.mean()),*np.quantile(draws,[.025,.975]).tolist()]


def observables(pred,y):
    # Pred carries seed, anchor, contract, horizon axes. Average losses, not logits or predictors.
    anchor_loss=np.square(pred-y[None]).mean((0,2,3))
    each=pred[:,:,[1,3],1:]-pred[:,:,[0,2],1:]
    true=y[:,[1,3],1:]-y[:,[0,2],1:]
    delta=each.mean(0)-true
    return anchor_loss,delta


def observed_checkpoints(path,thresholds,shared_setup):
    rows=[json.loads((path/f'm{r}.json').read_text()) for r in RUNGS]
    out=[]
    for threshold in thresholds:
        measured_wall=0.;previous=None;first=None
        for r in rows:
            measured_wall+=r['resume_segment_wall_s']
            if r['dev_brier']<=threshold:
                first={'budget_s':r['budget_s'],'active_optimizer_cpu_s':r['optimizer_cpu_s'],
                       'sum_fit_validation_and_checkpoint_wall_s':measured_wall,
                       'estimated_cached_raw_to_selected_predictor_wall_s':shared_setup+measured_wall}
                break
            previous=r['budget_s']
        out.append({'threshold':threshold,'first_observed_passing_checkpoint':first,
                    'preceding_nonpassing_observed_budget_s':previous,
                    'largest_observed_budget_s':rows[-1]['budget_s'],
                    'nonmonotone_caveat':'Checkpoint times do not bound unobserved earlier crossings.'})
    return out


def main():
    p=argparse.ArgumentParser()
    for n in ('data','out','core'):p.add_argument('--'+n,type=Path,required=True)
    args=p.parse_args();out=args.out
    sealfile=out/'seal.json'; seal=json.loads(sealfile.read_text())
    assert len(seal['selected'])==len(ARMS)*len(SEEDS)
    # Authenticate the full matrix before reading either test file.
    for seed in SEEDS:
        for arm in ARMS:
            label=f'{arm}-{seed}';directory=out/label
            for r in RUNGS:
                rec=json.loads((directory/f'm{r}.json').read_text())
                assert rec['optimizer_cpu_s']>=r and rec['weights_sha256']==digest(directory/f'm{r}.pt')
            selection=seal['selected'][label]
            assert selection==min([json.loads((directory/f'm{r}.json').read_text()) for r in RUNGS],key=lambda v:(v['dev_brier'],v['budget_s']))
    start=time.monotonic();torch.set_num_threads(1);torch.set_num_interop_threads(1)
    table=make_table(args.core);report={'seal_sha256':digest(sealfile),'sites':{}}
    thresh=sorted(seal['k']['development_brier'].values())[0]
    setup=json.loads((out/'setup_replay.json').read_text())
    shared_wall=setup['cached_raw_to_prepared_wall_s']+setup['isolated_import_train_dev_table_wall_s']
    report['setup_replay']=setup
    report['first_observed_dev_quality']={key:observed_checkpoints(out/key,[thresh,.98*thresh],shared_wall) for key in seal['selected']}
    report['timing_scope']='Sequential cost per fit excludes time spent waiting for other arms. Per-site cold timings are recorded separately. Cached-raw setup was independently replayed. Prior transient failures and internet acquisition are outside this estimate.'
    for name in ('fr','be'):
        data=Data(args.data/(name+'.npz'))
        with np.load(args.data/'train.npz') as train,np.load(args.data/(name+'.npz')) as raw:
            y=raw['y']; weeks=(raw['when']//1440+3)//7
            k=seal['k']['selected_k'];base=analog(train,raw,k)[None].astype(np.float32);when=raw['when']
        preds={}; cold_times={}
        for arm in ARMS:
            for seed in SEEDS:
                label=f'{arm}-{seed}'
                for r in RUNGS:
                    tick=time.monotonic()
                    net=model(arm,table)
                    net.load_state_dict(torch.load(out/label/f'm{r}.pt',weights_only=True))
                    preds[arm,seed,r]=predict(net,data)
                    cold_times[f'{arm}-{seed}-{r}']=time.monotonic()-tick
        pfile=out/f'{name}-predictions.npz'
        carrier={f'{a}-{s}-{r}':v for (a,s,r),v in preds.items()}
        np.savez_compressed(pfile,when=when,y=y,analog=base[0],**carrier)
        site={'anchors':len(y),'weeks':len(np.unique(weeks)),'predictions_sha256':digest(pfile),'budgets':{},'per_checkpoint_load_and_cold_infer_wall_s':cold_times}
        for budget in ['selected',*RUNGS]:
            arms={'analog':base}
            for arm in ARMS:
                arms[arm]=np.stack([preds[arm,s,seal['selected'][f'{arm}-{s}']['budget_s'] if budget=='selected' else budget] for s in SEEDS])
            oba={a:observables(v,y) for a,v in arms.items()}
            metrics={}
            for a,(loss,delta) in oba.items():
                signed=[[boot(delta[:,j,h],weeks) for h in range(2)] for j in range(2)]
                # The posted fee starts in slot 3 and therefore has exactly zero effect by slot 2.
                predictions=arms[a]
                one_hour=predictions[:,:,[1,3],0]-predictions[:,:,[0,2],0]
                time_violation=np.maximum(0,-np.diff(predictions,axis=3))
                reserve_violation=np.maximum(0,predictions[:,:,2:]-predictions[:,:,:2])
                invariant={'abs_one_hour_spurious_fee_effect':boot(np.abs(one_hour).mean((0,2)),weeks),'max_one_hour_spurious_effect_per_seed':np.max(np.abs(one_hour),axis=(1,2)).tolist(),'mean_horizon_monotonicity_violation':float(time_violation.mean()),'mean_reserve_monotonicity_violation':float(reserve_violation.mean())}
                metrics[a]={'contract_invariants':invariant,'brier':boot(loss,weeks),'fee_effect_error_signed_by_reserve_and_horizon':signed,'fee_effect_error_abs_macro':float(np.abs(delta.mean(0)).mean()),'per_seed_brier':np.square(arms[a]-y[None]).mean((1,2,3)).tolist()}
            site['budgets'][budget]={'metrics':metrics,'paired_literal_minus':{a:boot(oba['literal'][0]-oba[a][0],weeks) for a in arms if a!='literal'}}
        report['sites'][name]=site
    report['evaluation_wall_s']=time.monotonic()-start
    save_json(out/'cold.json',report)

if __name__=='__main__':main()
