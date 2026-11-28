"""Finite hidden ridge writes with a single shared multimodal Fisher projection."""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from direct import make_net, parameters, ridge, fit_same
from study import Data, HASHES, SEEDS, digest, inference, write_json, save_state
from calibrate import fit as calibrate, stats

METHODS = ("full", "shuffled", "head", "bp")
REGIMES = ("raw", "temperature_prior")


def scatter_parts(x, labels):
    """Return within-class residuals and count-weighted class centroids."""
    labels = labels.long()
    used, inverse, counts = torch.unique(labels, sorted=True, return_inverse=True, return_counts=True)
    sums = x.new_zeros(len(used), x.shape[1])
    sums.index_add_(0, inverse, x)
    centroids = sums / counts[:, None]
    return x - centroids[inverse], counts.sqrt()[:, None] * (centroids - x.mean(0))


def fisher(x, labels, output_dim):
    x = x.double()
    residuals, centered = scatter_parts(x, labels)
    within = residuals.T @ residuals
    within.diagonal().add_(max(1e-9, .05 * float(within.diagonal().mean())))
    chol = torch.linalg.cholesky(within)
    whitened = torch.linalg.solve_triangular(chol, centered.T, upper=False)
    s, vectors = torch.linalg.eigh(whitened @ whitened.T)
    rank = min(len(centered)-1, int((s > s.max() * 1e-12).sum()), output_dim)
    if rank < 1:
        raise ValueError("zero-rank discriminant")
    projection = torch.linalg.solve_triangular(chol.T, vectors[:, -rank:], upper=True).T
    weights = x.new_zeros(output_dim, x.shape[-1])
    weights[:rank] = projection
    return weights.float(), rank


@torch.no_grad()
def construct(net, data, ids, method, seed):
    y = data.y[ids]
    yy = y.repeat(2)
    hidden_y = yy
    if method == "shuffled":
        rng = torch.Generator().manual_seed(seed + 71439)
        hidden_y = y[torch.randperm(len(y), generator=rng)].repeat(2)
    h = torch.cat([net.front(data.v[ids], data.audio[ids]), net.text(data.tokens[y])])
    lower = None
    for mixer, norm, ff, norm_ff in zip(net.mixer, net.n1, net.ff, net.n2):
        def step(i):
            sl = slice(i, i + 64)
            return mixer(norm(h[sl]), None if lower is None else lower[sl], net.law)
        if method != "head":
            features, residuals = [], []
            hook = mixer.read.register_forward_pre_hook(lambda _m, a: features.append(a[0][:, -1].clone()))
            try:
                for i in range(0, len(h), 64):
                    out, _, _ = step(i)
                    residuals.append((h[i:i+64] + out)[:, -1])
            finally:
                hook.remove()
            within, _ = scatter_parts(torch.cat(residuals).double(), hidden_y)
            mixer.read.weight.add_(ridge(torch.cat(features), -within), alpha=.5)
        nxt, marks = [], []
        for i in range(0, len(h), 64):
            out, mark, _ = step(i)
            r = h[i:i+64] + out
            nxt.append(r + ff(norm_ff(r)))
            marks.append(mark)
        h, lower = torch.cat(nxt), torch.cat(marks)
    w, rank = fisher(net.out[0](h[:, -1]), yy, net.out[1].out_features)
    net.out[1].weight.copy_(w)
    return rank


def evaluate(logits, y, mode, scale, logprior):
    bias = logprior if mode == "temperature_prior" else np.zeros_like(logprior)
    return stats(logits, y, scale if mode == "temperature_prior" else 1., bias)


