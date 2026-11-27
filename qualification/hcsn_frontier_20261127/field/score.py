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


def intervals(path,score,thresholds):
    rows=[json.loads((path/f'm{r}.json').read_text()) for r in RUNGS]
    times=[]
    for target in thresholds:
        prev=0;match=None
        for r in rows:
            if r['dev_brier']<=target:
                match=[prev,r['optimizer_cpu_s']];break
            prev=r['optimizer_cpu_s']
        times.append({'threshold':target,'interval_cpu_s':match,'right_censor_at_s':None if match else prev})
    return times


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
    report['time_to_dev_quality']={key:intervals(out/key,None,[thresh,.98*thresh]) for key in seal['selected']}
    for name in ('fr','be'):
        data=Data(args.data/(name+'.npz'))
        with np.load(args.data/'train.npz') as train,np.load(args.data/(name+'.npz')) as raw:
            y=raw['y']; weeks=(raw['when']//1440+3)//7
            k=seal['k']['selected_k'];base=analog(train,raw,k)[None].astype(np.float32);when=raw['when']
        preds={}
        for arm in ARMS:
            for seed in SEEDS:
                label=f'{arm}-{seed}'
                for r in RUNGS:
                    net=model(arm,table)
                    net.load_state_dict(torch.load(out/label/f'm{r}.pt',weights_only=True))
                    preds[arm,seed,r]=predict(net,data)
        pfile=out/f'{name}-predictions.npz'
        carrier={f'{a}-{s}-{r}':v for (a,s,r),v in preds.items()}
        np.savez_compressed(pfile,when=when,y=y,analog=base[0],**carrier)
        site={'anchors':len(y),'weeks':len(np.unique(weeks)),'predictions_sha256':digest(pfile),'budgets':{}}
        for budget in ['selected',*RUNGS]:
            arms={'analog':base}
            for arm in ARMS:
                arms[arm]=np.stack([preds[arm,s,seal['selected'][f'{arm}-{s}']['budget_s'] if budget=='selected' else budget] for s in SEEDS])
            oba={a:observables(v,y) for a,v in arms.items()}
            metrics={}
            for a,(loss,delta) in oba.items():
                signed=[[boot(delta[:,j,h],weeks) for h in range(2)] for j in range(2)]
                metrics[a]={'brier':boot(loss,weeks),'fee_effect_error_signed_by_reserve_and_horizon':signed,'fee_effect_error_abs_macro':float(np.abs(delta.mean(0)).mean()),'per_seed_brier':np.square(arms[a]-y[None]).mean((1,2,3)).tolist()}
            site['budgets'][budget]={'metrics':metrics,'paired_literal_minus':{a:boot(oba['literal'][0]-oba[a][0],weeks) for a in arms if a!='literal'}}
        report['sites'][name]=site
    report['evaluation_wall_s']=time.monotonic()-start
    save_json(out/'cold.json',report)

if __name__=='__main__':main()
