"""Validate drift/cost/reset sensitivities and costs against #7149 and independent Lambert W."""
import json
import math
import platform
import time
from pathlib import Path
import numpy as np
from scipy.special import lambertw
import torch
from boundary_variant import DimensionlessRoot
from qualification.hcsn_closure_20261124.fast_kernel import NewtonQVI
from qualification.hcsn_smallnet_20261124.model import _residual

torch.set_num_threads(1);torch.set_num_interop_threads(1)
sigma,rho,eta,gain,maint=.55,.3,math.exp(-3*math.log1p(.3*.2/3)),.8,.25
def solve(fn,mu,co,a):
    return fn.apply(mu,co,a,sigma,rho,eta,gain,maint)
def run_grid():
    coords=torch.cartesian_prod(torch.linspace(-.35,-.05,41,dtype=torch.float64),
                                torch.linspace(.13,.17,19,dtype=torch.float64),
                                torch.linspace(1.15,1.25,9,dtype=torch.float64))
    inputs=[x.contiguous().requires_grad_() for x in coords.T]
    m,c,a=inputs; root=(m.square()+2*rho*sigma**2).sqrt(); k=2*rho/(root-m)
    h=1+k*((1-eta)*(a+m/rho-maint/gain)+c*rho/gain)
    w=lambertw((-eta*torch.exp(-h)).detach().numpy()).real
    reference=a-(h+torch.from_numpy(w))/k
    b=solve(DimensionlessRoot,*inputs); legacy=solve(NewtonQVI,*inputs)
    analytic=torch.autograd.grad(b.sum(),inputs)
    old=torch.autograd.grad(legacy.sum(),inputs)
    gres={}
    for i,label in enumerate(("mu","cost","absolute_reset")):
        p=[x.detach().clone() for x in inputs]; n=[x.detach().clone() for x in inputs]
        eps=1e-5;p[i]+=eps;n[i]-=eps
        fd=(solve(DimensionlessRoot,*p)-solve(DimensionlessRoot,*n))/(2*eps)
        gres[label]={"vs_implicit_max_abs":float((analytic[i]-old[i]).abs().max()),
                     "vs_difference_max_abs":float((analytic[i]-fd).abs().max())}
        assert gres[label]["vs_implicit_max_abs"]<1e-11 and gres[label]["vs_difference_max_abs"]<4e-8
    maximum=float((reference-b).abs().max().detach())
    assert maximum<1e-13
    r=_residual(b,*inputs,sigma,rho,eta,gain,maint)[0]
    return {"points":len(b),"max_abs_vs_scipy_lambert":maximum,"max_abs_vs_newton":float((b-legacy).abs().max().detach()),
            "max_abs_residual":float(r.abs().max().detach()),"gradients":gres}
def timing(n):
    gen=torch.Generator().manual_seed(27312)
    m=(-.35+torch.rand(n,dtype=torch.float64,generator=gen)*.3).requires_grad_()
    c=(.13+torch.rand(n,dtype=torch.float64,generator=gen)*.04).requires_grad_()
    a=torch.full_like(m,1.2,requires_grad=True)
    results={"old":[],"new":[]}
    for j in range(9):
        order=[("old",NewtonQVI),("new",DimensionlessRoot)]
        if j%2:order.reverse()
        for name,fn in order:
            start=time.perf_counter_ns()
            for _ in range(16):
                b=solve(fn,m,c,a); torch.autograd.grad(b.sum(),(m,c,a))
            elapsed=(time.perf_counter_ns()-start)/1e9
            if j:results[name].append(elapsed)
    return {**results,"median_old_over_new":float(np.median(results["old"])/np.median(results["new"]))}
out={"cpu":platform.processor(),"torch":str(torch.__version__),"grid":run_grid(),"timing":{str(n):timing(n) for n in (96,384,4096)}}
Path(__file__).with_name('root_verification.json').write_text(json.dumps(out,indent=2,allow_nan=False)+"\n")
print(out["grid"],{k:v["median_old_over_new"] for k,v in out["timing"].items()})
