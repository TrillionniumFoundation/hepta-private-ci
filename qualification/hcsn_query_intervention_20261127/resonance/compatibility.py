"""Normal forward/backward, state serialization and one-sided endpoint regressions."""
import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import torch
from dataclasses import replace
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from resonance import StablePublished,StationaryLaw,replace_published
from resonance.equity import curve
from hx_reference import StationaryFirm,Parameters

def native_cls(source):
    spec=importlib.util.spec_from_file_location('original_native_comparison',source);m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m);return m
def maximum(x,y):return float((x-y).abs().max().detach())
def gradtry(channels,q):
    return np.asarray([torch.autograd.grad(z,q,retain_graph=True)[0].item() for z in channels])
def side(func,step,side):
    return side*(-25*func(0.)+48*func(side*step)-36*func(2*side*step)+16*func(3*side*step)-3*func(4*side*step))/(12*step)
def forward_backward(m,inp):
    x=inp.detach().clone().requires_grad_();m.zero_grad(set_to_none=True);y=m(x)
    w=torch.linspace(-.9,1.3,y.numel(),dtype=y.dtype).reshape(y.shape)
    loss=(y*w+.03*y.square()).sum();loss.backward()
    g={n:p.grad.detach().clone() for n,p in m.named_parameters()}
    return y.detach(),x.grad.detach(),g
def reference(q,absolute):
    p=Parameters();f=StationaryFirm(p,q/.01);b=f.boundary_green();x=np.log(75./b) if absolute else .1
    fv,gv=f.first_passage(x);return np.array([b,f.equity_green(b*np.exp(x),b),fv,gv])
def run(path):
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.manual_seed(855974)
    mod=native_cls(path);orig=mod.Published();new=StablePublished(orig.p);p=orig.p
    x=torch.tensor([.001,.02,.1,.4,.8],dtype=torch.float64,requires_grad=True);P=torch.tensor([50.,56.,61.68,70.,78.],dtype=torch.float64,requires_grad=True)
    ev,hit=orig.values(x,P);nE,nF=new.values(x,P);g1=torch.autograd.grad(ev.sum(),(x,P),retain_graph=True);g2=torch.autograd.grad(nE.sum(),(x,P),retain_graph=True)
    close=dict(boundary=maximum(orig.boundary(P),new.boundary(P)),equity=maximum(ev,nE),hit=maximum(hit,nF),
               equity_dx=maximum(g1[0],g2[0]),equity_dP=maximum(g1[1],g2[1]),
               advance=maximum(orig.move_mean(x),new.move_mean(x)),different_horizon_hit=maximum(orig.passage(x,.17),new.passage(x,.17)))
    h1=torch.autograd.grad(hit.sum(),x)[0];h2=torch.autograd.grad(nF.sum(),x)[0];close['hit_dx']=maximum(h1,h2)
    checkstate=StablePublished(orig.p);loaded=checkstate.load_state_dict(orig.state_dict(),strict=True)
    c=mod.LiteralCell().eval();c2=replace_published(deepcopy(c));input_x=torch.randn((15,4,6),dtype=torch.float64)
    oo,gx,gg=forward_backward(c,input_x);nn,g2x,g2g=forward_backward(c2,input_x)
    net=dict(timesteps=15,batch=4,old_and_new_buffers_same_names=set(c.law.state_dict())==set(c2.law.state_dict()),
             strict_checkpoint_missing=loaded.missing_keys,strict_checkpoint_unexpected=loaded.unexpected_keys,
             output_abs=maximum(oo,nn),input_gradient_abs=maximum(gx,g2x),parameter_gradient_abs={n:maximum(gg[n],g2g[n]) for n in gg})
    zero=StablePublished(replace(StationaryLaw(),premium=0.));edge={}
    for absolute in (False,True):
        q=torch.tensor(0.,dtype=torch.float64,requires_grad=True);xv=torch.log(75./zero.boundary(61.68,premium=q)) if absolute else .1
        values=zero.channels(xv,61.68,premium=q);grads=gradtry(values,q)
        a=side(lambda z:reference(z,absolute),1e-5,1);b=side(lambda z:reference(z,absolute),1e-5,-1)
        edge['fixed_absolute_V75' if absolute else 'fixed_log_margin_0.1']=dict(B_E_F_G=[float(v.detach()) for v in values],gradient=grads.tolist(),
               physical_right_fd=a.tolist(),formal_left_fd=b.tolist(),max_abs_right=float(abs(a-grads).max()),max_abs_formal_left=float(abs(b-grads).max()))
    c0=deepcopy(c);c0.law=zero;v0,g0,gm=forward_backward(c0,input_x)
    edge['cell_all_finite']=bool(v0.isfinite().all() and g0.isfinite().all() and all(v.isfinite().all() for v in gm.values()))
    q=torch.tensor([[0.],[.01],[.1]],dtype=torch.float64,requires_grad=True);pp=torch.tensor([50.,61.68,75.,82.],dtype=torch.float64,requires_grad=True)
    stream=new.channels(torch.full((1,4),.1,dtype=torch.float64),pp,premium=q)
    qg,pg=torch.autograd.grad((stream.equity+stream.boundary).sum(),(q,pp))
    errs={}
    for name,fn in [('negative_physical_premium',lambda:new.channels(.1,61.68,premium=-1e-10)),('negative_principal',lambda:new.boundary(-1.)),
        ('zero_maturity',lambda:StablePublished(replace(StationaryLaw(),m=0))),('nan_margin',lambda:new.values(float('nan'),61.68))]:
        try:fn();errs[name]='accepted'
        except ValueError as exc:errs[name]=str(exc)
    with torch.inference_mode():inference=StablePublished().forward(.1,61.68)[0].item()
    cache=dict(compatible_at_premium_0_01=close,native_network=net,zero_limit=edge,broadcast_shape=list(stream.equity.shape),
          broadcast_gradients_finite=bool(qg.isfinite().all() and pg.isfinite().all()),invalid_inputs=errs,construction_inside_inference_mode=inference)
    assert max(close.values())<2e-8 and net['output_abs']<1e-8 and net['input_gradient_abs']<1e-7
    assert max(net['parameter_gradient_abs'].values())<2e-6 and edge['cell_all_finite'] and all(x!='accepted' for x in errs.values())
    return cache
if __name__=='__main__':
    par=argparse.ArgumentParser();par.add_argument('original',type=Path);par.add_argument('out',type=Path);a=par.parse_args()
    a.out.write_text(json.dumps(run(a.original),indent=1,allow_nan=False)+'\n')
