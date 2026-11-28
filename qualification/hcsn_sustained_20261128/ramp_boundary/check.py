"""Compare the continuous-boundary operator against paths, independent derivatives, and two half-steps."""
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import torch
from population import BoundaryPopulation, ContinuousSpikingNetwork

torch.set_num_threads(1)
torch.set_num_interop_threads(1)


def finite(z):
    if not torch.isfinite(z).all():
        raise ValueError("nonfinite")


def paths():
    rng=np.random.default_rng(6713)
    n=524288
    z=rng.standard_normal(n)
    uniforms=rng.random(n)
    h=.25
    p=BoundaryPopulation(1,1,17,dt=h,boundary_path="linear_log")
    cuts=p.cuts.numpy()
    cases=[]
    for atom in (0,2,4,8):
        x=float(p.grid[atom])
        m=torch.zeros_like(p.grid)
        m[atom]=1
        for shift in (-.28,-.04,0,.08,.21):
            relative=p.prices.mu-shift/h
            new,flux=p.ramp_transport(m,torch.tensor([relative],dtype=torch.float64))
            end=x+p.prices.mu*h+p.prices.p.sigma*math.sqrt(h)*z-shift
            probability=np.ones(n)
            live=end>0
            probability[live]=np.exp(-2*x*end[live]/(h*p.prices.var))
            killed=uniforms<probability
            bins=np.bincount(np.searchsorted(cuts,end[~killed]),minlength=len(p.grid))/n
            exact=float(flux)
            empirical=float(killed.mean())
            max_bin=float(np.max(np.abs(new.detach().numpy()-bins)))
            std=math.sqrt(max(exact*(1-exact),1/n)/n)
            if abs(empirical-exact)>6*std+2/n or max_bin>.004 or abs(float(new.sum()+flux)-1)>2e-10:
                raise ValueError((atom,shift,empirical,exact,max_bin))
            cases.append(dict(x=x,increment=shift,flux=exact,monte_carlo=empirical,
                              max_abs_bin_error=max_bin,mass_error=float(new.sum()+flux-1)))
    return cases


def semigroup():
    rows=[]
    for K in (32,64,128,256,512):
        h=.25
        relative=torch.tensor([.03355-.09/h],dtype=torch.float64)
        p=BoundaryPopulation(1,1,K,dt=h,boundary_path="linear_log")
        delta=2.6/K
        p.grid=(torch.arange(K,dtype=torch.float64)+.5)*delta
        p.cuts=p.grid[1:]-delta/2
        m=torch.exp(-.5*((p.grid-.31)/.04)**2)
        m=m/m.sum()
        one,f=p.ramp_transport(m,relative)
        p.dt=h/2
        mid,f1=p.ramp_transport(m,relative)
        two,f2=p.ramp_transport(mid,relative)
        err=abs(float(f-f1-f2))
        rows.append(dict(atoms=K,hit_one=float(f),hit_two=float(f1+f2),hit_abs_error=err,
                         survivor_l1=float((two-one).abs().sum())))
    if rows[-1]["hit_abs_error"]>=rows[0]["hit_abs_error"]*.03:
        raise ValueError(rows)
    return rows


def networks():
    rows=[]
    for path in ("step","linear_log"):
        for K,width in ((12,2),(32,3)):
            for seed,gain in ((137,None),(311,.15)):
                torch.manual_seed(seed)
                dense=ContinuousSpikingNetwork(3,width,2,K,"priced",False,True,gain,path)
                fft=ContinuousSpikingNetwork(3,width,2,K,"priced",True,True,gain,path)
                fft.load_state_dict(dense.state_dict(),strict=True)
                x=torch.randn(5,2,3,dtype=torch.float64)*.2
                def outputs(net):
                    v=x.clone().requires_grad_()
                    y,states=net(v)
                    loss=(y.square()).mean()+sum(t.square().mean()*.01 for lay in states for t in lay)
                    g=torch.autograd.grad(loss,[v,*net.parameters()])
                    for a in (y,*g):finite(a)
                    return y,g,loss
                y,g,l=outputs(dense)
                z,gg,_=outputs(fft)
                v=float((y-z).abs().max().detach())
                gd=max(float((i-j).abs().max()) for i,j in zip(g,gg))
                if v>1e-7 or gd>1e-7:raise ValueError((path,K,v,gd))
                direction=torch.randn_like(x)
                direction/=direction.norm()
                with torch.no_grad():
                    def obj(arg):
                        y,states=dense(arg)
                        return y.square().mean()+sum(t.square().mean()*.01 for lay in states for t in lay)
                    eps=1e-5
                    numeric=float((obj(x+eps*direction)-obj(x-eps*direction))/(2*eps))
                    err=abs(numeric-float((g[0]*direction).sum()))
                if err>1e-7:raise ValueError((path,K,err))
                rows.append(dict(path=path,atoms=K,width=width,seed=seed,initial_physical_gain=gain,
                                 forward_abs=v,gradient_abs=gd,directional_error=err))
    return rows


def fixed_and_jump():
    p=BoundaryPopulation(1,1,12,dt=.25)
    m=torch.zeros_like(p.grid);m[1]=1
    mu=torch.tensor([p.prices.mu],dtype=torch.float64)
    base,hit=p.ramp_transport(m,mu)
    direct,loss=p.kernels(p.grid)
    stationary=float(max((base-(m[:,None]*direct).sum(0)).abs().max(),(hit-(m*loss).sum()).abs()))
    inc=.19
    _,instant=p.kernels(p.grid-inc)
    _,continuous=p.ramp_transport(m,mu-inc/p.dt)
    z=dict(initial_log_margin=float(p.grid[1]),boundary_increment=inc,instantaneous_hit=float((instant*m).sum()),
           continuously_moving_hit=float(continuous),fixed_boundary_abs_error=stationary)
    if stationary>1e-12 or z["instantaneous_hit"]!=1 or z["continuously_moving_hit"]>=1:
        raise ValueError(z)
    return z

if __name__=="__main__":
    output=dict(torch=str(torch.__version__),device="cpu",paths_per_case=524288,paths=paths(),
                semigroup=semigroup(),network=networks(),same_and_distinct=fixed_and_jump())
    Path("verified.json").write_text(json.dumps(output,indent=2)+"\n")
    print(json.dumps({k:output[k] for k in ("semigroup","same_and_distinct")}),flush=True)
