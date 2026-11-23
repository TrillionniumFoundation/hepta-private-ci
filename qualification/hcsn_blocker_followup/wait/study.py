"""Preregistered UCI HAPT waiting study. Fit/confirm separation, no model selection on TEST."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from qualification.hcsn_intervention_value import policy
from qualification.hcsn_qvi_retrieval.adapt import solve_readout
from qualification.hcsn_qvi_retrieval.verify import UPSTREAM
from . import data

SEEDS=(181391,284729,395201); MODES=('plain','fixed','qvi'); STOP,READ,WAIT=0,1,2
HERE=Path(__file__).parent


def sources():
    root=HERE.parent.parent; names=['hcsn_intervention_value/policy.py','hcsn_qvi_retrieval/adapt.py','hcsn_qvi_retrieval/verify.py','hcsn_qvi_retrieval/dynamics.py','hcsn_qvi_task_surface/model.py']+sorted(UPSTREAM)
    return {p.relative_to(root).as_posix():data.sha(p) for p in [HERE/'study.py',HERE/'data.py',HERE/'protocol.json']+[root/n for n in names]}


def fixed(s,t,a): n=len(s['target']);return np.full(n,t,int),np.full(n,a,int)


def threshold(s,cap,c):
    confidence=s['scores'].max(-1); hit=confidence>=c; hit[:,cap:]=True;return np.argmax(hit,1),np.zeros(len(hit),int)


def actions(q,paid,immediate=False):
    q=q.copy();q[:,-1,WAIT]=-np.inf
    if not paid:q[:,:,READ]=-np.inf
    if immediate:q[:,:,WAIT]=-np.inf
    a=q.argmax(-1);t=(a!=WAIT).argmax(1);return t,a[np.arange(len(q)),t]


def evaluate(s,decision):
    t,a=(np.asarray(x) for x in decision); i=np.arange(len(t));gold=s['target'];pred=np.where(a==READ,s['read_scores'][i,t].argmax(1),s['scores'][i,t].argmax(1)); correct=pred==gold
    u=np.exp(-.2*.48*t)*(correct-.3*a)+2*np.expm1(-.2*.48*t);g=s['group'];by={k:float(u[g==k].mean()) for k in np.unique(g)}; ba={k:float(correct[g==k].mean()) for k in np.unique(g)}
    return dict(utility=float(np.mean(list(by.values()))),r1=float(np.mean(list(ba.values()))),by_group=by,r1_by_group=ba,
     reads=int(a.sum()),waits=int(np.sum(t>0)),read_after_wait=int(np.sum((a==READ)&(t>0))),prefix=t.tolist(),action=a.tolist(),u=u.tolist(),hit=correct.astype(int).tolist())


def comparison(lhs,rhs):
    d={g:v-rhs['by_group'][g] for g,v in lhs['by_group'].items()};v=np.array(list(d.values()));n=len(v);k=int(sum(v>1e-12));p=sum(math.comb(n,j) for j in range(k,n+1))/2**n
    return dict(utility_gain=float(v.mean()),delta_r1=lhs['r1']-rhs['r1'],by_group=d,positive=k,ties=int(sum(abs(v)<=1e-12)),subjects=n,sign_p=p)


def opportunity(s):
    n=len(s['target']); util=np.array([[evaluate(s,fixed(s,t,a))['u'] for a in (STOP,READ)] for t in range(6)]).transpose(2,0,1);i=np.arange(n)
    def agg(v):return float(np.mean([v[s['group']==g].mean() for g in np.unique(s['group'])]))
    return {'free_wait_over_immediate':agg(util[:,:,0].max(1)-util[:,0,0]),'joint_wait_over_best_immediate':agg(util.max((1,2))-util[:,0].max(1)),
        'paid_over_free_future':agg(util.max((1,2))-util[:,:,0].max(1)),'free_oracle_utility':agg(util[:,:,0].max(1)),
        'joint_oracle_utility':agg(util.max((1,2))),'free_wait_positive_queries':int((util[:,:,0].max(1)>util[:,0,0]+1e-12).sum())}


def score_summary(s,config):
    tab={f'{a}-{t}':evaluate(s,fixed(s,t,a)) for a in (STOP,READ) for t in range(6)}
    c,cap=config['threshold'];main=evaluate(s,threshold(s,cap,c));imm=tab['0-0'];best=tab['0-'+str(config['fixed_free'])]
    ci=s['scores'][:,0].max(1); t=np.array(main['prefix']); bins=[]
    for lo,hi in ((.5,.6),(.6,.75),(.75,.9),(.9,1.00000001)):
        mask=(ci>=lo)&(ci<hi); gs=np.unique(s['group'][mask]);
        def gm(value):return None if not len(gs) else float(np.mean([np.asarray(value)[mask&(s['group']==g)].mean() for g in gs]))
        bins.append(dict(lo=lo,hi=min(hi,1.),queries=int(mask.sum()),subjects=len(gs),wait_rate=gm(t>0),initial_accuracy=gm(imm['hit']),
                         adaptive_accuracy=gm(main['hit']),delta_utility=gm(np.array(main['u'])-imm['u'])))
    primary=comparison(main,imm);adapt=comparison(main,best)
    return dict(opportunity=opportunity(s),fixed_exits=tab,primary=main,primary_vs_immediate=primary,primary_vs_locked_fixed=adapt,
        primary_pass=primary['utility_gain']>=.015 and primary['positive']>=2 and primary['sign_p']<=.05 and main['waits']>0,
        state_dependent_gain=adapt['utility_gain']>1e-12,initial_confidence_bins=bins,
        query_id=s['query_id'].tolist(),group=s['group'].tolist(),posture=s['posture'].tolist(),target=s['target'].tolist())


def condition(s,mu,scale):
    z=policy.free_state(s['x'],s['scores'],s['dt']);return {'zt':torch.from_numpy((z-mu)/scale),'clock':torch.from_numpy(s['dt'])}


def transfer(split,avail,mode,seed,mu,scale,head=None):
    dim=len(mu);mod=policy.representation(mode,seed,dim);get=policy.features(mod,mode,avail=='read');physical=condition(split,mu,scale)
    with torch.no_grad():
        theta=torch.zeros(0,dtype=torch.float64) if mod is None else mod.initial_edit_vector();h=get(theta,physical)
        if head is None:
            g=split['group'];w=torch.tensor(np.repeat([1/np.sum(g==i) for i in g],6),dtype=torch.float64);w=w/w.sum()
            head=solve_readout(h.flatten(0,1),torch.from_numpy(split['targets'].reshape(-1,3)),w,.001)[0]
        else:head=torch.as_tensor(head,dtype=torch.float64)
        q=(h@head[:-1]+head[-1]).numpy()
    return head.tolist(),q


def fast_policies(s,q,paid):
    d={'immediate_conditional':evaluate(s,actions(q,paid,True)),'immediate_stop':evaluate(s,fixed(s,0,STOP))}
    if paid:d['immediate_paid']=evaluate(s,fixed(s,0,READ))
    return d


def stop_choices(dev):
    grid=[(1.,0)]+[(c,cap) for cap in (1,2,3) for c in (.55,.65,.75,.85,.95)]
    scores=[evaluate(dev,threshold(dev,cap,c))['utility'] for c,cap in grid];winner=max(range(len(grid)),key=lambda i:scores[i]);fixed_scores=[evaluate(dev,fixed(dev,t,STOP))['utility'] for t in range(6)]
    return dict(threshold=grid[winner],selected_index=winner,dev_grid=[dict(confidence=c,cap=cap,utility=u) for (c,cap),u in zip(grid,scores)],
                fixed_free=int(np.argmax(fixed_scores)),dev_fixed_free=fixed_scores)


def each_model():
    for mode in MODES:
        for seed in (SEEDS[:1] if mode=='plain' else SEEDS):yield mode,seed


def model_report(s,weights):
    results={};mu=np.array(weights['mu']);sd=np.array(weights['sd'])
    for mode,seed in each_model():
        for avail in ('read','noread'):
            key=f'{mode}-{seed}-{avail}'; record=weights['models'][key];t0=time.monotonic()
            _,q=transfer(s,avail,mode,seed,mu,sd,record['head']);paid=avail=='read';r=evaluate(s,actions(q,paid));fast=fast_policies(s,q,paid);mask=evaluate(s,actions(q,False));imm=fast[record['best_fast']];fixed_control=evaluate(s,fixed(s,*record['fixed_exit']))
            results[key]=dict(chosen=r,immediate=imm,immediate_name=record['best_fast'],vs_immediate=comparison(r,imm),vs_locked_fixed=comparison(r,fixed_control),
                    vs_masked_read=comparison(r,mask),conditional_seconds=time.monotonic()-t0)
        f=results[f'{mode}-{seed}-read'];n=results[f'{mode}-{seed}-noread'];f['vs_matched_noread']=comparison(f['chosen'],n['chosen'])
    return results


def check_roster(args):
    roster=args.out/'roster.json'; original=json.loads(roster.read_text());
    if data.inventory(args.archive)!=original:raise ValueError('source/roster mismatch')


def fit(args):
    start=time.monotonic();check_roster(args); raw,missing=data.extract(args.archive,'train');dv,md=data.extract(args.archive,'dev');cls=data.fit_classifiers(raw,np.ones(len(raw['target']),bool));tr=data.frontend(raw,cls,True);dev=data.frontend(dv,cls)
    mu=policy.free_state(tr['x'],tr['scores'],tr['dt']);g=tr['group'];ww=np.array([1/np.sum(g==v) for v in g]);ww/=ww.sum();mean=ww@mu.mean(1);sd=np.sqrt(ww@((mu-mean)**2).mean(1)).clip(1e-6)
    weights=dict(classifiers=cls,mu=mean.tolist(),sd=sd.tolist(),models={},foresight='none; nested source-exclusive continuation on canonical frontend',simple=stop_choices(dev)); start_fit=time.monotonic()
    for av in ('read','noread'):
        paid=av=='read';teacher=policy.fit_teacher(tr,paid);tr['targets']=teacher['targets'];eligible=(STOP,READ) if paid else (STOP,)
        exits=[(t,a) for t in range(6) for a in eligible];bestfix=max(exits,key=lambda v:evaluate(dev,fixed(dev,*v))['utility'])
        for mode,seed in each_model():
            tick=time.monotonic();head,_=transfer(tr,av,mode,seed,mean,sd);_,dq=transfer(dev,av,mode,seed,mean,sd,head);fast=fast_policies(dev,dq,paid);best=max(fast,key=lambda k:fast[k]['utility'])
            weights['models'][f'{mode}-{seed}-{av}']=dict(head=head,best_fast=best,fixed_exit=bestfix,conditional_seconds=time.monotonic()-tick)
    for n,s in [('train',tr),('dev',dev)]:
        with (args.out/(n+'.npz')).open('xb') as f:np.savez_compressed(f,**{k:v for k,v in s.items() if k!='targets'})
    data.write(args.out/'weights.json',weights);data.write(args.out/'development.json',dict(train=score_summary(tr,weights['simple']),dev=score_summary(dev,weights['simple']),models=model_report(dev,weights),omitted={'train':missing,'dev':md}))
    data.write(args.out/'fit_seal.json',dict(sources=sources(),files={n:data.sha(args.out/n) for n in ['weights.json','roster.json','development.json','train.npz','dev.npz']},
        raw_archive_sha=data.ARCHIVE,train_subjects=data.TRAIN,dev_subjects=data.DEV,test_subjects=data.TEST,test_signals_opened=False,wall_seconds=time.monotonic()-start))


def confirm(args):
    start=time.monotonic();check_roster(args);p=args.out/'fit_seal.json';seal=json.loads(p.read_text())
    if args.expected_seal!=data.sha(p) or seal['sources']!=sources() or any(data.sha(args.out/n)!=h for n,h in seal['files'].items()):raise ValueError('unsealed fit or sources')
    raw,missing=data.extract(args.archive,'test');weights=json.loads((args.out/'weights.json').read_text());s=data.frontend(raw,weights['classifiers']);summ=score_summary(s,weights['simple'])
    with (args.out/'test.npz').open('xb') as f:np.savez_compressed(f,**s)
    data.write(args.out/'confirmation.json',dict(dataset=data.ARCHIVE,fit_seal=data.sha(p),shard_sha=data.sha(args.out/'test.npz'),native_seconds_per_step=.48,
        omitted=missing,selected_simple=weights['simple'],summary=summ,models=model_report(s,weights),wall_seconds=time.monotonic()-start))


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('phase',choices=('fit','confirm'));cli.add_argument('archive',type=Path);cli.add_argument('out',type=Path);cli.add_argument('--expected-seal');args=cli.parse_args()
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    (fit if args.phase=='fit' else confirm)(args)
