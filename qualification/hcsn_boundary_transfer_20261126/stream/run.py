"""Prospective chronological room-occupancy comparison with immutable source models."""
import argparse
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import time

ENTRY = time.perf_counter()
import numpy as np
import torch
from qualification.hcsn_closure_20261124.baselines import CausalTransformer, GRUClassifier, LIFClassifier
from qualification.hcsn_closure_20261124.boundary_fix import BoundaryControlHCSN
from qualification.hcsn_smallnet_20261124.model import ModelConfig

ARMS = ("qvi_raw", "qvi_centered", "qvi_signed", "qvi_joint", "learned_centered",
        "fixed_centered", "gru", "lif", "attention")
SEEDS = (601, 1601, 2601)
FILES = {
    "datatest.txt": "1b92c7c1b2838963464fa891a610cf3c5db4becb7189189b29b330107a584c7f",
    "datatraining.txt": "b2c4d0ce2b9e4e453c476f7125ef31aeec2d1f5c7f5572d0e80de3df6521ab56",
    "datatest2.txt": "d026d1bd5aeccd4aff4f3b3710d48e40613bd5fc370db7e61bbdcaa50d985095",
}
SOURCE = "c4ae70d44613434aaf165529a6076fa3400ca431"
DATA = "ba2b1d7b53a71292ff61b867d3e16f0e539c7eb6"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open("x") as out:
        json.dump(value, out, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
        out.write("\n")


def load_data(root, wanted):
    days = {}
    for name, digest in FILES.items():
        path = root/name
        if sha(path) != digest:
            raise ValueError("Source checksum mismatch: "+name)
        with path.open(newline="") as stream:
            rows = csv.reader(stream)
            next(rows)
            for row in rows:
                date = row[1][:10]
                split = "train" if date <= "2015-02-08" else "dev" if date <= "2015-02-11" else "test"
                if split not in wanted:
                    continue
                timestamp = datetime.datetime.fromisoformat(row[1])
                days.setdefault((split, date, name), []).append((timestamp, row[2:7], int(row[7])))
    by_split = {s: [] for s in wanted}
    for (split, date, name), rows in sorted(days.items()):
        windows = []
        for start in range(0, len(rows)-7, 8):
            chunk = rows[start:start+8]
            gaps = [(chunk[i][0]-chunk[i-1][0]).total_seconds() for i in range(1,8)]
            if any(d < 58 or d > 62 for d in gaps):
                continue
            values = [[*map(float, row[1]), delta-60] for row, delta in zip(chunk,[60,*gaps])]
            windows.append((chunk[-1][0].isoformat(), date, values, chunk[-1][2]))
        # Uniform deterministic selection over each source-day, independent of labels.
        indices = np.linspace(0,len(windows)-1,min(32,len(windows)),dtype=int)
        by_split[split].extend(windows[i] for i in indices)
    train_rows = by_split["train"]
    train_x = np.asarray([r[2] for r in train_rows])
    mean, std = train_x.mean(axis=(0,1)), train_x.std(axis=(0,1)).clip(1e-6)
    result = {}
    for key, rows in by_split.items():
        x = ((np.asarray([r[2] for r in rows])-mean)/std).clip(-6,6).astype("float32")
        result[key] = (torch.from_numpy(x).transpose(0,1), torch.tensor([r[3] for r in rows]),
                       [r[0] for r in rows], [r[1] for r in rows])
    return result


def model_for(arm):
    if arm in ("gru","lif","attention"):
        return {"gru": GRUClassifier, "lif": LIFClassifier, "attention": CausalTransformer}[arm](16)
    policy = arm.split("_")[0]
    cfg = ModelConfig(neurons=32, precision="mixed", backend="uniformized", boundary_mode=policy,
                      message_mode="full", feature_bank="value_risk", feature_normalization="none")
    channel = {"qvi_signed":"signed_only","qvi_joint":"boundary_signed"}.get(arm,"boundary_only")
    return BoundaryControlHCSN(cfg, channel=channel, control_mode="accumulate",
                               boundary_mode="raw" if arm in ("qvi_raw","qvi_signed") else "centered")


def metrics(p,y,dates):
    p = np.array(p,dtype=float)
    y = np.array(y,dtype=int)
    pred = p>=.5
    loss = -(y*np.log(p.clip(1e-12,1))+(1-y)*np.log((1-p).clip(1e-12,1)))
    recalls = [float((pred[y==k]==k).mean()) if (y==k).any() else None for k in (0,1)]
    day_scores = {d:float((pred[np.array(dates)==d]==y[np.array(dates)==d]).mean())
                  for d in sorted(set(dates))}
    return dict(n=len(y), positive=int(y.sum()), accuracy=float((pred==y).mean()),
                balanced_accuracy=float(np.mean([r for r in recalls if r is not None])),
                brier=float(np.mean((p-y)**2)), logloss=float(loss.mean()), by_day=day_scores)


@torch.no_grad()
def evaluate(model, data):
    model.eval()
    x,y,ids,dates = data
    predictions = torch.cat([model(block)[-1].softmax(-1)[:,1].cpu() for block in x.split(16,1)])
    if not torch.isfinite(predictions).all():
        raise ValueError("nonfinite predictions")
    p=predictions.tolist()
    return metrics(p,y.tolist(),dates), dict(id=ids,date=dates,y=y.tolist(),p=p)


def fit(args):
    root = args.output/f"{args.arm}-{args.seed}"
    root.mkdir(parents=True, exist_ok=False)
    data = load_data(args.data, ["train","dev"])
    torch.manual_seed(args.seed)
    model = model_for(args.arm)
    optimizer = torch.optim.Adam(model.parameters(), lr=.003)
    generator = torch.Generator().manual_seed(11*args.seed)
    x,y,_,_ = data["train"]
    history=[]
    best=float("inf")
    budget_best=float("inf")
    best_step=budget_step=None
    train_start=time.perf_counter()
    for step in range(129):
        if step:
            model.train()
            rows = torch.randperm(len(y),generator=generator)[:12]
            optimizer.zero_grad(set_to_none=True)
            logits=model(x[:,rows])[-1]
            loss=torch.nn.functional.cross_entropy(logits,y[rows])
            loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),2)
            if not torch.isfinite(loss) or not torch.isfinite(norm):
                raise FloatingPointError("Nonfinite training")
            optimizer.step()
        if step in (0,8,16,32,64,96,128):
            score,_ = evaluate(model,data["dev"])
            elapsed=time.perf_counter()-train_start
            history.append(dict(step=step,seconds=elapsed,dev=score))
            if score["brier"] < best:
                best=score["brier"]; best_step=step
                torch.save(model.state_dict(),root/"selected.pt")
            if elapsed<=20 and score["brier"]<budget_best:
                budget_best=score["brier"];budget_step=step
                torch.save(model.state_dict(),root/"wall20.pt")
    out={"arm":args.arm,"seed":args.seed,"updates":128,"train_rows":len(y),
         "validation_rows":len(data["dev"][1]),"selected_step":best_step,
         "wall20_selected_step":budget_step,"history":history,
         "parameters":sum(p.numel() for p in model.parameters()),
         "source":SOURCE,"data":DATA,"torch":str(torch.__version__),"cpu":platform.machine(),
         "fit_wall_from_entry":time.perf_counter()-ENTRY,"optimizer_and_val_wall":time.perf_counter()-train_start,
         "process_cpu_s":time.process_time(),"peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         "checkpoint_sha256":sha(root/"selected.pt"),
         "wall20_checkpoint_sha256":sha(root/"wall20.pt") if budget_step is not None else None}
    write_new(root/"fit.json",out)


