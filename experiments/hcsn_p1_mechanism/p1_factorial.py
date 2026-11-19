"""P1 eight-arm Call/Risk/Margin attribution *pilot*, deliberately not a closure.

Every arm sees exactly the same frozen scalar Encoder input and stream; all
have the same three active nonlinear basis coefficients, recurrent model,
trainable parameter count and update schedule. The financial bases are
fixed He-Xiong scalar readouts at a *single* nominal financial regime,
calibrated to value=0 / signed slope=+1 at the same training-only anchor.
They are not option prices, independent information, or evidence of a novel
neuron. CPU PyTorch pilot; no P1 scientific superiority claim is permitted.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.special import ndtr, log_ndtr
import torch
from torch import nn
import torch.nn.functional as F

from experiments.hcsn_hx_unified_v3.hx import HX, boundary, bond_value, equity_closed

ARMS=("ordinary","call","risk","margin","call_risk","call_margin","risk_margin","all_three")
REPLACE={"ordinary":(),"call":(0,),"risk":(1,),"margin":(2,),
         "call_risk":(0,1),"call_margin":(0,2),"risk_margin":(1,2),"all_three":(0,1,2)}
TASKS=("selective_copy","key_value_overwrite")
SCHEMA='hcsn-p1-factorial-pilot-v1'


def _finance_readout(p: HX, z: float, b: float) -> np.ndarray:
    """Deterministic function of the *same* scalar encoded input, not extra data."""
    asset=b*math.exp(.95+.26*z) # always >b on [-1,1]
    logv=math.log(asset/b)
    u=p.volatility*math.sqrt(p.maturity)
    risk=float(ndtr((-logv-p.a*u*u)/u))
    # The log-tail product has a potentially huge opposite-sign exponent.
    risk+=math.exp(-2*p.a*logv+float(log_ndtr((-logv+p.a*u*u)/u)))
    return np.array((equity_closed(p,asset,b),risk,
                     bond_value(p,asset,p.maturity,b)-p.per_bond_principal),dtype=np.float64)


def _ordinary(z: np.ndarray):
    # All 3 ordinary bases are distinct and match +1 signed slope at zero.
    shifts=np.array((-.9,0.,.9))
    slope=1.4/(np.cosh(shifts)**2)
    return (np.tanh(1.4*z[...,None]+shifts)-np.tanh(shifts))/slope


def make_basis_table(n: int=101) -> dict:
    """Anchor, derivative and rank checks must pass before any model training."""
    if type(n) is not int or n<51 or n%2!=1:
        raise ValueError('invalid fixed interpolation resolution')
    p=HX(); b=boundary(p)
    grid=np.linspace(-1.,1.,n,dtype=np.float64)
    sample=np.stack([_finance_readout(p,float(z),b) for z in grid])
    if not np.all(np.isfinite(sample)):
        raise ValueError('nonfinite financial readout')
    fns=[PchipInterpolator(grid,sample[:,i]) for i in range(3)]
    slopes=np.array([float(fn.derivative()(0.)) for fn in fns])
    if np.any(~np.isfinite(slopes)) or np.any(np.abs(slopes)<1e-9):
        raise ValueError('financial feature has vanishing anchor slope')
    financial=np.column_stack([(fn(grid)-fn(0.))/s for fn,s in zip(fns,slopes)])
    ordinary=_ordinary(grid)
    if not np.allclose(financial[n//2],0.,atol=1e-11):
        raise ValueError('anchor value mismatch')
    def _rank(a):
        # Real effective-parameter geometry: normalize columns before SVD.
        norms=np.linalg.norm(a,axis=0)
        if np.any(norms<1e-5): raise ValueError('inactive nonlinear basis')
        singular=np.linalg.svd(a/norms,compute_uv=False)
        if singular[-1]<1e-4: raise ValueError('rank-deficient basis')
        return [float(x) for x in singular]
    columns={}
    for arm in ARMS:
        panel=ordinary.copy()
        for j in REPLACE[arm]: panel[:,j]=financial[:,j]
        columns[arm]=dict(values=panel.tolist(), singular_values=_rank(panel))
    return dict(grid=grid.tolist(),ordinary=ordinary.tolist(),financial=financial.tolist(),
                financial_original_anchor_slopes=slopes.tolist(),
                normalized_anchor_slopes=[1.,1.,1.],
                financial_barrier=float(b),columns=columns)


def interpolate_basis(table: dict, arm: str, z: np.ndarray) -> np.ndarray:
    if arm not in ARMS or np.any(~np.isfinite(z)) or np.any(np.abs(z)>1.000001):
        raise ValueError('invalid basis or normalized encoder input')
    grid=np.array(table['grid'])
    values=np.array(table['columns'][arm]['values'])
    return np.stack([np.interp(z,grid,values[:,j]) for j in range(3)],axis=-1).astype('float32')


def make_data(task: str, *, n: int, length: int, seed: int,
              ood: bool=False) -> tuple[np.ndarray,np.ndarray]:
    if task not in TASKS or n<1 or length<8: raise ValueError('invalid task')
    rng=np.random.default_rng(seed)
    x=np.zeros((n,length,3),dtype='float32')
    labels=np.zeros(n,dtype='float32')
    if task=='selective_copy':
        x[:,:,0]=rng.choice([-1.,1.],size=(n,length))
        x[:,:,2]=rng.uniform(-1.,1.,size=(n,length))
        for i in range(n):
            # OOD length 28 gives markedly longer distances to target.
            mark=int(rng.integers(1,max(2,length//3))) if ood else int(rng.integers(1,length-1))
            x[i,mark,1]=1.;labels[i]=float(x[i,mark,0]>0)
    else:
        x[:,:,0]=rng.choice([-1.,1.],size=(n,length)) # 2 keys
        x[:,:,1]=rng.choice([-1.,1.],size=(n,length)) # values
        x[:,:-1,2]=1. # memory writes; overwritten later
        for i in range(n):
            query=float(rng.choice([-1.,1.]))
            x[i,-1]=[query,0.,2.]
            matching=np.where(x[i,:-1,0]==query)[0]
            if len(matching)==0:
                x[i,0,0]=query;matching=np.array([0])
            labels[i]=float(x[i,int(matching[-1]),1]>0)
    return x,labels


def encoder_z(x: np.ndarray) -> np.ndarray:
    """Frozen shared encoder; same source coordinates for all arms."""
    z=np.tanh(.55*x[:,:,0]-.35*x[:,:,1]+.20*x[:,:,2]).astype('float32')
    if np.max(np.abs(z))>1:raise ValueError('invalid encoded domain')
    return z


class RecurrentReadout(nn.Module):
    def __init__(self,hidden: int=20):
        super().__init__()
        self.input=nn.Linear(3,hidden)
        self.recurrence=nn.Linear(hidden,hidden,bias=False)
        # Exactly 3 separate active nonlinear channels in EVERY arm.
        self.channels=nn.Parameter(torch.empty((3,hidden)))
        nn.init.normal_(self.channels,0.,.03)
        self.head=nn.Linear(hidden,1)
        self.hidden=hidden

    def forward(self,x,basis):
        h=x.new_zeros((x.shape[0],self.hidden))
        for i in range(x.shape[1]):
            h=torch.tanh(.65*h+self.input(x[:,i])+self.recurrence(h)
                         +basis[:,i]@self.channels)
        return self.head(h).squeeze(-1)


def _set_seed(seed: int):
    torch.manual_seed(seed)
    np.random.seed(seed%2**32)


def run_arm(task,arm,seed,table,*,updates=65,batch=48,hidden=20,
            train_count=512,test_count=384) -> dict:
    """Every arm receives identical data, initial weights and minibatch indices."""
    if task not in TASKS or arm not in ARMS or seed<0:
        raise ValueError('invalid preregistered task/arm/seed')
    xtr,ytr=make_data(task,n=train_count,length=12,seed=10000+seed)
    xte,yte=make_data(task,n=test_count,length=12,seed=20000+seed)
    xod,yod=make_data(task,n=test_count,length=28,seed=30000+seed,ood=True)
    begin_cpu=time.process_time();begin_wall=time.perf_counter()
    feat=[]
    for x in (xtr,xte,xod):
        feat.append(torch.from_numpy(interpolate_basis(table,arm,encoder_z(x))))
    xt,xe,xo=(torch.from_numpy(x) for x in (xtr,xte,xod))
    yt,ye,yo=(torch.from_numpy(y) for y in (ytr,yte,yod))
    precompute_cpu_seconds=time.process_time()-begin_cpu
    _set_seed(50000+seed)
    model=RecurrentReadout(hidden)
    param_count=sum(z.numel() for z in model.parameters() if z.requires_grad)
    optimizer=torch.optim.Adam(model.parameters(),lr=.012)
    sampler=np.random.default_rng(60000+seed)
    schedule=sampler.integers(0,train_count,size=(updates,batch))
    # identical completed updates, same data order, never per-arm early stop
    train_cpu_start=time.process_time()
    model.train()
    for ids in schedule:
        optimizer.zero_grad(set_to_none=True)
        logits=model(xt[ids],feat[0][ids])
        loss=F.binary_cross_entropy_with_logits(logits,yt[ids])
        loss.backward()
        optimizer.step()
    train_cpu_seconds=time.process_time()-train_cpu_start
    inference_cpu_start=time.process_time()
    model.eval()
    with torch.no_grad():
        pte=torch.sigmoid(model(xe,feat[1]))
        pod=torch.sigmoid(model(xo,feat[2]))
        acc=lambda a,y: float(((a>=.5)==(y>=.5)).float().mean())
        id_acc=acc(pte,ye);ood_acc=acc(pod,yo)
        id_logloss=float(F.binary_cross_entropy(pte,ye))
        ood_logloss=float(F.binary_cross_entropy(pod,yo))
        id_prob_checksum=hashlib.sha256(pte.numpy().tobytes()).hexdigest()
    inference_cpu_seconds=time.process_time()-inference_cpu_start
    return dict(task=task,arm=arm,seed=seed,train_count=train_count,test_count=test_count,
                updates=updates,batch=batch,hidden=hidden,params=param_count,
                id_acc=id_acc,ood_acc=ood_acc,id_logloss=id_logloss,ood_logloss=ood_logloss,
                ood_minus_id=ood_acc-id_acc,
                basis_precompute_cpu_seconds=precompute_cpu_seconds,
                train_cpu_seconds=train_cpu_seconds,inference_cpu_seconds=inference_cpu_seconds,
                cpu_seconds=time.process_time()-begin_cpu,
                wall_seconds=time.perf_counter()-begin_wall,
                id_probability_sha256=id_prob_checksum)


def run_full(*,seeds=(0,1,2),updates=65,batch=48,hidden=20,
             train_count=512,test_count=384):
    torch.set_num_threads(1)
    # Warm PyTorch once to remove one-sided lazy-library cold start from arm 0.
    warm=RecurrentReadout(hidden)
    with torch.no_grad():warm(torch.zeros(1,3,3),torch.zeros(1,3,3))
    del warm
    table=make_basis_table()
    records=[]
    for task in TASKS:
        for seed in seeds:
            # Rotate ordering across paired seeds to avoid systematic hot/cold advantage.
            order=ARMS[seed%len(ARMS):]+ARMS[:seed%len(ARMS)]
            for arm in order:
                records.append(run_arm(task,arm,seed,table,updates=updates,batch=batch,
                                       hidden=hidden,train_count=train_count,test_count=test_count))
    counts={x['params'] for x in records}
    if len(counts)!=1:raise RuntimeError('parameter-mismatch control violation')
    # Exact paired seed-sign randomization test, no asymptotic Gaussian CI.
    import itertools
    def sign_p(deltas):
        obs=abs(float(np.mean(deltas)))
        cases=[abs(float(np.mean(np.array(deltas)*np.array(signs))))
               for signs in itertools.product((-1.,1.),repeat=len(deltas))]
        return float(sum(x>=obs-1e-14 for x in cases)/len(cases))
    summary=[]
    for task in TASKS:
        base={r['seed']:r for r in records if r['task']==task and r['arm']=='ordinary'}
        for arm in ARMS:
            runs=[r for r in records if r['task']==task and r['arm']==arm]
            paired=[r['ood_acc']-base[r['seed']]['ood_acc'] for r in runs]
            summary.append(dict(task=task,arm=arm,
                                mean_id_acc=float(np.mean([r['id_acc'] for r in runs])),
                                mean_ood_acc=float(np.mean([r['ood_acc'] for r in runs])),
                                mean_paired_ood_delta=float(np.mean(paired)),
                                paired_ood_deltas=paired,
                                signflip_two_sided_p=(sign_p(paired) if arm!='ordinary' else 1.0),
                                mean_cpu_seconds=float(np.mean([r['cpu_seconds'] for r in runs]))))
    # Holm family-wise correction across 7 nonbaseline arms * 2 tasks.
    contrasts=sorted((v for v in summary if v['arm']!='ordinary'),
                     key=lambda v:v['signflip_two_sided_p'])
    running=0.
    for i,v in enumerate(contrasts):
        running=max(running,min(1.,(len(contrasts)-i)*v['signflip_two_sided_p']))
        v['holm_adjusted_p']=running
    result=dict(schema=SCHEMA,readout='HX financial-equity/first-hit-risk/rollover-margin scalar proxies',
                definition='small pilot; not preregistered scientific superiority gate',
                seeds=list(seeds),candidate_count=len(records),active_param_count=counts.pop(),
                data_and_encoder_shared=True,
                signed_local_slope_matched=True,
                no_future_information=True,
                no_model_selection=True,
                equal_updates_not_equal_measured_cpu=True,
                precomputed_financial_lookup_not_full_online_cost=True,
                production_activation=False,all_scientific_blockers_closed=False,
                source_model='tiny frozen scalar encoder and learned recurrent readout, NOT full HCSN',
                hardware='PyTorch CPU single thread',
                finance_original_anchor_slopes=table['financial_original_anchor_slopes'],
                feature_singular_values={a:table['columns'][a]['singular_values'] for a in ARMS},
                records=records,summary=summary)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    parser.add_argument('--updates',type=int,default=65)
    parser.add_argument('--seeds',type=int,default=3)
    args=parser.parse_args()
    result=run_full(seeds=tuple(range(args.seeds)),updates=args.updates)
    path=Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
    blob=json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+'\n'
    path.write_text(blob)
    print(json.dumps(dict(path=str(path),sha256=hashlib.sha256(blob.encode()).hexdigest(),
                          runs=len(result['records']),summary=result['summary']),indent=2))

if __name__=='__main__': main()
