"""Compare table interpolation with direct absorption and independent Brownian-bridge sampling."""
import json
from pathlib import Path
import numpy as np
import torch
from model import Classifier, Population, exact_prob, physical_table, ATOMS, SIGMA, DT, ARMS


def main(out):
    torch.set_num_threads(1)
    rng=np.random.default_rng(8559)
    shift=rng.uniform(-.34,.34,3000);drift=rng.uniform(-.349,.149,3000)
    exact=exact_prob(shift,drift)
    arms={}
    for method in ('literal','smooth'):
        cell=Population(28,method)
        shift32=torch.tensor(shift,dtype=torch.float32);mu32=torch.tensor(drift,dtype=torch.float32)
        k=cell.transition(shift32,mu32)[0].detach().numpy()
        row=np.abs(exact-k)
        arms[method]=dict(max_error=float(row.max()),rmse=float(np.sqrt(np.square(row).mean())),
                          max_row_mass_error=float(np.abs(k.sum(-1)-1).max()),min_probability=float(k.min()))
    origin=exact_prob(0.,-.10);smooth=physical_table('smooth')[0][90,20]
    direct=physical_table('literal')[0][90,20];assert np.max(abs(origin-direct))<1e-12
    # On a frozen interval a bridge conditional on endpoints x and z>0 hits with exp(-2*x*z/(sigma²*dt)).
    # Unlike the formula for the killed density, this simulation generates endpoints and crossing marks.
    sims=[];N=250000
    for sh,mu in [(-.04,.08),(.011,-.23),(.11,-.03)]:
        theoretical=exact_prob(sh,mu);sampled=[]
        for x in ATOMS-sh:
            if x<=0: sampled.append([0.,0.,0.,0.,1.]);continue
            z=x+mu*DT+SIGMA*np.sqrt(DT)*rng.normal(size=N)
            safe=(z>0)&(rng.random(N)>np.exp(-2*x*z.clip(min=0)/(SIGMA**2*DT)))
            j=np.where(safe,np.searchsorted((ATOMS[:-1]+ATOMS[1:])/2,z),4)
            sampled.append((np.bincount(j,minlength=5)/N).tolist())
        obs=np.array(sampled);se=np.sqrt(theoretical*(1-theoretical)/N)
        sims.append(dict(wall_shift=sh,drift=mu,sampled=sampled,exact=theoretical.tolist(),
                         max_abs=float(np.abs(obs-theoretical).max()),
                         max_z=float(np.max(np.abs(obs-theoretical)[se>2/N]/se[se>2/N]))))
    torch.manual_seed(83051)
    grads={}
    for arm in ARMS:
        model=Classifier(arm)
        x=(torch.randn(3,28,28)*.6).requires_grad_(True)
        y=model(x);y.square().mean().backward()
        finite=all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
        grad=float(x.grad.norm()); entry=dict(params=sum(p.numel() for p in model.parameters()),
            finite=bool(finite),input_grad_norm=grad)
        if arm in ('literal','smooth','fixed','no_feedback'):
            # Compare a readout direction and an upstream projection direction away from exact kinks.
            directions={}
            for name,par in [('head',model.head.weight),('sender',model.one.inp.weight)]:
                direction=torch.randn_like(par);direction/=direction.norm()
                target=float((par.grad*direction).sum())
                prev=par.detach().clone()
                with torch.no_grad():
                    par.copy_(prev+.001*direction);plus=float(model(x).square().mean())
                    par.copy_(prev-.001*direction);minus=float(model(x).square().mean());par.copy_(prev)
                directions[name]=dict(autograd=target,numerical=(plus-minus)/.002,abs_error=abs(target-(plus-minus)/.002))
            entry['directions']=directions
        assert finite and grad>0,(arm,entry)
        grads[arm]=entry
    res=dict(torch=str(torch.__version__),validation_pairs=3000,arms=arms,table_origin_max_smooth=float(abs(origin-smooth).max()),
             bridge_draws_per_active_atom=N,bridge=sims,training_gradients=grads)
    out.write_text(json.dumps(res,indent=2)+'\n')
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('out',type=Path);main(p.parse_args().out)
