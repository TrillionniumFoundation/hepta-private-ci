"""Exact table generation, interpolation error, stream equivalence and gradient checks."""
import hashlib
import json
from pathlib import Path
import sys
import numpy as np
import torch

from hcsn_temporal import Law
from encoder_adapter import AnalyticAVText
from exact_law import AnalyticLaw


def check(asset):
    table=Law(asset)
    reg=AnalyticLaw(table.grid,table.reset)
    learn=AnalyticLaw(table.grid,table.reset,learn_contract=True)
    law=reg.for_input(table.grid)
    u=torch.linspace(-1,1,129)
    prices=float((table.prices(u,False)-law.prices(u,False)).abs().max())
    knots=torch.linspace(-.8,.8,4097)
    direct=torch.cat([law.transition(t) for t in knots.split(128)])
    kmax=float((table.kernel-direct).abs().max())
    rng=torch.Generator().manual_seed(801)
    off=(torch.rand(1451,generator=rng)*1.58-.79).requires_grad_()
    d=law.transition(off)
    t=table.transition(off)
    q=torch.tensor([-.1,.3,-.26,.14,.72])
    g=torch.autograd.grad((d*q).sum(),off,retain_graph=True)[0]
    gg=torch.autograd.grad((t*q).sum(),off)[0]
    eps=1e-4
    # Knots at zero margin create genuine contacts; test slopes away from these points.
    keep=(off.detach()[:,None]+table.grid).abs().amin(1)>.002
    diff=(g-gg).abs()
    outside=torch.tensor([.80,.85,1.])
    extrap=float((law.transition(outside)[1:]-table.transition(outside)[1:]).abs().max())
    cols={}
    for continuous in (False,True):
        mod=AnalyticAVText(96,137,80,asset,learn_contract=True,continuous=continuous)
        m=torch.randn(2,5,96,generator=rng,requires_grad=True)
        whole=mod.encode(m)
        state=None
        for h in m.split([1,3,1],dim=1):
            out,state=mod.encode_chunk(h,state)
        err=float((whole-out).abs().max().detach())
        probe=torch.randn(whole.shape,generator=rng)
        labels=[m,mod.law.raw_sigma,mod.law.raw_premium,mod.mixer[1].wire.weight]
        gw=torch.autograd.grad((whole*probe).sum(),labels)
        gs=torch.autograd.grad((out*probe).sum(),labels)
        grad=max(float((a-b).abs().max()) for a,b in zip(gw,gs))
        cv=[]
        for j,par in enumerate([mod.law.raw_sigma,mod.law.raw_premium]):
            # Directional differences use double precision for the law; the net
            # emits normalized FP32 embeddings so use absolute finite differences.
            with torch.no_grad():
                val=par.detach().clone()
                par.copy_(val+.002);hi=float((mod.encode(m)*probe).sum())
                par.copy_(val-.002);lo=float((mod.encode(m)*probe).sum())
                par.copy_(val)
            numeric=(hi-lo)/.004
            cv.append(dict(analytic=float(gw[j+1]),finite=numeric,error=abs(numeric-float(gw[j+1]))))
        if err>3e-5 or grad>2e-4 or min(abs(i["analytic"]) for i in cv)<1e-9 or max(i["error"] for i in cv)>.0015:
            raise ValueError((continuous,err,grad,cv))
        cols[str(continuous)]=dict(stream_value_max=err,stream_four_gradient_max=grad,law_partials=cv)
    report=dict(table_sha256=hashlib.sha256(Path(asset).read_bytes()).hexdigest(),knot_count=len(knots),
                knot_max_abs=kmax,random_interpolation_max=float((d-t).abs().max().detach()),
                prices_max_abs=prices,kappa_abs=float((table.kappa-law.kappa).abs()),max_mass_error=float((d.sum(-1)-1).abs().max().detach()),
                away_from_contacts_count=int(keep.sum()),away_from_contacts_derivative_median=float(diff[keep].median()),
                away_from_contacts_derivative_max=float(diff[keep].max()),outside_table_range_max_abs=extrap,stream=cols)
    if kmax>2e-5 or prices>2e-5 or report["max_mass_error"]>1e-5:raise ValueError(report)
    return report


if __name__=="__main__":
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out=check(Path(sys.argv[1]))
    Path("verified.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out),flush=True)
