"""Differentiable finite-volume renewal CTMC, not an exact Brownian solver.

All evolving state mass is retained. Matrix exponentials include any number of
boundary/recovery/reset cycles within an external interval. Exponential recovery
is memoryless, so a distribution over the two refractory modes is sufficient;
this does not represent arbitrary age-dependent refractory durations.
"""
import math
import torch
from torch import nn

VERSION='joint-fv-renewal-ctmc-v1'
RAW_NAMES=('boundary','diffusion','gain','drift_bias','reset_plus','reset_minus','recovery_rate','reset_sd')
HORIZONS=(.25,.75,1.5)
THRESHOLDS=(-.5,0.,.5)


def normal_cdf(x):return .5*torch.erfc(-x/math.sqrt(2))


def normal_interval(lower,upper):
    lower,upper=torch.broadcast_tensors(lower,upper)
    right=lower>=0
    a,b=torch.where(right,-upper,lower),torch.where(right,-lower,upper)
    small,big=torch.special.log_ndtr(a),torch.special.log_ndtr(b)
    return torch.exp(big)*(-torch.expm1(small-big))


def basis(n_grid,mode,dtype=torch.float64,device=None):
    if not isinstance(n_grid,int) or n_grid<31 or n_grid%2!=1:
        raise ValueError('odd n_grid>=31 is required for the declared positive-rate envelope')
    if mode not in ('renewal','ordinary'):raise ValueError('unknown CTMC mode')
    n=n_grid+2;up=torch.zeros(n,n,dtype=dtype,device=device);down=torch.zeros_like(up)
    for i in range(n_grid):
        if i<n_grid-1 or mode=='renewal':
            up[i,i]=-1;up[i,i+1 if i<n_grid-1 else n_grid+1]=1
        if i>0 or mode=='renewal':
            down[i,i]=-1;down[i,i-1 if i else n_grid]=1
    return up,down


def validate_physical(p):
    keys=('boundary','diffusion','drift','reset_plus','reset_minus','recovery_rate','reset_sd')
    reference=next((p[k] for k in keys if torch.is_tensor(p[k])),None)
    device=reference.device if reference is not None else None
    values=torch.broadcast_tensors(*[torch.as_tensor(p[k],dtype=torch.float64,device=device) for k in keys])
    if any(not bool(torch.isfinite(x.detach()).all()) for x in values):raise ValueError('finite physical law required')
    b,s,mu,rp,rm,gamma,sd=values
    bad=((b<.8)|(b>1.2)|(s<.35)|(s>.8)|(mu.abs()>1.1)|(gamma<.25)|(gamma>2)
         |(rp.abs()>.6*b)|(rm.abs()>.6*b)|(sd<=0)|(sd>.12*b))
    if bool(bad.detach().any()):raise ValueError('physical law outside declared bounded envelope')
    return dict(zip(('boundary','diffusion','drift','reset_plus','reset_minus','recovery_rate','reset_sd'),values))


def reset_weights(p,n_grid):
    """Continuous truncated-Gaussian mass in representative-node Voronoi bins."""
    b=p['boundary'];u=torch.linspace(-1,1,n_grid+2,dtype=b.dtype,device=b.device)[1:-1]
    edges=torch.cat((u.new_tensor([-1.]),(u[:-1]+u[1:])/2,u.new_tensor([1.])))
    means=torch.stack((p['reset_minus'],p['reset_plus']),-1)/b[...,None]
    sd=p['reset_sd']/b
    z=(edges-means[...,None])/sd[...,None,None]
    return normal_interval(z[...,:-1],z[...,1:])/normal_interval(z[...,:1],z[...,-1:])


