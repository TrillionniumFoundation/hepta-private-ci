"""Slot-only raw-event service, observable client, and causal replay builder."""

import hashlib
import numpy as np
from experiments.hcsn_missing_reliability_r2_20261101.posterior import VisiblePosterior

POLICIES=("confidence_read","always_read","never_read","simple_threshold")
REPLY_FIELDS={"slot","original_timestamp","event","arrival_timestamp","charge","wait"}


class RawProvider:
    def __init__(self,full_x,dt,observed,price):
        # No labels, target keys, dependencies or posterior accepted by this API.
        if not np.isfinite(price) or price<0:raise ValueError("Finite nonnegative READ price required")
        self._events=np.array(full_x,copy=True);self.timestamps=np.cumsum(dt,dtype=np.float64)
        self._missing=set(np.flatnonzero(~observed).tolist());self.price=float(price)
        self.cursor=-1;self.now=0.;self.fees=0.;self.reads=0;self.cache={};self.requests=[]

    def advance(self,cursor):
        if cursor<self.cursor:raise ValueError("Provider cursor cannot move backwards")
        if cursor>self.cursor and float(self.timestamps[cursor])<self.now-1e-8:
            raise ValueError("A newly arriving source frame overlaps READ; queueing is outside this profile")
        self.cursor=int(cursor);self.now=max(self.now,float(self.timestamps[cursor]))

    def read(self,slot):
        if type(slot) is not int or slot not in self._missing or slot>self.cursor:
            raise ValueError("Only an ingested observed-missing slot can be requested")
        cached=slot in self.cache
        if not cached:
            if not self._events[slot,12]:raise ValueError("Registered missing payload is not WRITE")
            self.now+=.1;self.fees+=self.price;self.reads+=1
            self.cache[slot]=self._events[slot].copy()
        reply=dict(slot=slot,original_timestamp=float(self.timestamps[slot]),event=self.cache[slot].tolist(),
            arrival_timestamp=self.now,charge=0. if cached else self.price,wait=0. if cached else .1)
        self.requests.append(dict(slot=slot,cursor=self.cursor,cached=cached,**{k:reply[k] for k in ["original_timestamp","arrival_timestamp","charge","wait"]},
            event_sha256=hashlib.sha256(np.asarray(reply["event"],np.float32).tobytes()).hexdigest()))
        return reply


def accept_reply(reply,slot,timestamps,price,request_at,cached=False):
    if set(reply)!=REPLY_FIELDS or type(reply["slot"]) is not int or reply["slot"]!=slot or not 0<=slot<len(timestamps):
        raise ValueError("Reply schema or original timestamp mismatch")
    if any(type(reply[k]) not in (int,float) for k in ["original_timestamp","arrival_timestamp","charge","wait"]):
        raise ValueError("Numeric READ receipt fields required")
    numbers=np.asarray([reply[k] for k in ["original_timestamp","arrival_timestamp","charge","wait"]],np.float64)
    expected_wait=0. if cached else .1;expected_charge=0. if cached else price
    if (not np.isfinite(numbers).all() or (numbers<0).any()
            or abs(reply["original_timestamp"]-timestamps[slot])>1e-9
            or reply["original_timestamp"]>request_at+1e-9
            or abs(reply["wait"]-expected_wait)>1e-9 or abs(reply["charge"]-expected_charge)>1e-9
            or abs(reply["arrival_timestamp"]-(request_at+expected_wait))>1e-8):
        raise ValueError("Nonfinite, stale or inconsistent READ receipt")
    try:event=np.asarray(reply["event"],np.float32)
    except (TypeError,ValueError) as e:raise ValueError("Numeric raw WRITE payload required") from e
    if (event.shape!=(24,) or not np.isfinite(event).all() or event[12]!=1
            or not np.all((event==0)|(event==1))
            or event[12:16].sum()!=1 or event[:4].sum()!=1 or event[4:12].sum()!=1):
        raise ValueError("Raw WRITE payload required")
    return event


def generic_probability(x,observed):
    memory={};aliases={}
    for event,present in zip(x[:-1],observed[:-1],strict=True):
        if not present:continue
        if event[12]:memory[int(event[:4].argmax())]=int(event[4:12].argmax())
        if event[15]:aliases[int(event[19:23].argmax())]=int(event[:4].argmax())
    query=x[-1]
    if query[19:23].sum():key=aliases.get(int(query[19:23].argmax()),-1)
    else:key=int(query[:4].argmax())
    return np.eye(8)[memory[key]] if key in memory else np.full(8,1/8)


def belief(task,x,dt,observed,q):
    unread=np.flatnonzero(~observed)
    if not len(unread):return generic_probability(x,observed),"generic_complete"
    if len(unread)>1:return generic_probability(x,observed),"observable_fallback"
    try:
        p=VisiblePosterior(task,q).forward(x[None],dt[None],observed[None])["probabilities"][0,-1]
        return p,"r2_declared_law"
    except ValueError:
        return generic_probability(x,observed),"observable_fallback"


