"""Cold paired training of the literal two-layer HCSN on Optical Digits 0 vs 1."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import statistics
import subprocess
import sys
import tempfile
import time

import numpy as np

HERE=Path(__file__).resolve().parent
ARTIFACT=HERE/"digits01.npz"
ARTIFACT_SHA="64e0d2d6eefdf5690076708a08bc4ef38a2a8d996158f0c455386fdaf6ae255f"
SEEDS=(314,159)
GRIDS=(12,128)
UPDATES=16
CHECKS=(0,4,8,12,16)


def dataset():
    if hashlib.sha256(ARTIFACT.read_bytes()).hexdigest()!=ARTIFACT_SHA:
        raise ValueError("optical digits digest mismatch")
    with np.load(ARTIFACT,allow_pickle=False) as data:
        x=data["images"].astype(np.float64)/16
        y=data["labels"].astype(np.int64)
    rng=np.random.default_rng(20261128)
    train=[]; dev=[]; test=[]
    for c in (0,1):
        rows=rng.permutation(np.flatnonzero(y==c))
        n,m=int(.64*len(rows)),int(.80*len(rows))
        train.extend(rows[:n]);dev.extend(rows[n:m]);test.extend(rows[m:])
    return x,y,tuple(np.array(p) for p in (train,dev,test))


def arm(args):
    import torch
    from qualify_native import patched_module
    torch.set_num_threads(1)
    torch.manual_seed(args.seed)
    x,y,(train,dev,test)=dataset()
    starts=time.perf_counter()
    with tempfile.TemporaryDirectory() as t:
        mod=patched_module(HERE/"upstream",Path(t))
        model=mod.ContinuousSpikingNetwork(8,3,2,atoms=args.k,port="priced").double()
        model.first.matrix_free=model.second.matrix_free=args.mode=="fft"
        optim=torch.optim.AdamW(model.parameters(),lr=.016,weight_decay=.001)
        xt=torch.tensor(x,dtype=torch.float64).transpose(0,1)
        yt=torch.tensor(y,dtype=torch.long)
        schedule=np.random.default_rng(args.seed).choice(train,(UPDATES,8))
        def evaluate(ids):
            logits=[]
            with torch.no_grad():
                for group in np.array_split(ids, int(np.ceil(len(ids)/8))):
                    logits.append(model(xt[:,group])[0][-1])
                logits=torch.cat(logits)
                labels=yt[ids]
                acc=[float((logits.argmax(-1)[labels==c]==c).double().mean()) for c in (0,1)]
                return {"balanced_accuracy":sum(acc)/2,
                        "ce":float(torch.nn.functional.cross_entropy(logits,labels))}
        results=[]; task_start=time.perf_counter()
        for i in range(UPDATES+1):
            if i in CHECKS:
                scores=evaluate(dev)
                results.append({"updates":i,**scores,"seconds":time.perf_counter()-starts})
            if i==UPDATES: break
            ix=schedule[i]; optim.zero_grad(set_to_none=True)
            logits=model(xt[:,ix])[0][-1]
            torch.nn.functional.cross_entropy(logits,yt[ix]).backward()
            optim.step()
        held=evaluate(test)
        duration=time.perf_counter()-starts
    run={"k":args.k,"seed":args.seed,"mode":args.mode,"split_counts":[len(a) for a in (train,dev,test)],
         "updates":UPDATES,"batch":8,"hidden_width":3,"sequence_rows":8,"port":"priced",
         "dev":results,"time_to_dev_80_s":next((z["seconds"] for z in results if z["balanced_accuracy"]>=.80),None),
         "local_setup_training_eval_seconds":duration,"training_plus_final_eval_seconds":time.perf_counter()-task_start,
         "heldout_final":held,"torch":str(torch.__version__)}
    args.output.write_text(json.dumps(run,indent=2)+"\n")


def supervise(args):
    report={"dataset_sha256":ARTIFACT_SHA,"protocol":"class 0 vs 1; split seed 20261128; two paired seeds; sorted grid schedule",
            "arm_source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "runs":[],"paired":[]}
    for ki,k in enumerate(GRIDS):
        for si,seed in enumerate(SEEDS):
            modes=("dense","fft") if (ki+si)%2==0 else ("fft","dense")
            pair={}
            for mode in modes:
                with tempfile.TemporaryDirectory() as t:
                    path=Path(t)/"result.json"
                    start=time.perf_counter()
                    env={**os.environ,"OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1",
                         "ROCR_VISIBLE_DEVICES":"","CUDA_VISIBLE_DEVICES":""}
                    p=subprocess.run([sys.executable,__file__,"--arm","--mode",mode,"--k",str(k),"--seed",str(seed),
                                      "--output",str(path)],env=env,capture_output=True,text=True)
                    cold=time.perf_counter()-start
                    if p.returncode: raise RuntimeError(p.stderr[-3000:])
                    row=json.loads(path.read_text()); row["cold_wall_seconds"]=cold
                    report["runs"].append(row);pair[mode]=row
                    args.output.write_text(json.dumps(report,indent=2)+"\n")
                    print(mode,k,seed,round(cold,2),row["heldout_final"],flush=True)
            a,b=pair['dense'],pair['fft']
            comp={"k":k,"seed":seed,"cold_speed_ratio":a["cold_wall_seconds"]/b["cold_wall_seconds"],
                  "heldout_ce_absolute_gap":abs(a["heldout_final"]["ce"]-b["heldout_final"]["ce"]),
                  "heldout_balanced_accuracy_absolute_gap":abs(a['heldout_final']['balanced_accuracy']-b['heldout_final']['balanced_accuracy']),
                  "dev_ce_max_absolute_gap":max(abs(x["ce"]-y["ce"]) for x,y in zip(a["dev"],b["dev"])),
                  "both_reached_dev_80":a['time_to_dev_80_s'] is not None and b['time_to_dev_80_s'] is not None}
            report['paired'].append(comp)
            report['finished_pairs']=len(report['paired'])
            args.output.write_text(json.dumps(report,indent=2)+"\n")
    report["terminal"]=True
    args.output.write_text(json.dumps(report,indent=2)+"\n")


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--arm",action="store_true")
    p.add_argument("--mode",choices=("dense","fft"))
    p.add_argument("--k",type=int)
    p.add_argument("--seed",type=int)
    p.add_argument("--output",type=Path,default=HERE/"digits_cold.json")
    cfg=p.parse_args()
    (arm if cfg.arm else supervise)(cfg)
