"""Seal and evaluate five frozen action-readout edits on fresh finite-law worlds."""
import argparse
import hashlib
import importlib.util
import json
import secrets
import time
import types
import zipfile
from pathlib import Path

import numpy as np


SOURCE_REF = "2d0120e208ed81515837a7530c9f6943af03e87f"
GEOMETRY_SHA = "2928beeceabd3c6b48cda7d1b5df2de4ddbbaecc2ebedb23d2a8ce75df1816d5"
MODEL_SHAS = {
    11:"84c4386d0c8725959da10862cdfaad73b654b80e908f3de8d2383530767a38ac",
    23:"db58500626d4fc89161e4e4ce0ea89b75a70b92794c178cd679c56e60c7ac9ee",
    37:"cc4f66a63b0af1c90fb31764ee4a724b7837eab081abac94a50ccac7b882dd71",
    53:"608e4f54ebf89d85f9778a26034144c6c7cc3f5f8e0b988cbcd9a5ac57dcb937",
    71:"4d3c1124e4309b8124f98e2586f91fcc3022be5c733f29b04f2338fb6aa02d2c",
}
SOURCE_BLOBS = {
    "run_head_edit.py":"d77ea34c83cb55dd1b9dd11d0b686003a913bf9d",
    "joint_task.py":"0a9797e183420035d18cc027e4bb32f43a9c2db4",
    "legacy_task.py":"af897f81d3088fa4eb7316766b4e4a01015dcdbd",
    "joint_deploy.py":"2932f1207d7a4a70e5eaddc976f23d088daa0de6",
    "joint_law.py":"df4670f7027f6ab8fc7c08ab3794571c5920cfe0",
    "joint_protocol.json":"e6bc91af1eb5cafe007c687931f2370bb57fddcb",
    "truth_transitions.npz":"c69a72e2d59db9d7ab88e977b08524d727629d81",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def emit(path, content):
    with path.open("x") as stream:
        json.dump(content,stream,sort_keys=True,allow_nan=False,indent=2)
        stream.write("\n")


def source(directory):
    for name,sha in SOURCE_BLOBS.items():
        data=(directory/name).read_bytes()
        require(hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()==sha,
                f"source Git object mismatch in {name}")
    spec=importlib.util.spec_from_file_location("g245.original_readout_evaluator", directory/"run_head_edit.py")
    upstream=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    return upstream


def schedule_digest(public):
    return digest(json.dumps({k:v for k,v in public.items() if k not in {"id","packets","packet_sha256"}},
                             sort_keys=True,separators=(",",":")).encode())


def domains(upstream, seed, fit):
    # The upstream schedule sampler is unchanged. The zero fit index shares the
    # generated schedules across all real model fits in this confirmation.
    upstream.SEED = seed
    return {k:upstream.make_worlds(fit,k) for k in ("iid","ood")}


def seal(args):
    upstream = source(args.source)
    historical = {schedule_digest(p) for fit in MODEL_SHAS
                  for group in domains(upstream,870040000,fit).values() for p in group}
    artifact=json.loads(args.edits.read_bytes())
    require(artifact["input_sha256"]==GEOMETRY_SHA and artifact["margin"]==0.001, "unexpected TRAIN solve")
    for fit in MODEL_SHAS:
        edit=artifact["fits"][str(fit)]["joint"]
        require(edit["status"]=="feasible" and np.shape(edit["displacement"])==(245,)
                and np.isfinite(edit["displacement"]).all(), "invalid TRAIN delta")
    seed=secrets.randbits(128)
    fresh=domains(upstream,seed,0)
    hashes={k:[schedule_digest(p) for p in group] for k,group in fresh.items()}
    union=set(hashes["iid"]+hashes["ood"])
    require(len(union)==64 and not (historical & union),"duplicate old or new world")
    emit(args.seal,dict(version="held-geometry-245-v1", source_ref=SOURCE_REF,
         source_blobs=SOURCE_BLOBS,script_sha256=digest(Path(__file__).read_bytes()),
         edits_sha256=digest(args.edits.read_bytes()),fits=list(MODEL_SHAS),
         model_sha256=MODEL_SHAS,original_training_archive_sha256="87173e7699117f9870393832f428b9f3e0046efe7f92035be7b37f5348ad9124",
         seed=seed,worlds=hashes,prior_published_schedule_overlap=0,
         design="One 128-bit seed drawn after freezing the edit; 32 IID + 32 OOD public schedules, shared by every fit.",
         arms=["unchanged","joint_245"], edit_semantics="Add 3 continuation and 2 terminal score corrections at frozen hidden feature and belief. Terminal decision scores may exceed reward range; environment pays original expected outcome.",
         estimand="Exact expected policy utility under the original finite declared law and each fit's frozen TRAIN confusion.",
         decision="Per fit and domain, usefulness requires strictly positive mean delta and per-world delta at least -0.05. Combined success requires both conditions in every fit and domain. Report each failure.",
         retention_floor=-.05))


def evaluate(args):
    plan=json.loads(args.seal.read_bytes())
    require(plan["script_sha256"]==digest(Path(__file__).read_bytes()) and
            plan["edits_sha256"]==digest(args.edits.read_bytes()), "sealed code/edits changed")
    upstream=source(args.source)
    worlds=domains(upstream,plan["seed"],0)
    require(plan["worlds"]=={k:[schedule_digest(p) for p in ps] for k,ps in worlds.items()},
            "sealed world identities changed")
    edits=json.loads(args.edits.read_bytes())["fits"]
    def additive(weights,x):
        theta,delta=weights
        q,p=upstream.predicted(theta,x)
        q[1:] += delta @ x
        return q,p
    # Use the ORIGINAL recursive evaluator and change only its pure readout.
    env={**vars(upstream),"predicted":additive}
    with_edit=types.FunctionType(upstream.policy_value.__code__,env,upstream.policy_value.__name__)
    started=time.perf_counter()
    rows=[]
    with zipfile.ZipFile(args.models) as checkpoint:
        for fit,sha in MODEL_SHAS.items():
            raw=checkpoint.read(f"fit_{fit}/model_renewal/model.json")
            require(digest(raw)==sha,f"checkpoint mismatch for {fit}")
            model=json.loads(raw)
            head=upstream.head(model)
            delta=np.reshape(edits[str(fit)]["joint"]["displacement"],(5,49))
            features=upstream.FrozenFeatures(upstream.NumpyPolicy(model))
            for split,group in worlds.items():
                values=[]
                visits=[0,0]
                for i,p in enumerate(group):
                    oracle=upstream.Oracle(p,upstream.law,model["confusion"])
                    keep,v0=upstream.policy_value(p,head,features,oracle)
                    edited,v1=with_edit(p,(head,delta),features,oracle)
                    if i==0:
                        zero,v2=with_edit(p,(head,np.zeros_like(delta)),features,oracle)
                        require(v2==v0 and abs(zero-keep)<1e-13,"zero edit changed original evaluator")
                    require(np.isfinite([keep,edited]).all(),"nonfinite result")
                    values.append((keep,edited))
                    visits[0]+=v0
                    visits[1]+=v1
                output=np.asarray(values)
                differences=output[:,1]-output[:,0]
                floor=plan["retention_floor"]
                rows.append(dict(fit=fit,domain=split,model_sha256=sha,values=output.tolist(),
                                 original_mean=float(output[:,0].mean()),edited_mean=float(output[:,1].mean()),
                                 mean_delta=float(differences.mean()),worst_world_delta=float(differences.min()),
                                 failures_below_retention=int((differences<floor-1e-12).sum()),
                                 noninferior_worlds=int((differences>=floor-1e-12).sum()),
                                 passed=bool(differences.mean()>0 and differences.min()>=floor-1e-12),
                                 visited_nodes=visits,edit_l2=float(np.linalg.norm(delta))))
    emit(args.output,dict(seal_sha256=digest(args.seal.read_bytes()),rows=rows,
                          comparisons=sum(len(r["values"]) for r in rows),passed=all(r["passed"] for r in rows),
                          eval_wall_seconds=time.perf_counter()-started))
    print(json.dumps({r["domain"]+"-"+str(r["fit"]):[r["mean_delta"],r["worst_world_delta"],
                      r["failures_below_retention"]] for r in rows},allow_nan=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase",choices=("seal","evaluate"))
    parser.add_argument("source",type=Path)
    parser.add_argument("edits",type=Path)
    parser.add_argument("seal",type=Path)
    parser.add_argument("--models",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    if args.phase=="evaluate":
        if args.models is None or args.output is None or args.output.exists():
            parser.error("provide model archive and a new destination")
        evaluate(args)
    else:
        seal(args)
