"""Held point and derivative checks for the real endogenous two-channel Torch operator."""
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import torch
from equity import EquityTransform
from transform import Law
from torch_equity import EndogenousWalls,equity_and_slopes
from torch_flow import value


def main():
    torch.set_num_threads(1);torch.set_default_dtype(torch.float64)
    out=[];gaps=[];forward=[]
    for j0,p0 in [((.7,.35),(.01,.05)),((.13,.92),(.025,.055)),((1.2,.45),(.055,.022))]:
        jumps=torch.tensor(j0,requires_grad=True);premia=torch.tensor(p0,requires_grad=True)
        walls=EndogenousWalls.apply(jumps,premia)
        knots=np.array([60.,float(walls.detach().mean()),88.,123.])
        V=torch.tensor(knots)
        E,S=equity_and_slopes(V,walls,jumps,premia)
        h=value(V,torch.tensor(1.),walls,jumps,premia,torch.tensor(.23))
        debt=value(V,torch.tensor(1.),walls,jumps,premia,torch.tensor(.23),bond=True)
        # Safe bond vector solves the nonabsorbing two-state ODE for this fixed duration.
        I=torch.eye(2);Q=torch.stack((torch.stack((-jumps[0],jumps[0])),torch.stack((jumps[1],-jumps[1]))))
        M=Q-torch.diag(.08+premia);steady=torch.linalg.solve(M,-6.39*torch.ones(2))
        safe=steady+torch.matrix_exp(M)@(61.68*torch.ones(2)-steady)
        loss=safe-debt;weight=torch.arange(1.,9.).reshape(4,2)/40
        f=((E/20-1.3*loss/20+.4*h)*weight).sum()
        autograd=torch.cat(torch.autograd.grad(f,(jumps,premia))).detach().numpy()
        def objective(params,detail=False):
            from scipy.linalg import expm
            ll=Law(rates=tuple(params[:2]),premia=tuple(params[2:]))
            solver=EquityTransform(ll,width=24.,terms=34,smooth=30)
            wall=solver.barriers();ll=replace(ll,barriers=tuple(wall))
            eq=np.array([solver.grid_free(wall,float(a))[1] for a in knots])
            hit=np.array([ll.value(a,1.,"first_hit",width=23.) for a in knots])
            b=np.array([ll.value(a,1.,"bond",width=23.) for a in knots])
            l,r=ll.rates;M=np.array([[-l,l],[r,-r]])-np.diag(.08+params[2:])
            st=np.linalg.solve(M,-np.full(2,6.39))
            loss=st+expm(M)@(np.full(2,61.68)-st)-b
            if detail:return [wall,eq,loss,hit]
            return np.sum(weight.numpy()*(eq/20-1.3*loss/20+.4*hit))
        p=np.array([*j0,*p0]);ref=objective(p,True)
        fwd=[float(np.max(abs(v-r))) for v,r in zip((walls.detach().numpy(),E.detach().numpy(),
                    loss.detach().numpy(),h.detach().numpy()),ref)]
        grad=[]
        for i in range(4):
            step=2e-4*max(p[i],.05);dx=np.eye(4)[i]*step
            z=[objective(p+n*dx) for n in (2,1,-1,-2)]
            grad.append((-z[0]+8*z[1]-8*z[2]+z[3])/(12*step))
        err=max(abs(autograd-np.asarray(grad))/np.maximum(1.,abs(autograd)))
        forward.extend(fwd);gaps.append(float(err))
        out.append(dict(rates=j0,premia=p0,walls=walls.tolist(),V=knots.tolist(),fit=S.tolist(),
                        differences=fwd,autograd=autograd.tolist(),reroot_fourth=grad,gradient_scaled_error=float(err)))
    assert max(forward)<3e-6 and max(gaps)<1e-4
    return dict(rows=out,forward_max=max(forward),gradient_scaled_max=max(gaps))
if __name__=="__main__":
    result=main()
    print(result["forward_max"],result["gradient_scaled_max"])
    Path(__file__).with_name("endogenous_verified.json").write_text(json.dumps(result,indent=2)+"\n")
