"""Fit and seal nine supplemental arms; confirm only with a full immutable fit seal."""
import argparse
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

START = time.monotonic()

import numpy as np
import torch

from qualification.hcsn_qvi_retrieval import campaign
from qualification.hcsn_qvi_retrieval.adapt import fit_arm, FitConfig
from qualification.hcsn_qvi_retrieval.agent_edit import propose
from qualification.hcsn_qvi_retrieval.ndu import FiniteBellman, controls, policy_result, worst_delta
from .model import TaskSurface


HERE = Path(__file__).parent
digest, write = campaign.digest, campaign.put_json
CASES = list(itertools.product(campaign.PROTOCOL["methods"],campaign.PROTOCOL["seed"]))
MODE = "task_surface"


def sources():
    paths = [HERE/n for n in ("model.py","run.py","protocol.json")]
    paths += [campaign.HERE/n for n in ("campaign.py","ndu.py","adapt.py","dynamics.py",
                                         "agent_edit.py","protocol.json","data_manifest.json","media.py")]
    return {p.parent.name+"/"+p.name:digest(p) for p in paths}


def key(method,seed):
    return f"{MODE}-{method}-{seed}"


def configure(seed):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)


def frontend(model):
    def features(theta, split):
        x = split["xt"]
        # This is the free audio-retrieval margin, before standardization.
        current_margin = torch.from_numpy(split["x"][:,:,-2])
        y = model.features_with_edit(theta,x,split["clock"],current_margin)
        return torch.cat((x,y),-1).flatten(0,1)
    return features


def fit(args, out):
    configure(args.seed)
    train=campaign.shard(args.data,"train")
    dev,retain=(campaign.shard(args.data,s) for s in ("dev","retain"))
    mu = train["x"].mean((0,1))
    scale = train["x"].std((0,1)).clip(min=1e-8)
    for s in (train,dev,retain):
        campaign.prepare(s,mu,scale)
    evaluator=FiniteBellman(train)
    model=TaskSurface(train["x"].shape[-1],evaluator.edges,evaluator.q)
    features=frontend(model)
    initial=model.initial_edit_vector()
    incumbent={}
    def assess(theta,head):
        development=campaign.score_policy(features,theta,head,dev)
        retention=campaign.score_policy(features,theta,head,retain)
        if not incumbent:
            if bool(theta.ne(0).any()):
                raise ValueError("post-SVD incumbent must be evaluated first")
            incumbent.update(keep=retention,head=head.tolist())
        delta=worst_delta(retention,incumbent["keep"])
        return development["utility"],delta>=-.05-1e-12,{
            "dev":campaign.brief(development),"retain":campaign.brief(retention),"worst_retain_delta":delta}
    def editor(origin,diagnostics,probe):
        return propose(origin,diagnostics,model.edit_names,probe)
    editor.uses_train_probes=True
    result=fit_arm(args.method,initial,features,train,dev,config=FitConfig(),score=assess,
                   editor=editor if args.method=="wsp" else None)
    raw_boundary=model.task_boundaries(torch.from_numpy(train["x"][:,:,-2]))
    scale_by_prefix={
        "min":raw_boundary.min(0).values.tolist(), "max":raw_boundary.max(0).values.tolist(),
        "nominal":float(model.nominal_boundary),
    }
    write(out,dict(mode=MODE,method=args.method,seed=args.seed,train_hash=train["hash"],dev_hash=dev["hash"],
          retain_hash=retain["hash"],mean=mu.tolist(),scale=scale.tolist(),finite_edges=evaluator.edges.tolist(),
          finite_q=evaluator.q.tolist(),sources=sources(),names=model.edit_names,physical_channels=model.feature_names,
          fit=result.report,theta=result.theta.tolist(),head=result.head.tolist(),
          keep_theta=initial.tolist(),keep_head=incumbent["head"],train_boundary=scale_by_prefix,
          elapsed_seconds=time.monotonic()-START))


