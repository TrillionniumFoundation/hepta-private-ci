"""Closed stationary quotes and interval transitions for the four-atom audiovisual encoder."""
import math

import torch
from torch import nn

from torch_prices import price


class AnalyticLaw(nn.Module):
    def __init__(self,grid,reset,*,learn_contract=False,continuous=False):
        super().__init__()
        self.register_buffer("grid",grid.detach().clone())
        self.register_buffer("reset",reset.detach().clone())
        self.register_parameter("raw_sigma",nn.Parameter(torch.zeros((),dtype=torch.float32)) if learn_contract else None)
        self.register_parameter("raw_premium",nn.Parameter(torch.zeros((),dtype=torch.float32)) if learn_contract else None)
        self.continuous=continuous

    def for_input(self,h):
        # The returned object belongs to this forward call. No graph or mutable
        # cache is shared between nested calls, devices or optimization steps.
        ref=self.grid.to(device=h.device,dtype=torch.float64)
        c=ref.new_tensor
        sigma=c(.23) if self.raw_sigma is None else c(.23)*torch.exp(.7*torch.tanh(self.raw_sigma.double()))
        spread=c(.01) if self.raw_premium is None else c(.01)*torch.exp(.7*torch.tanh(self.raw_premium.double()))
        u=c([-1.,0.,1.])[:,None]
        quotes=price(ref,c(.08),c(.02),sigma,c(.27),c(.6),c(6.39),61.68*(1+.28*u),c(1.),spread)
        channel=torch.stack((quotes.equity,quotes.credit_loss),-1)/20
        # The original width-96 parent carries FP32 tables and performs the
        # physical recurrence in FP32 even when the large matmuls use BF16.
        dtype=self.grid.dtype
        return Interval(self.grid,self.reset,(quotes.boundary[2,0]/quotes.boundary[1,0]-1).to(dtype),
                        channel[1].to(dtype),((channel[2]-channel[0])/2).to(dtype),sigma.to(dtype),self.continuous)


class Interval:
    def __init__(self,grid,reset,kappa,base,slope,sigma,continuous):
        self.grid=grid;self.reset=reset
        self.kappa=kappa;self.base=base;self.slope=slope
        self.sigma=sigma;self.continuous=continuous
        self.cuts=(grid[:-1]+grid[1:])/2
        self.dt=.25

    def prices(self,u,smooth):
        if smooth:raise ValueError("the analytic law supplies the published price channels")
        return self.base+u[...,None,None]*self.slope

    def transition(self,shift):
        original_dtype=self.grid.dtype
        sigma=self.sigma
        mu=.08-.02-.5*sigma.square()
        width=sigma*math.sqrt(self.dt)
        if self.continuous:
            # Time-varying log-linear boundary. Double precision and log CDFs
            # keep the reflected Gaussian tail stable for a strongly inward drift.
            x=self.grid.double()
            rel=mu.double()+shift.double()[...,None]/self.dt
            log_weight=-2*rel*x/sigma.double().square()
            drift=rel*self.dt
            def logbins(center):
                low=(torch.cat((x.new_zeros(1),self.cuts[:-1].double()))-center[...,None])/width.double()
                high=(self.cuts.double()-center[...,None])/width.double()
                right=low>0
                la=torch.special.log_ndtr(torch.where(right,-high,low))
                lb=torch.special.log_ndtr(torch.where(right,-low,high))
                interior=lb+torch.log(-torch.expm1(la-lb))
                tail=torch.special.log_ndtr((center-self.cuts[-1].double())/width.double())
                return torch.cat((interior,tail[...,None]),-1)
            free=logbins(x+drift)
            image=logbins(-x+drift)+log_weight[...,None]
            alive=torch.exp(free)*(-torch.expm1((image-free).clamp_max(0)))
            hit=(torch.special.ndtr((-x-drift)/width.double())+
                 torch.exp(log_weight+torch.special.log_ndtr((-x+drift)/width.double())))
            return torch.cat((alive,hit[...,None]),-1).to(original_dtype)
        margin=self.grid+shift[...,None]
        x=margin.clamp_min(0)
        drift=mu*self.dt
        tilt=torch.exp(-2*mu*x/sigma.square())
        def bins(mean):
            p=torch.special.ndtr((self.cuts-mean[...,None])/width)
            atzero=torch.special.ndtr(-mean/width)[...,None]
            return torch.cat((atzero,p,torch.ones_like(atzero)),-1).diff(dim=-1)
        alive=(bins(x+drift)-tilt[...,None]*bins(-x+drift)).clamp_min(0)
        hit=torch.special.ndtr((-x-drift)/width)+tilt*torch.special.ndtr((-x+drift)/width)
        alive=torch.where((margin>0)[...,None],alive,torch.zeros_like(alive))
        hit=torch.where(margin>0,hit,torch.ones_like(hit))
        return torch.cat((alive,hit[...,None]),-1)
