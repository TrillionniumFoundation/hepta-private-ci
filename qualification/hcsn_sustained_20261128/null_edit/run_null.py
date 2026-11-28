"""A null-space constrained model edit on the exact shared HCSN gallery projection."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from direct import make_net,parameters
from study import Data,HASHES,SEEDS,digest,write_json


def parent(root,edit,best,data):
    net=make_net(root,data,best["seed"]).eval()
    p=edit/best["path"]
    if digest(p)!=best["sha256"]:raise ValueError("parent digest")
    w=torch.load(p,map_location="cpu",weights_only=True)
    with torch.no_grad():
        for k,par in parameters(net).items():par.copy_(w[k])
    return net


@torch.inference_mode()
def features(net,data,rows):
    captured=[]
    handle=net.out[1].register_forward_pre_hook(lambda _m,args:captured.append(args[0].clone()))
    try:
        if rows is None:
            net.encode(net.text(data.tokens))
        else:
            for group in np.array_split(rows,(len(rows)+31)//32):
                net.encode(net.front(data.v[group],data.audio[group]))
    finally:
        handle.remove()
    return torch.cat(captured).numpy()


def normalized(x):
    return x/np.maximum(np.linalg.norm(x,axis=1,keepdims=True),1e-12)


def ridge_write(original,x,target,preserved,penalty):
    width=original.shape[1]
    if preserved is None:
        basis=np.eye(width);rank=0
    else:
        _,s,vh=np.linalg.svd(preserved,full_matrices=True)
        rank=int((s>s[0]*1e-7).sum())
        basis=vh[rank:].T
    B=x@basis
    if len(basis.T):
        gram=B.T@B+penalty*np.eye(B.shape[1])
        delta=np.linalg.solve(gram,B.T@(target-x@original.T)).T@basis.T
    else:
        delta=np.zeros_like(original)
    return (original+delta).astype(np.float32),rank


def adam(original,x,target,keys):
    w=torch.tensor(original,dtype=torch.float32,requires_grad=True)
    xx,tt,kk=map(lambda v:torch.as_tensor(v,dtype=torch.float32),(x,target,keys))
    keep=F.linear(kk,w.detach())
    opt=torch.optim.AdamW([w],lr=.001,weight_decay=.01,foreach=False)
    for _ in range(16):
        opt.zero_grad(set_to_none=True)
        loss=F.mse_loss(F.linear(xx,w),tt)+F.mse_loss(F.linear(kk,w),keep)
        loss.backward();opt.step()
    return w.detach().numpy()


def CE(z,labels):
    z=z-z.max(1,keepdims=True)
    return np.log(np.exp(z).sum(1))-z[np.arange(len(labels)),labels]


def calc(v,t,w,y):
    z=12*(normalized(v@w.T)@normalized(t@w.T).T)
    target=y.copy();edit=target<6;target[edit]=(target[edit]+1)%6
    loss=CE(z,target);pred=z.argmax(1)
    out={}
    for name,mask in (("edited",edit),("retained",~edit)):
        out[name]=dict(n=int(mask.sum()),nll=float(loss[mask].mean()),top1=float((pred[mask]==target[mask]).mean()))
    zp=z[edit,:6];out["edited_six"]=dict(nll=float(CE(zp,target[edit]).mean()),top1=float((zp.argmax(1)==target[edit]).mean()))
    return z,loss,pred,out


def run(root,original,out):
    out.mkdir(exist_ok=True,parents=True)
    if (out/"terminal.json").exists():return
    start=time.perf_counter()
    if any(digest(root/p)!=v for p,v in HASHES.items()):raise ValueError("data identity")
    sys.path.insert(0,str(root/"src"))
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    data=Data(root)
    old=json.loads((original/"seal.json").read_text())
    accepted=json.loads((original/"terminal.json").read_text())
    if digest(original/"seal.json")!=accepted["seal_sha256"]:raise ValueError("parent seal")
    chosen={s:min(old[f"same_site_bp-{s}"],key=lambda r:(r["development_nll"],r["steps"])) for s in SEEDS}
    prep=time.perf_counter()-start
    fits={}
    for seed,best in chosen.items():
        tic=time.perf_counter();net=parent(root,original,best,data)
        text=features(net,data,None).astype(float)
        tr=features(net,data,data.train).astype(float)
        y=data.y[data.train].numpy();mask=y<6
        x=tr[mask];yedit=(y[mask]+1)%6
        w=net.out[1].weight.detach().numpy().astype(float)
        target=normalized(text@w.T)[yedit]*np.linalg.norm(x@w.T,axis=1,keepdims=True)
        penalty=max(1e-9,.01*(x*x).sum()/x.shape[1])
        order=np.random.default_rng(seed+47000).permutation(np.flatnonzero(~mask))[:32]
        keys={n:np.vstack((text,tr[order[:n]])) for n in (0,8,32)}
        feature_s=time.perf_counter()-tic
        fits[seed]={}
        for name in ("parent","ridge","null0","null8","null32","adam8"):
            tic=time.perf_counter()
            anchors=None;rank=None
            if name.startswith("null"):
                n=int(name[4:]);anchors=keys[n]
            elif name=="adam8":anchors=keys[8]
            if name=="parent":write=w.astype(np.float32)
            elif name=="adam8":write=adam(w,x,target,anchors)
            else:write,rank=ridge_write(w,x,target,anchors,penalty)
            fit_s=time.perf_counter()-tic
            p=out/f"{seed}-{name}.npy";np.save(p,write)
            d=write.astype(float)-w
            fitted=x@write.T
            fits[seed][name]=dict(sha256=digest(p),weights=p.name,protected_rank=rank,
                null_dim=None if rank is None else len(w.T)-rank,training_edited_clips=len(x),
                protected_points=len(anchors) if anchors is not None else 0,
                protected_max_abs=None if anchors is None else float(abs(anchors@d.T).max()),
                gallery_max_abs=float(abs(text@d.T).max()),delta_frobenius=float(np.linalg.norm(d)),
                target_mse=float(np.mean((fitted-target)**2)),writable=write.size,
                feature_s=feature_s,fit_s=fit_s,original_parent_sha256=best["sha256"])
    seal=out/"fits.json"
    write_json(seal,fits)
    metrics={};cold={};cols={};times={}
    for seed,best in chosen.items():
        net=parent(root,original,best,data)
        text=features(net,data,None).astype(float)
        metrics[seed]={}
        for split,rows in (("dev",data.dev),("cold",data.test)):
            tic=time.perf_counter();v=features(net,data,rows).astype(float);feature_t=time.perf_counter()-tic
            y=data.y[rows].numpy()
            zs={};arrays={}
            for name,rec in fits[seed].items():
                path=out/rec["weights"];assert digest(path)==rec["sha256"]
                t0=time.perf_counter();w=np.load(path).astype(float)
                z,l,p,m=calc(v,text,w,y);zs[name]=z
                m["scoring_s"]=time.perf_counter()-t0;m["feature_s"]=feature_t
                metrics[seed].setdefault(name,{})[split]=m
                if split=="cold":
                    cold[seed,name]=l;cols[seed,name]=p
                    if name=="parent":
                        prior_file=original/Path(best["path"]).parent/"cold.npz"
                        with np.load(prior_file) as a:
                            np.testing.assert_array_equal(a["ids"],data.names[rows])
                            replay=float(abs(z-a["scores"]).max())
                            if replay>2e-4:raise ValueError("parent replay")
                            m["max_original_logit_discrepancy"]=replay
            p=out/f"{seed}-{split}.npz"
            np.savez_compressed(p,ids=data.names[rows],labels=y,**zs)
    actor=np.array(data.actors[data.test]);y=data.y[data.test].numpy()
    comparisons={}
    for name in fits[SEEDS[0]]:
        comps={}
        for part,sel in (("edited",y<6),("retained",y>=6)):
            a=actor[sel];who,idx=np.unique(a,return_inverse=True)
            deltas=np.mean([(cold[s,name]-cold[s,"parent"])[sel] for s in SEEDS],0)
            changes=np.mean([(cols[s,name]!=cols[s,"parent"])[sel] for s in SEEDS])
            draw=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
            sums=np.bincount(idx,weights=deltas);mass=np.bincount(idx)
            ci=np.quantile(sums[draw].sum(1)/mass[draw].sum(1),[.025,.975])
            comps[part]=dict(nll_change=float(deltas.mean()),ci95=ci.tolist(),changed_top1=float(changes))
        comparisons[name]=comps
    write_json(out/"terminal.json",dict(fit_seal_sha256=digest(seal),source_sha256=digest(Path(__file__)),
                previously_selected=chosen,metrics=metrics,paired_vs_parent=comparisons,common_prep_s=prep,
                all_elapsed=time.perf_counter()-start))
    print("terminal",digest(out/"terminal.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("root",type=Path);p.add_argument("edit",type=Path);p.add_argument("out",type=Path)
    a=p.parse_args();run(a.root.resolve(),a.edit.resolve(),a.out.resolve())
