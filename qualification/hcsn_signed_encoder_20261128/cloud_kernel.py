"""GPU replay for signed feedback, gradients and mass. The full actor benchmark uses separate original inputs."""
import json
import math
from pathlib import Path
import numpy as np
import torch
from force_kernel import table,transport,signed_term,DT,MU

def run(device):
    grid=torch.tensor([.015,.3,.585,.87],device=device,dtype=torch.float64)
    reset=torch.tensor([0.,1.,0.,0.],device=device,dtype=torch.float64)
    kern=torch.from_numpy(table(grid.cpu().numpy())).to(device)
    u=torch.linspace(-.9,.9,12*6,dtype=torch.float64).reshape(12,2,3).to(device).requires_grad_()
    gains=torch.zeros((3,2),dtype=torch.float64,device=device,requires_grad=True)
    mass=reset.expand(2,3,-1)
    ref=torch.zeros_like(mass[...,0]);mark=torch.zeros_like(ref)
    # Fixed test prices strictly positive, for a mechanism-level GPU parity check.
    p0=torch.stack((.15+2*grid,1/(1+6*grid)),-1);quote=torch.zeros(2,3,2,dtype=torch.float64,device=device)
    flows=[];error=0.
    for t in range(len(u)):
        m=torch.log1p(.2935*u[t])
        d=MU-.15*u[t]+signed_term("signed",gains,mass,ref,quote,grid,reset)+(mark-m)/DT
        prob=transport(kern,d);next_mass=(prob*mass[...,None]).sum(-2)
        mass=next_mass[...,:-1]+ref[...,None]*reset
        ref=next_mass[...,-1];mark=m
        quote=(mass[...,None]*p0).sum(-2)
        flows.append(ref)
        error=max(error,float((mass.sum(-1)+ref-1).abs().max().detach().cpu()))
    y=torch.stack(flows);loss=(y*torch.linspace(.1,1.2,12,device=device,dtype=y.dtype)[:,None,None]).sum()
    gu,gw=torch.autograd.grad(loss,(u,gains))
    return [a.detach().cpu().numpy() for a in (y,gu,gw)],error
if __name__=="__main__":
    assert torch.cuda.is_available()
    dev=torch.cuda.get_device_name()
    a,e0=run("cpu");b,e1=run("cuda")
    dif=[float(np.max(abs(x-y))) for x,y in zip(a,b)]
    probe=torch.arange(1,8,device="cuda",dtype=torch.float64);dot=float(probe@probe)
    assert dot==140 and max(dif)<3e-10 and max(e0,e1)<1e-10
    result={"device":dev,"torch":str(torch.__version__),"cuda_dot":dot,"fp64_max_errors_flow_inputgrad_gaingrad":dif,
            "maximum_mass_error_cpu_gpu":[e0,e1],"gpu_grad_norm":float(np.linalg.norm(b[-1])),
            "scope":"independent GPU transport with synthetic price channels; no held corpus data"}
    Path("gpu_force_check.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result))
