"""Six finite hidden writes and a matched BP control on an identical audiovisual prefix."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys
import time
import numpy as np
import torch
from torch.nn import functional as F
from study import Data, digest, HASHES, SEEDS, inference, write_json, save_state

METHODS = ("forward", "shuffled", "head", "same_site_bp", "keep")
PREFIXES = (16, 128)


def parameters(net):
    return {**{f"read.{i}": mixer.read.weight for i,mixer in enumerate(net.mixer)},
            "projection": net.out[1].weight}


def ridge(x, y):
    x, y = x.double(), y.double()
    gram = x.T @ x
    penalty = max(1e-9, .01 * float(gram.diag().mean()))
    gram.diagonal().add_(penalty)
    return torch.linalg.solve(gram, x.T @ y).T.float()


def make_net(root, data, seed):
    from encoder import AVText
    return AVText("literal", 96, seed, data.words, root / "src/law4.npz")


@torch.no_grad()
def fit_forward(net, data, ids, method, seed):
    labels = data.y[ids]
    g = torch.Generator().manual_seed(seed + 71439)
    prototypes = torch.randn(6, 72, 96, generator=g)
    prototypes = F.normalize(prototypes, dim=-1) * (96 ** .5)
    final = F.normalize(torch.randn(72, 256, generator=g), dim=-1)
    hidden_labels = labels
    if method == "shuffled":
        hidden_labels = labels[torch.randperm(len(ids), generator=g)]
    hidden_labels = hidden_labels.repeat(2)
    h = torch.cat((net.front(data.v[ids], data.audio[ids]), net.text(data.tokens[labels])))
    lower = None
    for i,(m, n1, ff, n2) in enumerate(zip(net.mixer,net.n1,net.ff,net.n2)):
        features, residuals = [], []
        if method != "head":
            def hook(module, args):
                features.append(args[0][:,-1].clone())
            handle = m.read.register_forward_pre_hook(hook)
            for start in range(0,len(h),64):
                s = slice(start,start+64)
                out,_,_ = m(n1(h[s]), None if lower is None else lower[s], net.law)
                residuals.append((h[s]+out)[:,-1])
            handle.remove()
            before = torch.cat(residuals)
            target = prototypes[i,hidden_labels] * before.square().mean().sqrt()
            delta = ridge(torch.cat(features), target-before)
            m.read.weight.add_(delta,alpha=.5)
        new_h, marks = [], []
        for start in range(0,len(h),64):
            s = slice(start,start+64)
            out, mark, _ = m(n1(h[s]), None if lower is None else lower[s], net.law)
            u = h[s]+out
            new_h.append(u+ff(n2(u)))
            marks.append(mark)
        h,lower = torch.cat(new_h),torch.cat(marks)
    net.out[1].weight.copy_(ridge(net.out[0](h[:,-1]),final[labels.repeat(2)]))


def fit_same(net, data, ids):
    from encoder import pair_loss
    net.requires_grad_(False)
    chosen = list(parameters(net).values())
    for p in chosen:
        p.requires_grad_(True)
    opt = torch.optim.AdamW(chosen,lr=.0003,weight_decay=.01,foreach=False)
    for rows in ids.reshape(-1,16):
        y = data.y[rows]
        opt.zero_grad(set_to_none=True)
        av,tx = net(data.v[rows],data.audio[rows],data.tokens[y])
        loss = pair_loss(av,tx,y)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(chosen,1.,error_if_nonfinite=True)
        opt.step()


def fit(root,out,data,method,steps,seed):
    dst = out/f"{method}-{seed}-{steps}"
    dst.mkdir(exist_ok=True)
    meta = dst/"fit.json"
    if meta.exists():
        record = json.loads(meta.read_text())
        if digest(dst/"writes.pt") != record["sha256"]:
            raise ValueError("fit digest")
        return record
    start = time.perf_counter()
    model = make_net(root,data,seed)
    matrices = parameters(model)
    original = {k:v.detach().clone() for k,v in matrices.items()}
    gen = np.random.default_rng(seed+7369)
    ids = gen.choice(data.train,size=(steps,16)).ravel()
    before = time.perf_counter()
    if method == "same_site_bp":
        fit_same(model,data,ids)
    elif method != "keep":
        fit_forward(model,data,ids,method,seed)
    fit_s = time.perf_counter()-before
    ranks,changed = {},{}
    writes = {}
    for k,m in matrices.items():
        w = m.detach().clone()
        delta = w-original[k]
        ranks[k] = int(torch.linalg.matrix_rank(delta.double()))
        changed[k] = int(delta.count_nonzero())
        writes[k] = w
    pred = inference(model,data,data.dev)
    y = data.y[data.dev]
    save_state(dst/"writes.pt",writes)
    record = dict(method=method,seed=seed,steps=steps,training_examples=len(ids),
                  unique_training_examples=len(np.unique(ids)),input_index_sha256=hashlib.sha256(ids.astype("<i8").tobytes()).hexdigest(),
                  changed=changed,rank=ranks,optimization_s=fit_s,total_fit_dev_save_s=time.perf_counter()-start,
                  development_nll=float(F.cross_entropy(pred,y)),development_top1=float((pred.argmax(1)==y).float().mean()),
                  sha256=digest(dst/"writes.pt"),path=str(dst.relative_to(out)/"writes.pt"))
    write_json(meta,record)
    print("fit",method,seed,steps,round(record["development_nll"],5),round(fit_s,3),flush=True)
    return record


def execute(root,out):
    if (out/"terminal.json").is_file():
        return
    start = time.perf_counter()
    for r,h in HASHES.items():
        if digest(root/r) != h:
            raise ValueError("input mismatch "+r)
    sys.path.insert(0,str(root/"src"))
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    d=Data(root)
    preparation=time.perf_counter()-start
    records={}
    for seed_idx,seed in enumerate(SEEDS):
        for i in range(len(METHODS)):
            method=METHODS[(i+seed_idx)%len(METHODS)]
            rungs=(16,) if method=="keep" else PREFIXES
            records[f"{method}-{seed}"]=[fit(root,out,d,method,n,seed) for n in rungs]
    seal=out/"seal.json"
    if seal.exists() and json.loads(seal.read_text())!=records:
        raise ValueError("seal mismatch")
    if not seal.exists():
        write_json(seal,records)
    y=d.y[d.test]
    summary={}
    selected_losses={}
    for key,rr in records.items():
        best=min(rr,key=lambda r:(r["development_nll"],r["steps"]))
        coldrows=[]
        for r in rr:
            tic=time.perf_counter()
            model=make_net(root,d,r["seed"])
            p=out/r["path"]
            if digest(p)!=r["sha256"]:
                raise ValueError("cold digest")
            writes=torch.load(p,map_location="cpu",weights_only=True)
            with torch.no_grad():
                for k,m in parameters(model).items():
                    m.copy_(writes[k])
            scores=inference(model,d,d.test)
            losses=F.cross_entropy(scores,y,reduction="none").numpy()
            with (p.parent/"cold.npz").open("wb") as f:
                np.savez_compressed(f,ids=d.names[d.test],labels=y.numpy(),scores=scores.numpy())
            row=dict(steps=r["steps"],nll=float(losses.mean()),top1=float((scores.argmax(1)==y).float().mean()),cold_s=time.perf_counter()-tic)
            coldrows.append(row)
            if r==best:
                selected_losses[key]=losses
        selected=next(row for row in coldrows if row["steps"]==best["steps"])
        gates={}
        for g in (4.1,3.6):
            cumulative=preparation
            reached=None
            for r,row in zip(rr,coldrows):
                cumulative+=r["total_fit_dev_save_s"]+row["cold_s"]
                if r["development_nll"]<=g and row["nll"]<=g:
                    reached=dict(observed_steps=r["steps"],cumulative_seconds=cumulative)
                    break
            gates[str(g)]=reached
        summary[key]=dict(best_steps=best["steps"],chosen=selected,cold=coldrows,gates=gates,
                compared_prefixes_end_to_end_s=preparation+sum(r["total_fit_dev_save_s"] for r in rr)+sum(r["cold_s"] for r in coldrows))
    actors=d.actors[d.test];who=np.unique(actors);counts=np.array([(actors==a).sum() for a in who])
    ids=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    comparisons={}
    for method in METHODS[1:]:
        diff=np.stack([selected_losses[f"forward-{s}"]-selected_losses[f"{method}-{s}"] for s in SEEDS]).mean(0)
        sums=np.array([diff[actors==a].sum() for a in who])
        boot=sums[ids].sum(1)/counts[ids].sum(1)
        comparisons[method]=dict(mean=float(diff.mean()),ci95=np.quantile(boot,[.025,.975]).tolist())
    terminal=dict(seal_sha256=digest(seal),prepared_sha256=HASHES["data/data.npz"],source_sha256=digest(Path(__file__)),
                  device="cpu",torch=str(torch.__version__),preparation_s=preparation,execution_wall_s=time.perf_counter()-start,
                  cells=summary,forward_minus_control_nll=comparisons,actors=len(who),clips=len(y))
    write_json(out/"terminal.json",terminal)
    print("terminal",digest(out/"terminal.json"),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("parent",type=Path)
    parser.add_argument("out",type=Path)
    args=parser.parse_args()
    out=args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    with (out/"edit.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        execute(args.parent.resolve(),out)
