"""P2 non-blind follow-up: real 25 CPU-second training per arm, NO_GO.

This separate executable uses untouched seeds 2/3/4 after the original v1
2,000-step cap prevented budget matching. It is a registered *exploratory*
follow-up, not independent held-out confirmation nor a production owner.
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

from .event_content import TrainableEventContent,UnresolvedContent,model_digest
from .timed_training_budget_pilot import (physical_dataset, timed_forward, _score,
                                           ARMS, TASKS)

SCHEMA='hcsn-p2-timed-cpu-matched-followup-v2'
BUDGET=25.0
MAX_STEPS=8000
SEEDS=(2,3,4)


def run(task, seed, arm):
    if task not in TASKS or arm not in ARMS or type(seed) is not int or seed not in SEEDS:
        raise UnresolvedContent('unregistered P2 budget follow-up')
    torch.set_num_threads(1)
    torch.manual_seed(400+seed)
    model=TrainableEventContent(32)
    initial_sha=model_digest(model)
    parameters=sum(p.numel() for p in model.parameters())
    if parameters!=5186:
        raise UnresolvedContent('trainable parameter budget changed')
    start=time.process_time()
    train=physical_dataset(task,n=128,length=16,seed=100+seed)
    id_data=physical_dataset(task,n=128,length=16,seed=200+seed)
    ood_data=physical_dataset(task,n=128,length=32,seed=300+seed)
    build_time=time.process_time()-start
    if build_time>=BUDGET:
        raise UnresolvedContent('data construction exceeded preregistered CPU budget')
    opt=torch.optim.Adam(model.parameters(),lr=.006)
    rng=np.random.default_rng(500+seed)
    steps=0;loss_trace=[]
    model.train()
    while steps<MAX_STEPS and time.process_time()-start<BUDGET:
        index=rng.integers(0,128,size=24)
        opt.zero_grad(set_to_none=True)
        z=(model(train['x'][index],train['dt'][index],train['count'][index])
            if arm=='aggregate_count' else timed_forward(model,train,index))
        loss=(F.binary_cross_entropy_with_logits(z,train['y'][index],
              reduction='none')*train['mask'][index]).sum()/train['mask'][index].sum()
        if not bool(torch.isfinite(loss)):
            raise UnresolvedContent('nonfinite training loss')
        loss.backward()
        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in model.parameters()):
            raise UnresolvedContent('nonfinite or missing gradient')
        opt.step()
        steps+=1
        if steps in (1,10,100,400,1000,2000,4000,8000):
            loss_trace.append((steps,float(loss.detach())))
    training_cpu=time.process_time()-start
    if steps==MAX_STEPS or training_cpu<BUDGET:
        raise UnresolvedContent('actual CPU budget not consumed; record as failed (no quiet fallback)')
    id_out=_score(model,id_data,arm)
    ood_out=_score(model,ood_data,arm)
    return dict(schema=SCHEMA,task=task,seed=seed,arm=arm,
                params=parameters,initial_model_sha256=initial_sha,
                trained_model_sha256=model_digest(model),
                training_cpu_budget_seconds=BUDGET,
                training_cpu_seconds=training_cpu,
                build_data_cpu_seconds=build_time,
                optimize_cpu_seconds=training_cpu-build_time,
                optimizer_steps=steps,
                reached_step_cap=False,reached_cpu_budget=True,
                train_data_sha256=train['data_sha256'],
                id=id_out,ood=ood_out,loss_trace=loss_trace,
                total_cpu_seconds=training_cpu+id_out['cpu_seconds']+ood_out['cpu_seconds'],
                unblinded_exploratory_followup=True,
                negative_evidence_retained=True,
                production_activation=False,all_scientific_blockers_closed=False)


def validate_pair(aggregate, timed):
    """A fail-closed *CPU-accounting* comparator, not scientific admission."""
    if not isinstance(aggregate,dict) or not isinstance(timed,dict):
        raise UnresolvedContent('malformed paired evidence')
    if (aggregate.get('schema')!=SCHEMA or timed.get('schema')!=SCHEMA or
            aggregate.get('arm')!='aggregate_count' or
            timed.get('arm')!='physical_event_timestamp' or
            aggregate.get('task')!=timed.get('task') or
            aggregate.get('seed')!=timed.get('seed') or
            aggregate.get('seed') not in SEEDS):
        raise UnresolvedContent('nonpaired training arms')
    for arm in (aggregate,timed):
        if (arm.get('params')!=5186 or arm.get('reached_step_cap') is not False or
                arm.get('reached_cpu_budget') is not True or
                arm.get('training_cpu_seconds',0)<BUDGET or
                arm.get('training_cpu_seconds',0)>BUDGET*1.05 or
                arm.get('production_activation') is not False or
                arm.get('all_scientific_blockers_closed') is not False):
            raise UnresolvedContent('invalid training budget/authority evidence')
    keys=('initial_model_sha256','train_data_sha256')
    for k in keys:
        if aggregate.get(k)!=timed.get(k) or not aggregate.get(k):
            raise UnresolvedContent('initial model or physical training data mismatch')
    for panel in ('id','ood'):
        for k in ('data_sha256','total_events','queries','multi_fire_streams'):
            if aggregate[panel][k]!=timed[panel][k]:
                raise UnresolvedContent('paired evaluation inputs mismatch')
    a=aggregate['training_cpu_seconds'];b=timed['training_cpu_seconds']
    fraction=abs(a-b)/max(a,b)
    if fraction>0.05:
        raise UnresolvedContent('training CPU mismatch >5%')
    return dict(task=aggregate['task'],seed=aggregate['seed'],
                equal_cpu_within_five_percent=True,
                training_cpu_relative_gap=fraction,
                aggregate_steps=aggregate['optimizer_steps'],
                timed_steps=timed['optimizer_steps'],
                id_signed_pp=100*(timed['id']['accuracy']-aggregate['id']['accuracy']),
                ood_signed_pp=100*(timed['ood']['accuracy']-aggregate['ood']['accuracy']),
                production_activation=False,all_scientific_blockers_closed=False)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--task',required=True,choices=TASKS)
    p.add_argument('--seed',required=True,type=int,choices=SEEDS)
    p.add_argument('--arm',required=True,choices=ARMS)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args()
    result=run(args.task,args.seed,args.arm)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:result[k] for k in ('task','seed','arm','optimizer_steps',
        'training_cpu_seconds','trained_model_sha256','id','ood')},indent=2))
    print('artifact_sha256',hashlib.sha256(args.output.read_bytes()).hexdigest())

if __name__=='__main__':main()
