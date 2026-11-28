"""Refine observed equilibria, verify full one-step autograd and test finite input histories."""
import json
import math
from pathlib import Path
import numpy as np
import torch
from allen import gaussian
from phase import Fixed


CASES=[(-.9,.65,6.),(-.3,0.,3.),(-.3,.02,3.),(0.,.65,.65)]


def check_eig(fixed,row):
    m=fixed.m
    drive=row["drive"];P=m.prices.p.P0*(1+.28*torch.tensor(drive,dtype=torch.float64))
    E,L=[z.detach()/20. for z in m.priced_channels(P)]
    num=[]
    for ro in row["roots"]:
        mass=torch.from_numpy(fixed.stationary([ro["mu"]])[0])
        def forward(a):
            baseline=m.prices.mu-.7*drive
            avg=(a*m.grid).sum()/a.sum()
            mu=baseline+row["equity_gain"]*(a@E).clamp_min(0).tanh()*(.3-avg)-row["loss_gain"]*(a@L).clamp_min(0).tanh()
            surv,hit=m.ramp_transport(a[None,:],mu[None,None])
            return surv[0]+(1-a.sum())*m.reset_weights
        j=torch.autograd.functional.jacobian(forward,mass).numpy()
        rad=float(abs(np.linalg.eigvals(j)).max())
        err=float((forward(mass)-mass).abs().max())
        if abs(rad-ro["radius"])>3e-6 or err>2e-10:raise ValueError((rad,ro,err))
        num.append(dict(torch_radius=rad,radius_error=abs(rad-ro["radius"]),torch_fixed_error=err))
    return num


def histories(fixed,drive,ke,kl):
    m=fixed.m;rho=fixed.rho
    # Both rows begin at the same reset. The only intervention is the earlier scalar input.
    mass=np.stack([rho,rho]);ref=np.zeros(2);old_b=np.zeros(2);quotes=np.zeros((2,2))
    memo={};times=[]
    for section,v,steps in [("condition",np.array([-.995,.995]),700),
                            ("common",np.array([drive,drive]),900)]:
        p=m.prices.p.P0*(1+.28*torch.from_numpy(v))
        E,L=[a.detach().numpy()/20 for a in m.priced_channels(p)]
        b=(m.prices.boundary(p)/m.prices.B0).log().numpy()
        for i in range(steps):
            mean=mass@fixed.grid/mass.sum(1)
            eq,loss=np.tanh(np.maximum(quotes,0)).T
            mu=m.prices.mu-.7*v+ke*eq*(.3-mean)-kl*loss+(old_b-b)/m.dt
            k=gaussian(m,mu);out=np.einsum("bi,bij->bj",mass,k)
            mass=out[:,:-1]+ref[:,None]*rho;ref=out[:,-1]
            quotes=np.stack([(mass*E).sum(1),(mass*L).sum(1)],-1);old_b=b
            if i in (0,9,99,steps-2,steps-1):times.append(dict(section=section,step=i+1,flux=ref.tolist(),drift=mu.tolist()))
        memo[section]=dict(flux=ref.tolist(),conditional_mean=(mass@fixed.grid/mass.sum(1)).tolist())
    return dict(endpoints=memo,samples=times)


def main(out):
    torch.set_num_threads(1);data={}
    for n,edge in ((12,1.3),(24,1.3),(48,1.3),(96,1.3),(48,2.6),(72,3.9),(96,5.2)):
        k=f"{n}-{edge}";fx=Fixed(n,edge,1025);rows=[]
        for case in CASES:
            row=fx.steady_roots(*case)
            if edge==1.3 and n==24:
                row["torch_autograd"]=check_eig(fx,row)
                row["input_histories"]=histories(fx,*case)
            rows.append(row)
        data[k]=rows
        tmp=out.with_suffix(".tmp");tmp.write_text(json.dumps(data,indent=1,allow_nan=False)+"\n");tmp.replace(out)
        print(k,[len(row["roots"]) for row in rows],flush=True)
if __name__=="__main__":main(Path(__file__).with_name("refined.json"))