def confirm(args):
    rows = {}
    for seed in SEEDS:
        for arm in ARMS:
            root=args.output/f"{arm}-{seed}"
            fit_data=json.loads((root/"fit.json").read_text())
            if fit_data["checkpoint_sha256"]!=sha(root/"selected.pt"):
                raise ValueError("checkpoint mismatch")
            rows[root.name]=[sha(root/"fit.json"),fit_data["checkpoint_sha256"],fit_data["wall20_checkpoint_sha256"]]
    write_new(args.output/"seal.json",{"script":sha(__file__),"protocol":sha(Path(__file__).with_name("protocol.md")),"roster":rows})
    data=load_data(args.data,["train","test"])["test"]
    results={}; predictions={}
    for seed in SEEDS:
        for arm in ARMS:
            root=args.output/f"{arm}-{seed}";model=model_for(arm)
            vals={}
            for comparison,filename,ind in [("fixed_updates","selected.pt",1),("wall20_prefix","wall20.pt",2)]:
                expected=rows[root.name][ind]
                if expected is None:
                    vals[comparison]=None
                    continue
                if sha(root/filename)!=expected:
                    raise ValueError("sealed file changed")
                model.load_state_dict(torch.load(root/filename,weights_only=True))
                score,p=evaluate(model,data);vals[comparison]=score
                predictions[root.name+"/"+comparison]=p
            results[root.name]=vals
    write_new(args.output/"test.json",results)
    write_new(args.output/"predictions.json",predictions)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["fit","confirm"])
    parser.add_argument("--data",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--arm",choices=ARMS)
    parser.add_argument("--seed",choices=SEEDS,type=int)
    args=parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    fit(args) if args.mode=="fit" else confirm(args)
