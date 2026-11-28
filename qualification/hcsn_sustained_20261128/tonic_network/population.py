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
    def __init__(self,input_size,width,atoms=12,dt=.25,reset=.30,probe_horizons=(.08,.125,.5,3.),matrix_free=False,cache_prices=False,initial_physical_gain=None):
        super().__init__()
        self.matrix_free=matrix_free
        self.cache_prices=cache_prices
        if initial_physical_gain is not None and not math.isfinite(initial_physical_gain):
            raise ValueError('physical drift gain must be finite')
        gain=None if initial_physical_gain is None else torch.full((width,),float(initial_physical_gain),dtype=torch.float64)
        self.register_parameter("physical_gain",None if gain is None else nn.Parameter(gain))
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
    def physical_passage(self,x,horizon,mu):
        if mu is None:
            return self.prices.passage(x,horizon)
        width=self.prices.p.sigma*math.sqrt(horizon)
        log_weight=-2*mu*x/self.prices.var
        direct=torch.special.ndtr((-x-mu*horizon)/width)
        image=torch.exp(log_weight+torch.special.log_ndtr((-x+mu*horizon)/width))
        return direct+image

    def kernels(self,margin,mu=None):
        x=margin.clamp_min(0)
        s=self.prices.p.sigma*math.sqrt(self.dt)
        drift=self.prices.mu*self.dt if mu is None else mu*self.dt
        a=self.prices.a if mu is None else mu/self.prices.var
        downweight=torch.exp(-2*a*x)
        def cumulative(mean):
            at=torch.special.ndtr((self.cuts-mean[...,None])/s)
            zero=torch.special.ndtr(-mean/s)[...,None]
            return torch.cat((zero,at,torch.ones_like(zero)),dim=-1)
        free=cumulative(x+drift).diff(dim=-1)
        mirror=cumulative(-x+drift).diff(dim=-1)
        surv=(free-downweight[...,None]*mirror).clamp_min(0)
        surv=torch.where((margin>0)[...,None],surv,torch.zeros_like(surv))
        hit=torch.where(margin>0,self.physical_passage(x,self.dt,mu),torch.ones_like(x))
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
    def _price_basis(self):
        # At a fixed log-margin grid, both published prices are affine in
        # nominal principal. Build per forward pass so edits to grid, law
        # buffers, dtype/device and loaded checkpoints take effect immediately.
        center = self.prices.p.P0
        span = max(1., abs(center) * .28)
        anchors = self.grid.new_tensor([center-span, center+span])
        equity, loss = self.priced_channels(anchors)
        return anchors, equity, loss

    def step(self,frame,state,price_basis=None):
        frame=frame.to(self.sender.weight)
        mass,refractory,old_b,old_value=state
        u=self.sender(frame)+self.recurrent(old_b)+(old_value.tanh()*self.feedback).sum(-1)
        P=self.prices.p.P0*(1+.28*u.tanh());b=torch.log(self.prices.boundary(P)/self.prices.B0)
        mu=None if self.physical_gain is None else (self.prices.mu-self.physical_gain*u.tanh())[...,None]
        if self.matrix_free:
            from fft_transport import transported_mass
            newmass,flow=transported_mass(mass,old_b-b,self.grid,
                sigma=self.prices.p.sigma,a=self.prices.a if mu is None else mu/self.prices.var,dt=self.dt)
        else:
            margin=self.grid+old_b[...,None]-b[...,None]
            surv,hit=self.kernels(margin,mu)
            flow=(mass*hit).sum(-1)
            newmass=(mass[...,None]*surv).sum(-2)
        newmass=newmass+refractory[...,None]*self.reset_weights
        if price_basis is None:
            E,L=self.priced_channels(P)
        else:
            anchors,equity,loss=price_basis
            fraction=(P[...,None]-anchors[0])/(anchors[1]-anchors[0])
            E=torch.lerp(equity[0],equity[1],fraction)
            L=torch.lerp(loss[0],loss[1],fraction)
        v=torch.stack([(newmass*E).sum(-1)/20.,(newmass*L).sum(-1)/20.],dim=-1)
        probes=[(newmass*self.physical_passage(self.grid,t,mu)).sum(-1) for t in self.probe_horizons]
        transmitted=torch.stack([b,flow,v[...,0],v[...,1],*probes],dim=-1)
        return transmitted,(newmass,flow,b,v)
    def forward(self,frames,state=None):
        if frames.ndim!=3 or frames.shape[0]==0: raise ValueError('expected nonempty [time,batch,channel] input')
        if state is None:state=self.initial(frames.size(1))
        outputs=[]
        price_args=(self._price_basis(),) if self.cache_prices else ()
        for frame in frames:
            message,state=self.step(frame,state,*price_args);outputs.append(message)
        return torch.stack(outputs),state

class ContinuousSpikingNetwork(nn.Module):
    def __init__(self,input_size,width,outputs,atoms=12,port='augmented',matrix_free=False,cache_prices=False,initial_physical_gain=None):
        super().__init__()
        if port not in ('boundary','priced','augmented'):raise ValueError('unknown message port')
        self.port=port
        self.first=BoundaryPopulation(input_size,width,atoms,matrix_free=matrix_free,cache_prices=cache_prices,initial_physical_gain=initial_physical_gain)
        channels={'boundary':1,'priced':4,'augmented':4+len(self.first.probe_horizons)}[port]
        self.second=BoundaryPopulation(width*channels,width,atoms,matrix_free=matrix_free,cache_prices=cache_prices,initial_physical_gain=initial_physical_gain)
        self.head=nn.Linear(width*(4+len(self.second.probe_horizons)),outputs,dtype=torch.float64)
        self.channels=channels
    def forward(self,frames,state=None):
        s1,s2=(None,None) if state is None else state
        sender,s1=self.first(frames,s1)
        receiver,s2=self.second(sender[...,:self.channels].flatten(-2),s2)
        return self.head(receiver.flatten(-2)),(s1,s2)
