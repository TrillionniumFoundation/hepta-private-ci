"""Causal free-boundary population layer with priced channels, first-passage mass and a refractory compartment.

The financial coefficients are frozen within one interval. Inputs move each neuron's stationary
continuation boundary between intervals. The killed transition integrates probabilities exactly
over output bins, then places each surviving bin's mass at its grid representative. This last
spatial approximation and the one-tick refractory reset are neural modelling choices.
"""
import math
import torch
from torch import nn
from he_xiong import Published

class BoundaryPopulation(nn.Module):
    def __init__(self,input_size,width,atoms=12,dt=.25,reset=.30,probe_horizons=(.08,.125,.5,3.)):
        super().__init__()
        if atoms<3 or width<1 or dt<=0 or not 0<reset<1.30 or any(t<=0 for t in probe_horizons):
            raise ValueError('invalid population geometry or horizon')
        self.width=width; self.dt=float(dt); self.probe_horizons=tuple(probe_horizons)
        grid=torch.linspace(.015,1.30,atoms,dtype=torch.float64)
        self.register_buffer('grid',grid)
        self.register_buffer('cuts',.5*(grid[:-1]+grid[1:]))
        # Preserve the mass and first moment of a reset by interpolation onto adjacent atoms.
        if reset<grid[0] or reset>grid[-1]: raise ValueError('reset outside grid')
        k=int(torch.searchsorted(grid,torch.tensor(reset,dtype=grid.dtype),right=True).clamp(1,atoms-1))
        w=torch.zeros_like(grid);w[k]=(reset-grid[k-1])/(grid[k]-grid[k-1]);w[k-1]=1-w[k]
        self.register_buffer('reset_weights',w)
        self.prices=Published()
        self.sender=nn.Linear(input_size,width,dtype=torch.float64)
        self.recurrent=nn.Linear(width,width,bias=False,dtype=torch.float64)
        self.feedback=nn.Parameter(torch.tensor([.15,.15],dtype=torch.float64).repeat(width,1))
    def initial(self,batch):
        zero=self.grid.new_zeros(batch,self.width)
        return (self.reset_weights.expand(batch,self.width,-1),zero,zero,zero.unsqueeze(-1).expand(-1,-1,2))
    def kernels(self,margin):
        x=margin.clamp_min(0)
        s=self.prices.p.sigma*math.sqrt(self.dt);drift=self.prices.mu*self.dt
        downweight=torch.exp(-2*self.prices.a*x)
        def cumulative(mean):
            at=torch.special.ndtr((self.cuts-mean[...,None])/s)
            zero=torch.special.ndtr(-mean/s)[...,None]
            return torch.cat((zero,at,torch.ones_like(zero)),dim=-1)
        free=cumulative(x+drift).diff(dim=-1)
        mirror=cumulative(-x+drift).diff(dim=-1)
        surv=(free-downweight[...,None]*mirror).clamp_min(0)
        surv=torch.where((margin>0)[...,None],surv,torch.zeros_like(surv))
        hit=torch.where(margin>0,self.prices.passage(x,self.dt),torch.ones_like(x))
        return surv,hit
    def priced_channels(self,P):
        p=self.prices;x=self.grid.expand(*P.shape,-1);principal=P[...,None].expand_as(x)
        E=p.equity(x,principal)
        def hit(y):
            s=p.p.sigma*math.sqrt(p.p.m);shift=y*p.var*p.p.m
            return torch.exp(-(p.a-y)*x)*torch.special.ndtr((-x-shift)/s)+torch.exp(-(p.a+y)*x)*torch.special.ndtr((-x+shift)/s)
        F=hit(p.a);G=hit(p.zb);B=p.boundary(principal)
        L=p.disc*(principal/p.p.m-p.c/p.q)*F+(p.c/p.q-p.p.alpha*B/p.p.m)*G
        return E,L
    def step(self,frame,state):
        frame=frame.to(self.sender.weight)
        mass,refractory,old_b,old_value=state
        u=self.sender(frame)+self.recurrent(old_b)+(old_value.tanh()*self.feedback).sum(-1)
        P=self.prices.p.P0*(1+.28*u.tanh());b=torch.log(self.prices.boundary(P)/self.prices.B0)
        margin=self.grid+old_b[...,None]-b[...,None]
        surv,hit=self.kernels(margin)
        flow=(mass*hit).sum(-1)
        newmass=(mass[...,None]*surv).sum(-2)+refractory[...,None]*self.reset_weights
        E,L=self.priced_channels(P)
        v=torch.stack([(newmass*E).sum(-1)/20.,(newmass*L).sum(-1)/20.],dim=-1)
        probes=[(newmass*self.prices.passage(self.grid,t)).sum(-1) for t in self.probe_horizons]
        transmitted=torch.stack([b,flow,v[...,0],v[...,1],*probes],dim=-1)
        return transmitted,(newmass,flow,b,v)
    def forward(self,frames,state=None):
        if frames.ndim!=3 or frames.shape[0]==0: raise ValueError('expected nonempty [time,batch,channel] input')
        if state is None:state=self.initial(frames.size(1))
        outputs=[]
        for frame in frames:
            message,state=self.step(frame,state);outputs.append(message)
        return torch.stack(outputs),state

class ContinuousSpikingNetwork(nn.Module):
    def __init__(self,input_size,width,outputs,atoms=12,port='augmented'):
        super().__init__()
        if port not in ('boundary','priced','augmented'):raise ValueError('unknown message port')
        self.port=port
        self.first=BoundaryPopulation(input_size,width,atoms)
        channels={'boundary':1,'priced':4,'augmented':4+len(self.first.probe_horizons)}[port]
        self.second=BoundaryPopulation(width*channels,width,atoms)
        self.head=nn.Linear(width*(4+len(self.second.probe_horizons)),outputs,dtype=torch.float64)
        self.channels=channels
    def forward(self,frames,state=None):
        s1,s2=(None,None) if state is None else state
        sender,s1=self.first(frames,s1)
        receiver,s2=self.second(sender[...,:self.channels].flatten(-2),s2)
        return self.head(receiver.flatten(-2)),(s1,s2)
