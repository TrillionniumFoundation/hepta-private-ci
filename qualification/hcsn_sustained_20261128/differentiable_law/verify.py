"""Check prices and reverse-mode derivatives at all inputs against an independent SciPy panel."""
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch_prices import price

ROOT=Path(__file__).resolve().parent
RES=json.loads((ROOT/"reference.json").read_text())["cases"]
PARAMS=("margin","rate","payout","sigma","tax","recovery","coupon","principal","maturity","premium")


def test(dtype,accumulation_dtype=None):
    args_raw=np.array([[[x,*rec["contract"]] for x in rec["margin"]] for rec in RES])
    true=np.array([rec["values"] for rec in RES])
    jac=np.array([rec["jacobian"] for rec in RES])
    raw=torch.tensor(args_raw,dtype=dtype,requires_grad=True)
    start=time.perf_counter()
    outs=price(*raw.unbind(-1),accumulation_dtype=accumulation_dtype)
    pred=torch.stack(outs,-1)
    deriv=torch.stack([torch.autograd.grad(v.sum(),raw,retain_graph=True)[0] for v in outs],-2)
    elapsed=time.perf_counter()-start
    pred,deriv=pred.detach().double().numpy(),deriv.detach().double().numpy()
    if not np.isfinite(pred).all() or not np.isfinite(deriv).all():raise ValueError("nonfinite")
    single=0.
    for i,row in enumerate(args_raw):
        for j,item in enumerate(row):
            q=torch.tensor(item,dtype=dtype)
            singles=torch.stack(price(*q.unbind(),accumulation_dtype=accumulation_dtype)).double().numpy()
            single=max(single,float(np.max(np.abs(pred[i,j]-singles))))
    absval=np.max(np.abs(pred-true),axis=(0,1))
    absjac=np.max(np.abs(deriv-jac),axis=(0,1,3))
    reljac=np.max(np.abs(deriv-jac)/(1+np.abs(jac)),axis=(0,1,2))
    x=torch.tensor([0.,-.1],dtype=dtype,requires_grad=True)
    pp=[torch.tensor(i,dtype=dtype) for i in RES[0]["contract"]]
    q=price(x,*pp)
    if not ((q.equity==0).all() and (q.hit==1).all() and (q.discounted_hit==1).all()):
        raise ValueError("absorption")
    if dtype==torch.float64:
        if absval.max()>1e-7 or reljac.max()>2e-6 or single>1e-9:
            raise ValueError((absval,reljac,single))
    return dict(dtype=str(dtype),accumulation_dtype=str(accumulation_dtype or dtype),reference_values=int(true.size),reference_partials=int(jac.size),
                max_abs_by_output=absval.tolist(),max_abs_derivative_by_output=absjac.tolist(),
                max_scaled_derivative_by_input=dict(zip(PARAMS,reljac.tolist())),max_batch_scalar=single,
                reverse_and_forward_s=elapsed)


def calibrate():
    # A synthetic inverse problem with only volatility and spread open.
    rec=RES[0];x=torch.linspace(.025,.75,16,dtype=torch.float64)
    p=torch.tensor(rec["contract"],dtype=torch.float64)
    def quotes(sigma,premium):
        v=price(x,p[0],p[1],sigma,p[3],p[4],p[5],p[6],p[7],premium)
        return torch.stack([v.boundary/60,v.equity/30,v.credit_loss/30,v.hit,v.discounted_hit])
    target=quotes(p[2],p[-1]).detach()
    raw=torch.tensor([np.log(.27),np.log(.025)],dtype=torch.float64,requires_grad=True)
    opt=torch.optim.LBFGS([raw],max_iter=60,tolerance_grad=1e-12,tolerance_change=1e-15,line_search_fn="strong_wolfe")
    seen=[]
    def closure():
        opt.zero_grad();sigma,pre=raw.exp()
        cost=(quotes(sigma,pre)-target).square().mean();cost.backward();seen.append(float(cost.detach()));return cost
    opt.step(closure)
    out=raw.detach().exp().numpy()
    if not np.allclose(out,[.23,.01],rtol=.0002,atol=2e-6):raise ValueError(out)
    return dict(initial=[.27,.025],true=[.23,.01],estimated=out.tolist(),initial_loss=seen[0],
                last_loss=seen[-1],closure_calls=len(seen))


if __name__=="__main__":
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    out=dict(torch=str(torch.__version__),outputs=["boundary","equity","credit_loss","hit","discounted_hit"],
             cases=len(RES),convention="absorbed x<=0 for equity and hit, constant recovery price at boundary",
             comparisons=[test(torch.float64),test(torch.float32),test(torch.float32,torch.float64)],two_parameter_synthetic_fit=calibrate())
    (ROOT/"verified.json").write_text(json.dumps(out,indent=2)+"\n")
    print(json.dumps(out),flush=True)