def replay(source_x,source_dt,source_observed,acquired,markers):
    """Retrospective state reconstruction; historical environment actions stay fixed."""
    x=source_x.copy();observed=source_observed.copy();timestamps=np.cumsum(source_dt,dtype=np.float64)
    for slot,event in acquired.items():
        if slot>=len(x) or source_observed[slot]:raise ValueError("Acquisition is not a missing past slot")
        x[slot]=event;observed[slot]=True
    xx=[];dd=[];oo=[];clock=0.
    for t,(event,present) in enumerate(zip(x,observed,strict=True)):
        elapsed=float(timestamps[t]-clock)
        if elapsed < -1e-8:raise ValueError("A source event arrived during READ; queueing is outside this profile")
        xx.append(event.copy());dd.append(max(0.,elapsed));oo.append(present);clock=float(timestamps[t])
        if t in markers:
            wait=markers[t]
            xx.extend([np.zeros(24,np.float32),event.copy()]);dd.extend([wait,0.]);oo.extend([False,True]);clock+=wait
    return dict(x=np.asarray(xx,np.float32),dt=np.asarray(dd,np.float32),observed=np.asarray(oo,bool))


def choose_slots(policy,p,branch,unread,price,threshold):
    if policy=="always_read":return unread
    needed=bool(unread) and (branch=="observable_fallback" or p.max()<.95)
    if policy in ("confidence_read","simple_threshold") and needed:
        return unread if policy=="confidence_read" or price<=threshold else []
    return []


def plan(task,full_x,partial_x,dt,observed,price,policy,q,threshold):
    if policy not in POLICIES:raise ValueError("Unknown fixed policy")
    provider=RawProvider(full_x,dt,observed,price);acquired={};markers={};queries=[];inputs=[];client_now=0.
    for cursor,event in enumerate(partial_x):
        provider.advance(cursor)
        client_now=max(client_now,float(np.sum(dt[:cursor+1],dtype=np.float64)))
        if not observed[cursor] or not event[13]:continue
        visible=partial_x[:cursor+1].copy();present=observed[:cursor+1].copy()
        for slot,payload in acquired.items():visible[slot]=payload;present[slot]=True
        p,branch=belief(task,visible,dt[:cursor+1],present,q)
        unread=np.flatnonzero(~present).tolist()
        slots=choose_slots(policy,p,branch,unread,price,threshold)
        exact_p,exact_branch=belief(task,visible,dt[:cursor+1],present,2/3)
        if slots!=choose_slots(policy,exact_p,exact_branch,unread,price,threshold):raise ValueError("Exact ordinary reference chose different READ information")
        wait=0.;requests=[]
        for slot in slots:
            reply=provider.read(int(slot));payload=accept_reply(reply,int(slot),provider.timestamps[:cursor+1],price,client_now,cached=int(slot) in acquired)
            client_now=reply["arrival_timestamp"]
            acquired[int(slot)]=payload;wait+=reply["wait"];requests.append(reply)
        if wait:
            markers[cursor]=wait
            for slot,payload in acquired.items():visible[slot]=payload;present[slot]=True
        # After acquisition use generic typed replay, including shifted/multiple-erasure laws.
        after,after_branch=belief(task,visible,dt[:cursor+1],present,q)
        exact_after,_=belief(task,visible,dt[:cursor+1],present,2/3)
        neural_input=replay(partial_x[:cursor+1],dt[:cursor+1],observed[:cursor+1],acquired,markers)
        digest=hashlib.sha256()
        for key in ("x","dt","observed"):digest.update(neural_input[key].tobytes())
        inputs.append((digest.hexdigest(),neural_input))
        queries.append(dict(cursor=cursor,source_timestamp=float(provider.timestamps[cursor]),answer_timestamp=provider.now,
            pre_probability=p.tolist(),pre_branch=branch,post_probability=after.tolist(),post_branch=after_branch,
            ordinary_answer=int(exact_after.argmax()),exact_reference_same_requests=True,visible_missing_slots=unread,requested_slots=slots,
            receipts=requests,paid_so_far=provider.fees,wait_this_query=wait,replay_sha256=digest.hexdigest(),
            replay_steps=len(neural_input["dt"]),replay_elapsed=float(neural_input["dt"].astype(np.float64).sum()),
            reconstructed_after_acquisition=True,environment_action_history_unchanged=True))
    if len(queries)!=4:raise ValueError("Four actually ingested queries required")
    return dict(queries=queries,fee=provider.fees,reads=provider.reads,requests=provider.requests,
        answer=[r["ordinary_answer"] for r in queries],read_wait=sum(markers.values())),inputs
