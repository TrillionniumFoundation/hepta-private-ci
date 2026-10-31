"""P2 experimental *event-timestamp* content operations: research-only NO_GO.

Distinct from aggregate-count P2: physical Brownian FIRE timestamps, as sampled
by the exact upstream fixed-parameter SpikeStream, each separately:
  (1) evolve h across the actual no-observation time interval,
  (2) apply one trainable event transformation at that FIRE time.
Then evolve to the observation timestamp and apply one observation GRU write.
The stream RNG is not trainable and event times are exogenous sampled clocks.
Every ingest transaction stages both the Brownian and content state and commits
only on successful validation. Checkpoint SHA-256 is *integrity only*, not host
crash durability, signer authentication, or a Rust/GPU implementation.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math

import numpy as np
import torch
import torch.nn.functional as F

from experiments.hcsn_hx_unified_v3.renewal_spike_sampler import (SpikeSpec, SpikeStream,
                                                                  UnresolvedSpike)
from .event_content import (DIM, TrainableEventContent, UnresolvedContent,
                            canonical, model_digest)

SCHEMA = 'hcsn-p2-timed-fire-v1'
INITIAL_EVENT_DIGEST = hashlib.sha256(SCHEMA.encode()).hexdigest()


def _number(x):
    return type(x) in (float,int) and math.isfinite(x)


def _observation(value):
    try:
        a=np.asarray(value,dtype=np.float32)
    except (TypeError,ValueError,OverflowError) as e:
        raise UnresolvedContent('malformed observation') from e
    if a.shape != (DIM,) or not np.all(np.isfinite(a)) or np.max(np.abs(a))>3:
        raise UnresolvedContent('out-of-domain observation')
    return torch.from_numpy(a.copy()).reshape(1,DIM)


def _interval(dt: float) -> torch.Tensor:
    if not (_number(dt) and 0<=dt<=1e5):
        raise UnresolvedContent('invalid physical event time interval')
    t=torch.tensor([[float(dt)]],dtype=torch.float32)
    if dt>0 and float(t.item())==0:
        raise UnresolvedContent('unrepresentable positive time delta')
    return t


def timed_content_step(model: TrainableEventContent, obs: torch.Tensor,
                       start: float, end: float,
                       events: tuple[float,...], hidden: torch.Tensor):
    """Differentiable content update for frozen exogenous actual event stamps.

    Strict chronological ordering, including an initial immediate FIRE at t=0,
    ensures a physical FIRE operator is never postponed until observation.
    No in-place mutations of the caller's model, observation or hidden tensor.
    """
    if not isinstance(model,TrainableEventContent):
        raise UnresolvedContent('wrong content model')
    if obs.shape!=(1,DIM) or hidden.shape!=(1,model.hidden):
        raise UnresolvedContent('wrong input/hidden shape')
    if (obs.device.type!='cpu' or hidden.device.type!='cpu' or
            obs.dtype!=torch.float32 or hidden.dtype!=torch.float32 or
            any(p.device.type!='cpu' or p.dtype!=torch.float32
                for p in model.parameters())):
        raise UnresolvedContent('only real CPU float32 content arithmetic is implemented')
    if not (_number(start) and _number(end) and 0<=start<end and
            type(events) is tuple and len(events)<=100000):
        raise UnresolvedContent('invalid causal interval/event sequence')
    if not torch.isfinite(obs).all() or not torch.isfinite(hidden).all():
        raise UnresolvedContent('nonfinite input/hidden')
    cursor=float(start)
    h=hidden
    for index,event in enumerate(events):
        if not (_number(event) and start<=event<=end and
                (index==0 or event>events[index-1]) and event>=cursor):
            raise UnresolvedContent('out-of-order or outside-horizon FIRE event')
        h=h*torch.exp(-F.softplus(model.log_decay)*_interval(event-cursor))
        h=h+torch.tanh(model.event(h))  # exactly one differentiable pulse per FIRE
        cursor=float(event)
    h=h*torch.exp(-F.softplus(model.log_decay)*_interval(end-cursor))
    whole=_interval(end-start)
    count=torch.tanh(torch.tensor([[float(len(events))]],dtype=torch.float32))
    nxt=model.writer(torch.cat((obs,whole,count),dim=1),h)
    logit=model.head(nxt).squeeze(-1)
    if not torch.isfinite(nxt).all() or not torch.isfinite(logit).all():
        raise UnresolvedContent('nonfinite neural result')
    return nxt,logit


class TimedFireSession:
    """One stream with versioned model-bound event/content checkpoint.

    An in-process transaction has no disk WAL; process termination *between*
    external action and checkpoint publication is not covered by this contract.
    """
    VERSION=1
    def __init__(self,model:TrainableEventContent,spec:SpikeSpec,*,
                 seed:int,stream_id:str):
        if not isinstance(model,TrainableEventContent) or model.training:
            raise UnresolvedContent('session requires frozen eval model')
        self.model=model
        self.spikes=SpikeStream(spec,seed=seed,stream_id=stream_id)
        self.hidden=torch.zeros(1,model.hidden,dtype=torch.float32)
        self.last_time=0.
        self.processed=0
        self.last_logit=None
        self.event_digest=INITIAL_EVENT_DIGEST
        self.event_count=0

    def ingest(self,timestamp:float,observation,*,max_events=1024):
        if not (_number(timestamp) and self.last_time<timestamp and
                self.processed<65535):
            raise UnresolvedContent('noncausal timestamp or exhausted budget')
        if type(max_events) is not int or not 1<=max_events<=1024:
            raise UnresolvedContent('physical event budget exceeds studied CPU limit')
        obs=_observation(observation)
        trial=SpikeStream.from_checkpoint(self.spikes.checkpoint(),
                    expected_spec=self.spikes.spec,
                    expected_stream_id=self.spikes.stream_id)
        try:
            events=trial.advance_to(timestamp,max_events=max_events)
        except UnresolvedSpike as e:
            raise UnresolvedContent('physical FIRE transaction refused') from e
        with torch.no_grad():
            new,logit=timed_content_step(self.model,obs,self.last_time,
                                        float(timestamp),events,self.hidden)
        # The digest binds exactly the *ordered* event timestamps per ingest.
        # Neither hashes nor untrusted snapshots authenticate a remote owner.
        digest=hashlib.sha256((self.event_digest+canonical({
            'start':float(self.last_time),'end':float(timestamp),
            'event_times_hex':[float(t).hex() for t in events],
            'next_event_count':self.event_count+len(events)})).encode()).hexdigest()
        self.spikes=trial
        self.hidden=new.detach().clone()
        self.last_time=float(timestamp)
        self.last_logit=float(logit.item())
        self.processed+=1
        self.event_digest=digest
        self.event_count+=len(events)
        return events,self.last_logit

    def checkpoint(self):
        payload=dict(schema=SCHEMA,version=self.VERSION,model_sha256=model_digest(self.model),
                     spike_checkpoint=self.spikes.checkpoint(),
                     content=self.hidden.detach().cpu().contiguous().flatten().tolist(),
                     last_time=self.last_time,processed=self.processed,
                     last_logit=self.last_logit,event_digest=self.event_digest,
                     event_count=self.event_count)
        payload['sha256']=hashlib.sha256(canonical(payload).encode()).hexdigest()
        return canonical(payload)

    @classmethod
    def from_checkpoint(cls,model,raw,*,expected_spec=None,expected_stream_id=None):
        if not isinstance(model,TrainableEventContent) or model.training:
            raise UnresolvedContent('restoration requires frozen eval model')
        try:
            data=json.loads(raw)
            if type(data) is not dict:
                raise ValueError('snapshot not a map')
            digest=data.pop('sha256')
            if not (type(digest) is str and len(digest)==64 and
                    hashlib.sha256(canonical(data).encode()).hexdigest()==digest):
                raise ValueError('snapshot hash mismatch')
            keys={'schema','version','model_sha256','spike_checkpoint','content',
                  'last_time','processed','last_logit','event_digest','event_count'}
            if (set(data)!=keys or data['schema']!=SCHEMA or
                    type(data['version']) is not int or data['version']!=cls.VERSION or
                    data['model_sha256']!=model_digest(model)):
                raise ValueError('unknown schema/model')
            spikes=SpikeStream.from_checkpoint(data['spike_checkpoint'],
                       expected_spec=expected_spec,expected_stream_id=expected_stream_id)
            if (type(data['processed']) is not int or not 0<=data['processed']<=65535 or
                    not _number(data['last_time']) or data['last_time']<0 or
                    spikes.now!=data['last_time'] or
                    type(data['event_count']) is not int or data['event_count']<0 or
                    data['event_count']!=spikes.events or
                    type(data['event_digest']) is not str or
                    len(data['event_digest'])!=64 or
                    any(c not in '0123456789abcdef' for c in data['event_digest']) or
                    type(data['content']) is not list or
                    len(data['content'])!=model.hidden or
                    any(not _number(v) or abs(v)>1e6 for v in data['content']) or
                    (data['processed']==0 and (data['event_count']!=0 or
                     data['event_digest']!=INITIAL_EVENT_DIGEST or
                     data['last_time']!=0.)) or
                    (data['processed']>0 and data['last_time']<=0) or
                    (data['last_logit'] is not None and not _number(data['last_logit'])) or
                    (data['processed']==0 and data['last_logit'] is not None) or
                    (data['processed']>0 and data['last_logit'] is None)):
                raise ValueError('incoherent state/event history')
        except (ValueError,TypeError,KeyError,UnresolvedSpike,OverflowError) as e:
            raise UnresolvedContent('invalid or untrusted timed snapshot') from e
        obj=cls.__new__(cls)
        obj.model=model;obj.spikes=spikes
        obj.hidden=torch.tensor(data['content'],dtype=torch.float32).reshape(1,model.hidden)
        obj.last_time=float(data['last_time']);obj.processed=data['processed']
        obj.last_logit=data['last_logit'];obj.event_digest=data['event_digest']
        obj.event_count=data['event_count']
        return obj
