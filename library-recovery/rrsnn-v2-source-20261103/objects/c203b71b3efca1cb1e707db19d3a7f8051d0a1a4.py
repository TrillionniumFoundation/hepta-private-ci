"""Causal differentiable distribution-valued integrate/fire operator (v2).

The active voltage is a finite birth/death chain on [lower_bound, boundary).
An upward crossing fires, enters Erlang refractory phases, and then resets.
The finite-chain semigroup and its expected firing count use a matrix
exponential; arbitrarily many reset/fire cycles are included in an interval.
This removes conditional-mean closure, but is NOT an exact continuous diffusion:
spatial discretisation, a reflecting floor, Erlang refractory, and conservative
piecewise-linear observation remapping are explicit model choices/approximations.

Controls depend on deterministic observation history only, never on a mean
substituted for a sampled stochastic state. Distribution and hard CTMC sampling
can consequently use exactly the same externally supplied control tape.
The density readout is still an expected-state policy, not a hard-spike policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import torch
from torch import nn
from torch.nn import functional as F


@dataclass
class DensityState:
    probability: torch.Tensor
    context: torch.Tensor
    drift: torch.Tensor
    boundary: torch.Tensor
    initial_resource: torch.Tensor | None = None

    def detach(self):
        return DensityState(*(v.detach() if v is not None else None for v in (
            self.probability, self.context, self.drift, self.boundary,
            self.initial_resource)))


class _LambertW0(torch.autograd.Function):
    @staticmethod
    def forward(ctx, z):
        zz=z.to(torch.float64)
        w=zz.clone()
        for _ in range(16):
            ew=w.exp();residual=w*ew-zz
            w=w-residual/(ew*(w+1)-(w+2)*residual/(2*w+2))
        ctx.save_for_backward(w,zz)
        return w.to(z.dtype)

    @staticmethod
    def backward(ctx, gradient):
        w,z=ctx.saved_tensors
        return (gradient.to(torch.float64)*w/(z*(1+w))).to(gradient.dtype)


def frozen_control_boundary(drift, cost, sigma=.4, discount=.4, refractory=.1):
    """Scalar frozen-control impulse threshold; NOT a dynamic resource QVI."""
    gamma=(torch.sqrt(drift.square()+2*discount*sigma*sigma)-drift)/(sigma*sigma)
    z=-torch.exp(-discount*refractory-1-gamma*cost)
    return cost+(1+_LambertW0.apply(z))/gamma


class DensityNeuronOperator(nn.Module):
    """Finite CTMC operator with row-vector probability convention p exp(Q dt).

    generator(drift,boundary) returns (Q, event_rate), both differentiable in
    drift/boundary away from reset interpolation knots. The top transition is
    counted even if a zero-refractory reset lands back at its own state.
    """
    def __init__(self,grid_size=16,refractory_phases=2,lower_bound=-2.,sigma=.4,
                 refractory=.1,reset=0.,method='matrix_exp'):
        super().__init__()
        if grid_size<3 or refractory_phases<0:
            raise ValueError('grid_size>=3 and refractory_phases>=0 are required')
        if sigma<=0 or (refractory_phases and refractory<=0):
            raise ValueError('positive sigma and refractory mean are required')
        if lower_bound>=reset:
            raise ValueError('reset must be strictly above the reflecting floor')
        if method not in ('matrix_exp','uniformization'):
            raise ValueError('unknown finite-chain propagator')
        self.grid_size=int(grid_size);self.refractory_phases=int(refractory_phases)
        self.lower_bound=float(lower_bound);self.sigma=float(sigma)
        self.refractory=float(refractory);self.reset=float(reset);self.method=method
        self.state_size=self.grid_size+self.refractory_phases
        self.register_buffer('grid_fraction',torch.arange(self.grid_size,dtype=torch.float64)/self.grid_size)

    def nodes(self,boundary):
        return self.lower_bound+(boundary-self.lower_bound).unsqueeze(-1)*self.grid_fraction.to(boundary)

    def reset_distribution(self,boundary):
        n=self.grid_size
        z=(self.reset-self.lower_bound)/(boundary-self.lower_bound)*n
        lo=torch.floor(z).long().clamp(0,n-1)
        fraction=(z-lo.to(z.dtype)).clamp(0,1)
        hi=(lo+1).clamp(max=n-1)
        out=boundary.new_zeros(*boundary.shape,self.state_size)
        out=out.scatter_add(-1,lo.unsqueeze(-1),(1-fraction).unsqueeze(-1))
        return out.scatter_add(-1,hi.unsqueeze(-1),fraction.unsqueeze(-1))

    def generator(self,drift,boundary):
        """Upwind rates; spatial diffusion limit is first order for nonzero drift."""
        drift,boundary=torch.broadcast_tensors(drift,boundary)
        if bool((boundary<=self.reset).any()):
            raise ValueError('threshold must exceed reset')
        n=self.grid_size;s=self.state_size;k=self.refractory_phases
        spacing=(boundary-self.lower_bound)/n
        diffusion=self.sigma*self.sigma/(2*spacing.square())
        upward=diffusion+F.relu(drift)/spacing
        downward=diffusion+F.relu(-drift)/spacing
        q=drift.new_zeros(*drift.shape,s,s)
        indices=torch.arange(n-1,device=drift.device)
        q[...,indices,indices+1]=upward.unsqueeze(-1)
        q[...,indices+1,indices]=downward.unsqueeze(-1)
        reward=drift.new_zeros(*drift.shape,s)
        reward[...,n-1]=upward
        reset=self.reset_distribution(boundary)
        if k:
            q[...,n-1,n]=upward
            rate=k/self.refractory
            if k>1:
                phases=torch.arange(n,n+k-1,device=drift.device)
                q[...,phases,phases+1]=rate
            q[...,-1,:]=rate*reset
        else:
            q[...,n-1,:]=q[...,n-1,:]+upward.unsqueeze(-1)*reset
        q=q-torch.diag_embed(q.sum(dim=-1))
        return q,reward

    def _dt(self,dt,probability):
        value=torch.as_tensor(dt,dtype=probability.dtype,device=probability.device)
        while value.ndim<probability.ndim-1:
            value=value.unsqueeze(-1)
        if bool((value<0).any()):
            raise ValueError('negative elapsed time')
        return value.expand(probability.shape[:-1])

    def propagate(self,probability,dt,drift,boundary,method=None):
        """Return full probability and expected count, with no one-spike cap."""
        elapsed=self._dt(dt,probability)
        if not bool((elapsed>0).any()):
            return probability,torch.zeros_like(elapsed)
        q,reward=self.generator(drift,boundary)
        augmented=F.pad(q,(0,1,0,1))
        augmented[...,:self.state_size,-1]=reward
        initial=F.pad(probability,(0,1))
        method=self.method if method is None else method
        if method=='matrix_exp':
            transition=torch.matrix_exp(augmented*elapsed[...,None,None])
            result=torch.matmul(initial.unsqueeze(-2),transition).squeeze(-2)
        elif method=='uniformization':
            result=self._uniformization(initial,augmented,q,elapsed)
        else:
            raise ValueError('unknown finite-chain propagator')
        return result[...,:self.state_size],result[...,-1]

    def _uniformization(self,initial,augmented,q,elapsed):
        # Detaching the uniformization rate changes no infinite-series
        # derivative; the implemented series has a controlled tiny Poisson tail.
        rate=(-q.diagonal(dim1=-2,dim2=-1)).max().detach().clamp(min=1e-12)
        chunks=max(1,math.ceil(float((rate*elapsed.max()).detach())/16.))
        mean=rate*elapsed/chunks
        terms=math.ceil(float(mean.max().detach())+10*math.sqrt(float(mean.max().detach())+1)+20)
        eye=torch.eye(augmented.shape[-1],dtype=initial.dtype,device=initial.device)
        transition=eye+augmented/rate
        state=initial
        for _ in range(chunks):
            weight=torch.exp(-mean)
            term=state
            summed=weight.unsqueeze(-1)*term
            for order in range(1,terms+1):
                term=torch.matmul(term.unsqueeze(-2),transition).squeeze(-2)
                weight=weight*mean/order
                summed=summed+weight.unsqueeze(-1)*term
            state=summed
        return state

    def remap(self,probability,old_boundary,new_boundary,kick):
        """Conservative piecewise-linear voltage remapping at a true observation.

        Existing refractory phases are untouched. Active points beyond the new
        threshold fire immediately. Between the last active node and boundary,
        linear interpolation sends a fraction to the firing state; this is an
        explicit spatial remapping approximation, not an exact diffusion jump.
        Below-floor impulses clamp at the physical floor.
        """
        n=self.grid_size;k=self.refractory_phases;s=self.state_size
        locations=self.nodes(old_boundary)+kick.unsqueeze(-1)
        coordinates=((locations-self.lower_bound)/(new_boundary-self.lower_bound).unsqueeze(-1)*n).clamp(0,n)
        lo=torch.floor(coordinates).long()
        hi=(lo+1).clamp(max=n)
        fraction=coordinates-lo.to(coordinates.dtype)
        mapped=probability.new_zeros(*probability.shape[:-1],n+1)
        mapped=mapped.scatter_add(-1,lo,probability[...,:n]*(1-fraction))
        mapped=mapped.scatter_add(-1,hi,probability[...,:n]*fraction)
        fired=mapped[...,-1]
        result=F.pad(mapped[...,:n],(0,k))
        if k:
            result=result+F.pad(probability[...,n:],(n,0))
            destination=F.one_hot(torch.tensor(n,device=probability.device),s).to(probability)
            result=result+fired.unsqueeze(-1)*destination
        else:
            result=result+fired.unsqueeze(-1)*self.reset_distribution(new_boundary)
        return result,fired

    def remap_matrix(self,old_boundary,new_boundary,kick):
        """Return the stochastic observation map and immediate-count reward.

        Rows are source states. This exposes exactly the same discrete jump
        law to hard CTMC samplers or score-function training.
        """
        old_boundary,new_boundary,kick=torch.broadcast_tensors(old_boundary,new_boundary,kick)
        s=self.state_size
        identity=torch.eye(s,dtype=old_boundary.dtype,device=old_boundary.device)
        identity=identity.expand(*old_boundary.shape,s,s)
        expanded=[v.unsqueeze(-1).expand(*v.shape,s) for v in (old_boundary,new_boundary,kick)]
        return self.remap(identity,*expanded)

    def collapse_active_mean(self,probability,boundary):
        """Ablation: preserve active mass/mean and every refractory phase mass."""
        n=self.grid_size
        mass=probability[...,:n].sum(-1)
        mean=(probability[...,:n]*self.nodes(boundary)).sum(-1)/mass.clamp(min=1e-30)
        coordinate=((mean-self.lower_bound)/(boundary-self.lower_bound)*n).clamp(0,n-1)
        lo=torch.floor(coordinate).long();hi=(lo+1).clamp(max=n-1)
        fraction=coordinate-lo.to(coordinate.dtype)
        active=probability.new_zeros(*probability.shape[:-1],n)
        active=active.scatter_add(-1,lo.unsqueeze(-1),(mass*(1-fraction)).unsqueeze(-1))
        active=active.scatter_add(-1,hi.unsqueeze(-1),(mass*fraction).unsqueeze(-1))
        return torch.cat((active,probability[...,n:]),dim=-1)

    def readout(self,probability,boundary):
        value=torch.tanh(self.nodes(boundary))
        if self.refractory_phases:
            value=F.pad(value,(0,self.refractory_phases),value=math.tanh(self.reset))
        return (probability*value).sum(dim=-1)


class DensitySequenceModel(nn.Module):
    """Observation-causal expected-distribution encoder with deterministic context.

    step: advance under PREVIOUS controls -> observe/update -> readout.
    A false event_mask advances time only; it cannot modify held controls or
    context. New sequences begin with dt=0. Forward returns expected counts
    under the legacy 'spikes' key; these are explicitly not sampled hard spikes.
    """
    def __init__(self,input_size=22,hidden_size=8,grid_size=16,refractory_phases=2,
                 method='matrix_exp',ablations:Iterable[str]=(),lower_bound=-2.,
                 sigma=.4,refractory=.1,reset=0.,fixed_boundary=1.25,
                 drift_scale=1.5,kick_scale=.35):
        super().__init__()
        self.input_size=int(input_size);self.hidden_size=int(hidden_size)
        self.ablations=frozenset(ablations);self.mode='expected_distribution'
        known={'no_rollover','collapse_maturity','shuffle_maturity','fixed_boundary','moment_collapse',
               'frozen_resource','numerical_kernel'}
        if self.ablations-known:
            raise ValueError(f'Unknown ablations: {self.ablations-known}')
        self.operator=DensityNeuronOperator(grid_size,refractory_phases,lower_bound,
                                            sigma,refractory,reset,method)
        self.input_layer=nn.Linear(input_size,hidden_size)
        self.recurrent_layer=nn.Linear(hidden_size,hidden_size,bias=False)
        nn.init.xavier_uniform_(self.input_layer.weight,gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight,gain=.25)
        self.fixed_boundary=float(fixed_boundary)
        self.drift_scale=float(drift_scale);self.kick_scale=float(kick_scale)

    def initial_state(self,batch_size,device=None,dtype=None):
        parameter=self.input_layer.weight
        device=parameter.device if device is None else device
        dtype=parameter.dtype if dtype is None else dtype
        context=torch.zeros(batch_size,self.hidden_size,device=device,dtype=dtype)
        boundary=torch.full_like(context,self.fixed_boundary)
        initial_resource=(torch.full((batch_size,1),-1.,device=device,dtype=dtype)
                          if 'frozen_resource' in self.ablations else None)
        return DensityState(self.operator.reset_distribution(boundary),context,
                            torch.zeros_like(context),boundary,initial_resource)

    def _pressure(self,observation):
        remaining=(4*observation[...,7:11]).clamp(min=0)
        alive=observation[...,11:15].clamp(0,1)
        if 'collapse_maturity' in self.ablations:
            mean=(remaining*alive).sum(-1,keepdim=True)/alive.sum(-1,keepdim=True).clamp(min=1)
            remaining=mean.expand_as(remaining)
        if 'shuffle_maturity' in self.ablations:
            order=torch.tensor([2,0,3,1],device=observation.device)
            remaining=remaining.index_select(-1,order);alive=alive.index_select(-1,order)
        pressure=alive/(remaining+.25)
        assignment=torch.arange(self.hidden_size,device=observation.device)%4
        return pressure.index_select(-1,assignment)

    def controls_from_observation(self,context,observation,resource_override=None):
        """Public deterministic controller, independent of probability/hard state."""
        updated=torch.tanh(self.input_layer(observation)+self.recurrent_layer(context))
        drift=self.drift_scale*torch.tanh(updated)
        kick=self.kick_scale*(updated-context)
        resource=observation[:,4:5].clamp(0,1) if resource_override is None else resource_override
        pressure=self._pressure(observation)
        rollover=.12*pressure*(.5+.5*updated.abs())
        if 'no_rollover' in self.ablations:
            rollover=torch.zeros_like(rollover)
        cost=.20+.30*(1-resource)+rollover
        if 'fixed_boundary' in self.ablations:
            boundary=torch.full_like(drift,self.fixed_boundary)
        else:
            boundary=frozen_control_boundary(drift,cost,self.operator.sigma,.4,self.operator.refractory).clamp(.55,2.25)
        return {'context':updated,'drift':drift,'boundary':boundary,'kick':kick}

    def step(self,state,observation,dt_elapsed,event_mask=True):
        p,count=self.operator.propagate(state.probability,dt_elapsed,state.drift,state.boundary,
                    method='uniformization' if 'numerical_kernel' in self.ablations else None)
        b=p.shape[0]
        mask=torch.as_tensor(event_mask,dtype=torch.bool,device=p.device)
        if mask.ndim==0:
            mask=mask.expand(b)
        if mask.shape!=(b,):
            raise ValueError('event_mask must be scalar or shape [B]')
        if not bool(mask.any()):
            updated=DensityState(p,state.context,state.drift,state.boundary,state.initial_resource)
            return updated,{'latent':self.operator.readout(p,state.boundary),'spikes':count,
                            'expected_counts':count,'immediate_counts':torch.zeros_like(count),
                            'probabilities':p,'drift':state.drift,'boundary':state.boundary,
                            'kick':torch.zeros_like(count)}
        if observation is None:
            raise ValueError('a true observation event requires features')
        observation=torch.where(mask[:,None],observation,torch.zeros_like(observation))
        resource=observation[:,4:5].clamp(0,1)
        initial_resource=state.initial_resource
        if initial_resource is not None:
            first=initial_resource<0
            initial_resource=torch.where(first & mask[:,None],resource,initial_resource)
            resource=torch.where(initial_resource<0,resource,initial_resource)
        controls=self.controls_from_observation(state.context,observation,resource)
        context=controls['context'];drift=controls['drift'];boundary=controls['boundary'];kick=controls['kick']
        remapped,immediate=self.operator.remap(p,state.boundary,boundary,kick)
        if 'moment_collapse' in self.ablations:
            remapped=self.operator.collapse_active_mean(remapped,boundary)
        p=torch.where(mask[:,None,None],remapped,p)
        context=torch.where(mask[:,None],context,state.context)
        drift=torch.where(mask[:,None],drift,state.drift)
        boundary=torch.where(mask[:,None],boundary,state.boundary)
        immediate=torch.where(mask[:,None],immediate,torch.zeros_like(immediate))
        kick=torch.where(mask[:,None],kick,torch.zeros_like(kick))
        count=count+immediate
        updated=DensityState(p,context,drift,boundary,initial_resource)
        return updated,{'latent':self.operator.readout(p,boundary),'spikes':count,
                        'expected_counts':count,'immediate_counts':immediate,
                        'probabilities':p,'drift':drift,'boundary':boundary,'kick':kick}

    def forward(self,x,dt,event_mask=None,generator=None,state=None):
        if x.ndim!=3 or x.shape[-1]!=self.input_size:
            raise ValueError('x must have shape [B,T,input_size]')
        batch,steps,_=x.shape
        dt=torch.as_tensor(dt,dtype=x.dtype,device=x.device)
        if dt.ndim==0:
            dt=dt.expand(batch,steps)
        elif dt.ndim==1:
            dt=dt.unsqueeze(0).expand(batch,-1)
        if dt.shape!=(batch,steps):
            raise ValueError('dt must be scalar, [T], or [B,T]')
        if state is None:
            if bool((dt[:,0]!=0).any()):
                raise ValueError('new sequences must observe their first frame at dt=0')
            state=self.initial_state(batch,x.device,x.dtype)
        if event_mask is None:
            event_mask=torch.ones(batch,steps,device=x.device,dtype=torch.bool)
        else:
            event_mask=torch.as_tensor(event_mask,dtype=torch.bool,device=x.device)
        history=[]
        for index in range(steps):
            state,out=self.step(state,x[:,index],dt[:,index],event_mask[:,index])
            history.append(out)
        result={key:torch.stack([out[key] for out in history],dim=1) for key in history[0]}
        result['final_latent']=result['latent'][:,-1]
        result['state']=state
        result['state_distribution']=result['probabilities']
        result['controls_tape']={'drift':result['drift'],'boundary':result['boundary'],
                                 'kick':result['kick'],'dt':dt,'event_mask':event_mask}
        result['probabilities_semantics']='complete CTMC state distribution, not firing probability'
        return result

    def state_accounting(self,batch_size=1,dtype_bytes=4):
        h=self.hidden_size;s=self.operator.state_size
        components={'probability':h*s,'deterministic_context':h,'held_drift':h,'held_boundary':h}
        if 'frozen_resource' in self.ablations:
            components['initial_resource']=1
        floats=sum(components.values())
        return {'components_in_scalars':components,'active_state_scalars_per_sequence':floats,
                'active_state_bytes_per_sequence':floats*dtype_bytes,
                'active_state_bytes_batch':floats*dtype_bytes*batch_size,
                'excluded':'parameters, outputs/history, matrix-exp workspace and training/autograd storage'}

    def metadata(self):
        op=self.operator
        return {'model':'causal_density_ctmc_v2','mode':self.mode,
                'input_size':self.input_size,'hidden_size':self.hidden_size,
                'grid_size':op.grid_size,'refractory_phases':op.refractory_phases,
                'state_size_per_neuron':op.state_size,'encoder_trainable_parameters':sum(p.numel() for p in self.parameters()),
                'propagator':op.method,'lower_bound':op.lower_bound,'sigma':op.sigma,
                'refractory_mean':op.refractory,'reset':op.reset,
                'ablations':sorted(self.ablations),'state_accounting':self.state_accounting(),
                'control':'deterministic observation-history context; no stochastic-state or density feedback',
                'latent':'E[tanh(physical_voltage)]; refractory states contribute tanh(reset); no count accumulator is held',
                'causality':'advance old controls, observe current event, remap, read out; dt[0]=0; no-op mask keeps controls',
                'maturity_branch':'each neuron assigned item h mod 4; shuffle only reassigns deadline/alive branch pairs',
                'accuracy_scope':'matrix exponential solves the finite CTMC, not the continuous diffusion; upwind spatial and Erlang approximations require convergence',
                'training':'ordinary autograd of finite CTMC expectation; no surrogate spike gradient',
                'deployment':'density expectation is not a sampled hard-spike network',
                'boundary':'Lambert-W frozen scalar heuristic with bounds, not solved full resource/maturity QVI'}
