"""Verify the nominal reduction, changing-current response and gradient of physical drift."""
import argparse
import json
from pathlib import Path
import sys
import torch
import numpy as np


def verify(core):
    sys.path.insert(0,str(core.resolve()))
    from affine_ports import AffineBoundaryPopulation
    from drift import DriftBoundaryPopulation
    torch.set_num_threads(1);torch.manual_seed(77819)
    ref=AffineBoundaryPopulation(2,2,atoms=12)
    actual=DriftBoundaryPopulation(2,2,atoms=12)
    missing,unused=actual.load_state_dict(ref.state_dict(),strict=False)
    assert set(missing)=={'physical_drive.weight','physical_drive.bias'} and not unused
    x=torch.randn(12,3,2,dtype=torch.float64)*.4
    target,_=ref(x);v,state=actual(x)
    gap=float((target-v).abs().max().detach())
    assert gap<1e-11
    with torch.no_grad():actual.physical_drive.weight.copy_(torch.tensor([[-.7,.14],[.2,-.43]],dtype=torch.float64))
    msg,_=actual(x);loss=msg.square().mean()
    grad,=torch.autograd.grad(loss,actual.physical_drive.weight)
    direction=torch.randn_like(grad);direction/=direction.norm()
    numerical=[]
    p=actual.physical_drive.weight
    with torch.no_grad():
        original=p.clone()
        for eps in (1e-6,-1e-6):
            p.copy_(original+direction*eps);numerical.append(float(actual(x)[0].square().mean()))
        p.copy_(original)
    error=abs((numerical[0]-numerical[1])/2e-6-float((grad*direction).sum()))
    assert error<1e-8
    rx=DriftBoundaryPopulation(1,1,12)
    with torch.no_grad():
        rx.sender.weight.zero_();rx.sender.bias.zero_();rx.recurrent.weight.zero_();rx.feedback.zero_()
        rx.physical_drive.weight.fill_(-1);rx.physical_drive.bias.zero_()
        strengths=torch.tensor([-.5,0.,.25,.5,1.],dtype=torch.float64)
        # Exactly stationary solutions of each numerical finite transition; no burn-in approximation.
        mu=rx.prices.mu+rx.max_drift_shift*(-strengths).tanh()
        q,h=rx.live_transition(rx.grid.expand(len(mu),-1),mu[:,None])
        top=torch.cat([q,h.unsqueeze(-1)],-1)
        reset=torch.cat([rx.reset_weights,rx.grid.new_zeros(1)])
        M=torch.cat([top,reset.expand(len(mu),1,-1)],-2)
        error_mass=float((M.sum(-1)-1).abs().max());I=torch.eye(13,dtype=torch.float64)
        eq=I-M.transpose(-1,-2);eq[:,-1]=1;rhs=torch.zeros(len(mu),13,dtype=torch.float64);rhs[:,-1]=1
        pi=torch.linalg.solve(eq,rhs[...,None])[...,0]
        f=(pi[:,-1]/rx.dt).tolist()
        assert np.all(np.diff(f)>0) and error_mass<1e-12
    return {'nominal_abs_error':gap,'physical_drift_gradient_norm':float(grad.norm()),'directional_difference_abs_error':error,'row_mass_error':error_mass,'constant_inputs':strengths.tolist(),'drifts':mu.tolist(),'stationary_finite_grid_rate':f,'note':'Finite-grid stationary rate differs from the unbounded renewal limit. Physiological units and parameters require calibration.'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--core',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();d=verify(a.core);a.out.write_text(json.dumps(d,indent=1)+'\n');print(d)
