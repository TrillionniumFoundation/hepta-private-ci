"""Common action readout and optional correctly scored sampled-state training."""
from __future__ import annotations

import torch
from torch import nn

from .density_model import DensitySequenceModel, DensityState
from .causal_baselines import CausalTimeBasisRNN
from .spiking_baselines import CausalSpikingBaseline

VARIANTS = {
    'rr_density': (),
    'rr_fixed': ('fixed_boundary',),
    'rr_no_rollover': ('no_rollover',),
    'rr_moment_collapse': ('moment_collapse',),
    'rr_collapse_maturity': ('collapse_maturity',),
    'rr_shuffle_maturity': ('shuffle_maturity',),
    'rr_frozen_resource': ('frozen_resource',),
    'ctrnn': None,
    'ctrnn_matched': None,
    'lif': None,
    'alif': None,
    'resource_lif': None,
}


class Policy(nn.Module):
    def __init__(self, variant, hidden=8, grid_size=16, phases=2):
        super().__init__()
        if variant not in VARIANTS:
            raise ValueError(variant)
        self.variant = variant
        self.is_density = VARIANTS[variant] is not None
        if self.is_density:
            self.encoder = DensitySequenceModel(hidden_size=hidden, grid_size=grid_size,
                    refractory_phases=phases, ablations=VARIANTS[variant])
        elif variant in ('lif','alif','resource_lif'):
            self.encoder=CausalSpikingBaseline(variant,hidden_size=hidden)
        else:
            # Density state is H*(S+3); RNN state is H*(modes+1).
            modes = grid_size+phases+2 if variant == 'ctrnn_matched' else 1
            self.encoder = CausalTimeBasisRNN(hidden_size=hidden, modes=modes)
        self.head = nn.Linear(hidden, 81)

    def initial_state(self, batch_size, device=None, dtype=torch.float32):
        return self.encoder.initial_state(batch_size,device=device,dtype=dtype)

    def step(self,state,observation,dt_elapsed,event_mask=True,generator=None,sampled=False):
        state,out = self.encoder.step(state,observation,dt_elapsed,event_mask)
        if sampled:
            if not self.is_density:
                raise ValueError('Sampled state mode applies to finite CTMC models only')
            # Marginalize all within-interval jumps with exp(Q dt), then sample
            # the endpoint. This is exact for the finite CTMC at observations
            # up to the explicitly checked floating-point corrections. It is
            # not a timestamp-producing sampler (that is independently tested).
            p = state.probability
            if bool((p < -1e-5).any()) or bool((p.sum(-1)-1).abs().max()>2e-4):
                raise FloatingPointError('CTMC probability outside allowed numerical tolerance')
            normalized = p.clamp(min=0)
            normalized = normalized/normalized.sum(-1,keepdim=True)
            index = torch.multinomial(normalized.reshape(-1,normalized.shape[-1]),1,
                                      generator=generator).reshape(normalized.shape[:-1])
            score = normalized.gather(-1,index[...,None]).squeeze(-1).clamp(min=1e-30).log().sum(-1)
            sampled_p = torch.nn.functional.one_hot(index,normalized.shape[-1]).to(p).detach()
            state = DensityState(sampled_p,state.context,state.drift,state.boundary,state.initial_resource)
            out = dict(out)
            out['latent'] = self.encoder.operator.readout(sampled_p,state.boundary)
            out['transition_log_probability'] = score
            out['sampled_index'] = index
            out['maximum_probability_correction'] = (normalized-p).abs().max()
        out['logits'] = self.head(out['latent'])
        return state,out

    def forward(self,x,dt,event_mask=None,generator=None,sampled=False):
        if not sampled:
            result=self.encoder(x,dt,event_mask=event_mask,generator=generator)
            result['logits']=self.head(result['latent'])
            return result
        if bool((dt[:,0]!=0).any()):
            raise ValueError('Initial observation must have zero elapsed time')
        n,t,_=x.shape
        if event_mask is None:
            event_mask=torch.ones(n,t,device=x.device,dtype=torch.bool)
        state=self.initial_state(n,x.device,x.dtype)
        outputs=[]
        for i in range(t):
            state,out=self.step(state,x[:,i],dt[:,i],event_mask[:,i],generator,sampled=True)
            outputs.append(out)
        result={k:torch.stack([o[k] for o in outputs],dim=1)
                for k in ['latent','logits','expected_counts','transition_log_probability','sampled_index']}
        result['maximum_probability_correction']=torch.stack([o['maximum_probability_correction'] for o in outputs]).max()
        return result

    def metadata(self):
        result=self.encoder.metadata()
        result.update({'variant':self.variant,'parameters_including_head':sum(p.numel() for p in self.parameters()),
                       'output_size':81,'common_head':True})
        if self.is_density:
            result['persistent_state_bytes_float32']=result['state_accounting']['active_state_bytes_per_sequence']
        return result


def set_nll_per_decision(logits,valid,optimal):
    denominator=torch.logsumexp(logits.masked_fill(~valid,-1e9),dim=-1)
    numerator=torch.logsumexp(logits.masked_fill(~optimal,-1e9),dim=-1)
    return denominator-numerator


def expected_loss(logits,valid,optimal,decision):
    return set_nll_per_decision(logits,valid,optimal)[decision].mean()


def sampled_state_objective(output,valid,optimal,decision):
    """Unbiased likelihood-ratio estimator for the sampled trajectory objective.

    Loss = E_z[sum decision NLL], on externally supplied demonstration inputs.
    Includes the direct derivative of NLL plus the transition-path score. A
    leave-one-sequence-out baseline is independent of each sequence's samples.
    It has stochastic variance, but does not silently use a surrogate gradient.
    This is an observed-state CTMC objective, not a spike-time likelihood loss.
    """
    nll=set_nll_per_decision(output['logits'],valid,optimal)
    totals=(nll*decision).sum(-1)
    count=decision.sum().clamp(min=1)
    log_path=output['transition_log_probability'].sum(-1)
    if totals.shape[0]>1:
        baseline=(totals.detach().sum()-totals.detach())/(totals.shape[0]-1)
    else:
        baseline=torch.zeros_like(totals)
    # The score term has the desired derivative. Subtract its detached value
    # so the reported forward loss remains the ordinary sampled NLL.
    score=((totals.detach()-baseline)*log_path).sum()/count
    objective=totals.sum()/count+score-score.detach()
    return objective
