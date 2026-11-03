"""P2 v2 adversarial event-memory benchmark *data*, not HCSN performance.

Differences from v1: (a) timestamp changes alter the correct answer for
irregular_time via TTL, (b) MQAR queries occur after long distractor spans,
(c) reset truly repeats, (d) content hashing is independent of split labels,
(e) full independent prefix interpreter on bounded lengths.
"""
from __future__ import annotations
import hashlib
import json
import math
import random
from dataclasses import dataclass,asdict,replace

TASKS=('selective_copy','mqar','overwrite','long_range','irregular_time','regeneration')
SCALES=(64,256,1024,4096)
TTL=2.0

@dataclass(frozen=True)
class Event:
    time: float
    operation: str
    key:int=0
    value:int=0


def _validate_stream(events):
    last=-math.inf
    for ev in events:
        if (not isinstance(ev,Event) or not math.isfinite(ev.time)
                or ev.time<=last or ev.operation not in ('toggle','reset','write','query')
                or not isinstance(ev.key,int) or not isinstance(ev.value,int)):
            raise ValueError('invalid event ordering/finite time/op/type')
        last=ev.time


def generate(task,length,seed):
    if task not in TASKS or length not in SCALES or isinstance(seed,bool) or not isinstance(seed,int):
        raise ValueError('unregistered task/scale/seed')
    rng=random.Random(seed)
    t=0.0
    es=[]
    def put(op,key=0,value=0,step=1.):
        nonlocal t
        if task=='irregular_time' and step == 1.:
            step=10**rng.uniform(-3,0.3)
        t += step
        es.append(Event(t,op,key,value))
    if task=='mqar':
        keys=list(range(length))
        for key in keys:
            put('write',key,rng.randrange(1,1<<30))
        # Each query follows the complete write sequence; collision-free keys.
        rng.shuffle(keys)
        for key in keys[:max(16,length//4)]:
            put('query',key)
    elif task=='long_range':
        put('write',999999,rng.randrange(1,1<<30))
        for i in range(length):
            put('write',i%31,rng.randrange(1,1<<30))
        for i in range(8):
            put('query',999999)
    elif task=='irregular_time':
        for i in range(length):
            key=i%16
            put('write',key,rng.randrange(1,1<<30),step=.03+rng.random()*.2)
            if i%2==0:
                put('query',key,step=.1)
            else:
                put('query',key,step=2.25+rng.random())
        # Some queries should be expired, others should be live in every case.
    elif task=='regeneration':
        per=length//4
        for i in range(length):
            if i and i%per==0:
                put('reset')
                put('query',i%8)  # known missing just after epoch reset
            k=i%8
            put('write',k,rng.randrange(1,1<<30))
            if i%9==0:
                put('query',k)
        put('reset')
        put('query',0)
    elif task=='selective_copy':
        # Both ignored and active updates must be queried after distractors.
        for i in range(length):
            if i%19==0:
                put('toggle')
            k=i%12
            put('write',k,rng.randrange(1,1<<30))
            if i%11==0 and i>=11:
                put('query',(i-7)%12)
        for k in range(12):
            put('query',k)
    elif task=='overwrite':
        for i in range(length):
            k=i%8
            put('write',k,rng.randrange(1,1<<30))
            if i%17==0:
                put('query',k)
        for k in range(8):
            put('query',k)
    _validate_stream(es)
    return es


def oracle(events, task):
    if task not in TASKS:
        raise ValueError('invalid task')
    _validate_stream(events)
    register={}
    enabled=True
    out=[]
    for index,ev in enumerate(events):
        if ev.operation=='toggle':
            enabled=not enabled
        elif ev.operation=='reset':
            register.clear()
            enabled=True
        elif ev.operation=='write':
            if task!='selective_copy' or enabled:
                register[ev.key]=(ev.value,ev.time)
        else:
            seen=register.get(ev.key)
            result=-1 if seen is None else seen[0]
            if (seen is not None and task=='irregular_time'
                    and ev.time-seen[1]>TTL):
                result=-1
            out.append((index,result))
    return out


def replay_reference(events,task):
    """Intentionally independent O(number_of_queries * number_of_events) replay."""
    _validate_stream(events)
    out=[]
    for stop,ev in enumerate(events):
        if ev.operation!='query':
            continue
        history=events[:stop]
        last_reset=max((j for j,e in enumerate(history) if e.operation=='reset'),default=-1)
        latest=None
        for j,e in enumerate(history):
            if j<=last_reset or e.operation!='write' or e.key!=ev.key:
                continue
            if task=='selective_copy':
                toggles=sum(a.operation=='toggle' for a in history[last_reset+1:j])
                if toggles%2==1:
                    continue
            latest=e
        result=-1 if latest is None else latest.value
        if latest is not None and task=='irregular_time' and ev.time-latest.time>TTL:
            result=-1
        out.append((stop,result))
    return out


def time_blind_baseline(events,task):
    """Upper-bound simplistic current-key memory that ignores reset/gating/time."""
    memory={}
    guesses=[]
    for i,e in enumerate(events):
        if e.operation=='write':memory[e.key]=e.value
        if e.operation=='query':guesses.append((i,memory.get(e.key,-1)))
    truth=oracle(events,task)
    if len(guesses)!=len(truth):raise AssertionError('unmatched query count')
    return {'accuracy':sum(a[1]==b[1] for a,b in zip(guesses,truth))/len(truth),
            'queries':len(truth)}


def receipt(task,length,seed,split):
    if split not in ('train','validation','holdout'):
        raise ValueError('unregistered split')
    events=generate(task,length,seed)
    ans=oracle(events,task)
    payload={'task':task,'length':length,'seed':seed,
             'events':[asdict(e) for e in events], 'truth':ans}
    content=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    sha=hashlib.sha256(content).hexdigest()
    return {'task':task,'length':length,'seed':seed,'split':split,
            'content_sha256':sha,'query_count':len(ans),'event_count':len(events),
            'time_blind_baseline_accuracy':time_blind_baseline(events,task)['accuracy']}


def check_no_overlap(receipts):
    by_hash={}
    problems=[]
    for v in receipts:
        digest=v['content_sha256']
        if digest in by_hash and by_hash[digest]!=v['split']:
            problems.append(f'cross-split event content duplication: {digest}')
        by_hash[digest]=v['split']
    return problems


def audit():
    results=[]
    for t in TASKS:
        for n in SCALES:
            seed=101000+TASKS.index(t)*163+n
            result=receipt(t,n,seed,'holdout')
            es=generate(t,n,seed)
            # Cross-check independent reference on full <=256; for large
            # streams use a bounded prefix, avoiding quadratic explosion.
            if n<=256:
                if oracle(es,t)!=replay_reference(es,t):
                    raise AssertionError(f'disagree on {t} length {n}')
            elif t!='mqar':
                if oracle(es[:350],t)!=replay_reference(es[:350],t):
                    raise AssertionError(f'prefix reference disagree on {t}')
            results.append(result)
    return results
