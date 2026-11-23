"""Conditional second workload: find a passage's production from two same-instrument reference excerpts."""
import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.special import expit

from . import frontend as f
from . import independent as a
from .discovery import archive, metadata

HERE=Path(__file__).parent
CHANNELS=('audio','visual')
MATCH=('handwritten_visual','trained_visual')


def pairs(s):
    rec=s['recording'].astype(str)
    rows=[]
    for label in (0,1):
        works=sorted(set(rec[s['label']==label]),key=lambda k:int(''.join(c for c in k if c.isdigit())))
        if len(works)<2:raise ValueError('two references of the same instrument are needed')
        members=[np.where(rec==k)[0] for k in works]
        members=[ids[np.argsort(s['start_seconds'][ids])] for ids in members]
        for j,ids in enumerate(members):
            r0,r1=ids[0],members[(j+1)%len(members)][0]
            if s['group'][r0]==s['group'][r1]:raise ValueError('references from same creator')
            for h,q in enumerate(ids[1:]):
                if s['start_seconds'][q]+1e-6<s['start_seconds'][r0]+2.88:
                    raise ValueError('query overlaps its positive gallery excerpt')
                target=(j+h)%2
                rows.append((q,r1 if target else r0,r0 if target else r1,target))
    return np.asarray(rows,dtype=int)


def delta(s,p,channel,scale):
    q,l,r=p[:,:3].T
    desc=s[channel]
    return ((abs(desc[q]-desc[l])-abs(desc[q]-desc[r]))/np.asarray(scale)).clip(-8,8)


def metric(train,training_pairs,blocked):
    group=train['group']
    allowed=~np.isin(group,list(blocked))
    pp=training_pairs[allowed[training_pairs[:,:3]].all(axis=1)]
    result={}
    for ch in CHANNELS:
        h=train[ch]
        scale=h[allowed].std(axis=(0,1)).clip(1e-5)
        width=h.shape[-1]
        prior=np.ones(width)/width
        weight=prior.copy()
        if len(pp):
            z=delta(train,pp,ch,scale)
            g=group[pp[:,0]]
            sw=np.asarray([1./np.sum(g==key) for key in g]); sw/=sw.sum()
            w=np.repeat(sw/6,6)
            z=z.reshape(-1,width)
            y=np.repeat(2.*pp[:,3]-1,6)
            reg=.25*np.eye(width)
            weight=np.linalg.solve((z.T*w)@z+reg,z.T@(w*y)+reg@prior)
        result[ch]=dict(scale=scale.tolist(),weight=weight.tolist(),train_pairs=len(pp))
    return result


def build(raw,pp,models):
    q=pp[:,0]
    pieces={}
    for ch in CHANNELS:
        d=delta(raw,pp,ch,models[ch]['scale'])
        margin=.5*(d.mean(-1)+d@np.asarray(models[ch]['weight']))
        p=expit(2*margin)
        pieces[ch]=(np.stack((1-p,p),-1),d)
    free,da=pieces['audio']
    visual,dv=pieces['visual']
    pv=expit(2*dv.mean(-1))
    raw_prob=free[:,:,1]; m=abs(2*raw_prob-1)
    proj=np.linalg.qr(np.random.default_rng(420111).normal(size=(da.shape[-1],8)),mode='reduced')[0]
    x=np.concatenate([da@proj,np.stack([raw_prob,m,np.diff(raw_prob,axis=1,prepend=raw_prob[:,:1]),
           abs(da).mean(-1),raw['dt'][q].cumsum(1)-raw['dt'][q,:1]],axis=-1)],axis=-1)
    return (dict(x=x,scores=free,dt=raw['dt'][q],group=raw['group'][q].astype(str),
                 source=raw['recording'][q].astype(str),query_id=raw['query_id'][q].astype(str),split=raw['split'][q].astype(str),
                 class_id=raw['label'][q],target=pp[:,3],references=raw['query_id'][pp[:,1:3]].astype(str)),
            dict(handwritten_visual=np.stack((1-pv,pv),-1),trained_visual=visual))