def check_seal(root):
    sealpath=root/"selection_seal.json"
    seal=json.loads(sealpath.read_text())
    expected={key(m,s)+".json" for m,s in CASES}
    if (set(seal["files"])!=expected or seal["sources"]!=sources() or
            any(digest(root/"fit"/n)!=h for n,h in seal["files"].items())):
        raise ValueError("the complete nine-arm fit and scientific source seal is required")
    return sealpath


def confirm(args,out):
    sealpath=check_seal(args.evidence)
    fit_path=args.evidence/"fit"/(key(args.method,args.seed)+".json")
    record=json.loads(fit_path.read_text())
    if record["sources"]!=sources():
        raise ValueError("cannot confirm changed fit source")
    configure(args.seed)
    test=campaign.shard(args.data,"test")
    campaign.prepare(test,np.asarray(record["mean"]),np.asarray(record["scale"]))
    model=TaskSurface(test["x"].shape[-1],record["finite_edges"],record["finite_q"])
    features=frontend(model)
    def score(prefix):
        return campaign.score_policy(features,torch.tensor(record[prefix+"theta"],dtype=torch.float64),
               torch.tensor(record[prefix+"head"],dtype=torch.float64),test)
    chosen,keep=score(""),score("keep_")
    references=controls(test)
    lookup=FiniteBellman.__new__(FiniteBellman)
    lookup.edges,lookup.q=np.asarray(record["finite_edges"]),np.asarray(record["finite_q"])
    references["empirical_bellman"]=policy_result(lookup.predict(test),test)
    delta=worst_delta(chosen,keep)
    write(out,dict(mode=MODE,method=args.method,seed=args.seed,test_hash=test["hash"],
          fit_hash=digest(fit_path),selection_seal=digest(sealpath),chosen=chosen,keep=keep,controls=references,
          actor=test["group"].tolist(),query_id=test["query_id"].tolist(),worst_actor_delta=delta,
          worst_vs_common_stop=worst_delta(chosen,references["immediate_stop"]),
          success=chosen["utility"]>=.60 and chosen["r1"]>=.70 and delta>=-.05-1e-12,
          elapsed_seconds=time.monotonic()-START))


def run(args):
    folder=args.evidence/args.phase
    folder.mkdir(parents=True,exist_ok=True)
    if args.phase=="confirm":
        check_seal(args.evidence)
    hashes={}
    for method,seed in CASES:
        name=key(method,seed)
        out,log,cost=(folder/(name+s) for s in (".json",".log",".cost.json"))
        if any(p.exists() for p in (out,log,cost)):
            raise FileExistsError(f"prior attempt {name}")
        cmd=[sys.executable,"-m","qualification.hcsn_qvi_task_surface.run",args.phase+"-one",str(args.data),
             str(args.evidence),"--method",method,"--seed",str(seed)]
        start=time.time()
        env={**os.environ,"OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
        with log.open("xb") as stream:
            result=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT,env=env)
        end=time.time()
        write(cost,dict(returncode=result.returncode,wall_seconds=end-start,start_unix=start,end_unix=end,
                        log_sha=digest(log),output_sha=digest(out) if out.exists() else None))
        if result.returncode:
            raise RuntimeError(f"failed {name}; inspect {log}")
        hashes[out.name]=digest(out)
    if args.phase=="fit":
        write(args.evidence/"selection_seal.json",dict(files=hashes,sources=sources(),cases=CASES))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("fit","confirm","fit-one","confirm-one"))
    parser.add_argument("data",type=Path)
    parser.add_argument("evidence",type=Path)
    parser.add_argument("--seed",type=int,choices=campaign.PROTOCOL["seed"])
    parser.add_argument("--method",choices=campaign.PROTOCOL["methods"])
    args=parser.parse_args()
    if args.phase in ("fit","confirm"):
        run(args)
    else:
        if args.seed is None or args.method is None:
            parser.error("individual cold process requires --seed and --method")
        phase=args.phase.split("-")[0]
        path=args.evidence/phase/(key(args.method,args.seed)+".json")
        if path.exists():
            raise FileExistsError(path)
        (fit if phase=="fit" else confirm)(args,path)


if __name__=="__main__":
    main()
