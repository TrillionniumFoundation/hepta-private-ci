"""P2 preregistered equal-*measured CPU* training pilot, research-only NO_GO.

Both arms consume the SAME sampled Brownian streams, examples, initial model,
parameters, optimizer, batch-index sequence and total CPU training budget.
Unlike the frozen-weight #4503 migration comparison, this program actually
learns each operation with its *own* update law. It cannot certify mechanism
superiority with two unblinded seeds or a Python-CPU microbenchmark.

The original per-observation aggregate-count model is left untouched. The
new forward uses sampled per-FIRE timestamps, with a vectorized padded
batched differentiable computation, rather than deferring FIREs to observation.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
import torch.nn.functional as F

from experiments.hcsn_hx_unified_v3.renewal_spike_sampler import SpikeStream
from .event_content import (DIM, TrainableEventContent, default_spec, example,
                            model_digest, canonical, UnresolvedContent)
from .timed_fire_content import timed_content_step

SCHEMA = 'hcsn-p2-timed-equal-cpu-training-pilot-v1'
ARMS = ('aggregate_count', 'physical_event_timestamp')
TASKS = ('copy','mqar4')
DATA_SIZES = ((128, 16, 100), (128, 16, 200), (128, 32, 300))
CPU_BUDGET=25.0
MAX_STEPS=2000
BATCH_SIZE=24


def _digest(data):
    h=hashlib.sha256()
    for key in ('x','y','mask','dt','count','event_gap','event_valid'):
        arr=data[key].contiguous().numpy()
        h.update(key.encode());h.update(str(arr.shape).encode())
        h.update(str(arr.dtype).encode());h.update(arr.tobytes())
    return h.hexdigest()


def physical_dataset(task: str, *, n:int, length:int, seed:int):
    """Independently replayable observed content + physical FIRE time gaps.

    A padded no-event slot has gap zero. The LAST gap is always the exact
    time from the final real FIRE to observation. Timestamp validity and
    event count are derived from the same raw physical first-hit stream.
    """
    if task not in TASKS or type(n) is not int or not 1<=n<=10000 or not 12<=length<=256 or type(seed) is not int:
        raise UnresolvedContent('invalid physical dataset request')
    spec=default_spec()
    xs=[];ys=[];ms=[];dts=[];cts=[];all_lists=[]
    total_events=0;multi_fire=0
    for actor in range(n):
        x,y,mask,dt,times=example(task,length=length,seed=seed*100000+actor)
        stream=SpikeStream(spec,seed=seed*100000+actor,
                           stream_id=f'{task}-{seed}-{actor}')
        per_observation=[]
        for endpoint in times:
            events=stream.advance_to(endpoint,max_events=1024)
            if any(not (0<=t<=endpoint) for t in events):
                raise UnresolvedContent('impossible FIRE timestamp')
            per_observation.append(tuple(events))
        xs.append(x);ys.append(y);ms.append(mask);dts.append(dt)
        cts.append(np.asarray([len(v) for v in per_observation],dtype=np.float32))
        all_lists.append((times,per_observation))
        total_events+=stream.events;multi_fire+=int(stream.events>=2)
    max_fire=max(max(len(e) for e in v) for _,v in all_lists)
    if max_fire>64:
        raise UnresolvedContent('unbounded FIRE packing: reject instead of truncating')
    gaps=np.zeros((n,length,max_fire+1),dtype=np.float32)
    valid=np.zeros((n,length,max_fire),dtype=np.bool_)
    for actor,(times,per_observation) in enumerate(all_lists):
        start=0.0
        for t, (stop,fire_list) in enumerate(zip(times,per_observation)):
            cursor=start
            for j,fire in enumerate(fire_list):
                if not (start<=fire<=stop and fire>=cursor and
                        (j==0 or fire>fire_list[j-1])):
                    raise UnresolvedContent('invalid chronological sampled event time')
                gaps[actor,t,j]=np.float32(fire-cursor)
                valid[actor,t,j]=True
                cursor=fire
            gaps[actor,t,max_fire]=np.float32(stop-cursor)
            start=stop
    tensor=lambda seq:torch.from_numpy(np.stack(seq))
    out=dict(x=tensor(xs),y=tensor(ys),mask=tensor(ms),dt=tensor(dts),
             count=tensor(cts),event_gap=torch.from_numpy(gaps),
             event_valid=torch.from_numpy(valid),
             total_events=total_events,multi_fire_streams=multi_fire)
    if torch.any(out['count']!=out['event_valid'].sum(-1)):
        raise UnresolvedContent('event count and timestamp count disagree')
    if not torch.allclose(out['event_gap'].sum(-1),out['dt'],rtol=0,atol=1e-6):
        raise UnresolvedContent('time-gap sum differs from clock increment')
    out['data_sha256']=_digest(out)
    return out


def timed_forward(model:TrainableEventContent, data, index=None):
    """Autograd over physical-event updates (not through Brownian clock)."""
    if not isinstance(model,TrainableEventContent):
        raise UnresolvedContent('wrong neural content model')
    if index is None: index=slice(None)
    x,dt,count=data['x'][index],data['dt'][index],data['count'][index]
    gaps=data['event_gap'][index];valid=data['event_valid'][index]
    n,T,_=x.shape
    if (x.shape[-1]!=DIM or gaps.shape[:2]!=(n,T) or
            valid.shape!=(n,T,gaps.shape[-1]-1) or count.shape!=(n,T)):
        raise UnresolvedContent('bad batched FIRE shape')
    decay=F.softplus(model.log_decay)
    hidden=x.new_zeros(n,model.hidden)
    logits=[]
    K=valid.shape[2]
    for t in range(T):
        for j in range(K):
            hidden=hidden*torch.exp(-decay*gaps[:,t,j,None])
            pulsed=hidden+torch.tanh(model.event(hidden))
            hidden=torch.where(valid[:,t,j,None],pulsed,hidden)
        hidden=hidden*torch.exp(-decay*gaps[:,t,K,None])
        hidden=model.writer(torch.cat((x[:,t],dt[:,t,None],
                     torch.tanh(count[:,t,None])),dim=-1),hidden)
        logits.append(model.head(hidden).squeeze(-1))
    return torch.stack(logits,dim=1)


def _score(model,data,arm):
    model.eval()
    start_cpu=time.process_time();start_wall=time.perf_counter()
    with torch.no_grad():
        logits=(model(data['x'],data['dt'],data['count'])
                if arm=='aggregate_count' else timed_forward(model,data))
        mask=data['mask']
        correct=(((logits>=0)==(data['y']>=.5)).float()*mask).sum()
        bce=(F.binary_cross_entropy_with_logits(logits,data['y'],
                         reduction='none')*mask).sum()/mask.sum()
    return dict(accuracy=float(correct/mask.sum()),correct=int(correct),
                queries=int(mask.sum()),bce=float(bce),
                cpu_seconds=time.process_time()-start_cpu,
                wall_seconds=time.perf_counter()-start_wall,
                total_events=data['total_events'],
                multi_fire_streams=data['multi_fire_streams'],
                data_sha256=data['data_sha256'])


def execute(task,seed,arm,*,budget=CPU_BUDGET,max_steps=MAX_STEPS,
            train_n=128,test_n=128,smoke=False):
    if arm not in ARMS or task not in TASKS or type(seed) is not int or seed not in (0,1):
        raise UnresolvedContent('non-preregistered pilot arm/seed/task')
    if (type(budget) not in (float,int) or budget<=0 or
            type(max_steps) is not int or max_steps<=0):
        raise UnresolvedContent('invalid training budget')
    if not smoke and (budget!=CPU_BUDGET or max_steps!=MAX_STEPS or
                      train_n!=128 or test_n!=128):
        raise UnresolvedContent('different protocol requires new registration')
    torch.set_num_threads(1)
    torch.manual_seed(400+seed)
    model=TrainableEventContent(32)
    initial_sha=model_digest(model)
    initial_params=sum(p.numel() for p in model.parameters())
    # Includes whole model-specific data preparation in the 25 CPU-second budget.
    start=time.process_time()
    train=physical_dataset(task,n=train_n,length=16,seed=100+seed)
    id_data=physical_dataset(task,n=test_n,length=16,seed=200+seed)
    ood_data=physical_dataset(task,n=test_n,length=32,seed=300+seed)
    data_seconds=time.process_time()-start
    if data_seconds>budget:
        raise UnresolvedContent('data construction exhausted CPU budget')
    rng=np.random.default_rng(500+seed)
    opt=torch.optim.Adam(model.parameters(),lr=.006)
    losses=[];steps=0
    model.train()
    while steps<max_steps and time.process_time()-start<budget:
        idx=rng.integers(0,train_n,size=BATCH_SIZE)
        opt.zero_grad(set_to_none=True)
        logits=(model(train['x'][idx],train['dt'][idx],train['count'][idx])
                if arm=='aggregate_count' else timed_forward(model,train,idx))
        loss=(F.binary_cross_entropy_with_logits(logits,train['y'][idx],
                     reduction='none')*train['mask'][idx]).sum()/train['mask'][idx].sum()
        if not bool(torch.isfinite(loss)):
            raise UnresolvedContent('nonfinite training loss')
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
            raise UnresolvedContent('absent/nonfinite neural gradient')
        opt.step()
        steps+=1
        if steps in (1,10,100,400,1000,2000):losses.append([steps,float(loss.detach())])
    total_training_cpu=time.process_time()-start
    eval_id=_score(model,id_data,arm)
    eval_ood=_score(model,ood_data,arm)
    return dict(schema=SCHEMA,task=task,seed=seed,arm=arm,
                training_budget_cpu_seconds=budget,training_cpu_seconds=total_training_cpu,
                data_preparation_cpu_seconds=data_seconds,
                optimization_cpu_seconds=total_training_cpu-data_seconds,
                optimizer_updates=steps, reached_step_cap=(steps==max_steps),
                params=initial_params, initial_model_sha256=initial_sha,
                trained_model_sha256=model_digest(model),learning_trace=losses,
                train_data_sha256=train['data_sha256'],
                id=eval_id,ood=eval_ood,
                complete_cpu_seconds=total_training_cpu+eval_id['cpu_seconds']+eval_ood['cpu_seconds'],
                cpu_device='PyTorch CPU float32 single-thread',
                causal_event_times=True,gradients_through_event_operator=True,
                no_gradients_through_sampled_Brownian_clock=True,
                exploratory_pilot=True,not_blind_confirmation=True,
                production_activation=False,all_scientific_blockers_closed=False)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--task',choices=TASKS,required=True)
    p.add_argument('--seed',type=int,choices=(0,1),required=True)
    p.add_argument('--arm',choices=ARMS,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--smoke',action='store_true')
    args=p.parse_args()
    rec=execute(args.task,args.seed,args.arm,
                budget=2. if args.smoke else CPU_BUDGET,
                max_steps=3 if args.smoke else MAX_STEPS,
                train_n=8 if args.smoke else 128,
                test_n=8 if args.smoke else 128,smoke=args.smoke)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rec,sort_keys=True,indent=2)+'\n')
    print(json.dumps({k:rec[k] for k in ('task','seed','arm','optimizer_updates',
          'training_cpu_seconds','data_preparation_cpu_seconds','params',
          'initial_model_sha256','id','ood','all_scientific_blockers_closed')},
          indent=2))
    print('artifact_sha256',hashlib.sha256(args.output.read_bytes()).hexdigest())

if __name__=='__main__':main()
