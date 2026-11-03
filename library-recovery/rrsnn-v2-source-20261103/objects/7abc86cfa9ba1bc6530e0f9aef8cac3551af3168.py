"""Frozen-weight real-event rollouts for the v2 deterministic controller.

CTMC backend samples the EXACT finite-Q/remap law used by the density encoder.
Brownian backend uses the SAME learned control function, with unrestricted
continuous evidence and deterministic refractory, hence a distinct physical law.
Neither backend replaces actual spikes by a Bernoulli interval indicator.

Usage:
    rollout = SampledDensityRollout(encoder, batch_size=B, backend='ctmc', seed=101)
    out = rollout.step(observation, dt_elapsed, event_mask=True)
    logits = head(out['latent'])
    # The real environment uses this sampled policy action to make the next obs.

Expected-density and sampled-policy actions can differ under a nonlinear head or
argmax decision. Fixed coefficient-tape comparisons establish latent-law
agreement; they do not imply identical closed-loop policy utility.
"""
from __future__ import annotations

from types import SimpleNamespace
import numpy as np
import torch

from .exact_rollout import ExactIndependentRollout


def categorical_rows(probabilities, rng):
    p=np.asarray(probabilities,dtype=float)
    cdf=np.cumsum(p,axis=-1)
    cdf[...,-1]=1.
    return np.sum(rng.random(p.shape[:-1])[...,None]>=cdf,axis=-1)


