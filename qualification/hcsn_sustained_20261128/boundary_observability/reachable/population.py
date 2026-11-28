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
    def __init__(self,input_size,width,atoms=12,dt=.25,reset=.30,probe_horizons=(.08,.125,.5,3.),matrix_free=False,cache_prices=False,initial_physical_gain=None,boundary_path="step",signed_force_gains=None,initial_flow_coupling=None):
        super().__init__()
        if boundary_path not in ("step", "linear_log"):
            raise ValueError("boundary_path must be step or linear_log")
        self.boundary_path=boundary_path
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
        if initial_flow_coupling is not None and not math.isfinite(initial_flow_coupling):
            raise ValueError("flow-to-boundary coupling must be finite")
        coupling = None if initial_flow_coupling is None else nn.Parameter(
            torch.full((width,),float(initial_flow_coupling),dtype=torch.float64))
        self.register_parameter("flow_coupling",coupling)
        self.signed_forces = signed_force_gains is not None
        if self.signed_forces:
            gains = torch.as_tensor(signed_force_gains, dtype=torch.float64)
            if gains.shape != (2,) or not torch.isfinite(gains).all() or (gains <= 0).any():
                raise ValueError("signed_force_gains requires two finite positive gains")
            initial_feedback = gains + torch.log(-torch.expm1(-gains))
        else:
            initial_feedback = torch.tensor([.15,.15], dtype=torch.float64)
        self.feedback = nn.Parameter(initial_feedback.repeat(width,1))

    def signed_drift(self, mass, previous_values):
        alive = mass.sum(-1)
        reset = (self.grid * self.reset_weights).sum()
        conditional = (mass * self.grid).sum(-1) / torch.where(alive > 0, alive, 1.)
        margin = torch.where(alive > 0, conditional, reset)
        strength = torch.nn.functional.softplus(self.feedback)
        channels = previous_values.clamp_min(0).tanh() * strength
        return channels[..., 0] * (reset - margin) - channels[..., 1]
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
    def ramp_transport(self,mass,relative_mu):
        # Contract bounded blocks in probability space. Integrate each reflected
        # Gaussian in log space before multiplying by the potentially large tilt.
        scale=self.prices.p.sigma*math.sqrt(self.dt)
        variance=self.prices.var
        def bins(mean):
            lower=(torch.cat((self.cuts.new_zeros(1),self.cuts[:-1]))-mean[...,None])/scale
            upper=(self.cuts-mean[...,None])/scale
            right=lower>0
            far=torch.where(right,-upper,lower)
            near=torch.where(right,-lower,upper)
            lfar=torch.special.log_ndtr(far);lnear=torch.special.log_ndtr(near)
            inside=lnear+torch.log(-torch.expm1(lfar-lnear))
            tail=torch.special.log_ndtr((mean-self.cuts[-1])/scale)[...,None]
            return torch.cat((inside,tail),dim=-1)
        survivor=torch.zeros_like(mass)
        flow=torch.zeros_like(mass[...,0])
        for start in range(0,len(self.grid),32):
            x=self.grid[start:start+32]
            drift=relative_mu*self.dt
            log_weight=-2*relative_mu*x/variance
            ldirect=bins(x+drift)
            lref=bins(-x+drift)+log_weight[...,None]
            # Killed density is nonnegative. Roundoff can reverse its sign in extreme tails.
            delta=(lref-ldirect).clamp_max(0)
            alive=torch.exp(ldirect)*(-torch.expm1(delta))
            part=mass[...,start:start+32]
            survivor=survivor+(part[...,None]*alive).sum(-2)
            flow=flow+(part*self.physical_passage(x,self.dt,relative_mu)).sum(-1)
        return survivor,flow

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
        u=self.sender(frame)+self.recurrent(old_b)
        if self.flow_coupling is not None:
            u=u+self.flow_coupling*refractory
        if not self.signed_forces:
            u=u+(old_value.tanh()*self.feedback).sum(-1)
        P=self.prices.p.P0*(1+.28*u.tanh());b=torch.log(self.prices.boundary(P)/self.prices.B0)
        mu=None if self.physical_gain is None else (self.prices.mu-self.physical_gain*u.tanh())[...,None]
        if self.signed_forces:
            baseline = self.prices.mu if mu is None else mu.squeeze(-1)
            mu = (baseline + self.signed_drift(mass,old_value))[...,None]
        shift=old_b-b
        transport_mu=mu
        if self.boundary_path=="linear_log":
            # In the moving frame a linear log-boundary adds a constant relative drift.
            physical_mu=self.prices.mu if mu is None else mu
            transport_mu=physical_mu+shift[...,None]/self.dt
            shift=torch.zeros_like(shift)
        use_fft=self.matrix_free
        if self.boundary_path=="linear_log" and use_fft:
            # A strongly inward relative drift can amplify FFT roundoff through
            # the reflected image. Fall back before its worst-case amplification
            # spends more than about one third of this dtype's precision.
            max_log_weight=(-2*transport_mu.detach()*self.grid[-1]/self.prices.var).amax()
            use_fft=bool(max_log_weight < -math.log(torch.finfo(self.grid.dtype).eps)/3)
        if use_fft:
            from fft_transport import transported_mass
            newmass,flow=transported_mass(mass,shift,self.grid,
                sigma=self.prices.p.sigma,a=self.prices.a if transport_mu is None else transport_mu/self.prices.var,dt=self.dt)
        elif self.boundary_path=="linear_log":
            newmass,flow=self.ramp_transport(mass,transport_mu)
        else:
            margin=self.grid+old_b[...,None]-b[...,None]
            surv,hit=self.kernels(margin,transport_mu)
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
    def __init__(self,input_size,width,outputs,atoms=12,port='augmented',matrix_free=False,cache_prices=False,initial_physical_gain=None,boundary_path="step",signed_force_gains=None,initial_flow_coupling=None):
        super().__init__()
        if port not in ('boundary','priced','augmented'):raise ValueError('unknown message port')
        self.port=port
        self.first=BoundaryPopulation(input_size,width,atoms,matrix_free=matrix_free,cache_prices=cache_prices,initial_physical_gain=initial_physical_gain,boundary_path=boundary_path,signed_force_gains=signed_force_gains,initial_flow_coupling=initial_flow_coupling)
        channels={'boundary':1,'priced':4,'augmented':4+len(self.first.probe_horizons)}[port]
        self.second=BoundaryPopulation(width*channels,width,atoms,matrix_free=matrix_free,cache_prices=cache_prices,initial_physical_gain=initial_physical_gain,boundary_path=boundary_path,signed_force_gains=signed_force_gains,initial_flow_coupling=initial_flow_coupling)
        self.head=nn.Linear(width*(4+len(self.second.probe_horizons)),outputs,dtype=torch.float64)
        self.channels=channels
    def forward(self,frames,state=None):
        s1,s2=(None,None) if state is None else state
        sender,s1=self.first(frames,s1)
        receiver,s2=self.second(sender[...,:self.channels].flatten(-2),s2)
        return self.head(receiver.flatten(-2)),(s1,s2)