def generator_from_physical(physical,n_grid=31,mode='renewal',bases=None):
    """Return row-generator Q[...,n,n] for physical scalar/broadcast tensors.

    No clamp or stochastic renormalization is used. Space is discretized;
    numerical expm is time-continuous for this declared finite generator.
    """
    p=validate_physical(physical);b=p['boundary'];dx=2*b/(n_grid+1)
    right=p['diffusion'].square()/(2*dx.square())+p['drift']/(2*dx)
    left=p['diffusion'].square()/(2*dx.square())-p['drift']/(2*dx)
    if bool((torch.minimum(right,left).detach()<=0).any()):raise ArithmeticError('nonpositive jump rate')
    up,down=basis(n_grid,mode,b.dtype,b.device) if bases is None else bases
    q=right[...,None,None]*up+left[...,None,None]*down
    if mode=='renewal':
        r=reset_weights(p,n_grid);n=n_grid+2
        lower=torch.nn.functional.one_hot(torch.tensor(n_grid,device=b.device),n).to(b.dtype)
        upper=torch.nn.functional.one_hot(torch.tensor(n_grid+1,device=b.device),n).to(b.dtype)
        zeros=b.new_zeros(*r.shape[:-1],2)
        padded=torch.cat((r,zeros),-1)
        reinject=lower[:,None]*padded[...,0,None,:]+upper[:,None]*padded[...,1,None,:]
        q=q+p['recovery_rate'][...,None,None]*(reinject-torch.diag(lower+upper))
    return q


def physical_from_raw(raw,boundary_raw=None):
    b=.8+.4*torch.sigmoid(raw[0] if boundary_raw is None else boundary_raw)
    return dict(boundary=b,diffusion=.35+.45*torch.sigmoid(raw[1]),gain=.9*torch.tanh(raw[2]),
      drift_bias=.2*torch.tanh(raw[3]),reset_plus=.6*b*torch.tanh(raw[4]),
      reset_minus=.6*b*torch.tanh(raw[5]),recovery_rate=.25+1.75*torch.sigmoid(raw[6]),
      reset_sd=b*(.06+.06*torch.sigmoid(raw[7])))


