"""Separate the stochastic neuronal drift from the He–Xiong pricing drift."""
import math

import torch
from torch import nn

from affine_ports import AffineBoundaryPopulation


class DriftBoundaryPopulation(AffineBoundaryPopulation):
    """Preserve financial E/L pricing while modulating the firing first-passage law."""
    def __init__(self,input_size,width,atoms=12,dt=.25,reset=.30,max_drift_shift=.30):
        super().__init__(input_size,width,atoms=atoms,dt=dt,reset=reset)
        if max_drift_shift<=0:raise ValueError('max_drift_shift must be positive')
        self.max_drift_shift=float(max_drift_shift)
        self.physical_drive=nn.Linear(input_size,width,dtype=torch.float64)
        nn.init.zeros_(self.physical_drive.weight)
        nn.init.zeros_(self.physical_drive.bias)

    def physical_hit(self,margin,mu,t):
        x=margin.clamp_min(0);sig=self.prices.p.sigma;s=sig*math.sqrt(t)
        alpha=torch.special.log_ndtr((-x-mu*t)/s)
        beta=(-2*mu*x/sig**2)+torch.special.log_ndtr((-x+mu*t)/s)
        value=torch.logaddexp(alpha,beta).exp().clamp(max=1.)
        return torch.where(margin>0,value,torch.ones_like(value))

    def live_transition(self,margin,mu):
        x=margin.clamp_min(0);sigma=self.prices.p.sigma
        s=sigma*math.sqrt(self.dt);drift=mu*self.dt
        def intervals(mean):
            low=torch.special.ndtr(-mean/s).unsqueeze(-1)
            cut=torch.special.ndtr((self.cuts-mean.unsqueeze(-1))/s)
            return torch.cat([low,cut,torch.ones_like(low)],-1).diff(dim=-1)
        multiplier=torch.exp(-2*mu*x/(sigma*sigma))
        survival=(intervals(x+drift)-multiplier.unsqueeze(-1)*intervals(-x+drift)).clamp_min(0)
        survivor=torch.where((margin>0).unsqueeze(-1),survival,torch.zeros_like(survival))
        return survivor,self.physical_hit(margin,mu,self.dt)

    def step(self,frame,state):
        frame=frame.to(self.sender.weight)
        mass,ref,old,prices=state
        drive=self.sender(frame)+self.recurrent(old)+(prices.tanh()*self.feedback).sum(-1)
        physical_mu=self.prices.mu+self.max_drift_shift*self.physical_drive(frame).tanh()
        principal=self.prices.p.P0*(1+.28*drive.tanh())
        b=(self.prices.boundary(principal)/self.prices.B0).log()
        margin=self.grid+(old-b).unsqueeze(-1)
        mu=physical_mu.unsqueeze(-1)
        transition,hit=self.live_transition(margin,mu)
        flow=(mass*hit).sum(-1)
        newmass=(mass.unsqueeze(-2)@transition).squeeze(-2)+ref.unsqueeze(-1)*self.reset_weights
        E,L=self.priced_channels(principal)
        EL=torch.stack([(newmass*E).sum(-1)/20,(newmass*L).sum(-1)/20],-1)
        probes=[(newmass*self.physical_hit(self.grid,mu,t)).sum(-1) for t in self.probe_horizons]
        msg=torch.stack([b,flow,EL[...,0],EL[...,1],*probes],-1)
        return msg,(newmass,flow,b,EL)
