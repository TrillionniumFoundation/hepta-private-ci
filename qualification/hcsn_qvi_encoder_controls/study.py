"""Cold fitting and sealed confirmation for the preregistered encoder controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PRIMARY = HERE.with_name("hcsn_qvi_retrieval")
PLAN = json.loads((HERE / "protocol.json").read_text())
ARMS = [(m,a,s) for m, methods in PLAN["arms"].items() for a in methods for s in PLAN["seeds"]]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, obj):
    with path.open("x") as handle:
        json.dump(obj, handle, allow_nan=False, separators=(",", ":"))
        handle.write("\n")


def used_sources():
    return {str(p.relative_to(HERE.parent)):sha(p) for p in
            [HERE/"encoders.py",HERE/"study.py",HERE/"protocol.json",
             *[PRIMARY/f for f in ("adapt.py","campaign.py","ndu.py","protocol.json","data_manifest.json")]]}


def key(mode, method, seed):
    return f"{mode}-{method}-{seed}"


def worker(args):
    # Load numerical runtimes inside each measured cold process.
    import numpy as np
    import torch
    from .encoders import EconomyEncoder
    from qualification.hcsn_qvi_retrieval.adapt import fit_arm, FitConfig
    from qualification.hcsn_qvi_retrieval.campaign import shard, prepare, score_policy, brief
    from qualification.hcsn_qvi_retrieval.ndu import worst_delta

    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    mode, method, seed = args.mode, args.method, args.seed
    if (mode,method,seed) not in ARMS:
        raise ValueError("unregistered fit")
    stem = key(mode,method,seed)
    encoder = EconomyEncoder(mode,8,seed)

    def features(theta, s):
        result = encoder.features(theta, s["xt"], s["clock"])
        return result.reshape(-1, result.shape[-1])

    if args.phase == "fit":
        data = {n:shard(args.data,n) for n in ("train","dev","retain")}
        train = data["train"]
        mean = train["x"].mean(axis=(0,1))
        scale = train["x"].std(axis=(0,1)).clip(min=1e-8)
        for split in data.values():
            prepare(split, mean, scale)
        incumbent = {}

        def select(theta, head):
            dev = score_policy(features, theta, head, data["dev"])
            retained = score_policy(features, theta, head, data["retain"])
            if not incumbent:
                if bool(theta.ne(0).any()):
                    raise ValueError("nonzero initial edit")
                incumbent.update(theta=theta.tolist(), head=head.tolist(), retained=retained)
            delta = worst_delta(retained, incumbent["retained"])
            return dev["utility"], delta>=-0.05-1e-12, {
                "dev":brief(dev),"retain":brief(retained),"worst_retain_delta":delta}

        model = fit_arm(method, encoder.origin(), features, train, data["dev"],
                        score=select, config=FitConfig())
        if model.report["errors"] or model.report["cost"]["backward_calls"] != (4 if method=="bp" else 0):
            raise ValueError("declared fit failed or failed to perform its updates")
        record = {"mode":mode,"method":method,"seed":seed,"mean":mean.tolist(),"scale":scale.tolist(),
                  "params":encoder.counts(method),"sources":used_sources(),"numpy":np.__version__,"torch":torch.__version__,
                  "loaded_shards":{k:s["hash"] for k,s in data.items()},
                  "theta":model.theta.tolist(),"head":model.head.tolist(),"keep_theta":incumbent["theta"],
                  "keep_head":incumbent["head"],"fit":model.report}
    else:
        seal_path = args.evidence/"selection_seal.json"
        seal = check_seal(args.evidence)
        fit_path = args.evidence/"fit"/(stem+".json")
        fitted = json.loads(fit_path.read_text())
        if fitted["sources"] != used_sources():
            raise ValueError("source changed after fitting")
        test = shard(args.data,"test")
        prepare(test, np.asarray(fitted["mean"]), np.asarray(fitted["scale"]))
        chosen, keep = [score_policy(features, torch.tensor(fitted[prefix+"theta"],dtype=torch.float64),
                                     torch.tensor(fitted[prefix+"head"],dtype=torch.float64), test)
                        for prefix in ("","keep_")]
        delta = worst_delta(chosen,keep)
        record = {"mode":mode,"method":method,"seed":seed,"test_hash":test["hash"],
                  "fit_sha256":seal["files"][fit_path.name],"seal_sha256":sha(seal_path),
                  "query_id":test["query_id"].tolist(),"group":test["group"].tolist(),
                  "chosen":chosen,"keep":keep,"worst_actor_delta":delta,
                  "success":chosen["utility"]>=.60 and chosen["r1"]>=.70 and delta>=-.05-1e-12}
    write_new(args.evidence/args.phase/(stem+".json"),record)


def check_seal(evidence):
    seal = json.loads((evidence/"selection_seal.json").read_text())
    expected = {key(*arm)+".json" for arm in ARMS}
    if set(seal["files"]) != expected or seal["sources"] != used_sources():
        raise ValueError("incorrect model or source set in selection seal")
    if any(sha(evidence/"fit"/n)!=digest for n,digest in seal["files"].items()):
        raise ValueError("selected fit altered")
    return seal


def launch(args):
    if args.phase=="confirm":
        check_seal(args.evidence)
    if args.phase=="fit" and (args.evidence/"selection_seal.json").exists():
        raise FileExistsError("selection already sealed")
    parent = args.evidence/args.phase
    parent.mkdir(parents=True,exist_ok=False)
    env={**os.environ, "OMP_NUM_THREADS":"1", "OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    selected = {}
    for mode,method,seed in ARMS:
        stem=key(mode,method,seed)
        output=parent/(stem+".json")
        log=parent/(stem+".log")
        args_for_child=[sys.executable,"-m","qualification.hcsn_qvi_encoder_controls.study",
                        args.phase,str(args.data),str(args.evidence),"--worker","--mode",mode,
                        "--method",method,"--seed",str(seed)]
        started=time.time()
        clock=time.monotonic()
        before=resource.getrusage(resource.RUSAGE_CHILDREN)
        with log.open("xb") as fh:
            proc=subprocess.run(args_for_child,env=env,stdout=fh,stderr=subprocess.STDOUT)
        elapsed=time.monotonic()-clock
        after=resource.getrusage(resource.RUSAGE_CHILDREN)
        cost={"returncode":proc.returncode,"start_unix":started,"end_unix":time.time(),"wall_seconds":elapsed,
              "child_cpu_seconds":after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
              "output_sha256":sha(output) if output.exists() else None,"log_sha256":sha(log)}
        write_new(parent/(stem+".cost.json"),cost)
        if proc.returncode:
            raise RuntimeError(str(log))
        selected[output.name]=sha(output)
        print(args.phase,stem,round(elapsed,3),flush=True)
    if args.phase=="fit":
        write_new(args.evidence/"selection_seal.json",{"files":selected,"sources":used_sources(),"arms":ARMS})
        check_seal(args.evidence)


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("phase",choices=("fit","confirm"))
    cli.add_argument("data",type=Path)
    cli.add_argument("evidence",type=Path)
    cli.add_argument("--worker",action="store_true")
    cli.add_argument("--mode")
    cli.add_argument("--method")
    cli.add_argument("--seed",type=int)
    args=cli.parse_args()
    worker(args) if args.worker else launch(args)
