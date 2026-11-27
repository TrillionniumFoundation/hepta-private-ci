import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
from scipy.linalg import eigh
from threadpoolctl import threadpool_info
from receiver import Cell, brier, delta_grad, encode, fitted_parent, scores

SEEDS=(271,577,911)
BUDGETS=(3,15,45)
ARMS=('direct','wrong','bp','lora')
RATES=(.003,.015,.05)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,data): path.write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n')


def load_data(root,key):
    with np.load(root/(key+'.npz'),allow_pickle=False) as d:
        return d['x'].astype('float64'),d['y'],d['speaker'],d['record']


def panel(root,key,p,law,subsample=False):
    x,y,speaker,name=load_data(root,key)
    if subsample:
        rng=np.random.default_rng(17319)
        # Original recordings remain balanced across both labels and speakers.
        chosen=[]
        for digit in range(10):
            for sp in sorted(set(speaker)):
                obs=np.flatnonzero((speaker==sp)&(y==digit))
                chosen.extend(rng.choice(obs,12//len(set(speaker)),replace=False))
        i=np.sort(chosen);x=x[i];y=y[i];name=name[i]
    return encode(x,p,law),y,name


def dev_metrics(dv,w,p,law):
    out={}
    for split,(k,y,_) in dv.items():
        z,_=scores(k,w,p,law)
        out[split]=[float(np.mean(z.argmax(1)==y)),float(brier(z,y).mean())]
    return out


def numerical(p,law,root):
    rng=np.random.default_rng(402)
    k=rng.normal(size=(4,6,12));t=rng.normal(size=(4,10))
    g=delta_grad(k,p['W'],p,law,t)
    checks=[]
    for _ in range(8):
        direction=rng.normal(size=g.shape);direction/=np.linalg.norm(direction)
        step=1.e-6
        vals=[]
        for sign in (1,-1):
            z,_=scores(k,p['W']+sign*step*direction,p,law)
            vals.append(np.mean((z-t)**2))
        est=(vals[0]-vals[1])/(2*step)
        exact=float((g*direction).sum());checks.append([exact,est,abs(exact-est)])
    if max(row[2] for row in checks)>2.e-6: raise ArithmeticError(checks)
    return checks


def adam(g,states,lr,step):
    m,v=states;m*=.9;m+=.1*g;v*=.999;v+=.001*g*g
    return lr*(m/(1-.9**step))/(np.sqrt(v/(1-.999**step))+1e-8)


def direction_bank(kold,knew):
    ko=kold.reshape(-1,kold.shape[-1]);kn=knew.reshape(-1,knew.shape[-1])
    old=ko.T@ko/len(ko);new=kn.T@kn/len(kn)
    _,vec=eigh(new+.001*np.eye(len(old)),old+.05*np.trace(old)/len(old)*np.eye(len(old)))
    vec=vec[:,::-1];return vec/np.linalg.norm(vec,axis=0,keepdims=True)


def fit_arm(seed,budget,arm,p,law,cal,dv,base):
    start=time.process_time();wall=time.perf_counter()
    k=np.concatenate([cal['new'][0],cal['old'][0]])
    n=len(cal['new'][0]); d=p['W'].shape[1]
    label=cal['new'][1]
    if arm=='wrong':label=(label+1)%10
    old_target=scores(cal['old'][0],p['W'],p,law)[0]
    target=np.concatenate([np.eye(10)[label],old_target])
    chosen=p['W'].copy(); chosen_score=None;history=[];admissible=0;pick=None
    cpu=lambda:time.process_time()-start

    def consider(w,info):
        nonlocal chosen,chosen_score,pick,admissible
        if cpu()>=budget:return
        val=dev_metrics(dv,w,p,law);elapsed=cpu()
        new=val['new'][0];old=val['old'][0]
        ok=elapsed<=budget and new>=base['new'][0]+.02-1e-12 and old>=base['old'][0]-.02-1e-12
        row={**info,'cpu':elapsed,'new_acc':new,'old_acc':old,'new_brier':val['new'][1],'eligible':bool(ok)}
        history.append(row)
        rank=(new,old,-val['new'][1])
        if ok:
            admissible+=1
            if chosen_score is None or rank>chosen_score:
                chosen=w.copy();chosen_score=rank;pick=len(history)-1

    if arm in ('direct','wrong'):
        vec=direction_bank(cal['old'][0],cal['new'][0]);w=p['W'].copy();iteration=0
        while cpu()<budget:
            initial=scores(k,w,p,law)[0]
            # Four new/old covariance directions × four receiver coordinates per round.
            # Rotate endpoint coordinates and introduce other admissible directions in later rounds.
            group=np.array([(3*iteration+j)%len(vec) for j in range(4)])
            cols=np.array([(4*iteration+j)%d for j in range(4)])
            dirs=[];jacs=[]
            for j in group:
                for col in cols:
                    if cpu()>=budget:break
                    delta=np.zeros_like(w);delta[:,col]=vec[:,j];h=.018
                    hi=scores(k,w+h*delta,p,law)[0];lo=scores(k,w-h*delta,p,law)[0]
                    dirs.append(delta);jacs.append(((hi-lo)/(2*h)).ravel())
                if cpu()>=budget:break
            if len(dirs)!=16 or cpu()>=budget:break
            J=np.stack(jacs,axis=1);cov=J.T@J/len(J)
            rhs=J.T@(target-initial).ravel()/len(J)
            coeff=np.linalg.solve(cov+np.eye(len(cov))*(.02*np.trace(cov)/len(cov)+1e-7),rhs)
            delta=np.einsum('g,gij->ij',coeff,np.array(dirs))
            norm=np.linalg.norm(delta);delta*=min(1,1.5/max(norm,1e-12))
            for scale in (.25,.5,1.):
                consider(w+scale*delta,{'iter':iteration,'scale':scale})
            # Forward-only line search on calibration rows; development chooses archived candidates.
            if cpu()>=budget:break
            candidates=[w,w+.25*delta,w+.5*delta,w+delta]
            w=min(candidates,key=lambda v:np.mean((scores(k,v,p,law)[0]-target)**2))
            iteration+=1
    else:
        states=[]
        for lr in RATES:
            rng=np.random.default_rng(1993+seed)
            if arm=='bp': pars=[p['W'].copy()]
            else:pars=[rng.normal(scale=.08,size=(d,3)),np.zeros((3,d))]
            moments=[(np.zeros_like(a),np.zeros_like(a)) for a in pars]
            states.append((lr,rng,pars,moments))
        step=0
        while cpu()<budget:
            step+=1
            for lr,rng,pars,moments in states:
                if cpu()>=budget:break
                ids=np.r_[rng.choice(n,32,False),n+rng.choice(len(k)-n,32,False)]
                w=pars[0] if arm=='bp' else p['W']+pars[0]@pars[1]
                g=delta_grad(k[ids],w,p,law,target[ids])
                grads=[g] if arm=='bp' else [g@pars[1].T,pars[0].T@g]
                for par,gp,st in zip(pars,grads,moments):
                    par-=adam(gp,st,lr,step)
                if step in (1,2,4) or step%8==0:
                    w=pars[0] if arm=='bp' else p['W']+pars[0]@pars[1]
                    consider(w,{'step':step,'lr':lr})
    return chosen,{'seed':seed,'budget':budget,'arm':arm,'cpu':cpu(),'wall':time.perf_counter()-wall,'selected':pick,'admissible':admissible,'history':history,'changed':int((chosen!=p['W']).sum()),'calibration_records':{q:[str(x) for x in cal[q][2]] for q in cal}}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('data',type=Path);parser.add_argument('table',type=Path);parser.add_argument('out',type=Path);parser.add_argument('--seed',type=int,choices=SEEDS,required=True)
    a=parser.parse_args();out=a.out;out.mkdir(exist_ok=True,parents=True)
    mark=time.process_time();wall=time.perf_counter()
    law=Cell(a.table);x,y,_,_=load_data(a.data,'parent')
    p=fitted_parent(x,y,a.seed,law)
    cal={s:panel(a.data,s+'_cal',p,law,True) for s in ('old','new')}
    dv={s:panel(a.data,s+'_dev',p,law) for s in ('old','new')}
    base=dev_metrics(dv,p['W'],p,law)
    np.savez_compressed(out/('parent_'+str(a.seed)+'.npz'),**p)
    status={'seed':a.seed,'dev':base,'gradient_check':numerical(p,law,a.data),'common_prep_cpu':time.process_time()-mark,'common_prep_wall':time.perf_counter()-wall,'platform':platform.platform(),'threadpools':threadpool_info(),'source_table_sha256':sha(a.table)}
    dump(out/f'parent_{a.seed}.json',status)
    print('parent prepared',a.seed,flush=True)
    for budget in BUDGETS:
        for offset in range(len(ARMS)):
            arm=ARMS[(offset+SEEDS.index(a.seed))%len(ARMS)]
            w,rec=fit_arm(a.seed,budget,arm,p,law,cal,dv,base)
            stem=out/f'{arm}_{a.seed}_{budget}'
            np.save(str(stem)+'.npy',w)
            dump(stem.with_suffix('.json'),rec)
            print('fit complete',a.seed,budget,arm,flush=True)


if __name__=='__main__':
    main()
