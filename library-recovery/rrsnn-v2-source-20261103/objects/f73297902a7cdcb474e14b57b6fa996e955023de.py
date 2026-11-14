"""A stronger continuous-time RNN within the RR parameter/state envelope.

96 float32 state scalars = 384 active bytes. 1984 trainable parameters including
the 81-action head, versus RR's 2001 parameters and 384 active state bytes.
The update is exponential relaxation to a frozen nonlinear target on each
observation interval, not a claim of an exact global nonlinear-ODE solution.
"""
from __future__ import annotations

import torch
from torch import nn


class BudgetMatchedCTRNN(nn.Module):
    def __init__(self,input_size=22,hidden_size=96,in_rank=4,readout_rank=7,
                 output_size=81,tau=1.25):
        super().__init__()
        self.input_size=int(input_size)
        self.hidden_size=int(hidden_size)
        self.output_size=int(output_size)
        self.tau=float(tau)
        self.input_factor=nn.Linear(input_size,in_rank,bias=False)
        self.input_expand=nn.Linear(in_rank,hidden_size,bias=False)
        self.recurrent_diagonal=nn.Parameter(torch.full((hidden_size,),0.10))
        self.state_bias=nn.Parameter(torch.zeros(hidden_size))
        self.readout_factor=nn.Linear(hidden_size,readout_rank,bias=False)
        self.readout_expand=nn.Linear(readout_rank,output_size,bias=True)
        nn.init.xavier_uniform_(self.input_factor.weight,gain=0.8)
        nn.init.xavier_uniform_(self.input_expand.weight,gain=0.8)
        nn.init.xavier_uniform_(self.readout_factor.weight,gain=0.8)
        nn.init.xavier_uniform_(self.readout_expand.weight,gain=0.8)
        nn.init.zeros_(self.readout_expand.bias)

    def state_accounting(self,batch_size=1,dtype_bytes=4):
        return {
            'trainable_parameters':sum(p.numel() for p in self.parameters()),
            'head_included':True,
            'state_scalars_per_sequence':self.hidden_size,
            'active_state_bytes_per_sequence':self.hidden_size*dtype_bytes,
            'active_state_bytes_batch':self.hidden_size*dtype_bytes*batch_size,
            'state_components':{'continuous_hidden':self.hidden_size},
            'excludes':'input, outputs, autograd tape, temporary matrix products',
        }

    def metadata(self):
        return {'variant':'ctrnn_budget_matched','is_cfc':False,
                'accounting':self.state_accounting(),
                'parameter_comparison':'1984 vs RR 2001; 17 fewer (0.8496%), not exactly equal',
                'state_comparison':'96 float32 active state scalars, equal to RR 384-byte active state budget',
                'limitations':['Frozen nonlinear target per observation interval.',
                               'CPU timing includes head; compare to complete RR model, not encoder alone.']}

    def forward(self,x,dt=1.0,generator=None):
        b,t,f=x.shape
        if f!=self.input_size:
            raise ValueError('input feature dimension mismatch')
        durations=torch.as_tensor(dt,dtype=x.dtype,device=x.device)
        if durations.ndim==0:
            durations=durations.expand(b,t)
        elif durations.ndim==1:
            durations=durations.unsqueeze(0).expand(b,t)
        if durations.shape!=(b,t) or bool(torch.any(durations<0)):
            raise ValueError('dt must be nonnegative and scalar/[T]/[B,T]')
        projected=self.input_expand(self.input_factor(x))
        state=x.new_zeros((b,self.hidden_size))
        diagonal=torch.tanh(self.recurrent_diagonal)
        history=[]
        for step in range(t):
            duration=durations[:,step:step+1]
            duration=torch.where(duration>0,duration,torch.full_like(duration,0.05))
            decay=torch.exp(-duration/self.tau)
            target=torch.tanh(projected[:,step]+diagonal*state+self.state_bias)
            state=decay*state+(1-decay)*target
            history.append(state)
        latent=torch.stack(history,dim=1)
        logits=self.readout_expand(self.readout_factor(latent))
        return {'latent':latent,'final_latent':state,'logits':logits,
                'spikes':torch.zeros_like(latent)}

