"""Run all editing streams at three nested CPU budgets from one shared parent."""
import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path
import numpy as np
from scipy.linalg import eigh
from model import Cell,balanced,checks,fitted_parent,forward,grad,load_panel,smooth_law,standardized

SEEDS=(271,577,911)
ACTIVE=('joint','receiver','bp','lora','wrong')
RUNGS=(3,15,60)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,obj):p.write_text(json.dumps(obj,allow_nan=False,indent=2)+'\n')
def clock():return (time.process_time(),time.perf_counter())
def since(start):
    c,w=clock();return {'cpu':c-start[0],'wall':w-start[1]}
def stats(a,y):return [float((a.argmax(1)==y).mean()),float(np.mean((a-np.eye(10)[y])**2))]
def fields(path):
    with np.load(path,allow_pickle=False) as f:return dict(f)
def directions(new,old):
    zn=new.reshape(-1,new.shape[-1]);zo=old.reshape(-1,old.shape[-1])
    a=zn.T@zn/len(zn);b=zo.T@zo/len(zo)
    eig,v=eigh(a+np.eye(len(a))*.001,b+.05*np.trace(b)*np.eye(len(b))/len(b))
    v=v[:,::-1];return v/np.linalg.norm(v,axis=0,keepdims=True)

class Expired(Exception):pass

class Track:
    def __init__(self,arm,seed,p,law,dev,out,ref,mats):
        self.start=clock();self.arm=arm;self.seed=seed;self.p=p;self.law=law;self.dev=dev;self.out=out;self.ref=ref
        self.picks={r:[None,[a.copy() for a in mats],None] for r in RUNGS}
        self.reached={};self.history=[];self.original=mats;self.eval_count=0
    def check(self):
        t=since(self.start)
        for r in RUNGS:
            if t['cpu']>=r and r not in self.reached:self.reached[r]=t
        if t['cpu']>=RUNGS[-1]:raise Expired
        return t
    def consider(self,mats,desc):
        self.check()
        val={k:stats(forward(x,mats,self.p,self.law)[0],y) for k,(x,y) in self.dev.items()}
        self.eval_count+=1;t=since(self.start)
        active=val['new'][0]>=self.ref['new'][0]+.02-1.e-12 and val['old'][0]>=self.ref['old'][0]-.02-1.e-12
        score=(val['new'][0],val['old'][0],-val['new'][1])
        i=len(self.history);self.history.append({'option':desc,'time':t,'dev':val,'eligible':active})
        if active:
            for r in RUNGS:
                if t['cpu']<=r and (self.picks[r][0] is None or score>self.picks[r][0]):
                    self.picks[r]=[score,[a.copy() for a in mats],i]
        self.check()
    def save(self):
        used=since(self.start);picks={}
        for r in RUNGS:
            score,ms,idx=self.picks[r];path=self.out/f'{self.arm}_{r}.npz'
            np.savez_compressed(path,sender=ms[0],receiver=ms[1])
            picks[r]={'selection':idx,'sha256':sha(path),'wall_upper':self.reached.get(r,used)['wall'],
                      'cpu_upper':self.reached.get(r,used)['cpu'],
                      'ranks':[int(np.linalg.matrix_rank(b-a)) for a,b in zip(self.original,ms)],
                      'norms':[float(np.linalg.norm(b-a)) for a,b in zip(self.original,ms)]}
        dump(self.out/(self.arm+'.json'),dict(picks=picks,history=self.history,finished=used,candidates=self.eval_count))

