"""Paired CPU readout of v1 aggregate count vs v2 physically timed event updates.

Frozen weights trained ONLY with the v1 aggregated update. This is a migration
stress test, not a fair training-performance superiority benchmark. All actor
streams/timestamps/inputs are paired. CPU totals include Python event sampling,
head and recurrent operations, but exclude training, model loading and weights.
"""
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time

import torch

from .event_content import (ContentSession,TrainableEventContent,default_spec,
                            example,model_digest,train_pilot)
from .timed_fire_content import TimedFireSession


def audit(weights,*,task,actors=96,length=16,data_seed=200):
    if task not in ('copy','mqar4') or actors<1 or length<12:
        raise ValueError('invalid actor workload')
    torch.set_num_threads(1)
    model=TrainableEventContent(32).eval()
    model.load_state_dict(torch.load(weights,weights_only=True,map_location='cpu'))
    correct=dict(aggregate=0,timed=0)
    actor_accuracy={key:[] for key in correct}
    cpu={key:0. for key in correct}
    clock={key:0. for key in correct}
    all_events=0;multi_events=0;different_actions=0;queries=0
    for i in range(actors):
        x,y,mask,_,times=example(task,length=length,seed=data_seed*100000+i)
        kwargs=dict(seed=data_seed*100000+i,stream_id=f'{task}-{data_seed}-{i}')
        spec=default_spec()
        owners={'aggregate':ContentSession(model,spec,**kwargs),
                'timed':TimedFireSession(model,spec,**kwargs)}
        result={key:[] for key in correct}
        actor_event={key:[] for key in correct}
        # Alternate which mode is measured first to reduce order effects.
        for key in (('aggregate','timed') if i%2==0 else ('timed','aggregate')):
            a=time.process_time_ns();b=time.perf_counter_ns()
            for t in range(length):
                evt,pred=owners[key].ingest(times[t],x[t])
                actor_event[key].append(evt)
                if mask[t]:result[key].append((int(pred>=0),int(y[t]>=.5)))
            cpu[key]+=(time.process_time_ns()-a)/1e9
            clock[key]+=(time.perf_counter_ns()-b)/1e9
            c=sum(a==b for a,b in result[key]);correct[key]+=c
            actor_accuracy[key].append(c/len(result[key]))
        if actor_event['aggregate']!=actor_event['timed']:
            raise AssertionError('nonidentical exogenous physical FIRE trains')
        all_events+=owners['timed'].event_count
        multi_events+=int(owners['timed'].event_count>=2)
        different_actions+=sum(a[0]!=b[0] for a,b in zip(result['aggregate'],result['timed']))
        queries+=len(result['timed'])
    return dict(task=task,length=length,actors=actors,data_seed=data_seed,
                model_sha256=model_digest(model),events=all_events,
                streams_multi_fire=multi_events,queries=queries,
                disagreements=different_actions,
                models={key:dict(accuracy=correct[key]/queries,correct=correct[key],
                                 cpu_seconds=cpu[key],wall_seconds=clock[key])
                        for key in correct},
                mean_paired_delta=sum(x-y for x,y in zip(actor_accuracy['timed'],actor_accuracy['aggregate']))/actors,
                producer='PyTorch 2.10.0 CPU; physical Brownian SpikeStream',
                inference_only=True,trained_only_on_aggregate=True,
                production_activation=False,all_scientific_blockers_closed=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--weights-dir',type=Path,default=None)
    parser.add_argument('--regenerate',action='store_true',help='Regenerate frozen aggregate-trained weights using original P2 pilot')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--actors',type=int,default=96)
    args=parser.parse_args()
    results=[]
    if not args.regenerate and args.weights_dir is None:
        parser.error('provide --regenerate or --weights-dir')
    expected={'copy':'e92c7f7d5efd75ba4bd7c3511da02bc157f13af127e48cd16ba72dea24dfa895',
              'mqar4':'bd8cf2b234e749b0320d2372a27a1c2dab1b7a2692b9ba3897e8e28966ec1a62'}
    if args.regenerate:
        import tempfile
        weight_dir=tempfile.TemporaryDirectory()
        wd=Path(weight_dir.name)
        for task in ('copy','mqar4'):
            m,report=train_pilot(task,seed=0,steps=400,train_n=256,test_n=256)
            if model_digest(m)!=expected[task]:
                raise RuntimeError('frozen training weights differ; refuse scientifically incompatible rerun')
            torch.save(m.state_dict(),wd/f'{task}_seed0_state.pt')
    else:
        wd=args.weights_dir
    for task in ('copy','mqar4'):
        weights=wd/f'{task}_seed0_state.pt'
        m=TrainableEventContent(32).eval()
        m.load_state_dict(torch.load(weights,weights_only=True,map_location='cpu'))
        if model_digest(m)!=expected[task]:
            raise RuntimeError('wrong or corrupted frozen model weights')
        for length,seed in ((16,200),(32,300)):
            rec=audit(weights,task=task,actors=args.actors,length=length,data_seed=seed)
            results.append(rec)
            print(task,length,rec['models'],flush=True)
    out=dict(schema='hcsn-p2-timed-frozen-inference-v1',
             controls='frozen aggregate-trained weights paired with timed-event forward',
             records=results,
             claim='migration stress test only; NOT matched-budget retraining superiority',
             production_activation=False,all_scientific_blockers_closed=False)
    args.output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('sha256:',hashlib.sha256(args.output.read_bytes()).hexdigest())

if __name__=='__main__':main()
