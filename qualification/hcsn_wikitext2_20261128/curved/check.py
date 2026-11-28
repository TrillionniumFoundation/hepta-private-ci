"""Test derivative propagation through the native evaluation against torch's double graph."""
import json
from pathlib import Path
import torch
from curvemodel import CurveLM,evaluate,HERE


def run():
    torch.manual_seed(1237);pts=20000;out={}
    for kind in ('hxcurve','bilinear'):
        model=CurveLM(33278,kind)
        c=model.blocks[0].pricing
        u=(2*torch.rand(pts)-1).requires_grad_()
        t=(2*torch.rand(pts)-1).requires_grad_()
        f=evaluate(u,t,c);g=torch.autograd.grad(f.sum(),(u,t))
        ud=u.detach().double().requires_grad_();td=t.detach().double().requires_grad_()
        real=evaluate(ud,td,c);dg=torch.autograd.grad(real.sum(),(ud,td))
        err=float((f.detach().double()-real.detach()).abs().max())
        grad=[float((x.double()-y).abs().max()) for x,y in zip(g,dg)]
        ids=torch.randint(0,33278,(2,128));other=ids.clone();other[:,52:]=torch.randint(0,33278,(2,76))
        with torch.inference_mode():
            a=model.encode(ids);b=model.encode(other);cut=(model.encode(ids,True)-model.encode(other,True)).abs().max().item()
        if err>2e-6 or max(grad)>2e-6 or cut!=0 or (a[:,:52]-b[:,:52]).abs().max()!=0:raise ArithmeticError((err,grad,cut))
        out[kind]=dict(trials=pts,max_value_abs=err,max_partials_abs=grad,causal_prefix_max=float((a[:,:52]-b[:,:52]).abs().max()),cut_max=cut,
                       parameters=sum(q.numel() for q in model.parameters()))
    return out
if __name__=='__main__':
    (HERE/'checks.json').write_text(json.dumps(run(),indent=2)+'\n')