class SampledDensityRollout:
    def __init__(self,encoder,batch_size,backend="ctmc",seed=101,record_spikes=True):
        if backend not in ("ctmc","brownian"):
            raise ValueError("backend must be ctmc or brownian")
        if "moment_collapse" in encoder.ablations:
            raise ValueError("moment_collapse is a distribution feedback ablation with no single-path same-law realization")
        if encoder.operator.refractory_phases<1:
            raise ValueError("This marked-jump sampler requires at least one refractory phase")
        parameter=next(encoder.parameters())
        if parameter.device.type!="cpu":
            raise ValueError("Independent reference rollout currently supports CPU only")
        self.encoder=encoder
        self.operator=encoder.operator
        self.backend=backend
        self.batch=int(batch_size)
        self.hidden=encoder.hidden_size
        self.dtype=parameter.dtype
        initial=encoder.initial_state(self.batch,device="cpu",dtype=self.dtype)
        # Only the sampled index is persistent. Keeping the initial full p
        # would silently retain an unused H*S probability table per sequence.
        self.state=SimpleNamespace(context=initial.context,drift=initial.drift,
            boundary=initial.boundary,initial_resource=initial.initial_resource)
        self.rng=np.random.default_rng(seed)
        self.time=np.zeros(self.batch)
        self.total_counts=np.zeros((self.batch,self.hidden),dtype=np.int64)
        self.record_spikes=bool(record_spikes)
        self.has_observed=np.zeros(self.batch,dtype=bool)
        self.indices=(categorical_rows(initial.probability.detach().numpy(),self.rng)
                      if backend=="ctmc" else None)
        self.engines=[]
        if backend=="brownian":
            op=self.operator
            for row in range(self.batch):
                self.engines.append(ExactIndependentRollout(np.full(self.hidden,op.reset),
                    drift=0.,threshold=encoder.fixed_boundary,sigma=op.sigma,
                    reset=op.reset,refractory=op.refractory,seed=seed+100003*row))

    def _record(self,events,time,row,component,cause,**extra):
        if self.record_spikes:
            events.append({"time":float(time),"batch":int(row),"component":int(component),
                           "cause":cause,**extra})

    def _advance_ctmc(self,dt):
        q,_=self.operator.generator(self.state.drift.double(),self.state.boundary.double())
        q=q.detach().numpy().reshape(-1,self.operator.state_size,self.operator.state_size)
        off=q.copy()
        diagonal=np.arange(self.operator.state_size)
        off[:,diagonal,diagonal]=0
        rates=off.sum(axis=-1)
        probabilities=np.divide(off,rates[:,:,None],out=np.zeros_like(off),where=rates[:,:,None]>0)
        cdf=probabilities.cumsum(axis=-1);cdf[:,:,-1]=1.
        states=self.indices.reshape(-1).copy()
        clock=np.zeros(len(states));ends=np.repeat(dt,self.hidden)
        counts=np.zeros(len(states),dtype=np.int64)
        active=ends>0
        events=[]
        rounds=0
        while active.any():
            rounds+=1
            if rounds>100000:
                raise RuntimeError("CTMC jump cap exceeded")
            ids=np.flatnonzero(active)
            local_rates=rates[ids,states[ids]]
            wait=np.full(len(ids),np.inf)
            moving=local_rates>0
            wait[moving]=self.rng.exponential(1/local_rates[moving])
            within=clock[ids]+wait<=ends[ids]
            active[ids[~within]]=False
            chosen=ids[within]
            if not len(chosen):
                continue
            before=states[chosen].copy()
            after=(self.rng.random(len(chosen))[:,None]>=cdf[chosen,before]).sum(axis=-1)
            clock[chosen]+=wait[within]
            fired=(before==self.operator.grid_size-1)&(after==self.operator.grid_size)
            counts[chosen]+=fired
            if self.record_spikes:
                for index in np.flatnonzero(fired):
                    flat=int(chosen[index]);row=flat//self.hidden;component=flat%self.hidden
                    self._record(events,self.time[row]+clock[flat],row,component,"ctmc_threshold")
            states[chosen]=after
        self.indices=states.reshape(self.batch,self.hidden)
        return counts.reshape(self.batch,self.hidden),events

    def _advance_brownian(self,dt):
        counts=np.zeros((self.batch,self.hidden),dtype=np.int64)
        events=[]
        for row,engine in enumerate(self.engines):
            before=engine.count.copy()
            emitted=engine.advance_to(self.time[row]+dt[row])
            counts[row]=engine.count-before
            if self.record_spikes:
                for e in emitted:
                    self._record(events,e.time,row,e.component,e.cause,evidence_before=e.evidence_before)
        return counts,events

    @torch.no_grad()
    def step(self,observation,dt_elapsed,event_mask=True):
        raw_dt=dt_elapsed.detach().cpu().numpy() if torch.is_tensor(dt_elapsed) else dt_elapsed
        dt=np.asarray(raw_dt,dtype=float)
        dt=np.broadcast_to(dt.reshape(-1) if dt.ndim else dt,(self.batch,)).copy()
        if np.any(dt<0) or not np.isfinite(dt).all():
            raise ValueError("Finite nonnegative elapsed time required")
        mask=np.broadcast_to(np.asarray(torch.as_tensor(event_mask).cpu(),dtype=bool),
                             (self.batch,)).copy()
        if np.any((~self.has_observed)&(dt>0)):
            raise ValueError("First observation must occur at dt=0")
        if observation is None and mask.any():
            raise ValueError("A real observation requires features")
        if self.backend=="ctmc":
            count,events=self._advance_ctmc(dt)
        else:
            count,events=self._advance_brownian(dt)
        self.time+=dt
        immediate=np.zeros_like(count)
        kick=torch.zeros_like(self.state.drift)
        if mask.any():
            obs=torch.as_tensor(observation,dtype=self.dtype,device="cpu")
            if obs.shape!=(self.batch,self.encoder.input_size):
                raise ValueError("Unexpected observation shape")
            m=torch.from_numpy(mask)
            obs=torch.where(m[:,None],obs,torch.zeros_like(obs))
            resource=obs[:,4:5].clamp(0,1)
            if self.state.initial_resource is not None:
                first=self.state.initial_resource<0
                self.state.initial_resource=torch.where(first&m[:,None],resource,self.state.initial_resource)
                resource=torch.where(self.state.initial_resource<0,resource,self.state.initial_resource)
            controls=self.encoder.controls_from_observation(self.state.context,obs,resource)
            if self.backend=="ctmc":
                matrix,_=self.operator.remap_matrix(self.state.boundary.double(),
                    controls["boundary"].double(),controls["kick"].double())
                transition=matrix.detach().numpy()
                rows,hidden=np.indices(self.indices.shape)
                probabilities=transition[rows,hidden,self.indices]
                after=categorical_rows(probabilities,self.rng)
                fired=(self.indices<self.operator.grid_size)&(after==self.operator.grid_size)&mask[:,None]
                immediate=fired.astype(np.int64)
                if self.record_spikes:
                    for row,component in zip(*np.nonzero(fired)):
                        self._record(events,self.time[row],row,component,"ctmc_observation_remap")
                self.indices=np.where(mask[:,None],after,self.indices)
            else:
                for row in np.flatnonzero(mask):
                    engine=self.engines[row]
                    before=engine.count.copy()
                    emitted=engine.observe(drift=controls["drift"][row].numpy(),
                        threshold=controls["boundary"][row].numpy(),kick=controls["kick"][row].numpy())
                    immediate[row]=engine.count-before
                    if self.record_spikes:
                        for e in emitted:
                            self._record(events,e.time,row,e.component,e.cause,evidence_before=e.evidence_before)
            for field in ("context","drift","boundary"):
                setattr(self.state,field,torch.where(m[:,None],controls[field],getattr(self.state,field)))
            kick=torch.where(m[:,None],controls["kick"],kick)
            self.has_observed|=mask
        count=count+immediate
        self.total_counts+=count
        if self.backend=="ctmc":
            nodes=self.operator.nodes(self.state.boundary).numpy()
            idx=np.minimum(self.indices,self.operator.grid_size-1)
            evidence=np.take_along_axis(nodes,idx[...,None],axis=-1)[...,0]
            evidence=np.where(self.indices<self.operator.grid_size,evidence,self.operator.reset)
        else:
            evidence=np.stack([e.evidence for e in self.engines])
        events.sort(key=lambda event:(event["time"],event["batch"],event["component"]))
        return {"latent":torch.as_tensor(np.tanh(evidence),dtype=self.dtype),
                "spikes":torch.as_tensor(count,dtype=self.dtype),
                "actual_counts":torch.from_numpy(count.copy()),
                "immediate_counts":torch.from_numpy(immediate.copy()),
                "spike_times":events,"drift":self.state.drift,"boundary":self.state.boundary,
                "kick":kick,"time":self.time.copy(),"backend":self.backend,
                "semantics":("Exact sampled finite CTMC and stochastic remap at supplied frozen controls"
                    if self.backend=="ctmc" else
                    "Same learned controls, continuous Brownian evidence and deterministic refractory; distinct from CTMC approximation")}

    def metadata(self):
        """Count the persistent numeric buffers actually retained by this object.

        Object headers, generator internals and retained event logs are named
        separately; these byte counts must not be represented as process RSS.
        """
        buffers={"time_float64":int(self.time.nbytes),
                 "observed_bool":int(self.has_observed.nbytes),
                 "total_counts_int64":int(self.total_counts.nbytes)}
        for name in ("context","drift","boundary","initial_resource"):
            value=getattr(self.state,name)
            if value is not None:
                buffers[name]=int(value.numel()*value.element_size())
        if self.indices is not None:
            buffers["sampled_indices_int64"]=int(self.indices.nbytes)
        if self.backend=="brownian":
            for name in ("evidence","drift","sigma","threshold","reset","refractory",
                         "refractory_until","count"):
                buffers["brownian_"+name]=sum(int(getattr(e,name).nbytes) for e in self.engines)
        total=sum(buffers.values())
        return {"backend":self.backend,"batch_size":self.batch,"hidden_size":self.hidden,
                "dtype":str(self.dtype),"persistent_numeric_buffer_bytes":buffers,
                "persistent_numeric_buffer_bytes_total":total,
                "persistent_numeric_buffer_bytes_per_sequence":total/self.batch,
                "persistent_probability_table":False,
                "shared_rng":"One PCG64 generator for CTMC; its Python/C storage is not a per-sequence numeric buffer.",
                "brownian_rng":"One PCG64 per component; generator object/internal storage is additional." if self.backend=="brownian" else None,
                "excludes":"Model parameters/shared buffers, Python object headers, RNG implementation storage, optional retained Brownian event histories, output tensors/logs, temporary Q/remap matrices, and interpreter/framework RSS."}
