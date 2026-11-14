"""Causal constant-current LIF comparators with analytic repeated firings.

Forward evolution uses the closed first crossing and inter-spike period of a
constant-current LIF, including exact refractory waits and exponential traces.
Hard event counts are integers. Backward uses explicitly biased smooth count
and threshold surrogates; this is not exact pathwise stochastic training.

The ALIF comparator refreshes its adaptive threshold at external observation
events and holds that threshold between observations. Its adaptation trace
continues to decay and receive spikes. This specified event-grid ALIF is NOT
a continuous-decaying-threshold ALIF or a full LSNN training reproduction.
Resource-LIF similarly holds a budget-observed threshold until the next event.
No-op time splits do not refresh context or either held threshold.
"""
from __future__ import annotations

import math
import torch
from torch import nn
from torch.nn import functional as F


def _hard_with_surrogate(hard,soft):
    # Parentheses keep the forward correction bitwise zero.
    return hard+(soft-soft.detach())


class CausalSpikingBaseline(nn.Module):
    def __init__(self,variant='lif',input_size=22,hidden_size=8,
                 membrane_tau=1.25,threshold=.65,refractory=.1,
                 trace_tau=2.5,adaptation_tau=3.,adaptation_strength=.3,
                 resource_penalty=.5,current_scale=1.8,kick_scale=.35,
                 surrogate_slope=5.):
        super().__init__()
        if variant not in ('lif','alif','resource_lif'):
            raise ValueError(variant)
        self.variant=variant;self.input_size=int(input_size);self.hidden_size=int(hidden_size)
        self.membrane_tau=float(membrane_tau);self.threshold=float(threshold)
        self.refractory=float(refractory);self.trace_tau=float(trace_tau)
        self.adaptation_tau=float(adaptation_tau);self.adaptation_strength=float(adaptation_strength)
        self.resource_penalty=float(resource_penalty);self.current_scale=float(current_scale)
        self.kick_scale=float(kick_scale);self.surrogate_slope=float(surrogate_slope)
        self.input_layer=nn.Linear(input_size,hidden_size)
        self.recurrent_layer=nn.Linear(hidden_size,hidden_size,bias=False)
        nn.init.xavier_uniform_(self.input_layer.weight,gain=.7)
        nn.init.zeros_(self.input_layer.bias)
        nn.init.orthogonal_(self.recurrent_layer.weight,gain=.25)

    def initial_state(self,batch_size,device=None,dtype=None):
        p=self.input_layer.weight
        device=p.device if device is None else device
        dtype=p.dtype if dtype is None else dtype
        zero=lambda:torch.zeros(batch_size,self.hidden_size,device=device,dtype=dtype)
        state={'voltage':zero(),'context':zero(),'refractory_remaining':zero(),'spike_trace':zero()}
        if self.variant=='alif':
            state['adaptation_trace']=zero()
        if self.variant!='lif':
            state['held_threshold']=torch.full_like(state['voltage'],self.threshold)
        return state

    def _advance(self,state,elapsed):
        v=state['voltage'];context=state['context'];ref=state['refractory_remaining']
        threshold=state.get('held_threshold',torch.full_like(v,self.threshold))
        current=self.current_scale*torch.tanh(context)
        wait=torch.minimum(elapsed,ref)
        available=(elapsed-ref).clamp(min=0)
        attainable=current>threshold
        # All inactive algebra stays finite; masks apply only after evaluation.
        denominator=(current-threshold).clamp(min=1e-7)
        numerator=(current-v).clamp(min=1e-7)
        first=self.membrane_tau*torch.log(numerator/denominator).clamp(min=0)
        first=torch.where(attainable,first,available+1.)
        cycle=self.refractory+self.membrane_tau*torch.log(current.clamp(min=1e-7)/denominator).clamp(min=0)
        cycle=cycle.clamp(min=max(self.refractory,1e-6))
        fires=attainable & (available>=first) & (available>0)
        hard_count=torch.where(fires,1.+torch.floor(((available-first)/cycle).clamp(min=0)),torch.zeros_like(v))
        no_reset_voltage=current+(v-current)*torch.exp(-available/self.membrane_tau)
        no_reset_voltage=torch.where(available>0,no_reset_voltage,v)
        soft_first=torch.sigmoid(self.surrogate_slope*(no_reset_voltage-threshold))
        soft_count=soft_first*(1.+F.relu((available-first)/cycle))
        soft_count=torch.where(available>0,soft_count,torch.zeros_like(soft_count))
        count=_hard_with_surrogate(hard_count,soft_count)
        last_time=wait+first+(hard_count-1.)*cycle
        after_last=torch.where(fires,(elapsed-last_time).clamp(min=0),torch.zeros_like(v))
        post_ref=(self.refractory-after_last).clamp(min=0)
        post_voltage=current*(-torch.expm1(-(after_last-self.refractory).clamp(min=0)/self.membrane_tau))
        voltage=torch.where(fires,post_voltage,no_reset_voltage)
        refractory_remaining=torch.where(fires,post_ref,(ref-elapsed).clamp(min=0))

        def event_trace(old,tau):
            # Geometric sum of all exact equally spaced event times. The count
            # surrogate affects gradients only; forward values use hard counts.
            ratio_denominator=(-torch.expm1(-cycle/tau)).clamp(min=1e-12)
            increments=torch.exp(-after_last/tau)*(-torch.expm1(-count*cycle/tau))/ratio_denominator
            return old*torch.exp(-elapsed/tau)+increments

        updated=dict(state)
        updated['voltage']=voltage;updated['refractory_remaining']=refractory_remaining
        updated['spike_trace']=event_trace(state['spike_trace'],self.trace_tau)
        if self.variant=='alif':
            updated['adaptation_trace']=event_trace(state['adaptation_trace'],self.adaptation_tau)
        return updated,count

    def _readout(self,state):
        return torch.tanh(state['voltage'])+.25*state['context']+.20*torch.tanh(state['spike_trace'])

    def step(self,state,observation,dt_elapsed,event_mask=True):
        v=state['voltage'];n=v.shape[0]
        elapsed=torch.as_tensor(dt_elapsed,device=v.device,dtype=v.dtype)
        if elapsed.numel()==1:
            elapsed=elapsed.expand(n)
        if elapsed.shape!=(n,):
            raise ValueError('elapsed time must be scalar or [B]')
        if bool((elapsed<0).any()):
            raise ValueError('negative elapsed time')
        elapsed=elapsed[:,None]
        mask=torch.as_tensor(event_mask,dtype=torch.bool,device=v.device)
        if mask.numel()==1:
            mask=mask.expand(n)
        if mask.shape!=(n,):
            raise ValueError('event_mask must be scalar or [B]')
        state,count=self._advance(state,elapsed)
        if not bool(mask.any()):
            return state,{'latent':self._readout(state),'spikes':count,
                          'immediate_counts':torch.zeros_like(count)}
        if observation is None:
            raise ValueError('a real observation event requires features')
        observation=torch.where(mask[:,None],observation,torch.zeros_like(observation))
        old_context=state['context']
        proposed=torch.tanh(self.input_layer(observation)+self.recurrent_layer(old_context))
        context=torch.where(mask[:,None],proposed,old_context)
        if self.variant=='alif':
            threshold=self.threshold+self.adaptation_strength*state['adaptation_trace']
        elif self.variant=='resource_lif':
            threshold=(self.threshold+self.resource_penalty*(1-observation[:,4:5].clamp(0,1))).expand_as(v)
        else:
            threshold=torch.full_like(v,self.threshold)
        available=(state['refractory_remaining']<=0) & mask[:,None]
        kick=self.kick_scale*(context-old_context)
        candidate=state['voltage']+torch.where(available,kick,torch.zeros_like(kick))
        hard=((candidate>=threshold)&available).to(v.dtype)
        soft=torch.sigmoid(self.surrogate_slope*(candidate-threshold))*available.to(v.dtype)
        immediate=_hard_with_surrogate(hard,soft)
        state=dict(state)
        state['context']=context
        state['voltage']=candidate*(1-immediate)
        state['refractory_remaining']=torch.where(hard.bool(),torch.full_like(v,self.refractory),state['refractory_remaining'])
        state['spike_trace']=state['spike_trace']+immediate
        if self.variant=='alif':
            state['adaptation_trace']=state['adaptation_trace']+immediate
            threshold=self.threshold+self.adaptation_strength*state['adaptation_trace']
        if self.variant!='lif':
            state['held_threshold']=torch.where(mask[:,None],threshold,state['held_threshold'])
        return state,{'latent':self._readout(state),'spikes':count+immediate,'immediate_counts':immediate}

    def forward(self,x,dt,event_mask=None,generator=None):
        if x.ndim!=3 or x.shape[-1]!=self.input_size:
            raise ValueError('x must be [B,T,input_size]')
        n,length,_=x.shape
        dt=torch.as_tensor(dt,dtype=x.dtype,device=x.device)
        if dt.shape!=(n,length):
            raise ValueError('dt must be [B,T]')
        if bool((dt[:,0]!=0).any()):
            raise ValueError('initial observation must have dt=0')
        if event_mask is None:
            event_mask=torch.ones(n,length,device=x.device,dtype=torch.bool)
        state=self.initial_state(n,x.device,x.dtype)
        outputs=[]
        for t in range(length):
            state,out=self.step(state,x[:,t],dt[:,t],event_mask[:,t])
            outputs.append(out)
        result={key:torch.stack([out[key] for out in outputs],dim=1) for key in outputs[0]}
        result['final_latent']=result['latent'][:,-1]
        result['final_state']=state
        return result

    def metadata(self):
        components={'voltage':self.hidden_size,'context':self.hidden_size,
                    'refractory_remaining':self.hidden_size,'spike_trace':self.hidden_size}
        if self.variant=='alif':
            components['adaptation_trace']=self.hidden_size
        if self.variant!='lif':
            components['held_threshold']=self.hidden_size
        scalars=sum(components.values())
        return {'model':'causal_analytic_interval_'+self.variant,'variant':self.variant,
                'hidden_size':self.hidden_size,'encoder_parameters':sum(p.numel() for p in self.parameters()),
                'persistent_state_components':components,'persistent_state_scalars':scalars,
                'persistent_state_bytes_float32':scalars*4,'shared_constant_buffer_bytes':0,
                'forward':'hard integer events; analytic constant-current LIF crossing/reset/refractory and repeated firing traces',
                'backward':'biased sigmoid/continuous-count surrogate; not exact stochastic path likelihood',
                'readout':'tanh(voltage)+0.25*context+0.20*tanh(spike_trace)',
                'event_semantics':'advance old current/threshold, observe, optional instantaneous kick/fire, readout; first dt=0',
                'adaptation_semantics':'ALIF trace decays/receives all spikes; threshold refreshed only at external observation events, held otherwise; not full continuous ALIF/LSNN',
                'resource_semantics':'resource-LIF threshold uses observed budget; no claim of measured energy or separate conserved neural budget',
                'constants':{'membrane_tau':self.membrane_tau,'threshold':self.threshold,'refractory':self.refractory,
                    'trace_tau':self.trace_tau,'adaptation_tau':self.adaptation_tau,'adaptation_strength':self.adaptation_strength,
                    'resource_penalty':self.resource_penalty,'current_scale':self.current_scale,'kick_scale':self.kick_scale,
                    'surrogate_slope':self.surrogate_slope},
                'state_excludes':'parameters, common readout, inputs/outputs/history, temporaries and task environment'}
