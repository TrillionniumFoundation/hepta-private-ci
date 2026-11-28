"""Sequential adaptation to Speech Commands while preserving both previous speech domains."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import numpy as np
from fit_model import (Cell, Expired, RUNGS, Track, clock, dump, fields, forward, grad,
                       load_panel, secants, sha, since, standardized, stats)
from sensitivity import released_update

def support(panel):
    take=[]
    for y in range(10):
        ids=np.flatnonzero(panel['y']==y)
        order=sorted(ids,key=lambda i:hashlib.sha256(str(panel['record'][i]).encode()).digest())
        take.extend(order[:10])
    assert len(take)==100
    return {k:v[take] for k,v in panel.items()}

class MultipleOld(Track):
    def consider(self,mats,desc):
        self.check()
        v={k:stats(forward(x,mats,self.p,self.law)[0],y) for k,(x,y) in self.dev.items()}
        t=since(self.start);self.eval_count+=1
        gain={k:v[k][0]-self.ref[k][0] for k in v}
        ok=gain['new']>=.02-1e-12 and min(gain['old'],gain['previous'])>=-.02-1e-12
        rank=(v['new'][0],min(gain['old'],gain['previous']),-v['new'][1])
        idx=len(self.history);self.history.append(dict(option=desc,dev=v,time=t,eligible=ok))
        if ok:
            for b in RUNGS:
                if t['cpu']<=b and (self.picks[b][0] is None or rank>self.picks[b][0]):
                    self.picks[b]=[rank,[w.copy() for w in mats],idx]
        self.check()

def sgd(track,x,y):
    states=[]
    for lr in (.003,.015,.05):
        m=[w.copy() for w in track.original]
        states.append((lr,np.random.default_rng(track.seed+5656),m,[(np.zeros_like(w),np.zeros_like(w)) for w in m]))
    step=0
    while True:
        step+=1
        for lr,rng,mats,mom in states:
            track.check();idx=np.concatenate([g*100+rng.choice(100,16,replace=False) for g in range(3)])
            gs=grad(x[idx],mats,track.p,track.law,y[idx])
            for w,g,(u,v) in zip(mats,gs,mom):
                u*=.9;u+=.1*g;v*=.999;v+=.001*g*g
                w-=lr*(u/(1-.9**step))/(np.sqrt(v/(1-.999**step))+1e-8)
            if step==1 or step%4==0:track.consider(mats,{'step':step,'lr':lr})

def ridge(track,x,y):
    m=track.original; parent=track.p;law=track.law
    z=forward(x,m,parent,law)[0];raw=x.reshape(len(x),-1);mu=raw.mean(0);sd=np.maximum(raw.std(0),1e-4);u=(raw-mu)/sd
    cov=u.T@u/len(u);rhs=u.T@(y-z)/len(u)
    hist=[];options={};wins={r:None for r in RUNGS}
    for reg in (.01,.1,1):
        W=np.linalg.solve(cov+reg*np.eye(len(cov)),rhs);options[reg]=W
        v={}
        for k,(a,t) in track.dev.items():
            pred=forward(a,m,parent,law)[0]+((a.reshape(len(a),-1)-mu)/sd)@W
            v[k]=stats(pred,t)
        g={k:v[k][0]-track.ref[k][0] for k in v}
        ok=g['new']>=.02-1e-12 and min(g['old'],g['previous'])>=-.02-1e-12
        rank=(v['new'][0],min(g['old'],g['previous']),-v['new'][1]);t=since(track.start)
        hist.append(dict(dev=v,time=t,reg=reg,eligible=ok))
        if ok:
            for b in RUNGS:
                if t['cpu']<=b and (wins[b] is None or rank>wins[b][0]):wins[b]=(rank,reg)
    el=since(track.start);out={}
    for b in RUNGS:
        reg=wins[b][1] if wins[b] else None;W=options[reg] if reg is not None else np.zeros_like(next(iter(options.values())))
        f=track.out/f'ridge_{b}.npz';np.savez_compressed(f,w=W,mean=mu,scale=sd)
        out[b]=dict(selection=reg,sha256=sha(f),cpu_upper=el['cpu'],wall_upper=el['wall'])
    dump(track.out/'ridge.json',dict(picks=out,history=hist,finished=el))

def main(a):
    src=a.models/f'{a.arch}_{a.seed}';out=a.out/f'{a.arch}_{a.seed}_{a.start}';out.mkdir(parents=True,exist_ok=True)
    begin=clock();p=fields(src/'parent.npz')
    prevsha=None
    if a.start=='after1':
        f=src/'lm_joint_15.npz';w=fields(f);prevsha=sha(f);p['encoder']=w['sender'];p['W']=w['receiver']
    np.savez_compressed(out/'parent.npz',**p)
    mats=[p['encoder'],p['W']];law=Cell(src/'smooth.npz' if a.arch=='smooth' else a.law)
    files={'new':(a.sc/'support.npz',a.sc/'development.npz'),'old':(a.prior/'old_cal.npz',a.prior/'old_dev.npz'),'previous':(a.prior/'new_cal.npz',a.prior/'new_dev.npz')}
    cal={};dev={}
    for k,(cf,df) in files.items():
        c=support(load_panel(cf));d=load_panel(df)
        cal[k]=(standardized(c['x'],p),c['y']);dev[k]=(standardized(d['x'],p),d['y'])
    X=np.concatenate([cal[k][0] for k in ('new','old','previous')])
    targets=np.vstack([np.eye(10)[cal['new'][1]],forward(cal['old'][0],mats,p,law)[0],forward(cal['previous'][0],mats,p,law)[0]])
    ref={k:stats(forward(x,mats,p,law)[0],y) for k,(x,y) in dev.items()}
    dump(out/'parent.json',dict(old=sha(src/'parent.npz'),stage1=prevsha,parents=sha(out/'parent.npz'),base=ref,setup=since(begin)))
    methods=['lm_joint','bp','joint','ridge']
    if a.arch=='literal':methods+=['wrong']
    off=(271,577,911).index(a.seed)+(a.start=='after1');methods=methods[off:]+methods[:off]
    for method in methods:
        if (out/(method+'.json')).exists():continue
        print(a.arch,a.seed,a.start,method,flush=True)
        track=MultipleOld(method,a.seed,p,law,dev,out,ref,mats);y=targets.copy()
        if method=='ridge':ridge(track,X,y);continue
        if method=='wrong':y[:100]=np.eye(10)[(cal['new'][1]+1)%10]
        try:
            if method=='bp':sgd(track,X,y)
            elif method=='joint':secants(track,X,y,100,False)
            else:released_update(track,X,y,True)
        except Expired:track.save()
    print('done',a.arch,a.seed,a.start,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('prior','sc','models','out','law'):p.add_argument(n,type=Path)
    p.add_argument('arch',choices=('literal','smooth'));p.add_argument('seed',type=int,choices=(271,577,911))
    p.add_argument('start',choices=('parent0','after1'));main(p.parse_args())