def secants(track,x,targets,n,receiver_only):
    w=[a.copy() for a in track.original];count=0
    nper=12 if receiver_only else 6
    first=directions(x[:n],x[n:]);dd=.018
    while True:
        track.check();z,(_,_,keys)=forward(x,w,track.p,track.law);kay=directions(keys[:n],keys[n:])
        descriptors=[];jac=[]
        for stage in ([1] if receiver_only else [0,1]):
            basis=[first,kay][stage];cols=w[stage].shape[1];r=basis.shape[1]
            for j in range(nper):
                track.check()
                # Cover every output column first; alternate preferred and lower support directions over rounds.
                flat=nper*count+j; col=flat%cols;index=(flat//cols+col//3)%r
                d=np.zeros_like(w[stage]);d[:,col]=basis[:,index]
                plus=w.copy();minus=w.copy();plus[stage]=w[stage]+dd*d;minus[stage]=w[stage]-dd*d
                hi=forward(x,plus,track.p,track.law)[0];lo=forward(x,minus,track.p,track.law)[0]
                jac.append(((hi-lo)/(2*dd)).ravel());descriptors.append((stage,d))
        J=np.stack(jac,1);cov=J.T@J/J.shape[0]
        alpha=np.linalg.solve(cov+np.eye(len(cov))*(.02*np.trace(cov)/len(cov)+1.e-7),J.T@(targets-z).ravel()/J.shape[0])
        delta=[np.zeros_like(a) for a in w]
        for a,(which,d) in zip(alpha,descriptors):delta[which]+=a*d
        alpha_norm=min(1,1.5/max(1.e-12,np.sqrt(sum(np.sum(v*v) for v in delta))))
        options=[w];loss=[np.mean((z-targets)**2)]
        for f in (.25,.5,1):
            cur=[v+f*alpha_norm*d for v,d in zip(w,delta)]
            track.consider(cur,{'round':count,'scale':f})
            options.append(cur);loss.append(np.mean((forward(x,cur,track.p,track.law)[0]-targets)**2))
        w=options[int(np.argmin(loss))];count+=1

def adam(track,x,y,n,lora):
    rates=(.003,.015,.05);states=[];old=track.original;step=0
    for lr in rates:
        rng=np.random.default_rng(1993+track.seed)
        if lora:
            params=[]
            for w in old:params.extend([rng.normal(scale=.08,size=(w.shape[0],3)),np.zeros((3,w.shape[1]))])
        else:params=[w.copy() for w in old]
        states.append((lr,rng,params,[(np.zeros_like(a),np.zeros_like(a)) for a in params]))
    def merged(params):
        return [old[i]+params[2*i]@params[2*i+1] for i in range(2)] if lora else params
    while True:
        step+=1
        for lr,rng,params,mom in states:
            track.check()
            idx=np.concatenate((rng.choice(n,24,replace=False),n+rng.choice(len(x)-n,24,replace=False)))
            gs=grad(x[idx],merged(params),track.p,track.law,y[idx])
            if lora:gs=[g for i,d in enumerate(gs) for g in (d@params[2*i+1].T,params[2*i].T@d)]
            for v,g,(m,u) in zip(params,gs,mom):
                m*=.9;m+=.1*g;u*=.999;u+=.001*g*g
                v-=lr*(m/(1-.9**step))/(np.sqrt(u/(1-.999**step))+1e-8)
            if step==1 or step%4==0:track.consider(merged(params),{'lr':lr,'step':step})

def acoustic_ridge(x,y,parent,law,dev,base,out):
    st=clock();m=[parent['encoder'],parent['W']]
    z=forward(x,m,parent,law)[0];flat=x.reshape(len(x),-1)
    fm=flat.mean(0); fs=np.maximum(flat.std(0),1.e-4);u=(flat-fm)/fs
    residual=y-z
    cov=u.T@u/len(u);rhs=u.T@residual/len(u)
    history=[];picks={r:None for r in RUNGS};weights={}
    for reg in (.01,.1,1.):
        w=np.linalg.solve(cov+reg*np.eye(len(cov)),rhs);weights[reg]=w
        val={}
        for k,(a,b) in dev.items():
            v=forward(a,m,parent,law)[0]+((a.reshape(len(a),-1)-fm)/fs)@w
            val[k]=stats(v,b)
        t=since(st);rank=(val['new'][0],val['old'][0],-val['new'][1]);ok=rank[0]>=base['new'][0]+.02-1e-12 and rank[1]>=base['old'][0]-.02-1e-12
        if ok:
            for r in RUNGS:
                if t['cpu']<=r and (picks[r] is None or rank>picks[r][0]):picks[r]=(rank,reg)
        history.append(dict(reg=reg,time=t,dev=val,eligible=ok))
    used=since(st);outcomes={}
    for r,entry in picks.items():
        chosen=entry[1] if entry else None;w=np.zeros_like(next(iter(weights.values()))) if chosen is None else weights[chosen]
        path=out/f'ridge_{r}.npz';np.savez_compressed(path,w=w,mean=fm,scale=fs)
        outcomes[r]=dict(selection=chosen,sha256=sha(path),wall_upper=used['wall'],cpu_upper=used['cpu'])
    dump(out/'ridge.json',dict(picks=outcomes,history=history,finished=used))

def main(arg):
    out=arg.work/f'{arg.arch}_{arg.seed}';out.mkdir(parents=True,exist_ok=True)
    wall=clock()
    if arg.arch=='smooth':
        table=out/'smooth.npz';smooth_law(arg.law,table)
    else:table=arg.law
    law=Cell(table);parent=load_panel(arg.data/'parent.npz')
    p=fitted_parent(parent['x'].astype('float64'),parent['y'],arg.seed,law)
    parent_fit=since(wall)
    maxdiff=None
    if arg.arch=='literal':
        ref=fields(arg.archive/f'parent_{arg.seed}.npz')
        maxdiff=max(float(abs(p[k]-v).max()) for k,v in ref.items());assert maxdiff<1e-9,maxdiff
        p=ref
    np.savez_compressed(out/'parent.npz',**p)
    base_mats=[p['encoder'],p['W']]
    diagnostic=checks(p,law)
    wall=clock();cal={};dev={}
    for mode in ('new','old'):
        c=balanced(load_panel(arg.data/(mode+'_cal.npz')),17319)
        cal[mode]=(standardized(c['x'],p),c['y'])
        d=load_panel(arg.data/(mode+'_dev.npz'));dev[mode]=(standardized(d['x'],p),d['y'])
    xx=np.concatenate([cal['new'][0],cal['old'][0]]);n=len(cal['new'][0])
    old=forward(cal['old'][0],base_mats,p,law)[0]; y=np.vstack((np.eye(10)[cal['new'][1]],old))
    base={k:stats(forward(a,base_mats,p,law)[0],b) for k,(a,b) in dev.items()}
    prep=since(wall)
    dump(out/'parent.json',dict(parent_fit=parent_fit,study_prep=prep,dev=base,gradcheck=diagnostic,archive_maxdiff=maxdiff,
                               parent_sha=sha(out/'parent.npz'),law_sha=sha(table)))
    # Equal rotation across parents interleaves arm order without affecting the fixed streams.
    arms=list(ACTIVE);rot=SEEDS.index(arg.seed)+(arg.arch=='smooth');arms=arms[rot:]+arms[:rot]
    for arm in arms:
        if (out/(arm+'.json')).exists():continue
        print(arg.arch,arg.seed,arm,flush=True);tr=Track(arm,arg.seed,p,law,dev,out,base,base_mats)
        tgt=y.copy()
        if arm=='wrong':tgt[:n]=np.eye(10)[(cal['new'][1]+1)%10]
        try:
            if arm in ('joint','receiver','wrong'):secants(tr,xx,tgt,n,arm=='receiver')
            else:adam(tr,xx,tgt,n,arm=='lora')
        except Expired:tr.save()
    acoustic_ridge(xx,y,p,law,dev,base,out)
    print('finished',arg.arch,arg.seed,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser()
    for name in ('data','archive','work','law'):ap.add_argument('--'+name,required=True,type=Path)
    ap.add_argument('--arch',choices=('literal','smooth'),required=True);ap.add_argument('--seed',choices=SEEDS,type=int,required=True)
    main(ap.parse_args())
