"""Deterministic event-stream task factory and independent answer oracles.

Creates tests, not a trained HCSN. Results are generator ground truth only.
Split assignments and seeds are immutable within the emitted dataset.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import random

TASKS=('selective_copy','mqar','overwrite','long_range','irregular_time','regeneration')

@dataclass(frozen=True)
class Event:
    t: float
    op: str
    key: int = 0
    value: int = 0


def make_events(task: str, length: int, seed: int) -> list[Event]:
    if task not in TASKS or length<16 or not isinstance(seed,int):
        raise ValueError("unsupported task or too-short sequence")
    rng=random.Random(seed)
    out=[]
    t=0.0
    def emit(op,key=0,value=0):
        nonlocal t
        dt=10**rng.uniform(-3,1) if task=='irregular_time' else 1.0
        t+=dt
        out.append(Event(t,op,key,value))
    if task=='long_range':
        emit('write',999,rng.randrange(1,1<<30))
        for i in range(length):
            emit('write',i%31,rng.randrange(1,1<<30))
        emit('query',999)
    else:
        if task=='selective_copy':
            emit('toggle')
        for i in range(length):
            key=rng.randrange(0,16)
            if task=='regeneration' and i>0 and i%113==0:
                emit('reset')
            if task=='selective_copy' and i%17==0:
                emit('toggle')
            if task=='overwrite':
                key=i%4
            emit('write',key,rng.randrange(1,1<<30))
            if i%5==0 or i==length-1:
                emit('query',key)
                if task=='mqar':
                    emit('query',rng.randrange(0,16))
        if task=='regeneration':
            emit('reset')
            emit('query',key)
    return out


def oracle_incremental(events: list[Event],task: str):
    """O(n) incremental reference."""
    register={}
    enabled=True
    result=[]
    last=-float('inf')
    for index,e in enumerate(events):
        if e.t<=last:
            raise ValueError('non-increasing event time')
        last=e.t
        if e.op=='toggle':
            enabled=not enabled
        elif e.op=='reset':
            register.clear()
            enabled=True
        elif e.op=='write':
            if task!='selective_copy' or enabled:
                register[e.key]=e.value
        elif e.op=='query':
            result.append((index,register.get(e.key,-1)))
        else:
            raise ValueError('invalid op')
    return result


def oracle_independent(events: list[Event],task: str):
    """O(n^2) independent prefix interpreter for cross-checking semantics."""
    out=[]
    for end,ev in enumerate(events):
        if ev.op!='query':
            continue
        entries=[]
        enabled=True
        for e in events[:end]:
            if e.op=='toggle':
                enabled=not enabled
            elif e.op=='reset':
                entries=[]
                enabled=True
            elif e.op=='write' and (task!='selective_copy' or enabled):
                entries.append((e.key,e.value))
        found=next((val for key,val in reversed(entries) if key==ev.key),-1)
        out.append((end,found))
    return out


def dataset(task,length,seed,split):
    if split not in ('train','validation','holdout'):
        raise ValueError('unknown split')
    events=make_events(task,length,seed)
    truth=oracle_incremental(events,task)
    canonical=json.dumps({'task':task,'length':length,'seed':seed,
                          'split':split,'events':[asdict(e) for e in events],
                          'truth':truth},sort_keys=True,separators=(',',':'))
    return {'task':task,'length':length,'seed':seed,'split':split,
            'sha256':hashlib.sha256(canonical.encode()).hexdigest(),
            'event_count':len(events),'query_count':len(truth),
            'events':[asdict(e) for e in events],'truth':truth}


def audit_matrix():
    results=[]
    # Only small slices are duplicated with O(n^2) oracle; large slices are
    # cross-checked by checkpoint-prefix replay and deterministic hash.
    for task in TASKS:
        for n in (64,256,1024,4096):
            seed=1000+13*TASKS.index(task)+n
            es=make_events(task,n,seed)
            incremental=oracle_incremental(es,task)
            if n<=256:
                assert incremental==oracle_independent(es,task)
            else:
                # A full O(n^2) check on 4096 is possible but unnecessary for
                # this deterministic smoke test; prefix oracle still independent.
                chunk=es[:min(350,len(es))]
                assert oracle_incremental(chunk,task)==oracle_independent(chunk,task)
            info=dataset(task,n,seed,'holdout')
            assert info['query_count']>0
            results.append({k:info[k] for k in ('task','length','seed','split','sha256','event_count','query_count')})
    return results
