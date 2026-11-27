"""Trainable boundary-updated spike-feedback CTMC network with full path scores.

All actual top->refractory jumps and observation-remap firings update an
exponential spike trace. R reads that stochastic trace only at real observation
boundaries. The action head reads tanh(trace), with no analog context shortcut.
Between observations Q is held fixed. This is NOT continuously refreshed
asynchronous feedback, and it does not claim a factorized joint density closure.

Conditional on past sampled paths, intervals are finite CTMCs. Their likelihood
is sum_ij N_ij log q_ij - sum_i dwell_i * exit_rate_i. Initial and observed remap
discrete probabilities are included. Samples/time/counts/dwell/trace are detached;
training uses the path score plus the direct task-loss derivative.
"""

from dataclasses import dataclass
import math
import numpy as np
import torch
from torch import nn

from .operators import DensityNeuronOperator, frozen_control_boundary, numerical_control_boundary
def set_nll_per_decision(logits,valid,optimal):
    if not bool(valid.any(-1).all()) or not bool((optimal & valid).any(-1).all()):
        raise ValueError("empty feasible or optimal action set")
    return torch.logsumexp(logits.masked_fill(~valid,-1e9),-1)-torch.logsumexp(logits.masked_fill(~optimal,-1e9),-1)



def normalized_probabilities(p):
    if not bool(torch.isfinite(p).all()) or bool((p < -1e-8).any()):
        raise FloatingPointError("Nonfinite or negative discrete probability")
    p=p.clamp(min=0)
    if bool((p.sum(-1)<=0).any()):raise FloatingPointError("Zero-mass discrete row")
    return p/p.sum(-1,keepdim=True)


def categorical_rows(p,rng):
    cdf=np.asarray(p,dtype=float).cumsum(-1);cdf[...,-1]=1.
    return np.sum(rng.random(cdf.shape[:-1])[...,None]>=cdf,axis=-1)


def chosen_log_probability(probability,index,required_mask=None):
    chosen=torch.as_tensor(index,dtype=torch.long,device=probability.device)
    value=probability.gather(-1,chosen[...,None]).squeeze(-1)
    required=torch.ones_like(value,dtype=torch.bool) if required_mask is None else required_mask
    if bool(((value<=0)|(~torch.isfinite(value)))[required.expand_as(value)].any()):
        raise ValueError("Recorded discrete transition is outside the new parameter support")
    return value.clamp(min=1e-30).log()


