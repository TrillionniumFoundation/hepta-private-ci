"""Replay edited matrices through their sealed parents and re-score paired actor results."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch


def sha(p):
    with p.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def verify(source,prefix,root):
    sys.path[:0]=[str(prefix.parent),str(source/"src")]
    from direct import make_net,parameters
    from study import Data,inference
    data=Data(source)
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    result=json.loads((root/"terminal.json").read_text())
    fits=json.loads((root/"fits.json").read_text())
    if sha(root/"fits.json")!=result["fit_seal_sha256"]:raise ValueError("fit seal")
    largest=0.;count=0;loss={};pred={}
    for seed in ("137","311","557"):
        parent=result["previously_selected"][seed]
        net=make_net(source,data,int(seed)).eval()
        point=prefix/parent["path"]
        assert sha(point)==parent["sha256"]
        original=torch.load(point,weights_only=True,map_location="cpu")
        with torch.no_grad():
            for k,w in parameters(net).items():w.copy_(original[k])
        for split,ix in (("dev",data.dev),("cold",data.test)):
            with np.load(root/f"{seed}-{split}.npz") as vec:
                y0=vec["labels"]
                np.testing.assert_array_equal(y0,data.y[ix].numpy())
                np.testing.assert_array_equal(vec["ids"],data.names[ix])
                changed=y0<6
                y=np.where(changed,(y0+1)%6,y0)
                for method,entry in fits[seed].items():
                    wp=root/entry["weights"]
                    if sha(wp)!=entry["sha256"]:raise ValueError("matrix integrity")
                    w=np.load(wp)
                    with torch.no_grad():net.out[1].weight.copy_(torch.from_numpy(w))
                    actual=inference(net,data,ix).double().numpy()
                    scores=vec[method]
                    if not np.isfinite(actual).all() or scores.shape!=(len(ix),72):raise ValueError("raw logits")
                    err=np.abs(actual-scores).max()
                    if err>2e-4:raise ValueError((split,method,err))
                    largest=max(largest,float(err));count+=scores.size
                    ell=np.logaddexp.reduce(scores,axis=1)-scores[np.arange(len(ix)),y]
                    ixhat=scores.argmax(1)
                    for key,mask in (("edited",changed),("retained",~changed)):
                        m=result["metrics"][seed][method][split][key]
                        np.testing.assert_allclose([ell[mask].mean(),(ixhat[mask]==y[mask]).mean()],
                                                   [m["nll"],m["top1"]],atol=1e-12,rtol=1e-12)
                    if split=="cold":
                        pred[seed,method]=ixhat;loss[seed,method]=ell
    actor=np.array(data.actors[data.test]);edited=data.y[data.test].numpy()<6
    pairs=0
    for method,details in result["paired_vs_parent"].items():
        for k,mask in (("edited",edited),("retained",~edited)):
            unique,ix=np.unique(actor[mask],return_inverse=True)
            draw=np.random.default_rng(91363).integers(0,len(unique),(4000,len(unique)))
            delta=np.mean([(loss[s,method]-loss[s,"parent"])[mask] for s in fits],axis=0)
            changed=np.mean([(pred[s,method]!=pred[s,"parent"])[mask] for s in fits])
            sums=np.bincount(ix,weights=delta);counts=np.bincount(ix)
            intervals=np.quantile(sums[draw].sum(1)/counts[draw].sum(1),[.025,.975])
            m=details[k]
            np.testing.assert_allclose([delta.mean(),*intervals,changed],
                                       [m["nll_change"],*m["ci95"],m["changed_top1"]],atol=1e-11)
            pairs+=1
    return dict(verified=True,source_matrices=18,replayed_score_arrays=36,
                independently_replayed_and_rescored_logits=count,largest_fp32_model_vs_fp64_archive_abs=largest,
                paired_actor_contrasts=pairs,terminal_sha256=sha(root/"terminal.json"))


if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("source",type=Path);a.add_argument("prefix",type=Path);a.add_argument("out",type=Path)
    args=a.parse_args();m=verify(args.source,args.prefix,args.out)
    (args.out/"verification.json").write_text(json.dumps(m,indent=2)+"\n")
    print(m,flush=True)
