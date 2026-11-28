"""Physical sign, checkpoint compatibility and forward/backward tests at finite mass."""
import importlib.util
import json
from pathlib import Path
import sys

import torch
from population import BoundaryPopulation, ContinuousSpikingNetwork


def checks(parent):
    oldspec=importlib.util.spec_from_file_location("old_boundary",parent)
    old=importlib.util.module_from_spec(oldspec);oldspec.loader.exec_module(old)
    torch.set_num_threads(1);torch.manual_seed(944)
    dtype=torch.float64
    model=BoundaryPopulation(1,1,12,signed_force_gains=(.65,.65),initial_physical_gain=.70,boundary_path="linear_log")
    with torch.no_grad():
        model.sender.weight.zero_();model.sender.bias.zero_();model.recurrent.weight.zero_()
    signs={}
    for i in (0,2,5):
        mass=torch.zeros(1,1,12,dtype=dtype);mass[...,i]=1
        values=torch.tensor([[[.3,.4]]],dtype=dtype,requires_grad=True)
        z=torch.zeros(1,1,dtype=dtype)
        drift=model.signed_drift(mass,values)
        message,state=model.step(z,(mass,z,z,values))
        dg=torch.autograd.grad(drift,values,retain_graph=True)[0].flatten()
        fg=torch.autograd.grad(message[...,1],values)[0].flatten()
        x=float(model.grid[i])
        if (dg[0]*(.3-x)<=0 or dg[1]>=0 or fg[0]*(.3-x)>=0 or fg[1]<=0):
            raise ValueError((x,dg,fg))
        signs[str(i)]=dict(margin=x,drift_grad=dg.tolist(),flux_grad=fg.tolist(),flux=message[...,1].item())
    mass=torch.zeros(1,1,12,dtype=dtype)
    z=torch.zeros(1,1,dtype=dtype)
    values=torch.ones(1,1,2,dtype=dtype)
    _,st=model.step(z,(mass,z+1,z,values))
    torch.testing.assert_close(st[0],model.reset_weights[None,None,:])
    if st[1].abs().max()!=0:raise ValueError("empty population hit")
    torch.manual_seed(7);legacy=old.ContinuousSpikingNetwork(2,2,3,atoms=8,cache_prices=True)
    copy=ContinuousSpikingNetwork(2,2,3,atoms=8,cache_prices=True)
    copy.load_state_dict(legacy.state_dict(),strict=True)
    x=torch.randn(6,3,2,dtype=dtype)*.2
    assert torch.equal(copy(x)[0],legacy(x)[0])
    results={}
    for path in ("step","linear_log"):
        ref=ContinuousSpikingNetwork(2,2,3,atoms=16,cache_prices=True,boundary_path=path,
                                initial_physical_gain=.1,signed_force_gains=(.25,.25))
        fft=ContinuousSpikingNetwork(2,2,3,atoms=16,matrix_free=True,cache_prices=True,boundary_path=path,
                                initial_physical_gain=.1,signed_force_gains=(.25,.25))
        fft.load_state_dict(ref.state_dict())
        inp=x.clone().requires_grad_();y,st=ref(inp)
        yo,_=fft(inp)
        if (y-yo).abs().max()>1e-9:raise ValueError("fft forward")
        a,state=ref(inp[:2]);b,_=ref(inp[2:],state)
        loss=y.square().sum();tensors=[inp,ref.first.feedback,ref.second.feedback,ref.first.sender.weight]
        grads=torch.autograd.grad(loss,tensors)
        fg=torch.autograd.grad(yo.square().sum(),[inp,fft.first.feedback,fft.second.feedback,fft.first.sender.weight])
        max_diff=max((a-b).abs().max().item() for a,b in zip(grads,fg))
        numerical=[]
        for li,par in enumerate([ref.first.feedback,ref.second.feedback]):
            for j in range(2):
                with torch.no_grad():
                    saved=par[0,j].item();par[0,j]=saved+1e-5;hi=ref(inp)[0].square().sum().item()
                    par[0,j]=saved-1e-5;lo=ref(inp)[0].square().sum().item();par[0,j]=saved
                numerical.append(abs((hi-lo)/2e-5-grads[li+1][0,j].item()))
        chunk=(torch.cat([a,b])-y).abs().max().item();me=max((s[0].sum(-1)+s[1]-1).abs().max().item() for s in st)
        if max(max_diff,chunk,me,max(numerical))>1e-8:raise ValueError((path,max_diff,me,numerical))
        results[path]=dict(fft_forward=(y-yo).abs().max().item(),fft_gradient=max_diff,
                          four_gain_gradients=[g.norm().item() for g in grads[1:3]],finite_difference=max(numerical),
                          mass_error=me,chunk=chunk)
    return dict(interventions=signs,default_outputs_bitwise=True,strict_legacy_checkpoint=True,
                empty_refractory_reset=True,network=results)

if __name__=="__main__":
    r=checks(Path(sys.argv[1]));print(json.dumps(r,indent=2))
    Path(__file__).with_name("verified.json").write_text(json.dumps(r,indent=2)+"\n")
