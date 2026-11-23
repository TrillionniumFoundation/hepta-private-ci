"""Bound paid and waiting opportunities on the original roster from actual observed prefix ranks."""
import argparse
import itertools
import json
from pathlib import Path

import numpy as np

from .frontend import dump,digest
from .independent import CausalChooser


def intervals(free,paid):
    d=np.exp(-.2*.48*np.arange(6))
    uf=d*free+2.*(d-1)
    up=d*(paid.astype(float)-.30)+2.*(d-1)
    ff=uf.max(axis=1);both=np.maximum(ff,up.max());inst=np.maximum(uf[:,0],up[0])
    return {'paid_gain':both-ff,'wait_gain':both-inst,'joint':both,'free_oracle':ff,
            'always_stop':uf[:,0],'always_read':np.full(len(ff),up[0])}


def policy_bounds(chooser,prob,paid,label,immediate):
    known=len(prob)
    edges=np.unique(np.clip(np.r_[0.,chooser.edges,1.],0.,1.))
    margins=np.unique(np.r_[edges,(edges[:-1]+edges[1:])/2])
    # Only the published margin bin and the binary decision can affect this finite rule.
    options=[]
    seen=set()
    for m in margins:
        for prob1 in ((1-m)/2,(1+m)/2):
            v=np.asarray([1-prob1,prob1])
            h=(int(np.searchsorted(chooser.edges,abs(v[1]-v[0]))),int(v.argmax()))
            if h not in seen:
                seen.add(h);options.append(v)
    values={k:[np.inf,-np.inf] for k in ['full','no_read','instant','full_minus_no_read','full_minus_instant']}
    paths=itertools.product(range(len(options)),repeat=6-known)
    d=np.exp(-.2*.48*np.arange(6))
    while True:
        batch=list(itertools.islice(paths,12000))
        if not batch:break
        obs=np.zeros((len(batch),6,2))
        if known:obs[:,:known,:]=np.asarray(prob)
        if known!=6:obs[:,known:,:]=np.asarray(options)[np.asarray(batch)]
        cells={}
        for name,regime in [('full',None),('no_read','refit_no_read'),('instant',immediate)]:
            t,a=chooser.acts(obs,regime)
            free=obs.argmax(axis=2)==label
            hit=np.where(a==1,paid[t],free[np.arange(len(t)),t])
            cells[name]=d[t]*(hit.astype(float)-.3*(a==1))+2*(d[t]-1)
        cells['full_minus_no_read']=cells['full']-cells['no_read']
        cells['full_minus_instant']=cells['full']-cells['instant']
        for name,v in cells.items():
            values[name]=[min(values[name][0],float(v.min())),max(values[name][1],float(v.max()))]
    return values


def report(data,roster,partial):
    with np.load(data/'test.npz',allow_pickle=False) as z:s=dict(z)
    control=json.loads((data/'heldout_controls.json').read_text())
    if partial['ready_hash']!=digest(data/'test.npz'):raise ValueError('unbound prefix observations')
    chooser=CausalChooser.from_state_dict(json.loads((data/'chooser.json').read_text()))
    policy=control['policy']
    n=len(roster);groups={j['query_id']:j['group'] for j in roster}
    weight={q:1/(len(set(groups.values()))*sum(v==g for v in groups.values())) for q,g in groups.items()}
    bounds={};examples={}
    for j,q in enumerate(s['query_id']):
        y=s['target'][j]
        arr=intervals((s['scores'][j].argmax(1)==y)[None,:],s['read_scores'][j].argmax(1)==y)
        pp=policy['policies'];v=lambda k:pp[k]['episode_utility'][j]
        for k,val in dict(full=v('full'),no_read=v('refit_no_read'),instant=v(policy['immediate_baseline']),
                full_minus_no_read=v('full')-v('refit_no_read'),full_minus_instant=v('full')-v(policy['immediate_baseline'])).items():
            arr['tabular_'+k]=[val]
        for k,v in arr.items():bounds[k]=bounds.get(k,np.zeros(2))+weight[q]*np.array([min(v),max(v)])
    for q,feat in partial['partial_frontend'].items():
        y=feat['target'];p=np.asarray(feat['paid_probability']);free=feat['free_probability']
        if p.shape!=(6,2) or len(free)!=partial['observed_prefixes'][q]:raise ValueError(q)
        paid=p.argmax(1)==y;known=[int(np.argmax(row)==y) for row in free]
        sequence=np.asarray([known+list(tail) for tail in itertools.product((0,1),repeat=6-len(known))])
        all_values=intervals(sequence,paid)
        ex={k:[float(min(v)),float(max(v))] for k,v in all_values.items()}
        ex.update({'tabular_'+k:v for k,v in policy_bounds(chooser,free,paid,y,policy['immediate_baseline']).items()})
        examples[q]=ex
        for k,v in ex.items():bounds[k]+=weight[q]*np.array(v)
    if set(s['query_id'])&set(examples) or set(s['query_id'])|set(examples)!=set(groups):
        raise ValueError('original roster differs')
    return dict(scheduled=n,fully_observed=len(s['query_id']),original_creator_weights=weight,
                limits={k:v.tolist() for k,v in bounds.items()},individual_incomplete=examples,
                scope='Sharp over arbitrary missing free correctness sequences and finite-table margin/rank states, conditional on the frozen camera and intact input observations; the unknown waveform can impose additional restrictions.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('data',type=Path);p.add_argument('roster',type=Path)
    p.add_argument('early',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    dump(a.output,report(a.data,json.loads(a.roster.read_text()),json.loads(a.early.read_text())))
