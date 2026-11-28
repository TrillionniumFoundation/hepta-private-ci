"""Inspect why the locked monotone readout can collapse to its intercept on real recorded ramps."""
import json
import numpy as np
from forecast import ROOT, EPS, DT, Model, put, sha, features, probability


def main():
    src=ROOT/"source"
    c=json.loads((src/"cohort.json").read_text())
    models=json.loads((ROOT/"results/seal.json").read_text())["models"]
    m=Model(src,ROOT/"law4.npz")
    out={};exposure={}
    for role,ids in [("train",c["train"]),("development",c["dev"]),("refit",c["train"]+c["dev"]),("held",c["held"])]:
        traces=m.traces(ids)
        exposure[role]=dict(specimens=len(ids),sweeps=len(traces),seconds=DT*sum(len(t[3]) for t in traces),spikes=sum(int(t[3].sum()) for t in traces),
             occupied=sum(int((t[3]>0).sum()) for t in traces),silent=sum(np.max(t[3])==0 for t in traces).item(),
             immediately_consecutive_occupied_pairs=sum(int(np.sum((t[3][1:]>0)&(t[3][:-1]>0))) for t in traces),
             per_specimen={str(sid):dict(sweeps=sum(t[0]==sid for t in traces),spikes=sum(int(t[3].sum()) for t in traces if t[0]==sid),seconds=DT*sum(len(t[3]) for t in traces if t[0]==sid)) for sid in ids})
        if role!="refit":continue
        for arm in ("dual","equity","loss","no_price","lif"):
            reg=models[arm]["selected"];opt=reg["opt"]
            X,valid,y,w=features(m,traces,arm,opt)
            z=(X[valid,0]-reg["mean"][0])/reg["sd"][0];w=w[valid];y=y[valid]
            b=float(np.log(-np.log1p(-np.average(y,weights=w))))
            q=np.exp(b);p=probability(np.array([b]))[0]
            gradient=float(np.dot(w*z,np.where(y,-q*np.exp(-q)/p,q)))
            def loss(step):
                v=probability(b+step*z)
                return float(np.dot(w,-np.where(y,np.log(v),np.log1p(-v))))
            out[arm]=dict(selected_option=opt,estimated_slope=reg["weights"][1],
                derivative_at_zero_slope=gradient,loss_at_flat=loss(0.),loss_at_positive_step=loss(.01),
                standardized_feature_at_eligible_events=np.average(z[y],weights=w[y]),standardized_feature_at_eligible_silent_bins=np.average(z[~y],weights=w[~y]))
    put(ROOT/"fit_diagnostics.json",dict(exposure=exposure,gradient_columns_use_train_plus_development=True,
        selected_conditional_models=out,source_seal_sha256=sha(ROOT/"results/seal.json")))


if __name__=="__main__":
    main()
