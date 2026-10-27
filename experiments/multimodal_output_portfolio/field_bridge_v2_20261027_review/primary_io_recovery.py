"""Restart the identical frozen primary evaluation after a temporary-directory fault.

The only deployment changes are a distinct retained output directory and one
fresh /tmp directory per batch. The frozen deploy_batch, models, predictors,
random marks, observations, actions, labels, scores and inference remain intact.
"""

import argparse
import gzip
import json
from pathlib import Path
import tempfile
import time

import numpy as np

from ..field_bridge_v2_20261027.primary_evaluate import deploy_batch
from ..field_bridge_v2_20261027.primary_common import P, source_freeze, setup_primary, load_checkpoint
from ..field_bridge_v2_20261027.learning import make_model
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from ..field_bridge_v2_20261027.primary_media import MediaStore
from ..field_bridge_20261027.run import digest, write_json, object_hash
from ..v6.data import make_batch
from ..v6.neural import parameter_hash


def verify_recovery(args):
    root=Path(args.out).resolve()
    record=json.loads((root/"IO_RECOVERY_REGISTRATION.json").read_text())
    if (digest(__file__)!=record["recovery_source_sha256"]
            or digest(root/"PRETEST_FREEZE.json")!=record["pretest_freeze_sha256"]
            or source_freeze()!=record["unchanged_scientific_sources"]
            or args.registered_commit!=record["original_pretest_commit"]):
        raise ValueError("Recovery source or frozen scientific objects changed")
    for relative, identity in record["partial_attempt_files_sha256"].items():
        if digest(root/relative)!=identity:
            raise ValueError("Preserved original partial attempt changed")
    return record


def evaluate(args):
    verify_recovery(args)
    root = Path(args.out).resolve()
    frozen = json.loads((root / "PRETEST_FREEZE.json").read_text())
    if source_freeze()!=frozen["source_files"] or object_hash(P)!=frozen["protocol_sha256"]:
        raise ValueError("Primary decision source differs from the pretest freeze")
    for relative, identity in frozen["files_sha256"].items():
        if digest(root / relative)!=identity:
            raise ValueError(f"Frozen primary input changed: {relative}")
    corpus, observers, originals, identities = setup_primary(args,audit=True)
    seed, info = args.seed, frozen["seeds"][str(args.seed)]
    models={"frozen":make_model(originals[seed],seed,info["recipe"])}
    for profile in ("ordinary","field","generic","richer"):
        models[profile],_,_=load_checkpoint(root/"training"/str(seed)/f"{profile}.pt",originals[seed],seed,info["recipe"])
    out=root/"eval_recovered"/str(seed)
    out.mkdir(parents=True,exist_ok=False)
    media=MediaStore(out/"media.zip")
    arms={**P["canonical_arms"],**P["supplementary_arms"]}
    order=list(arms); np.random.default_rng(seed+271027).shuffle(order)
    count,started=0,time.perf_counter_ns()
    with NativeFastBridge(args.native,frozen["native_library_sha256"]) as bridge, \
            gzip.open(out/"rows.jsonl.gz","xt",encoding="utf-8",compresslevel=6) as stream, \
            gzip.open(out/"native.jsonl.gz","xt",encoding="utf-8",compresslevel=6) as native_stream:
        for arm in order:
            profile,control=arms[arm]
            readout=None if control=="fixed" else info["readouts"][profile]["native" if control=="reset" else control]
            for split in ("test","retention"):
                for ci,condition in enumerate(P[f"{split}_conditions"]):
                    for start in range(0,P[f"{split}_pairs"],P["evaluation_batch_size"]):
                        size=min(P["evaluation_batch_size"],P[f"{split}_pairs"]-start)
                        batch_seed,noise_seed=271027+start+ci*10000,seed*100003+start+ci*1009
                        batch=make_batch(corpus,split,size,batch_seed,offset=P[f"{split}_offset"]+start,corruption=condition)
                        context=dict(seed=seed,arm=arm,split=split,corruption=condition,batch_start=start,batch_seed=batch_seed)
                        count+=deploy_batch(models[profile],readout,control,info["fixed_action"],bridge,
                            observers,batch,noise_seed,context,Path(tempfile.mkdtemp(prefix=f"hepta-primary-{seed}-",dir="/tmp")),media,stream,native_stream)
            print(f"primary seed={seed} arm={arm} complete; rows={count}",flush=True)
    media_info=media.close()
    expected=len(arms)*sum(P[f"{split}_pairs"]*len(P[f"{split}_conditions"]) for split in ("test","retention"))
    if count!=expected or source_freeze()!=frozen["source_files"]:
        raise RuntimeError("Primary execution grid incomplete or source changed")
    if any(parameter_hash(originals[s])!=identities[s]["parameter_sha256"] for s in P["seeds"]):
        raise RuntimeError("Original model changed during primary deployment")
    write_json(out/"COMPLETE.json",{"rows":count,"seed":seed,"media":media_info,
        "files_sha256":{name:digest(out/name) for name in ("rows.jsonl.gz","native.jsonl.gz","media.zip")},
        "pretest_freeze_sha256":digest(root/"PRETEST_FREEZE.json"),"registered_pretest_commit":args.registered_commit,
        "registered_recovery_commit":args.recovery_commit,"recovery_source_sha256":digest(__file__),
        "source_files":frozen["source_files"],"source_models_unchanged":True,"wall_ns":time.perf_counter_ns()-started})


def analyze(args):
    from ..field_bridge_v2_20261027.primary_analyze import analyze as compute
    root=Path(args.out).resolve()
    recovery=verify_recovery(args)
    rows,completions=[],{}
    for seed in P["seeds"]:
        path=root/"eval_recovered"/str(seed)
        done=json.loads((path/"COMPLETE.json").read_text())
        for name,identity in done["files_sha256"].items():
            if digest(path/name)!=identity: raise ValueError("Recovered primary evidence changed")
        with gzip.open(path/"rows.jsonl.gz","rt") as stream:
            for line in stream:
                row=json.loads(line)
                rows.append({k:row[k] for k in ("seed","arm","split","corruption","pair","source_ids","action",
                                                "refinement_count","reward","audit","resources")})
        completions[str(seed)]=done
    write_json(root/"RESULT.json",compute(rows))
    write_json(root/"EVALUATION_COMPLETE.json",{"rows":len(rows),"seeds":completions,
        "result_sha256":digest(root/"RESULT.json"),"source_files":source_freeze(),
        "pretest_freeze_sha256":digest(root/"PRETEST_FREEZE.json"),
        "evaluation_subdirectory":"eval_recovered", "original_attempt":"eval",
        "recovery_source_sha256":digest(__file__),"registered_recovery_commit":args.recovery_commit,
        "recovery_registration_sha256":digest(root/"IO_RECOVERY_REGISTRATION.json"),
        "original_attempt_counts":recovery["partial_attempt_counts"],
        "repeated_execution_interpretation":"Same frozen decisions and RNG after an I/O fault; one statistical grid, no extra independent replicate"})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("evaluate","analyze"))
    parser.add_argument("--assets",required=True)
    parser.add_argument("--out",required=True)
    parser.add_argument("--native",required=True)
    parser.add_argument("--registered-commit",required=True)
    parser.add_argument("--recovery-commit",required=True)
    parser.add_argument("--seed",type=int,choices=P["seeds"])
    args=parser.parse_args()
    if args.phase=="evaluate" and args.seed is None:parser.error("Require --seed")
    (evaluate if args.phase=="evaluate" else analyze)(args)


if __name__=="__main__":
    main()