def crossfit(train,pp):
    groups=train['group'][pp[:,:3]].astype(str)
    blocks=[tuple(sorted(set(v))) for v in groups]
    parts=[]
    for pair in sorted(set(blocks)):
        ix=np.array([i for i,k in enumerate(blocks) if k==pair])
        pred=build(train,pp[ix],metric(train,pp,pair))
        parts.append((ix,pred))
    order=np.argsort(np.concatenate([i for i,_ in parts]))
    return tuple({k:np.concatenate([r[j][k] for _,r in parts])[order] for k in parts[0][1][j]} for j in (0,1))


def hashes():
    return {n:f.digest(HERE/n) for n in ('reference.py','alternate_protocol.json','frontend.py','independent.py','protocol.json','media/sources.json','media/recording_features.py')}


def discover(args):
    st=time.time()
    previous=json.loads(args.primary_seal.read_text())
    if previous['selected'] is not None or previous['heldout_opened']:
        raise ValueError('conditional experiment requires primary nonqualification before TEST')
    args.output.mkdir(parents=True,exist_ok=False)
    names=('train','dev','retain')
    raw={n:f.load_raw(args.raw/(n+'.npz')) for n in names}
    coverage=a.verify_disjoint(metadata(raw))
    pp={n:pairs(s) for n,s in raw.items()}
    final=metric(raw['train'],pp['train'],())
    pred={'train':crossfit(raw['train'],pp['train'])}
    pred.update({n:build(raw[n],pp[n],final) for n in ('dev','retain')})
    panels={};choosers={}
    for m in MATCH:
        tr,dv=(f.candidate(pred[n],m) for n in ('train','dev'))
        chooser=a.fit_causal(tr)
        choosers[m]=chooser.state_dict()
        panels[m]=dict(train=a.opportunity(tr),dev=a.opportunity(dv),dev_policy=a.evaluate(chooser,dv))
    win=a.select_frontend(panels)
    f.dump(args.output/'front_weights.json',final);f.dump(args.output/'panels.json',panels)
    if win:
        for n in names:archive(args.output/(n+'.npz'),f.candidate(pred[n],win))
        f.dump(args.output/'chooser.json',choosers[win])
    f.dump(args.output/'frontend_seal.json',dict(selected=win,heldout_opened=False,source=hashes(),
       primary_negative_seal=f.digest(args.primary_seal),rosters=coverage,start_unix=st,end_unix=time.time(),
       sha256={p.name:f.digest(p) for p in args.output.iterdir()},
       immediate_baseline=panels[win]['dev_policy']['immediate_baseline'] if win else None))


def confirm(args):
    from .run import check_seal,check_front
    seal=json.loads((args.output/'frontend_seal.json').read_text())
    if not seal['selected'] or seal['source']!=hashes() or args.policy_seal.name!='selection_seal.json':
        raise ValueError('no original capable frozen reference matcher')
    check_seal(args.policy_seal.parent)
    if json.loads((args.policy_seal.parent/'prepare/metadata.json').read_text())['frontend_seal']!=check_front(args.output):
        raise ValueError('unbound frontend')
    raw=f.load_raw(args.raw/'test.npz')
    full={n:f.load_raw(args.raw/(n+'.npz')) for n in ('train','dev','retain')}
    coverage=a.verify_disjoint(metadata({**full,'test':raw}))
    data=f.candidate(build(raw,pairs(raw),json.loads((args.output/'front_weights.json').read_text())),seal['selected'])
    archive(args.output/'test.npz',data)
    chooser=a.CausalChooser.from_state_dict(json.loads((args.output/'chooser.json').read_text()))
    f.dump(args.output/'heldout_controls.json',dict(opportunity=a.opportunity(data),policy=a.evaluate(chooser,data,stage='confirmation',
            immediate_baseline=seal['immediate_baseline']),coverage=coverage,ready_hash=f.digest(args.output/'test.npz'),
            policy_seal=f.digest(args.policy_seal),frontend_seal=f.digest(args.output/'frontend_seal.json'),
            dependence='Within-instrument reference ring connects all query sources of that instrument. Creator sign tests are descriptive only; interpret at two connected test complexes.'))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase',choices=('fit','confirm'));p.add_argument('raw',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--primary-seal',type=Path);p.add_argument('--policy-seal',type=Path)
    args=p.parse_args()
    (discover if args.phase=='fit' else confirm)(args)
