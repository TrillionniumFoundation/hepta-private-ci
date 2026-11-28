"""Independently score all released readouts, including the preconditioned path."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import numpy as np
from fit_newton import DATA,ARMS,SEEDS,METHODS,load_data,make_features,law,digest,analytical_check


def calc(features,weights,expected,y):
    if digest(weights)!=expected:raise ValueError("input weight identity")
    with np.load(weights) as w:
        X=(features-w["mean"])/w["scale"]
        z=np.einsum("nd,dc->nc",X,w["w"],optimize=False)+w["b"]
        original=X@w["w"]+w["b"]
    loss=np.logaddexp.reduce(z,axis=1)-z[np.arange(len(y)),y]
    hit=z.argmax(1)==y
    return float(loss.mean()),float(hit.mean()),sha256(original.tobytes()).hexdigest()


def run(newton,precondition):
    x,y,_,(_,_,ix)=load_data(DATA)
    a=json.loads((newton/"seal.json").read_text())
    t=json.loads((newton/"terminal.json").read_text())
    assert digest(newton/"seal.json")==t["seal_sha"] and digest(newton/"per_clip.npz")==t["loss_sha"]
    b=json.loads((precondition/"seal.json").read_text())
    u=json.loads((precondition/"terminal.json").read_text())
    assert digest(precondition/"seal.json")==u["seal"]
    worst=0.;n=0;m=0
    for arm in ARMS:
        g=law(arm)
        for s in SEEDS:
            h=make_features(x[ix],arm,s,g)
            for method in METHODS:
                key=f"{arm}-{s}-{method}"
                loss,acc,zh=calc(h,newton/(key+".npz"),a[key]["sha"],y[ix])
                row=t["results"][key]
                assert zh==row["score_sha"]
                worst=max(worst,abs(loss-row["nll"]),abs(acc-row["top1"]));n+=1
            if arm!="returning":continue
            info=b[str(s)]
            for r in info["history"]:
                key=r["key"]
                loss,acc,_=calc(h,precondition/(key+".npz"),r["sha"],y[ix])
                row=u["results"][str(s)]["all_endpoints"][key]
                worst=max(worst,abs(loss-row["nll"]),abs(acc-row["accuracy"]));m+=1
            best=min(info["history"],key=lambda r:r["development"])["key"]
            assert best==info["best"]==u["results"][str(s)]["best"]
            for target,key in info["first"].items():
                assert key==next((r["key"] for r in info["history"] if r["development"]<=float(target)),None)
                if key:
                    ref=u["results"][str(s)]
                    assert ref["first"][target]["passed"]==(ref["all_endpoints"][key]["nll"]<=float(target))
    assert worst<1e-10
    return dict(newton_models=n,preconditioned_models=m,total_score_values=(n+m)*len(ix)*72,
                max_loss_or_accuracy_error=worst,analytic_hessian=analytical_check())


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("newton",type=Path);p.add_argument("precondition",type=Path)
    a=p.parse_args();r=run(a.newton,a.precondition)
    Path(__file__).with_name("verified.json").write_text(json.dumps(r,indent=2)+"\n");print(r)
