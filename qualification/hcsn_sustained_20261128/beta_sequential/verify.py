"""Recompute all selected heads' quality gates and sharp paired actor intervals with NumPy."""
import hashlib
import json
import os
from pathlib import Path
import sys

import numpy as np


def scores(x,txt,w):
    av=x.astype('float64')@w;tx=txt.astype('float64')@w
    return 12*(av/np.linalg.norm(av,axis=1,keepdims=True))@(tx/np.linalg.norm(tx,axis=1,keepdims=True)).T


def cell(z,y,stage):
    s=y//6;target=np.where(s<=stage,6*s+(y%6+1)%6,y)
    loss=np.logaddexp.reduce(z,axis=1)-z[np.arange(len(z)),target]
    right=(z.argmax(1)==target)
    out={}
    for name,mask in {'current':s==stage,'past':s<stage,'protected':s>=6}.items():
        if mask.any():out[name]={'n':int(mask.sum()),'nll':float(loss[mask].mean()),'top1':float(right[mask].mean())}
    return out,loss


def passed(m,p):
    return bool(p['current']['nll']-m['current']['nll']>=.10
                and ('past' not in m or p['past']['nll']-m['past']['nll']>=.05)
                and m['protected']['nll']-p['protected']['nll']<=.10
                and p['protected']['top1']-m['protected']['top1']<=.02)


def verify(task,out):
    r=json.loads((out/'terminal.json').read_text())
    sel=json.loads((out/'development_seal.json').read_text())
    assert hashlib.sha256((out/'development_seal.json').read_bytes()).hexdigest()==r['selection_sha256']
    maxlogit=metric_error=bootstrap_error=0.
    counts=gates=0; cache={}; ns={}
    for seed in (137,311,557):
        p=task/'run'/str(seed)
        with np.load(p/'basis.npz',allow_pickle=False) as basis,np.load(p/'held.npz',allow_pickle=False) as held:
            text=held['text'];w0=held['W0']
            stocks={'dev':(basis['dev'],basis['dev_y']),'held':(held['held'],held['held_y'])}
            who=np.array([i.split('_')[0] for i in held['held_ids']])
            for which,(x,y) in stocks.items():
                z0=scores(x,text,w0)
                for arm,gain in sel['gains'].items():
                    with np.load(out/f'{arm}-{seed}.npz') as heads:
                        array=out/f'logits-{arm}-{seed}.npz'
                        for stage in range(6):
                            w=heads[f's{stage}']
                            pmet,_=cell(z0,y,stage)
                            for name,g in [('unit',1.),('dev_gain',gain)]:
                                z=scores(x,text,w0.astype('float64')+g*(w.astype('float64')-w0))
                                m,l=cell(z,y,stage)
                                k=f'{seed}/{arm}/{stage}/{name}';entry=r['rows'][k]
                                other=(entry['metrics'] if which=='held' else
                                       sel['evidence'][f'{arm}-{seed}']['stages'][stage]['dev_candidates'][str(g)]['metrics'])
                                for t in m:
                                    for n in ('nll','top1'):metric_error=max(metric_error,abs(m[t][n]-other[t][n]))
                                ok=passed(m,pmet)
                                if which=='dev':
                                    assert ok==entry['dev_pass'];ns[k]=ok
                                else:
                                    assert (ok and ns[k])==entry['both_pass']
                                    if stage==5:cache[seed,arm,name]=l
                                    if name=='unit' and stage==5:
                                        with np.load(array) as a:
                                            maxlogit=max(maxlogit,float(np.max(abs(z-a['scores']))))
                                counts+=z.size;gates+=1
    u=np.unique(who);ix=np.random.default_rng(83573).integers(len(u),size=(4000,len(u)))
    for key,v in r['paired_actor_nll_beta_minus_other'].items():
        profile,arm,group=key.split('/')
        delta=np.mean([cache[s,'beta',profile]-cache[s,arm,profile] for s in (137,311,557)],axis=0)
        mask={'current':y//6==5,'past':y//6<5,'protected':y//6>=6}[group]
        sums=np.array([delta[mask&(who==a)].sum() for a in u])
        sz=np.array([(mask&(who==a)).sum() for a in u])
        ci=np.quantile(sums[ix].sum(1)/sz[ix].sum(1),[.025,.975])
        bootstrap_error=max(bootstrap_error,float(np.max(abs(np.r_[delta[mask].mean(),ci]-v))))
    assert maxlogit<3e-5 and metric_error<5e-6 and bootstrap_error<3e-6
    outcome={'scored_scalar_logits_including_development':counts,'development_and_held_gate_checks':gates,
             'max_final_archived_logit_difference':maxlogit,'max_metric_difference':metric_error,
             'max_paired_bootstrap_contrast_difference':bootstrap_error,'numpy':np.__version__,
             'development_seal_sha256':r['selection_sha256'],'terminal_sha256':hashlib.sha256((out/'terminal.json').read_bytes()).hexdigest()}
    (out/'verified.json').write_text(json.dumps(outcome,indent=2)+'\n')
    print(json.dumps(outcome),flush=True)


if __name__=='__main__':
    verify(Path(sys.argv[1]),Path(sys.argv[2]))
