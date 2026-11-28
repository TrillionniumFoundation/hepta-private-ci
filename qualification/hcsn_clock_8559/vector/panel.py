"""Equal-clock SHD wall-only fitting, cold ablations and paired cluster inference."""
import argparse
import json
import os
from pathlib import Path
import time
import numpy as np
import torch
from scipy.special import logsumexp
from law import ARMS,WallClassifier
import train
from train import Data,apply,atomic_json,digest

def fit(root,runs,arm,seed,rung):
    train.Classifier=WallClassifier
    data=Data(root);train.train_one(data,runs,arm,seed,rung)
def cold(root,runs,out,rung):
    rows=json.loads((runs/f'seal-{rung}.json').read_text())
    assert {(r['arm'],r['seed']) for r in rows}=={(a,s) for a in ARMS for s in train.SEEDS} and len(rows)==15
    d=Data(root);out.mkdir(parents=True,exist_ok=True)
    streams={}
    for key in ('natural','fast','slow'):
        with np.load(root/f'test-{key}.npz') as z:
            if key=='natural':source=np.stack([z['row'],z['y'],z['speaker']])
            assert np.array_equal(source,np.stack([z['row'],z['y'],z['speaker']]))
            streams[key]=(torch.from_numpy(np.log1p(z['counts'].astype(np.float32)))-d.m)/d.s
    streams['reverse']=streams['natural'].flip([1]);streams['silent']=(-d.m/d.s).expand_as(streams['natural'])
    for item in rows:
        arm=item['arm'];seed=item['seed'];n=f'{arm}-{seed}'
        f=runs/n/f'selected-{rung}.pt';rec=runs/n/f'rung-{rung}.json';assert digest(f)==item['selected_sha256'] and digest(rec)==item['receipt_sha256']
        receipt=out/(n+'.json');raw=out/(n+'.npz')
        if receipt.exists():assert json.loads(receipt.read_text())['prediction_sha256']==digest(raw);continue
        begin=time.perf_counter();m=WallClassifier(arm);apply(m,torch.load(f,weights_only=True));m.eval();scores={};clocks={}
        for name in [*streams,*(('clamp_wire','shuffle_wire','no_equity','no_flux') if arm!='cnn' else ())]:
            x=streams[name] if name in streams else streams['natural'];mode=name if name not in streams else 'natural'
            st=time.perf_counter()
            with torch.no_grad():z=torch.cat([m(x[ix:ix+48],mode) for ix in range(0,len(x),48)]).numpy()
            assert np.isfinite(z).all()
            clocks[name]=time.perf_counter()-st;scores[name]=z
        tmp=raw.with_suffix('.partial')
        with tmp.open('wb') as h:np.savez_compressed(h,row=source[0],y=source[1],speaker=source[2],**scores)
        os.replace(tmp,raw);atomic_json(receipt,dict(arm=arm,seed=seed,checkpoint_sha256=digest(f),prediction_sha256=digest(raw),forward_wall_s=clocks,entire_cold_s=time.perf_counter()-begin))
    atomic_json(out/'complete.json',{p.name:digest(p) for p in out.glob('*.npz')})
def stats(out):
    complete=json.loads((out/'complete.json').read_text());table={};hit={};base=None
    for a in ARMS:
        rows={}
        for s in train.SEEDS:
            f=out/f'{a}-{s}.npz';assert digest(f)==complete[f.name]
            with np.load(f) as z:
                if base is None:base=np.stack([z['row'],z['y'],z['speaker']])
                assert np.array_equal(base,np.stack([z['row'],z['y'],z['speaker']]))
                y=base[1].astype(int);sp=base[2]
                groups=[np.flatnonzero(sp==k) for k in np.unique(sp)]
                for k in z.files:
                    if k in ('row','y','speaker'):continue
                    arr=z[k].astype(float);h=(arr.argmax(-1)==y).astype(float)
                    nll=logsumexp(arr,axis=1)-arr[np.arange(len(y)),y]
                    rows.setdefault(k,[]).append(dict(seed=s,macro_accuracy=float(np.mean([h[g].mean() for g in groups])),
                                           macro_nll=float(np.mean([nll[g].mean() for g in groups])),
                                           new_speaker={str(key):float(h[sp==key].mean()) for key in (4,5)}))
                    hit.setdefault((a,k),[]).append(h)
        table[a]=rows
    contrasts=[(a,'natural',0. if a!='cnn' else -.02) for a in ('wall_smooth','wall_flexible','cnn','wall_direct')]
    contrasts.extend(('wall_literal',mode,0.) for mode in ('clamp_wire','shuffle_wire','no_equity','no_flux'))
    matrix=np.stack([np.mean(hit['wall_literal','natural'],0)-np.mean(hit[a,k],0) for a,k,_ in contrasts],1)
    means=np.mean([matrix[g].mean(0) for g in groups],0);random=np.random.default_rng(68777);draw=[]
    for _ in range(4000):
        rr=random.integers(len(groups),size=len(groups));draw.append(np.mean([matrix[random.choice(groups[g],len(groups[g]))].mean(0) for g in rr],0))
    draws=np.array(draw);comparisons={}
    for i,(a,k,goal) in enumerate(contrasts):
        low=float(np.quantile(draws[:,i],.05/3 if i<3 else .05/len(contrasts)))
        comparisons[a+'/'+k]=dict(literal_minus=float(means[i]),simultaneous_lower=low,threshold=goal,
                                  passed=bool(low>goal),marginal95=np.quantile(draws[:,i],[.025,.975]).tolist())
    atomic_json(out/'SUMMARY.json',dict(methods=table,paired=comparisons,records=len(y),speakers=np.unique(sp).tolist(),
            architecture_gate=all(comparisons[a+'/natural']['passed'] for a in ('wall_smooth','wall_flexible','cnn'))))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['fit','cold']);p.add_argument('data',type=Path);p.add_argument('runs',type=Path);p.add_argument('rung',type=int)
    p.add_argument('--arm',choices=ARMS);p.add_argument('--seed',type=int);p.add_argument('--out',type=Path);a=p.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if a.mode=='fit':fit(a.data,a.runs,a.arm,a.seed,a.rung)
    else:cold(a.data,a.runs,a.out,a.rung);stats(a.out)
