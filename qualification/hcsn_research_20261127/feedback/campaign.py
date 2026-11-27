"""Train, seal, cold-score and verify the preregistered HCSN mechanism matrix."""
import argparse
import gzip
import hashlib
import json
import os
import platform
import resource
import time
from pathlib import Path
import numpy as np
import torch
from datasets import load
from model import FeedbackBoundary, PlainCenteredGate, GAINS
from qualification.hcsn_closure_20261124.baselines import CausalTransformer, GRUClassifier, LIFClassifier
from qualification.hcsn_boundary_transfer_20261126.stream.run import metrics

HERE=Path(__file__).resolve().parent
PLAN=json.loads((HERE/"protocol.json").read_text())

def file_sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def write_once(path,data):
    with path.open("x") as f: json.dump(data, f,sort_keys=True,allow_nan=False,indent=2);f.write("\n")

def require_frozen():
    m=json.loads((HERE/"freeze.json").read_text())
    for name,digest in m.items():
        if file_sha(HERE/name)!=digest: raise ValueError("Frozen input changed: "+name)

def make(arm):
    if arm in GAINS: return FeedbackBoundary(arm,PLAN["width"])
    if arm=="plain": return PlainCenteredGate(PLAN["width"])
    return {"gru":GRUClassifier,"lif":LIFClassifier,"attention":CausalTransformer}[arm](PLAN["baseline_width"])

@torch.no_grad()
def predict(model, task, silence=False):
    x,y,ids,sources=task
    model.eval()
    probs=[]
    for b in x.split(16,1):
        logits=model(b,silence_boundary=True) if silence else model(b)
        probs.extend(logits[-1].softmax(-1)[:,1].cpu().tolist())
    if not np.isfinite(probs).all(): raise FloatingPointError("invalid probability")
    return metrics(probs,y.tolist(),sources),probs

def fit(args,task,arm,seed,train,dev):
    p=args.out/task/f"{arm}-{seed}"
    if (p/"fit.json").is_file():
        meta=json.loads((p/"fit.json").read_text())
        if meta["weights"]!=file_sha(p/"weights.pt"):raise ValueError("checkpoint checksum mismatch")
        return
    p.mkdir(exist_ok=True,parents=True)
    # A retry after interruption reruns the complete slot from its original seed.
    start=time.perf_counter(); cpu=time.process_time()
    torch.manual_seed(seed);model=make(arm);optim=torch.optim.Adam(model.parameters(),lr=.003)
    initial_state_sha=hashlib.sha256(b"".join(v.detach().cpu().numpy().tobytes() for _,v in model.named_parameters())).hexdigest()
    rng=torch.Generator().manual_seed(11*seed); x,y,_,_=train; history=[]; best=float("inf")
    for step in range(PLAN["updates"]+1):
        if step:
            model.train(); rows=torch.randperm(len(y),generator=rng)[:PLAN["batch"]]
            optim.zero_grad(set_to_none=True); scores=model(x[:,rows])[-1]
            loss=torch.nn.functional.cross_entropy(scores,y[rows]); loss.backward()
            norm=torch.nn.utils.clip_grad_norm_(model.parameters(),2)
            if not bool(torch.isfinite(loss)&torch.isfinite(norm)):raise FloatingPointError("invalid fit")
            optim.step()
        if step in PLAN["checkpoints"]:
            score,_=predict(model,dev);history.append(dict(step=step,brier=score["brier"],ba=score["balanced_accuracy"],elapsed=time.perf_counter()-start))
            if score["brier"]<best:
                best=score["brier"]; selected=step
                torch.save(model.state_dict(),p/"weights.tmp")
                os.replace(p/"weights.tmp",p/"weights.pt")
    param_count=sum(v.numel() for v in model.parameters())
    active=param_count
    if isinstance(model,FeedbackBoundary):
        active-=model.recurrent.weight.numel()-int(model.synaptic_mask.count_nonzero())
        active-=model.raw_boundary.numel()
    elif isinstance(model,PlainCenteredGate):
        active-=model.synapse.weight.numel()-int(model.mask.count_nonzero())
    vals=dict(task=task,arm=arm,seed=seed,train_rows=len(y),dev_rows=len(dev[1]),initial_trainable_sha=initial_state_sha,
              wall_seconds=time.perf_counter()-start,process_cpu_seconds=time.process_time()-cpu,
              process_high_water_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,updates=PLAN["updates"],
              selected_step=selected,history=history,parameters=param_count,active_after_known_masks=active,
              weights=file_sha(p/"weights.pt"),torch=str(torch.__version__),python=platform.python_version())
    write_once(p/"fit.json",vals)
    print("FIT",task,arm,seed,selected,round(best,6),round(vals["wall_seconds"],2),flush=True)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("mode",choices=["fit","confirm"]);parser.add_argument("--office",type=Path,required=True)
    parser.add_argument("--beijing",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--task",choices=PLAN["tasks"]);parser.add_argument("--arms",nargs="+",choices=PLAN["arms"])
    args=parser.parse_args();require_frozen()
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    if args.mode=="fit":
        for task in [args.task] if args.task else PLAN["tasks"]:
            root=getattr(args,task);train=load(task,root,"train");dev=load(task,root,"dev")
            for seed in PLAN["seeds"]:
                for arm in args.arms or PLAN["arms"]:fit(args,task,arm,seed,train,dev)
        return
    keys={}
    for task in PLAN["tasks"]:
        for seed in PLAN["seeds"]:
            for arm in PLAN["arms"]:
                key=f"{task}/{arm}-{seed}";p=args.out/key; meta=json.loads((p/"fit.json").read_text())
                assert meta["arm"]==arm and meta["seed"]==seed and meta["task"]==task
                if file_sha(p/"weights.pt")!=meta["weights"]:raise ValueError(key)
                keys[key]=[meta["weights"],file_sha(p/"fit.json")]
    seal={"frozen":file_sha(HERE/"freeze.json"),"slots":keys}
    if (args.out/"seal.json").exists():
        if seal!=json.loads((args.out/"seal.json").read_text()):raise ValueError("conflicting seal")
    else:write_once(args.out/"seal.json",seal)
    for task in PLAN["tasks"]:
        root=getattr(args,task);t=time.perf_counter();sample=load(task,root,"test");prep=time.perf_counter()-t
        x,y,ids,sources=sample
        for seed in PLAN["seeds"]:
            for arm in PLAN["arms"]:
                p=args.out/task/f"{arm}-{seed}";t=time.perf_counter()
                model=make(arm);model.load_state_dict(torch.load(p/"weights.pt",weights_only=True))
                score,probs=predict(model,sample); cold=time.perf_counter()-t
                silent=silent_probs=trace=None
                if arm in GAINS:
                    silent,silent_probs=predict(model,sample,silence=True)
                    with torch.no_grad():model(x[:,:8],trace=True)
                    trace=model.last_trace
                data={"task":task,"arm":arm,"seed":seed,"ids":ids,"sources":sources,"y":y.tolist(),"p":probs,
                      "p_silent":silent_probs,"score":score,"score_silent":silent,"trace":trace,"cold_score_s":cold,"shared_data_prepare_s":prep}
                if not (p/"predictions.json").exists():write_once(p/"predictions.json",data)
                else:
                    old=json.loads((p/"predictions.json").read_text())
                    for name in ("p","p_silent","ids","sources","y"):
                        if old[name]!=data[name]:raise ValueError("cold replay mismatch")
                print("EVAL",task,arm,seed,score["balanced_accuracy"],score["brier"],flush=True)

if __name__=="__main__":main()
