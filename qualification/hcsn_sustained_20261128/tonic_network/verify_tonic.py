"""Optional signed physical drift in the original two-layer population."""
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.append(str(Path(__file__).resolve().parents[2]/"hcsn_continuous_20261127"/"core"))
from population import BoundaryPopulation, ContinuousSpikingNetwork


def tensors(tree):
    if isinstance(tree,torch.Tensor):
        yield tree
    else:
        for item in tree:yield from tensors(item)


def evaluate(net,x):
    xx=x.clone().requires_grad_()
    pred,state=net(xx)
    loss=pred.square().mean()+sum(k.square().mean() for k in tensors(state))
    grad=torch.autograd.grad(loss,[xx,*net.parameters()])
    return list(tensors((pred,state))),list(grad)


def err(a,b):
    return float(max((x-y).abs().max() for x,y in zip(a,b)))


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    folder=Path(__file__).resolve().parent
    old=folder/"original_population.py"
    if not old.is_file():old=folder.parent/"price_cache/population.py"
    ss=importlib.util.spec_from_file_location("previous",old)
    previous=importlib.util.module_from_spec(ss);ss.loader.exec_module(previous)
    torch.manual_seed(9181)
    x=torch.randn(5,3,2,dtype=torch.float64)*.45
    ref=previous.ContinuousSpikingNetwork(2,3,4)
    g=ContinuousSpikingNetwork(2,3,4);g.load_state_dict(ref.state_dict(),strict=True)
    a,b=evaluate(ref,x);c,e=evaluate(g,x)
    if err(a,c)!=0 or err(b,e)!=0:raise ValueError("default changed")
    pairs=[]
    for atoms in (12,64):
        for cache in (False,True):
            net=ContinuousSpikingNetwork(2,3,4,atoms=atoms,initial_physical_gain=.15,cache_prices=cache)
            fft=ContinuousSpikingNetwork(2,3,4,atoms=atoms,initial_physical_gain=.15,cache_prices=cache,matrix_free=True)
            fft.load_state_dict(net.state_dict(),strict=True)
            aa,bb=evaluate(net,x);cc,dd=evaluate(fft,x)
            if err(aa,cc)>1e-11 or err(bb,dd)>1e-8:raise ValueError("FFT drift disagreement")
            p=net.first.physical_gain
            def val():
                o,state=net(x)
                return o.square().mean()+sum(k.square().mean() for k in tensors(state))
            target=torch.autograd.grad(val(),p)[0][0].item()
            eps=1e-6
            with torch.no_grad():
                initial=p[0].item();p[0]=initial+eps;hi=val().item();p[0]=initial-eps;lo=val().item();p[0]=initial
            fd=(hi-lo)/(2*eps)
            if abs(target-fd)>1e-6 or abs(target)<1e-7:raise ValueError("drift gradient mismatch")
            pairs.append(dict(atoms=atoms,cache=cache,state_error=err(aa,cc),gradient_error=err(bb,dd),gain_grad=target,fd=fd))
    steady=[]
    with torch.no_grad():
        for gain in (None,.15):
            cell=BoundaryPopulation(1,1,12,initial_physical_gain=gain)
            cell.sender.weight.fill_(1.);cell.sender.bias.zero_();cell.recurrent.weight.zero_();cell.feedback.zero_()
            cell.cache_prices=True
            for drive in (-2.,0.,.5,2.):
                frame=torch.tensor([[drive]],dtype=torch.float64)
                mu=cell.prices.mu-(gain or 0.)*float(np.tanh(drive))
                S,a=cell.kernels(cell.grid,None if gain is None else cell.grid.new_tensor(mu))
                ns=S.numpy();reset=cell.reset_weights.numpy()
                inv=np.linalg.solve(np.eye(len(ns))-ns,np.ones(len(ns)))
                rr=float(1/(1+reset@inv))
                if np.max(abs(ns.sum(1)+a.numpy()-1))>1e-10:raise ValueError("mass conservation")
                state=cell.initial(1);basis=cell._price_basis()
                message,state=cell.step(frame,state,basis);first=float(message[0,0,1])
                # At a constant wall the exact same Markov matrix is used at every subsequent tick.
                M=np.vstack((np.column_stack((ns,a.numpy())),np.append(reset,0.)))
                vec=np.concatenate((state[0].ravel().numpy(),state[1].ravel().numpy()))
                prediction=vec@np.linalg.matrix_power(M,4095)
                if abs(prediction[-1]-rr)>1e-8:raise ValueError("stationary flux mismatch")
                message2,state2=cell.step(frame,state,basis)
                np.testing.assert_allclose(np.append(state2[0].numpy(),state2[1].numpy()),vec@M,atol=5e-12)
                steady.append(dict(gain=gain,drive=drive,physical_mu=mu,first_flux=first,steady_flux_per_tick=rr,
                    continuum_rate=0. if mu>=0 else 1/(.25+.30/abs(mu)),finite_mesh_rate=rr/.25))
    report=dict(legacy_exact=True,new_pairs=pairs,clamped_drive=steady,device="cpu",torch=str(torch.__version__))
    (folder/"result.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report),flush=True)


if __name__=="__main__":main()
