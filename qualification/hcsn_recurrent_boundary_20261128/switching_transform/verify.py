"""Independent PDE, single-regime formula, autograd, and equilibrium differencing controls."""
from dataclasses import replace
import json
import sys
from pathlib import Path
import numpy as np
import torch
from equity import EquityTransform
from transform import Law
from torch_flow import value
this=Path(__file__).resolve().parent
sys.path.insert(0,str(this.parent.parent/"hcsn_sustained_20261128"/"resolvent"))
from closed_form import Prices,Contract


def check():
    torch.set_num_threads(1);torch.set_default_dtype(torch.float64)
    base=Law();pde=json.loads((this.parent/"stationary_switching"/"verified.json").read_text())
    default=Contract()
    rows={};static_errors=[];sum_errors=[];permute=[]
    for name,jump in [("fixed",(0.,0.)),("permanent_down",(.7,0)),("returning",(.7,.35))]:
        law=replace(base,rates=jump);model=EquityTransform(law);walls=model.barriers()
        law=replace(law,barriers=tuple(walls));ref=pde["grids"]["1536"][name]
        vals={m:[] for m in ("first_hit","bond","equity")}
        for V in pde["probes"]:
            vals["equity"].append(model.grid_free(walls,V)[1].tolist())
            for m in ("first_hit","bond"):vals[m].append(law.value(V,1.,m,width=24.).tolist())
        errs={m:float(np.max(abs(np.array(vals[m]).T-np.array(ref[{"first_hit":"hit"}.get(m,m)])))) for m in vals}
        errs["wall"]=float(np.max(abs(np.asarray(ref["walls"])-walls)))
        if name=="fixed":
            for i,prem in enumerate(law.premia):
                orig=Prices(replace(default,premium=prem))
                static_errors.append(abs(walls[i]-orig.boundary))
                for j,V in enumerate(pde["probes"]):
                    x=np.log(V/orig.boundary)
                    static_errors.extend(abs(vals[m][j][i]-v) for m,v in
                                         (("equity",orig.equity(x)),("bond",orig.bond(x)),("first_hit",orig.hit(x))))
        if name=="returning":
            for A in (18.4,24.,26.):
                chk=EquityTransform(law,width=A,terms=36,smooth=32)
                w2=chk.barriers()
                sum_errors.append(float(np.max(abs(walls-w2))))
            flip=replace(law,barriers=law.barriers[::-1],rates=jump[::-1],premia=law.premia[::-1])
            flip_solver=EquityTransform(flip)
            permute.extend(abs(flip_solver.barriers()[::-1]-walls))
            for V in (72.,73.55,82.,90.,115.):
                permute.extend(abs(flip_solver.grid_free(flip.barriers,V)[1][::-1]-model.grid_free(walls,V)[1]))
                for m in ("first_hit","bond"):
                    permute.extend(abs(flip.value(V,1,m)[::-1]-law.value(V,1,m)))
        rows[name]=dict(walls=walls.tolist(),max_pde_errors=errs,values=vals)
    assert max(static_errors)<5e-7 and max(sum_errors)<2e-6 and max(permute)<2e-6
    assert max(max(r["max_pde_errors"].values()) for r in rows.values())<.01
    walls=np.array(rows["returning"]["walls"]);law=replace(base,barriers=tuple(walls))
    spots=np.array([72.,(walls[0]+walls[1])/2,82.,90.,115.])
    t=1.
    scores=np.arange(1.,11).reshape(5,2)/50
    deriv={};all_checks=[]
    for m in ("first_hit","bond"):
        args=[torch.tensor(x,requires_grad=True) for x in (spots,t,walls,np.array(law.rates),np.array(law.premia),law.sigma)]
        out=value(*args,bond=m=="bond")
        ref=np.array([law.value(v,t,m,width=24.,terms=34,smooth=30) for v in spots])
        forward=float(np.max(abs(ref-out.detach().numpy())))
        ag=torch.autograd.grad((out*torch.as_tensor(scores)).sum(),args,allow_unused=True)
        def objective(vals):
            V,tt,w,j,p,sig=vals
            ll=replace(law,barriers=w,rates=j,premia=p,sigma=sig)
            return np.sum(scores*np.array([ll.value(v,tt,m,width=22.,terms=32,smooth=27) for v in V]))
        vals=[spots,np.array(t),walls,np.array(law.rates),np.array(law.premia),np.array(law.sigma)]
        comparisons={}
        for i,key in enumerate(("assets","time","walls","switch_rates","premia","sigma")):
            ans=np.zeros_like(vals[i]);target=np.zeros_like(ans) if ag[i] is None else ag[i].detach().numpy()
            for ix in np.ndindex(ans.shape):
                step=1e-3*max(float(abs(vals[i][ix])),.05)
                samples=[]
                for mult in (2.,1.,-1.,-2.):
                    z=[a.copy() for a in vals];z[i][ix]+=mult*step
                    samples.append(objective(z))
                ans[ix]=(-samples[0]+8*samples[1]-8*samples[2]+samples[3])/(12*step)
            absolute=float(np.max(abs(target-ans)))
            scaled=float(np.max(abs(target-ans)/np.maximum(1.,abs(target))))
            comparisons[key]=dict(autograd=target.tolist(),finite_difference=ans.tolist(),
                                  absolute_error=absolute,scaled_error=scaled)
            all_checks.append(scaled)
        assert forward<2e-7
        deriv[m]=dict(forward=forward,derivatives=comparisons)
    assert max(all_checks)<2e-5
    # Compute the IFT slope while holding the candidate wall fixed at each call.
    # Compare to fresh independent full coupled-equilibrium roots at perturbed rates.
    model=EquityTransform(law)
    def central(fn,v,idx,h):
        z1=v.copy();z2=v.copy();z1[idx]+=h;z2[idx]-=h
        return (fn(z1)-fn(z2))/(2*h)
    j=np.array(law.rates)
    J=np.column_stack([central(model.grid_free,walls,i,1e-3) for i in (0,1)])
    H=np.column_stack([central(lambda z: EquityTransform(replace(law,rates=z)).grid_free(walls),j,i,1e-4) for i in (0,1)])
    implicit=-np.linalg.solve(J,H)
    direct=np.column_stack([central(lambda z: EquityTransform(replace(law,rates=z)).barriers(),j,i,2e-4) for i in (0,1)])
    assert np.max(abs(implicit-direct))<5e-4
    return dict(contract=base.__dict__,parameters={"width":22,"terms":29,"smooth":24},rows=rows,
                static_max=float(max(static_errors)),permutation_max=float(max(permute)),
                inversion_wall_changes=sum_errors,
                differentiable=deriv,implicit_barrier=dict(jacobian=J.tolist(),condition=float(np.linalg.cond(J)),
                implicit=implicit.tolist(),resolved=direct.tolist(),error=float(np.max(abs(implicit-direct)))))
if __name__=="__main__":
    j=check();print(j["static_max"],j["inversion_wall_changes"],j["implicit_barrier"])
    (this/"verified.json").write_text(json.dumps(j,indent=2)+"\n")