def run(root, out):
    start = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("request a fresh output directory")
    for name, expected in HASHES.items():
        if digest(root/name) != expected:
            raise ValueError(name)
    sys.path.insert(0, str(root/"src"))
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    data = Data(root)
    count = np.bincount(data.y[data.train].numpy(), minlength=72)
    logprior = np.log(count / count.sum())
    ydev = data.y[data.dev].numpy()
    prep = time.perf_counter()-start
    candidates = {}
    for idx, seed in enumerate(SEEDS):
        for offset in range(len(METHODS)):
            method = METHODS[(idx+offset) % len(METHODS)]
            key = f"{method}-{seed}"
            candidates[key] = []
            for steps in (16,128):
                tic = time.perf_counter()
                ids = np.random.default_rng(seed+7369).choice(data.train, size=steps*16)
                net = make_net(root,data,seed)
                params = parameters(net)
                original = {k:p.detach().clone() for k,p in params.items()}
                if method == "bp":
                    fit_same(net,data,ids)
                    rank = None
                else:
                    rank = construct(net,data,ids,method,seed)
                writes = {k:p.detach().clone() for k,p in params.items()}
                changes = {k:int((v!=original[k]).sum()) for k,v in writes.items()}
                seconds = time.perf_counter()-tic
                path = out / f"{key}-{steps}.pt"
                save_state(path,writes)
                raw = inference(net,data,data.dev).double().numpy()
                z = calibrate(raw,ydev,logprior)
                dev = {mode:evaluate(raw,ydev,mode,z["multiplier"],logprior)[0] for mode in REGIMES}
                rec = dict(method=method,seed=seed,steps=steps,rank=rank,changed=changes,temperature=z["multiplier"],
                           fit_s=seconds,fit_through_validation_s=time.perf_counter()-tic,path=path.name,
                           file_sha256=digest(path),input_indices_sha256=hashlib.sha256(ids.astype("<i8").tobytes()).hexdigest(),
                           dev=dev)
                candidates[key].append(rec)
                print(key,steps,round(dev["raw"]["nll"],5),flush=True)
    picks = {k:{mode:min(rr,key=lambda r:(r["dev"][mode]["nll"],r["steps"]))["path"] for mode in REGIMES}
             for k,rr in candidates.items()}
    write_json(out/"development_seal.json", dict(candidates=candidates,picks=picks,counts=count.tolist(),input_sha256=HASHES))
    cold, losses, chosen, clocks, gates = {}, {}, {}, {}, {}
    y = data.y[data.test].numpy()
    for k,rr in candidates.items():
        losses[k], chosen[k], cold[k], clocks[k], gates[k] = {}, {}, {}, {}, {}
        elapsed = prep
        for r in rr:
            tic = time.perf_counter()
            net = make_net(root,data,r["seed"])
            path = out/r["path"]
            if digest(path)!=r["file_sha256"]:
                raise ValueError(path.name)
            w = torch.load(path,map_location="cpu",weights_only=True)
            with torch.no_grad():
                for n,v in parameters(net).items():
                    v.copy_(w[n])
            z = inference(net,data,data.test).double().numpy()
            np.savez_compressed(out/(path.stem+".npz"),scores=z.astype(np.float32),ids=data.names[data.test],labels=y)
            ms = {}
            for mode in REGIMES:
                ms[mode],ls = evaluate(z,y,mode,r["temperature"],logprior)
                if picks[k][mode]==path.name:
                    losses[k][mode] = ls
                    chosen[k][mode] = ms[mode]
            elapsed += r["fit_through_validation_s"] + time.perf_counter()-tic
            for mode in REGIMES:
                if max(ms[mode]["nll"],r["dev"][mode]["nll"]) <= 4.1 and mode not in gates[k]:
                    gates[k][mode] = dict(first_prefix=r["steps"],seconds=elapsed)
            cold[k][str(r["steps"])] = ms
        clocks[k] = elapsed
    actors=data.actors[data.test]
    who=np.unique(actors)
    draw=np.random.default_rng(91363).integers(len(who),size=(4000,len(who)))
    counts=np.array([(actors==a).sum() for a in who])
    differences = {}
    for mode in REGIMES:
        differences[mode] = {}
        for method in METHODS[1:]:
            delta = np.mean([losses[f"full-{s}"][mode]-losses[f"{method}-{s}"][mode] for s in SEEDS],axis=0)
            sums = np.array([delta[actors==a].sum() for a in who])
            differences[mode][method] = dict(nll=float(delta.mean()),ci95=np.quantile(sums[draw].sum(1)/counts[draw].sum(1),[.025,.975]).tolist())
    write_json(out/"terminal.json",dict(seal_sha256=digest(out/"development_seal.json"),script_sha256=digest(Path(__file__)),
               chosen=chosen,cold=cold,gates=gates,differences=differences,preparation_s=prep,charged_seconds=clocks,
               session_wall_s=time.perf_counter()-start,all_cold_scored=len(cold)*2))
    print("terminal",digest(out/"terminal.json"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("root",type=Path)
    p.add_argument("out",type=Path)
    a=p.parse_args()
    run(a.root.resolve(),a.out.resolve())
