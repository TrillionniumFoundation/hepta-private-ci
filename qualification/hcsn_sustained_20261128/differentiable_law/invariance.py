"""Finite indistinguishable contracts and the analytic null direction for the full quote function."""
import json
from pathlib import Path

import numpy as np
import torch
from torch_prices import price


def run():
    src=Path(__file__).with_name("reference.json")
    exact_res=[]
    for row in json.loads(src.read_text())["cases"]:
        p=torch.tensor(row["contract"],dtype=torch.float64,requires_grad=True)
        x=torch.linspace(.002,1.0,81,dtype=torch.float64)
        def quotes(pp):return torch.stack(price(x,*pp.unbind()),dim=-1)
        z=quotes(p)
        B=z[0,0].detach()
        q=(p[0]+p[-1]).detach();C=p[5].detach()
        scales=torch.tensor([60.,30.,30.,1.,1.],dtype=torch.float64)
        direction=torch.zeros_like(p)
        direction[3]=(1-p[3].detach())/C
        direction[4]=1/(q*B)
        direction[5]=1;direction[6]=1/q
        _,der=torch.autograd.functional.jvp(quotes,(p,),(direction,))
        # Contract rank at three margins. All margins share exactly the same B.
        small=x[[2,23,61]]
        jac=torch.autograd.functional.jacobian(lambda pp:torch.stack(price(small,*pp.unbind()),dim=-1),p)
        scaled=jac/scales[:,None]*p.detach().abs().clamp_min(.02)
        singular=torch.linalg.svdvals(scaled.reshape(-1,9))
        tests=[]
        for f in (-.02,-.01,.01,.025):
            h=f*float(C)
            changed=p.detach().clone()
            changed[5]+=h;changed[6]+=h/q;changed[4]+=h/(q*B)
            changed[3]=1-(1-p[3].detach())*C/changed[5]
            check=quotes(changed)
            dif=(check-z).abs().amax(0).detach().tolist()
            if max(dif)>1e-8 or float(der.abs().max())>1e-9:raise ValueError((dif,der.abs().max()))
            tests.append(dict(h=h,changed_contract=changed.tolist(),max_by_channel=dif))
        exact_res.append(dict(contract=p.detach().tolist(),boundary=float(B),direction=direction.tolist(),
                              max_jvp=float(der.abs().max()),singular_values=singular.detach().tolist(),changes=tests))
    return exact_res


if __name__=="__main__":
    torch.set_num_threads(1)
    r=run()
    out=dict(contracts=len(r),finite_edits=sum(len(v["changes"]) for v in r),
             margins_per_contract=81,observables_per_margin=5,cases=r,
             worst_jvp=max(v["max_jvp"] for v in r),
             max_finite_abs=max(max(j["max_by_channel"]) for v in r for j in v["changes"]))
    Path("invariance.json").write_text(json.dumps(out,indent=2)+"\n")
    print(out["max_finite_abs"],out["worst_jvp"],r[0]["singular_values"],flush=True)
