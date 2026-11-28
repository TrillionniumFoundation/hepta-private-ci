"""Match physical and smooth channels at the declared reference and verify causal port isolation."""
import argparse
import json
from pathlib import Path
import numpy as np
import torch
from law import *
def main(out):
    torch.set_num_threads(1);torch.manual_seed(18911)
    x=torch.randn(8,28,28,requires_grad=True);m=WallClassifier('wall_literal')
    base=m.event_stream(x);future=x.detach().clone();future[:,13:]=torch.randn_like(future[:,13:])*5.
    before=(base[:,:13]-m.event_stream(future)[:,:13]).abs().max()
    clamped=m(x,'clamp_wire')
    blocked=(clamped-clamped[0]).abs().max()
    d,=torch.autograd.grad(m(x).pow(2).sum(),x)
    w,state=m.one(x,state=True);r,pre,flux,q,margin,eq,loss=state
    old=r[:,0]*0;series=[]
    for at in q.unbind(1):
        old=(m.one.retain.sigmoid()-at)*old+at;series.append(old)
    error=(r-torch.stack(series,1)).abs().max()
    source=Wall(28,'wall_literal');smooth=Wall(28,'wall_smooth')
    at=torch.full((5,),REF);rel=torch.linspace(-.21,.21,5)
    loss_point=lambda kind:torch.stack(kind.response(at,rel),-1).detach()
    value=(loss_point(source)-loss_point(smooth)).abs().max()
    slopes=[]
    for layer in (source,smooth):
        hi=torch.stack(layer.response(at+GRID,rel),-1);lo=torch.stack(layer.response(at-GRID,rel),-1)
        slopes.append((hi-lo)/(2*GRID))
    xpos=np.random.default_rng(32988).uniform(0.,.6,1000);rs=np.random.default_rng(9453).uniform(-.21,.21,1000)
    cp,_=reference_prices(xpos);truth=(cp[0]+rs[:,None]*cp[1]);qtruth=passage(xpos,DRIFT,DT)
    a,l,p=source.response(torch.tensor(xpos,dtype=torch.float32),torch.tensor(rs,dtype=torch.float32))
    interp=np.stack([a.detach().numpy(),l.detach().numpy(),p.detach().numpy()],1)-np.c_[truth,qtruth]
    result=dict(prefix_error=float(before.detach()),clamped_across_examples_max=float(blocked.detach()),input_gradient_norm=float(d.norm()),
                recurrence_vs_sequential_error=float(error.detach()),flux_range=[float(flux.detach().min()),float(flux.detach().max())],
                refractory_range=[float(r.detach().min()),float(r.detach().max())],match_values_max=float(value),two_sided_slope_error=float((slopes[0]-slopes[1]).detach().abs().max()),
                price_price_probability_interpolation_max=np.max(abs(interp),axis=0).tolist(),
                counts={arm:sum(p.numel() for p in WallClassifier(arm).parameters()) for arm in ARMS})
    assert result['prefix_error']<2e-5 and result['clamped_across_examples_max']<1e-7 and result['recurrence_vs_sequential_error']<2e-6
    out.write_text(json.dumps(result,indent=1)+'\n');print(result)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);a=p.parse_args();main(a.out)
