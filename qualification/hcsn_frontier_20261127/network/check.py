"""Check gradient flow, causality, state streaming and the counterfactual forecast API."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch


def run(core,out,build):
    sys.path.insert(0,str(core.resolve()));reach=Path(__file__).resolve().parents[1]/'reachable'
    sys.path.insert(0,str(reach))
    from population import BoundaryPopulation
    from compress import histories,queries
    from witness import Population
    from predictive import PredictiveSpikingNetwork,forced_flow,full_mass
    torch.set_num_threads(1);torch.manual_seed(77349)
    pop=Population(BoundaryPopulation(1,1,atoms=12))
    bank=queries(pop,histories(np.random.default_rng(92747),128,8,False))
    u,s,_=np.linalg.svd(bank-bank.mean(0),full_matrices=False)
    basis=Path(__file__).with_name('projection7.json')
    if build:
        basis.write_text(json.dumps({'atoms':12,'dt':.25,'generated_schedule_seed':92747,'columns':u[:,:7].tolist(),'singular_values':s.tolist()},indent=1)+'\n')
    network=PredictiveSpikingNetwork(3,2,2)
    frames=(torch.randn(6,2,3,dtype=torch.float64)*.12).requires_grad_(True)
    y,terminal=network(frames)
    early,part=network(frames[:3]);later,_=network(frames[3:],part)
    streaming=float((torch.cat([early,later])-y).abs().max().detach())
    assert streaming<1e-12
    replay=frames.detach().clone();replay[3:]+=1.
    causal=float((network(replay)[0][:3]-early).abs().max().detach());assert causal<1e-12
    objective=y.square().mean();objective.backward()
    grad={n:float(p.grad.norm()) for n,p in network.named_parameters()}
    assert all(np.isfinite(x) and x>1e-12 for x in grad.values())
    directions={}
    for key,p in [('inputs',frames),*network.named_parameters()]:
        g=p.grad.detach().clone();d=torch.randn_like(p)
        d/=d.norm()
        with torch.no_grad():
            original=p.clone()
            p.copy_(original+1e-5*d);plus=network(frames)[0].square().mean()
            p.copy_(original-1e-5*d);minus=network(frames)[0].square().mean()
            p.copy_(original)
        numeric=float((plus-minus)/2e-5);exact=float((g*d).sum())
        directions[key]={'backward':exact,'central_difference':numeric,'absolute_error':abs(numeric-exact)}
    assert max(x['absolute_error'] for x in directions.values())<1e-8
    plan=torch.tensor([.01,-.03,.07,-.08,0],dtype=torch.float64)[:,None,None].expand(5,2,2).clone().requires_grad_(True)
    flow=forced_flow(network.sender,terminal[0],plan)
    mass=full_mass(terminal[0]).detach().numpy();prev=0.;gaps=[]
    for j,level in enumerate(plan[:,0,0].detach().tolist()):
        mass=mass@pop.matrix(prev-level)[0]
        gaps.append(float(np.max(abs(flow[j].detach().numpy()-mass[...,-1]))))
        prev=level
    assert max(gaps)<1e-12
    plan_grad,=torch.autograd.grad(flow[-1].sum(),plan)
    assert torch.isfinite(plan_grad).all() and plan_grad.abs().max()>1e-12
    # Backpropagate a concrete supervised objective through both complete spiking cells.
    net=PredictiveSpikingNetwork(3,3,2)
    x=torch.randn(7,12,3,dtype=torch.float64)*.3
    target=(x[:,:,0].cumsum(0)>0).long()
    opt=torch.optim.AdamW(net.parameters(),lr=.01)
    history=[]
    for step in range(65):
        opt.zero_grad(set_to_none=True)
        logits,_=net(x)
        loss=torch.nn.functional.cross_entropy(logits.reshape(-1,2),target.flatten())
        loss.backward();opt.step();history.append(float(loss.detach()))
    assert history[-1]<history[0]
    r={'torch':torch.__version__,'basis_sha256':hashlib.sha256(basis.read_bytes()).hexdigest(),'streaming_error':streaming,'causality_error':causal,'named_grad_norms':grad,'directional_gradients':directions,'forced_query_forward_error_by_step':gaps,'forced_query_gradient_norm':float(plan_grad.norm()),'sanity_loss_curve':history,'scope':'synthetic implementation sanity check, no held-out task advantage inferred'}
    out.write_text(json.dumps(r,indent=1)+'\n')
    print(streaming,max(gaps),history[0],history[-1],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--core',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--build-basis',action='store_true')
    a=p.parse_args();run(a.core,a.out,a.build_basis)
