"""Independently recompute raw/secondary held scores and paired effects after the full panel."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read(p):return json.loads(p.read_text())


def scores(z,y):
    z=z.astype(np.float64)
    z=z-z.max(1,keepdims=True)
    loss=np.log(np.exp(z).sum(1))-z[np.arange(len(y)),y]
    return loss,float(np.mean(z.argmax(1)==y))


def close(a,b):np.testing.assert_allclose(a,b,rtol=1.e-10,atol=1.e-11)


def verify(r):
    t=read(r/'terminal.json');seal=read(r/'development_seal.json');design=read(r/'design.json')
    if sha(r/'design.json')!=seal['design_sha256'] or sha(r/'development_seal.json')!=t['development_seal_sha256']:
        raise ValueError('seal chain')
    prior=np.log(np.array(design['train_histogram'])/sum(design['train_histogram']))
    lossmap={'raw':{},'secondary':{}};gates={};n=0;seeds=design['seeds'];arms=design['arms']
    for group,rows in seal['candidates'].items():
        gates[group]={}
        for mode in ('raw','secondary'):
            rank=lambda x: (x['raw']['nll'] if mode=='raw' else x['secondary']['dev']['nll'],x['steps'])
            best=min(rows,key=rank)['cell']
            if best!=seal['picks'][group][mode]:raise ValueError('development pick mismatch')
            before=None;running_s=0
            for j,row in enumerate(sorted(rows,key=lambda x:x['steps'])):
                cell=r/row['cell'];fit=read(cell/'fit.json')
                if sha(cell/'writes.pt')!=row['weights_sha256'] or fit['sha256']!=row['weights_sha256']:raise ValueError('weights')
                observed={}
                for split in ('dev','cold'):
                    p=cell/split/'scores.npz'
                    if sha(p)!=read(cell/split/'timing.json')['sha256']:raise ValueError('scores hash')
                    with np.load(p) as a:
                        z,y,ids=a['scores'],a['labels'],a['ids']
                    if z.shape!=((1147 if split=='dev' else 1311),72):raise ValueError('incomplete split')
                    if mode=='secondary':z=z.astype(np.float64)*row['secondary']['multiplier']+prior
                    l,acc=scores(z,y);observed[split]=float(l.mean())
                    expected=t['cold_by_candidate'][row['cell']][mode][split]
                    close([l.mean(),acc],[expected['nll'],expected['top1']])
                    if split=='cold' and best==row['cell']:lossmap[mode][group]=l
                running_s+=row['original_fit_seconds']+row['dev_seconds']+t['cold_by_candidate'][row['cell']]['cold_seconds']
                if mode=='secondary':running_s+=row['calibration_seconds']
                if max(observed.values())<=4.1 and before is None:
                    before={'steps':row['steps'],'cumulative_prefix_cost_s_excluding_common_preparation':running_s}
            gates[group][mode]=before
        n+=len(rows)
    actor_ids=np.array([s.split('_')[0] for s in ids]);who=np.unique(actor_ids);mass=np.array([(actor_ids==a).sum() for a in who])
    ix=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    for mode,all_losses in lossmap.items():
        for arm in arms[1:]:
            d=np.stack([all_losses[f'forward-{s}']-all_losses[f'{arm}-{s}'] for s in seeds]).mean(0)
            sums=np.array([d[actor_ids==a].sum() for a in who]);res=t['paired_actor_contrasts'][mode][arm]
            close(d.mean(),res['mean']);close(np.quantile(sums[ix].sum(1)/mass[ix].sum(1),[.025,.975]),res['actor_ci95'])
    if n!=27 or len(seal['candidates'])!=15:raise ValueError('panel incomplete')
    return {'verified':True,'candidates':n,'weights_files':n,'dev_and_cold_score_archives':2*n,
            'paired_actor_contrasts':8,'earliest_observed_fixed_prefix_4_1':gates,'terminal_sha256':sha(r/'terminal.json')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('--output',type=Path);a=p.parse_args()
    result=verify(a.run);report=json.dumps(result,indent=2)+'\n'
    if a.output:a.output.write_text(report)
    print(report)
