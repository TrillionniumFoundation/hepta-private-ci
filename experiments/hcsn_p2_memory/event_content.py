"""P2 trainable event/content research bridge, NO_GO for production.

Exact scalar sampled regenerative FIRE clocks are inherited byte-for-byte
from the existing renewal_spike_sampler. Content stores a trainable recurrent
vector and decays continuously across time gaps, but FIRE does not auto-reset
content. This is an explicit experimental choice, not an optimal neural QVI.
A coupled content+event checkpoint binds both to a model weight digest and
has transactional observation ingestion. The SHA-256 is integrity only, NOT
signer authentication or durable journal/atomic disk write assurance.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
import torch.nn.functional as F

from experiments.hcsn_hx_unified_v3.renewal_spike_sampler import (SpikeSpec,SpikeStream,
                                                                  UnresolvedSpike)

DIM=7
K=4
SCHEMA='hcsn-p2-event-content-v1'


class UnresolvedContent(ValueError):
    """Refuse unsupported training/serialization/causal state."""


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(',',':'),allow_nan=False)


def default_spec():
    return SpikeSpec(drift=1.1,diffusion=.95,discount=.12,cost=.3,
                     reset=0.,refractory=.22,boundary=.8,initial=.9)


def model_digest(model: nn.Module):
    h=hashlib.sha256()
    for name,tensor in sorted(model.state_dict().items()):
        a=tensor.detach().cpu().contiguous().numpy()
        h.update(name.encode());h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode());h.update(a.tobytes())
    return h.hexdigest()


class TrainableEventContent(nn.Module):
    """No observation between events: autonomous exponential content flow.

    A trainable event term then applies once per observation interval, scaled
    by actual FIRE count, followed by an observed-token GRU write. Thus counts
    change content and have gradients through the event operator, without
    pretending a sampled Brownian clock is itself differentiable.
    """
    def __init__(self,hidden=32):
        super().__init__()
        if type(hidden) is not int or not 8<=hidden<=256:
            raise UnresolvedContent('invalid memory size')
        self.hidden=hidden
        self.log_decay=nn.Parameter(torch.tensor(-2.,dtype=torch.float32))
        self.event=nn.Linear(hidden,hidden,bias=False)
        self.writer=nn.GRUCell(DIM+2,hidden)
        self.head=nn.Linear(hidden,1)

    def step(self,obs,dt,count,old):
        if obs.ndim!=2 or obs.shape[1]!=DIM or dt.shape!=(len(obs),1) or count.shape!=(len(obs),1):
            raise UnresolvedContent('invalid event/content tensor shapes')
        h=old*torch.exp(-F.softplus(self.log_decay)*dt)
        h=h+torch.tanh(count)*torch.tanh(self.event(h))
        nxt=self.writer(torch.cat((obs,dt,torch.tanh(count)),dim=1),h)
        return nxt,self.head(nxt).squeeze(-1)

    def forward(self,observations,delta_times,event_counts):
        if observations.ndim!=3 or observations.shape[2]!=DIM:
            raise UnresolvedContent('invalid observation batch')
        if delta_times.shape!=observations.shape[:2] or event_counts.shape!=delta_times.shape:
            raise UnresolvedContent('invalid event/time batch')
        h=observations.new_zeros((observations.shape[0],self.hidden))
        output=[]
        for t in range(observations.shape[1]):
            h,logit=self.step(observations[:,t],delta_times[:,t,None],
                              event_counts[:,t,None],h)
            output.append(logit)
        return torch.stack(output,dim=1)


class ContentSession:
    VERSION=1
    def __init__(self,model,spike_spec:SpikeSpec,*,seed:int,stream_id:str):
        if not isinstance(model,TrainableEventContent):
            raise UnresolvedContent('wrong content model type')
        if model.training:
            raise UnresolvedContent('session requires frozen eval weights')
        self.model=model
        self.spikes=SpikeStream(spike_spec,seed=seed,stream_id=stream_id)
        self.hidden=torch.zeros(1,model.hidden,dtype=torch.float32)
        self.last_time=0.
        self.processed=0
        self.last_logit=None

    def ingest(self,timestamp:float,obs,*,max_events=10000):
        """Copy-on-success; invalid timestamps, event caps, or tensors cannot mutate."""
        if (type(timestamp) not in (int,float) or not math.isfinite(timestamp)
                or timestamp<=self.last_time or self.processed>=65535):
            raise UnresolvedContent('noncausal timestamp or exhausted content budget')
        try:
            v=np.asarray(obs,dtype=np.float32)
        except (ValueError,TypeError) as exc:
            raise UnresolvedContent('malformed observation') from exc
        if v.shape!=(DIM,) or not np.all(np.isfinite(v)) or np.max(np.abs(v))>3:
            raise UnresolvedContent('invalid observation payload')
        trial=SpikeStream.from_checkpoint(self.spikes.checkpoint(),
                    expected_spec=self.spikes.spec,
                    expected_stream_id=self.spikes.stream_id)
        try:
            events=trial.advance_to(timestamp,max_events=max_events)
        except UnresolvedSpike as exc:
            raise UnresolvedContent('event subsystem refused transaction') from exc
        with torch.no_grad():
            new,logit=self.model.step(torch.from_numpy(v.copy())[None],
                torch.tensor([[timestamp-self.last_time]],dtype=torch.float32),
                torch.tensor([[len(events)]],dtype=torch.float32),self.hidden)
        if not torch.isfinite(new).all() or not torch.isfinite(logit).all():
            raise UnresolvedContent('nonfinite content state; no commit')
        self.spikes=trial
        self.hidden=new.detach().clone()
        self.last_time=float(timestamp)
        self.processed+=1
        self.last_logit=float(logit.item())
        return events,self.last_logit

    def checkpoint(self):
        payload=dict(version=self.VERSION,model_sha256=model_digest(self.model),
                     spike_checkpoint=self.spikes.checkpoint(),
                     content=self.hidden.detach().cpu().contiguous().flatten().tolist(),
                     last_time=self.last_time,processed=self.processed,
                     last_logit=self.last_logit)
        payload['sha256']=hashlib.sha256(canonical(payload).encode()).hexdigest()
        return canonical(payload)

    @classmethod
    def from_checkpoint(cls,model,raw,*,expected_spec=None,expected_stream_id=None):
        if not isinstance(model,TrainableEventContent) or model.training:
            raise UnresolvedContent('restoration requires frozen eval model')
        try:
            data=json.loads(raw)
            if type(data) is not dict:
                raise ValueError('non-map checkpoint')
            digest=data.pop('sha256')
            if type(digest) is not str or len(digest)!=64 or hashlib.sha256(canonical(data).encode()).hexdigest()!=digest:
                raise ValueError('checkpoint digest mismatch')
            if set(data)!={'version','model_sha256','spike_checkpoint','content','last_time','processed','last_logit'}:
                raise ValueError('unknown checkpoint fields')
            if data['version']!=cls.VERSION or data['model_sha256']!=model_digest(model):
                raise ValueError('model version/digest mismatch')
            spike=SpikeStream.from_checkpoint(data['spike_checkpoint'],
                            expected_spec=expected_spec,expected_stream_id=expected_stream_id)
            if (type(data['processed']) is not int or not 0<=data['processed']<=65535
                    or type(data['last_time']) not in (int,float) or not math.isfinite(data['last_time'])
                    or spike.now!=data['last_time']
                    or type(data['content']) is not list or len(data['content'])!=model.hidden
                    or any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>1e6
                           for v in data['content'])):
                raise ValueError('invalid content/spike consistency')
            if (data['last_logit'] is not None and
                    (type(data['last_logit']) not in (int,float) or not math.isfinite(data['last_logit']))):
                raise ValueError('invalid logit')
        except (ValueError,TypeError,KeyError,UnresolvedSpike,OverflowError) as exc:
            raise UnresolvedContent('untrusted or incompatible content snapshot') from exc
        obj=cls.__new__(cls)
        obj.model=model;obj.spikes=spike
        obj.hidden=torch.tensor(data['content'],dtype=torch.float32).reshape(1,model.hidden)
        obj.last_time=float(data['last_time']);obj.processed=data['processed']
        obj.last_logit=data['last_logit']
        return obj


def example(task:str,*,length:int,seed:int):
    """Causal payload, repeated overwrite and irregular clock; queries last."""
    if task not in ('copy','mqar4') or type(length) is not int or length<12:
        raise UnresolvedContent('invalid task or length')
    rng=np.random.default_rng(seed)
    x=np.zeros((length,DIM),dtype=np.float32)
    y=np.zeros(length,dtype=np.float32)
    mask=np.zeros(length,dtype=np.float32)
    if task=='copy':
        mark=int(rng.integers(1,length//2))
        x[:-1,0]=1.
        x[:-1,4]=rng.choice([-1.,1.],size=length-1)
        x[mark,5]=1.
        x[-1,0]=1.;x[-1,6]=1.
        y[-1]=float(x[mark,4]>0)
        mask[-1]=1.
    else:
        write_keys=np.concatenate((np.arange(K),rng.integers(0,K,size=length-K-K)))
        rng.shuffle(write_keys)
        values=rng.choice([-1.,1.],size=len(write_keys))
        for i,(key,value) in enumerate(zip(write_keys,values)):
            x[i,int(key)]=1.;x[i,4]=value;x[i,5]=1.
        query_keys=rng.permutation(K)
        for j,key in enumerate(query_keys):
            idx=length-K+j
            x[idx,int(key)]=1.;x[idx,6]=1.
            last=np.flatnonzero(write_keys==key)[-1]
            y[idx]=float(values[last]>0)
            mask[idx]=1.
    dt=rng.uniform(.2,1.1,size=length).astype(np.float64)
    times=np.cumsum(dt).tolist()
    return x,y,mask,np.asarray(dt,dtype=np.float32),times


def make_batch(task:str,*,n:int,length:int,seed:int):
    if not 1<=n<=10000:raise UnresolvedContent('invalid batch size')
    xs=[];ys=[];ms=[];dts=[];cts=[];total_events=0;multi_fire=0
    spec=default_spec()
    for k in range(n):
        x,y,m,dt,times=example(task,length=length,seed=seed*100000+k)
        stream=SpikeStream(spec,seed=seed*100000+k,
                           stream_id=f'{task}-{seed}-{k}')
        counts=[]
        for t in times:
            counts.append(len(stream.advance_to(t)))
        total_events+=sum(counts);multi_fire+=int(stream.events>=2)
        xs.append(x);ys.append(y);ms.append(m);dts.append(dt);cts.append(np.array(counts,dtype=np.float32))
    to=lambda arr:torch.from_numpy(np.stack(arr))
    return dict(x=to(xs),y=to(ys),mask=to(ms),dt=to(dts),count=to(cts),
                total_events=total_events,multi_fire_streams=multi_fire)


def train_pilot(task:str,*,seed=0,steps=100,train_n=128,test_n=128,hidden=32):
    torch.set_num_threads(1)
    train=make_batch(task,n=train_n,length=16,seed=100+seed)
    test=make_batch(task,n=test_n,length=16,seed=200+seed)
    ood=make_batch(task,n=test_n,length=32,seed=300+seed)
    torch.manual_seed(400+seed)
    model=TrainableEventContent(hidden)
    before=model_digest(model)
    opt=torch.optim.Adam(model.parameters(),lr=.006)
    rng=np.random.default_rng(500+seed)
    cpu=time.process_time()
    model.train()
    for _ in range(steps):
        ids=rng.integers(0,train_n,size=24)
        opt.zero_grad(set_to_none=True)
        logits=model(train['x'][ids],train['dt'][ids],train['count'][ids])
        loss=(F.binary_cross_entropy_with_logits(logits,train['y'][ids],reduction='none')*train['mask'][ids]).sum()/train['mask'][ids].sum()
        loss.backward();opt.step()
    train_cpu=time.process_time()-cpu
    model.eval()
    def score(data):
        with torch.no_grad():
            logits=model(data['x'],data['dt'],data['count'])
            match=((logits>=0)==(data['y']>=.5)).float()*data['mask']
            accuracy=float(match.sum()/data['mask'].sum())
            err=float((F.binary_cross_entropy_with_logits(logits,data['y'],reduction='none')*data['mask']).sum()/data['mask'].sum())
        return dict(accuracy=accuracy,logloss=err,total_events=data['total_events'],multi_fire_streams=data['multi_fire_streams'])
    return model,dict(task=task,seed=seed,steps=steps,train_n=train_n,test_n=test_n,
                      train_cpu_seconds=train_cpu,params=sum(p.numel() for p in model.parameters()),
                      model_sha256=model_digest(model),initial_model_sha256=before,
                      id=score(test),ood=score(ood),
                      production_activation=False,all_scientific_blockers_closed=False)