def sample_interval(q,indices,elapsed,trace,rng,*,trace_tau=2.5,spike_edge=None,
                    absolute_time=None,record_spikes=False,max_rounds=100000):
    """Sample full CTMC jump paths and sufficient statistics under supplied Q.

    q:[B,H,S,S], index/trace:[B,H], elapsed/time:[B]. Rates are not recomputed
    during an interval. The returned integer N_ij and dwell T_i cover the full
    interval, including the final censored holding time.
    """
    if not math.isfinite(trace_tau) or trace_tau<=0:
        raise ValueError("trace_tau must be finite and positive")
    if not np.isfinite(elapsed).all() or np.any(np.asarray(elapsed)<0):
        raise ValueError("Elapsed time must be finite and nonnegative")
    q=np.asarray(q,dtype=float)
    b,h,s,_=q.shape;paths=b*h
    matrices=q.reshape(paths,s,s)
    off=matrices.copy();diag=np.arange(s);off[:,diag,diag]=0
    rates=off.sum(-1)
    probabilities=np.divide(off,rates[:,:,None],out=np.zeros_like(off),where=rates[:,:,None]>0)
    cdf=probabilities.cumsum(-1);cdf[:,:,-1]=1.
    states=np.asarray(indices,dtype=np.int64).reshape(-1).copy()
    end=np.repeat(np.asarray(elapsed,dtype=float),h)
    clock=np.zeros(paths)
    dwell=np.zeros((paths,s),dtype=np.float64)
    transitions=np.zeros((paths,s,s),dtype=np.int32)
    counts=np.zeros(paths,dtype=np.int64)
    final_trace=np.asarray(trace,dtype=float).reshape(-1)*np.exp(-end/trace_tau)
    active=end>0;events=[];rounds=0
    start_times=np.zeros(b) if absolute_time is None else np.asarray(absolute_time,dtype=float)
    while active.any():
        rounds+=1
        if rounds>max_rounds:raise RuntimeError("CTMC path exceeded jump-round cap")
        ids=np.flatnonzero(active);before=states[ids].copy()
        local_rates=rates[ids,before]
        wait=np.full(len(ids),np.inf);moving=local_rates>0
        wait[moving]=rng.exponential(1/local_rates[moving])
        remaining=end[ids]-clock[ids]
        duration=np.minimum(wait,remaining)
        dwell[ids,before]+=duration
        occurs=wait<=remaining
        active[ids[~occurs]]=False
        chosen=ids[occurs]
        if not len(chosen):continue
        before=states[chosen].copy()
        after=(rng.random(len(chosen))[:,None]>=cdf[chosen,before]).sum(-1)
        clock[chosen]+=wait[occurs]
        transitions[chosen,before,after]+=1
        marked=((before==spike_edge[0])&(after==spike_edge[1])
                if spike_edge is not None else np.zeros(len(chosen),dtype=bool))
        marked_ids=chosen[marked]
        counts[marked_ids]+=1
        final_trace[marked_ids]+=np.exp(-(end[marked_ids]-clock[marked_ids])/trace_tau)
        if record_spikes:
            for flat in marked_ids:
                row=int(flat//h);component=int(flat%h)
                events.append({"time":float(start_times[row]+clock[flat]),"batch":row,
                    "component":component,"cause":"ctmc_threshold"})
        states[chosen]=after
    if not np.allclose(dwell.sum(-1),end,rtol=0,atol=1e-10):
        raise AssertionError("Censored holding times do not cover the full interval")
    return {"indices":states.reshape(b,h),"trace":final_trace.reshape(b,h),
            "counts":counts.reshape(b,h),"jump_counts":transitions.reshape(b,h,s,s),
            "dwell_times":dwell.reshape(b,h,s),"events":events}


def interval_log_likelihood(q,jump_counts,dwell_times,check_support=False):
    s=q.shape[-1]
    off=q*(1-torch.eye(s,dtype=q.dtype,device=q.device))
    exits=off.sum(-1)
    n=torch.as_tensor(jump_counts,dtype=q.dtype,device=q.device)
    dwell=torch.as_tensor(dwell_times,dtype=q.dtype,device=q.device)
    if check_support and bool(((n>0)&(off<=0)).any()):
        raise ValueError("Recorded CTMC transition is outside the new parameter support")
    return (n*off.clamp(min=1e-30).log()).sum((-1,-2))-(dwell*exits).sum(-1)


@dataclass
class CoupledState:
    indices:np.ndarray
    trace:np.ndarray
    context:torch.Tensor
    drift:torch.Tensor
    boundary:torch.Tensor
    time:np.ndarray
    total_counts:np.ndarray
    observed:np.ndarray
    pending_initial_score:torch.Tensor
    initial_resource:torch.Tensor


class RRPolicy(nn.Module):
    is_stochastic=True
    def __init__(self,input_size=22,hidden_size=8,grid_size=16,refractory_phases=2,
                 trace_tau=2.5,variant="rr_full",boundary_method="closed_form"):
        super().__init__()
        self.input_size=input_size;self.hidden_size=hidden_size
        self.variant=variant;self.boundary_method=boundary_method
        allowed={"rr_full","fp_no_rollover","rr_mean_maturity","rr_shuffle_maturity","rr_fixed_boundary","rr_frozen_resource"}
        if variant not in allowed or boundary_method not in {"closed_form","root"}:raise ValueError("invalid RR mechanism")
        self.operator=DensityNeuronOperator(grid_size,refractory_phases)
        if refractory_phases<1:raise ValueError("At least one refractory phase is required")
        self.input_layer=nn.Linear(input_size,hidden_size)
        self.recurrent_layer=nn.Linear(hidden_size,hidden_size,bias=False)
        self.head=nn.Linear(hidden_size,81)
        nn.init.xavier_uniform_(self.input_layer.weight,gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight,gain=.25)
        self.trace_tau=float(trace_tau);self.fixed_boundary=1.25
        if not math.isfinite(self.trace_tau) or self.trace_tau<=0:
            raise ValueError("trace_tau must be finite and positive")
        self.drift_scale=1.5;self.kick_scale=.35

    def controls(self,observation,spike_trace,held_context,initial_resource):
        feedback=torch.as_tensor(np.tanh(spike_trace),dtype=observation.dtype,
                                 device=observation.device).detach()
        context=torch.tanh(self.input_layer(observation)+self.recurrent_layer(feedback))
        drift=self.drift_scale*torch.tanh(context)
        kick=self.kick_scale*(context-held_context)
        remaining=(4*observation[:,7:11]).clamp(min=0)
        alive=observation[:,11:15].clamp(0,1)
        if self.variant=="rr_mean_maturity":
            mean=(remaining*alive).sum(-1,keepdim=True)/alive.sum(-1,keepdim=True).clamp(min=1)
            remaining=mean.expand_as(remaining)
        elif self.variant=="rr_shuffle_maturity":remaining=remaining[:,[1,2,3,0]]
        pressure=(alive/(remaining+.25))[:,torch.arange(self.hidden_size)%4]
        if self.variant=="fp_no_rollover":pressure=torch.zeros_like(pressure)
        resource=(initial_resource if self.variant=="rr_frozen_resource" else observation[:,4:5]).clamp(0,1)
        cost=.20+.30*(1-resource)+.12*pressure*(.5+.5*context.abs())
        boundary_fn=numerical_control_boundary if self.boundary_method=="root" else frozen_control_boundary
        boundary=boundary_fn(drift,cost,self.operator.sigma,.4,self.operator.refractory).clamp(.55,2.25)
        if self.variant=="rr_fixed_boundary":boundary=torch.full_like(boundary,self.fixed_boundary)
        return {"context":context,"drift":drift,"boundary":boundary,"kick":kick}

    def initial_state(self,batch_size,rng):
        parameter=self.input_layer.weight
        if parameter.device.type!="cpu":raise ValueError("Reference implementation is CPU-only")
        context=parameter.new_zeros(batch_size,self.hidden_size)
        boundary=torch.full_like(context,self.fixed_boundary)
        p=normalized_probabilities(self.operator.reset_distribution(boundary.double()))
        indices=categorical_rows(p.detach().numpy(),rng)
        score=chosen_log_probability(p,indices).sum(-1)
        return CoupledState(indices,np.zeros((batch_size,self.hidden_size)),context,
            torch.zeros_like(context),boundary,np.zeros(batch_size),
            np.zeros((batch_size,self.hidden_size),dtype=np.int64),np.zeros(batch_size,dtype=bool),score,parameter.new_zeros(batch_size,1))

    def step(self,state,observation,dt_elapsed,rng,event_mask=True,record_spikes=False,record_path=False):
        b,h=state.indices.shape
        raw=dt_elapsed.detach().cpu().numpy() if torch.is_tensor(dt_elapsed) else dt_elapsed
        elapsed=np.broadcast_to(np.asarray(raw,dtype=float).reshape(-1),(b,)).copy()
        mask=np.broadcast_to(np.asarray(event_mask.detach().cpu().numpy() if torch.is_tensor(event_mask)
                                        else event_mask,dtype=bool),(b,)).copy()
        if not np.isfinite(elapsed).all() or np.any(elapsed<0) or np.any((~state.observed)&(elapsed>0)):
            raise ValueError("Causal nonnegative dt and initial observation at dt0 required")
        if observation is None and mask.any():raise ValueError("Observed event needs input features")
        q,_=self.operator.generator(state.drift.double(),state.boundary.double())
        sampled=sample_interval(q.detach().numpy(),state.indices,elapsed,state.trace,rng,
            trace_tau=self.trace_tau,spike_edge=(self.operator.grid_size-1,self.operator.grid_size),
            absolute_time=state.time,record_spikes=record_spikes)
        interval_score=interval_log_likelihood(q,sampled["jump_counts"],sampled["dwell_times"]).sum(-1)
        score=interval_score+state.pending_initial_score
        current_time=state.time+elapsed
        indices=sampled["indices"];trace=sampled["trace"].copy();count=sampled["counts"].copy()
        events=sampled["events"];immediate=np.zeros_like(count)
        new_context,new_drift,new_boundary=state.context,state.drift,state.boundary
        initial_resource=state.initial_resource
        kick=torch.zeros_like(state.context)
        source_indices=indices.copy()
        if mask.any():
            obs=torch.as_tensor(observation,dtype=state.context.dtype,device="cpu")
            if obs.shape!=(b,self.input_size):raise ValueError("Input shape mismatch")
            observed=torch.from_numpy(mask)
            obs=torch.where(observed[:,None],obs,torch.zeros_like(obs))
            initial_resource=torch.where((observed & ~torch.from_numpy(state.observed))[:,None],obs[:,4:5],state.initial_resource)
            controls=self.controls(obs,trace,state.context,initial_resource)
            matrix,_=self.operator.remap_matrix(state.boundary.double(),controls["boundary"].double(),controls["kick"].double())
            row=torch.arange(b)[:,None];neuron=torch.arange(h)[None,:]
            probs=normalized_probabilities(matrix[row,neuron,torch.from_numpy(indices)])
            after=categorical_rows(probs.detach().numpy(),rng)
            log_remap=chosen_log_probability(probs,after)
            score=score+(log_remap*observed[:,None]).sum(-1)
            fired=(indices<self.operator.grid_size)&(after==self.operator.grid_size)&mask[:,None]
            immediate=fired.astype(np.int64);trace+=immediate;count+=immediate
            if record_spikes:
                for row_index,component in zip(*np.nonzero(fired)):
                    events.append({"time":float(current_time[row_index]),"batch":int(row_index),
                                   "component":int(component),"cause":"ctmc_observation_remap"})
            indices=np.where(mask[:,None],after,indices)
            new_context=torch.where(observed[:,None],controls["context"],state.context)
            new_drift=torch.where(observed[:,None],controls["drift"],state.drift)
            new_boundary=torch.where(observed[:,None],controls["boundary"],state.boundary)
            kick=torch.where(observed[:,None],controls["kick"],kick)
        next_state=CoupledState(indices,trace,new_context,new_drift,new_boundary,current_time,
            state.total_counts+count,state.observed|mask,torch.zeros_like(score),initial_resource)
        latent=torch.as_tensor(np.tanh(trace),dtype=state.context.dtype).detach()
        events.sort(key=lambda event:(event["time"],event["batch"],event["component"]))
        out={"latent":latent,"logits":self.head(latent),"actual_counts":torch.from_numpy(count),
             "spikes":torch.as_tensor(count,dtype=state.context.dtype),"full_path_log_probability":score,
             "spike_times":events,"drift":new_drift,"boundary":new_boundary,"kick":kick,
             "immediate_counts":torch.from_numpy(immediate)}
        if record_path:
            out["path_record"]={"initial_indices":state.indices.copy(),"indices_after_interval":source_indices,
                "indices_after_observation":indices.copy(),"trace_after_interval":sampled["trace"].copy(),
                "trace_after_observation":trace.copy(),"jump_counts":sampled["jump_counts"],
                "dwell_times":sampled["dwell_times"],"event_mask":mask.copy(),"elapsed":elapsed.copy()}
        return next_state,out

    def forward(self,x,dt,event_mask=None,rng=None,record_spikes=False,record_path=False):
        if x.ndim!=3 or x.shape[-1]!=self.input_size:raise ValueError("Expected[B,T,F] observations")
        b,t,_=x.shape
        if bool((dt[:,0]!=0).any()):raise ValueError("Initial dt must be0")
        rng=np.random.default_rng() if rng is None else rng
        event_mask=torch.ones(b,t,dtype=torch.bool) if event_mask is None else event_mask
        state=self.initial_state(b,rng);outputs=[]
        for k in range(t):
            state,out=self.step(state,x[:,k],dt[:,k],rng,event_mask[:,k],record_spikes,record_path)
            outputs.append(out)
        result={key:torch.stack([o[key] for o in outputs],dim=1)
                for key in ("latent","logits","actual_counts","spikes","full_path_log_probability",
                            "drift","boundary","kick","immediate_counts")}
        result["state"]=state
        result["spike_times"]=[event for out in outputs for event in out["spike_times"]]
        if record_path:result["path_records"]=[o["path_record"] for o in outputs]
        return result

    def score_fixed_path(self,x,records):
        """Re-score recorded paths at new weights for held-path FD checks."""
        b,t,_=x.shape
        context=x.new_zeros(b,self.hidden_size);drift=torch.zeros_like(context)
        boundary=torch.full_like(context,self.fixed_boundary)
        p=normalized_probabilities(self.operator.reset_distribution(boundary.double()))
        total=chosen_log_probability(p,records[0]["initial_indices"]).sum(-1)
        observed_seen=torch.zeros(b,dtype=torch.bool)
        initial_resource=x.new_zeros(b,1)
        for k,record in enumerate(records):
            q,_=self.operator.generator(drift.double(),boundary.double())
            total=total+interval_log_likelihood(q,record["jump_counts"],record["dwell_times"],check_support=True).sum(-1)
            mask=torch.from_numpy(record["event_mask"])
            if not bool(mask.any()):continue
            obs=torch.where(mask[:,None],x[:,k],torch.zeros_like(x[:,k]))
            initial_resource=torch.where((mask & ~observed_seen)[:,None],obs[:,4:5],initial_resource)
            controls=self.controls(obs,record["trace_after_interval"],context,initial_resource)
            observed_seen=observed_seen|mask
            matrix,_=self.operator.remap_matrix(boundary.double(),controls["boundary"].double(),controls["kick"].double())
            rows=torch.arange(b)[:,None];neurons=torch.arange(self.hidden_size)[None,:]
            p=normalized_probabilities(matrix[rows,neurons,torch.from_numpy(record["indices_after_interval"])])
            total=total+(chosen_log_probability(p,record["indices_after_observation"],mask[:,None])*mask[:,None]).sum(-1)
            context=torch.where(mask[:,None],controls["context"],context)
            drift=torch.where(mask[:,None],controls["drift"],drift)
            boundary=torch.where(mask[:,None],controls["boundary"],boundary)
        return total

    def metadata(self):
        return {"model":"observation-boundary-spike-feedback-ctmc","input_size":self.input_size,
            "hidden_size":self.hidden_size,"parameters_including_head":sum(p.numel() for p in self.parameters()),
            "grid_size":self.operator.grid_size,"refractory_phases":self.operator.refractory_phases,
            "trace_tau":self.trace_tau,"head_input":"tanh(actual exponential spike trace) only",
            "feedback":"context=tanh(Wx+R*tanh(actual_spike_trace)); controls refresh only on true observations",
            "likelihood":"initial discrete law + all intervalNij logqij minus dwell*exit + observed-remap discrete law",
            "sampling":"All jump times, state indices, dwell times, counts and derived trace are detached sampled quantities",
            "control_semantics":"Held coefficients between observations; not fully asynchronous spike-triggered refresh",
            "same_observation_order":"Controls read pre-remap trace; immediate remap spikes enter the head now and affect R at the next true observation",
            "physical_model":"Finite voltage CTMC, reflecting floor, Erlang refractory, P1 observed remap",
            "variant":self.variant,"boundary_method":self.boundary_method,
            "persistent_numeric_state_bytes":self.numeric_state_bytes(),
            "physical_pulse_task_cost":0,"communication_output_cost":1,
            "scope":"V4 query-delivery task bridge; latent compute measured separately; not the V3 common-budget model."}

    def numeric_state_bytes(self):
        state=self.initial_state(1,np.random.default_rng(901001))
        return sum(v.nbytes if isinstance(v,np.ndarray) else v.numel()*v.element_size() for v in vars(state).values())


def training_objective(output,valid,optimal,decision):
    nll=set_nll_per_decision(output["logits"],valid,optimal)
    costs=nll*decision;denominator=decision.sum().clamp(min=1)
    loss=costs.sum()/denominator
    if "full_path_log_probability" not in output:return loss
    future=torch.flip(torch.cumsum(torch.flip(costs,[-1]),-1),[-1]).detach()
    baseline=(future.sum(0,keepdim=True)-future)/(len(future)-1) if len(future)>1 else torch.zeros_like(future)
    correction=((future-baseline)*output["full_path_log_probability"]).sum()/denominator
    return loss+(correction-correction.detach())


class BaselinePolicy(nn.Module):
    is_stochastic=False
    def __init__(self,variant):
        super().__init__()
        from .baselines import make_encoder
        self.variant=variant
        core=variant.replace("_cpu","")
        analog=core.endswith("_analog")
        core=core.replace("_analog","")
        modes={"ctrnn_state":8,"ctrnn_upper_state":20}.get(core,1)
        core="ctrnn" if core in {"ctrnn_state","ctrnn_upper_state"} else core
        kwargs={"readout_mode":"analog" if analog else ("memory" if core=="ctrnn" else "spike")}
        if core=="ctrnn":kwargs["modes"]=modes
        self.encoder=make_encoder(core,**kwargs)
        self.head=nn.Linear(8,81)

    def initial_state(self,batch_size,rng=None):
        return self.encoder.initial_state(batch_size)

    def step(self,state,observation,dt_elapsed,rng=None,event_mask=True,record_spikes=False):
        state,out=self.encoder.step(state,observation,dt_elapsed,event_mask,record_spikes=record_spikes)
        out=dict(out);out["logits"]=self.head(out["latent"])
        return state,out

    def forward(self,x,dt,event_mask=None,rng=None,record_spikes=False,record_path=False):
        state=self.initial_state(len(x));outputs=[]
        if event_mask is None:event_mask=torch.ones(x.shape[:2],dtype=torch.bool)
        for k in range(x.shape[1]):
            state,out=self.step(state,x[:,k],dt[:,k],rng,event_mask[:,k],record_spikes)
            outputs.append(out)
        return {"logits":torch.stack([o["logits"] for o in outputs],1),
                "actual_counts":torch.stack([o["actual_counts"] for o in outputs],1),
                "latent":torch.stack([o["latent"] for o in outputs],1),"state":state,
                "spike_times":[e for o in outputs for e in o.get("spike_times",[])]}

    def metadata(self):
        return {**self.encoder.metadata(),"variant":self.variant,
            "parameters_including_head":sum(p.numel() for p in self.parameters()),
            "communication_output_cost":1,"internal_compute_cost":"independently measured, not assigned fictitious pulse energy"}


def make_policy(variant):
    if variant in {"rr_full","fp_no_rollover","rr_mean_maturity","rr_shuffle_maturity","rr_fixed_boundary","rr_frozen_resource"}:
        return RRPolicy(variant=variant)
    return BaselinePolicy(variant)