class DifferentiableRenewalCell(nn.Module):
    def __init__(self,raw=None,n_grid=31,mode='renewal',learn_boundary=True):
        super().__init__()
        value=torch.zeros(8,dtype=torch.float64) if raw is None else torch.as_tensor(raw,dtype=torch.float64).clone().detach()
        if value.shape!=(8,) or not bool(torch.isfinite(value).all()):raise ValueError('eight finite raw parameters required')
        self.raw=nn.Parameter(value);self.n_grid=n_grid;self.n_states=n_grid+2
        self.mode=mode;self.learn_boundary=bool(learn_boundary)
        up,down=basis(n_grid,mode)
        self.register_buffer('up_basis',up);self.register_buffer('down_basis',down)
        self.register_buffer('normalized_grid',torch.linspace(-1,1,n_grid+2,dtype=torch.float64)[1:-1])
        self.register_buffer('fixed_boundary_raw',value[0].clone())

    def physical(self):
        return physical_from_raw(self.raw,None if self.learn_boundary else self.fixed_boundary_raw)

    def law(self,symbol=0.,reliability=.5):
        s=torch.as_tensor(symbol,dtype=self.raw.dtype,device=self.raw.device)
        r=torch.as_tensor(reliability,dtype=self.raw.dtype,device=self.raw.device)
        if not bool(torch.isfinite(s).all() and torch.isfinite(r).all()) or bool(((s!=-1)&(s!=0)&(s!=1)).any() or ((r<0)|(r>1)).any()):
            raise ValueError('symbol must be -1/0/+1 and reliability in [0,1]')
        p=self.physical();p['drift']=p['drift_bias']+p['gain']*s*(2*r-1)
        return p

    def generator(self,symbol=0.,reliability=.5):
        return generator_from_physical(self.law(symbol,reliability),self.n_grid,self.mode,(self.up_basis,self.down_basis))

    def transition(self,dt,symbol=0.,reliability=.5):
        dt=torch.as_tensor(dt,dtype=self.raw.dtype,device=self.raw.device)
        if not bool(torch.isfinite(dt).all()) or bool(((dt<0)|(dt>2)).any()):raise ValueError('duration must be in [0,2]')
        return torch.matrix_exp(dt[...,None,None]*self.generator(symbol,reliability))

    def initial(self):
        return torch.nn.functional.one_hot(torch.tensor(self.n_grid//2,device=self.raw.device),self.n_states).to(self.raw.dtype)

    def advance_distribution(self,mass,dt,symbol=0.,reliability=.5):
        if mass.shape[-1]!=self.n_states or mass.dtype!=self.raw.dtype:raise ValueError('incompatible full mass')
        return torch.matmul(mass.unsqueeze(-2),self.transition(dt,symbol,reliability)).squeeze(-2)

    def free_features(self,symbol=0.,reliability=.5):
        p=self.law(symbol,reliability);u=self.normalized_grid;x=u*p['boundary']
        calls=[normal_cdf((x+p['drift'][...,None]*h-k*p['boundary'])/(p['diffusion']*math.sqrt(h))) for h in HORIZONS for k in THRESHOLDS]
        position=u.expand(calls[0].shape)
        active=torch.cat((torch.stack(calls,-1),position[...,None],position.new_zeros(*position.shape,2)),-1)
        ref=position.new_zeros(2,12);ref[0,10]=1;ref[1,11]=1
        return torch.cat((active,ref.expand(*active.shape[:-2],2,12)),-2)

    def bank_features(self,symbol=0.,reliability=.5):
        """Reset-aware P(X_h>k*b) for this finite process, horizon-major."""
        q=self.generator(symbol,reliability)
        h=q.new_tensor(HORIZONS)
        transitions=torch.matrix_exp(q.unsqueeze(-3)*h[:,None,None])
        coordinates=torch.cat((self.normalized_grid,self.normalized_grid.new_tensor([-1.,1.])))
        indicators=(coordinates[:,None]>coordinates.new_tensor(THRESHOLDS)).to(q.dtype)
        forecasts=torch.matmul(transitions,indicators).transpose(-3,-2)
        return forecasts.reshape(*forecasts.shape[:-2],9)

    def features(self,symbol=0.,reliability=.5):
        bank=self.bank_features(symbol,reliability)
        coordinates=torch.cat((self.normalized_grid,self.normalized_grid.new_tensor([-1.,1.])))
        flags=bank.new_zeros(self.n_states,2);flags[-2,0]=1;flags[-1,1]=1
        extras=torch.cat((coordinates[:,None],flags),-1).expand(*bank.shape[:-2],self.n_states,3)
        return torch.cat((bank,extras),-1)

    def coordinates(self):
        b=self.physical()['boundary']
        return b*torch.cat((self.normalized_grid,self.normalized_grid.new_tensor([-1.,1.])))

    def event_rates(self,symbol=0.,reliability=.5):
        q=self.generator(symbol,reliability)
        return q[...,:,self.n_grid:].sum(-1)*torch.cat((self.raw.new_ones(self.n_grid),self.raw.new_zeros(2)))

    def expected_events(self,mass,dt,symbol=0.,reliability=.5):
        q=self.generator(symbol,reliability);r=self.event_rates(symbol,reliability)
        top=torch.cat((q,r[...,None]),-1);bottom=q.new_zeros(*q.shape[:-2],1,self.n_states+1)
        augmented=torch.cat((top,bottom),-2)
        duration=torch.as_tensor(dt,dtype=q.dtype,device=q.device)
        if not bool(torch.isfinite(duration).all()) or bool(((duration<0)|(duration>2)).any()):raise ValueError('duration must be in [0,2]')
        t=torch.matrix_exp(duration[...,None,None]*augmented)
        extended=torch.cat((mass,mass.new_zeros(*mass.shape[:-1],1)),-1)
        return torch.matmul(extended.unsqueeze(-2),t).squeeze(-2)[...,-1]

    @property
    def active_raw_names(self):
        names=list(RAW_NAMES if self.mode=='renewal' else RAW_NAMES[:4])
        if not self.learn_boundary:names.remove('boundary')
        return names

    def export(self):
        return dict(schema=VERSION,n_grid=self.n_grid,n_states=self.n_states,mode=self.mode,
          raw_names=list(RAW_NAMES),raw=self.raw.detach().cpu().tolist(),learn_boundary=self.learn_boundary,
          fixed_boundary_raw=float(self.fixed_boundary_raw),physical={k:float(v.detach()) for k,v in self.physical().items()},
          active_raw_names=self.active_raw_names,state_order='active internal grid, lower refractory, upper refractory',
          approximation='finite space, continuous-time CTMC; no exact continuum/free-boundary claim')
