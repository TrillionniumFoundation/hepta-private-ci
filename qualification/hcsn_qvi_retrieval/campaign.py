"""Isolated TRAIN discovery, development selection, and sealed confirmation."""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path

PROCESS_START = time.monotonic()

import numpy as np
import torch

from .adapt import FitConfig, fit_arm, nonlinear_screen, predict, training_diagnostics
from .dynamics import RetrievalFlow
from .ndu import FiniteBellman, actions_and_targets, controls, policy_result, worst_delta


HERE = Path(__file__).parent
PROTOCOL = json.loads((HERE / "protocol.json").read_text())
MANIFEST = json.loads((HERE / "data_manifest.json").read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def put_json(path, value):
    with path.open("x") as fh:
        json.dump(value, fh, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")


def shard(root, name):
    path = root / (name + ".npz")
    receipt = json.loads(path.with_suffix(".receipt.json").read_text())
    if digest(path) != receipt["output_sha256"] or receipt["split"] != name:
        raise ValueError("unbound input shard")
    with np.load(path, allow_pickle=False) as data:
        s = {key:data[key] for key in ("x","dt","scores","read_scores","target","group","split","query_id","gallery_id")}
    groups = {f"ravdess-actor-{g:02d}" for g in MANIFEST["splits"][name]}
    if (set(s["group"]) != groups or set(s["split"]) != {name}
            or len(np.unique(s["query_id"])) != len(s["x"])
            or set(s["query_id"]) != set(s["gallery_id"].flatten())):
        raise ValueError("split / gallery identity mismatch")
    s["teacher"], s["correct"] = actions_and_targets(s["scores"],s["read_scores"],s["target"],s["dt"])
    s["targets"] = s["teacher"].reshape(-1,3)
    s["legal_actions"] = np.ones_like(s["teacher"], dtype=bool)
    s["legal_actions"][:, -1, 2] = False
    s["hash"] = receipt["output_sha256"]
    return s


def prepare(s, mu, scale):
    s["xt"] = torch.from_numpy((s["x"]-mu)/scale)
    s["clock"] = torch.from_numpy(s["dt"])


def features_for(model):
    def features(theta, s):
        # Input tensors expose only causal free audio metadata and observations.
        physical = model.features_with_edit(theta, s["xt"], s["clock"])
        return torch.cat((s["xt"], physical),dim=-1).reshape(-1,s["xt"].shape[-1]+physical.shape[-1])
    return features


def score_policy(features, theta, head, s):
    with torch.no_grad():
        q=predict(features(theta,s), head).reshape(*s["dt"].shape,3).numpy()
    return policy_result(q,s)


def brief(r):
    return {k:v for k,v in r.items() if k not in ("episode_utility","hits","exit_prefix","terminal_action")}


def fingerprint():
    return {p.name:digest(p) for p in sorted(HERE.glob("*.py"))}


def base_record(s, model, seed):
    return dict(seed=seed,mode=model.mode,names=model.edit_names,python=platform.python_version(),
                torch=torch.__version__,numpy=np.__version__,train_hash=s["hash"],
                physical_channels=list(model.feature_names),sources=fingerprint(),
                protocol_hash=digest(HERE/"protocol.json"))


def model_and_data(root, mode, seed):
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)
    train=shard(root,"train")
    mu=train["x"].mean(axis=(0,1))
    scale=train["x"].std(axis=(0,1)).clip(min=1e-8)
    prepare(train,mu,scale)
    model=RetrievalFlow(train["x"].shape[-1],mode=mode)
    return train,mu,scale,model,features_for(model)


def diagnostic(args):
    train,_,_,model,features=model_and_data(args.data,args.mode,args.seed)
    origin=model.initial_edit_vector()
    result=base_record(train,model,args.seed)
    result["diagnostics"]=training_diagnostics(origin,features,train)
    # Local sensitivity is a separate audit, withheld from the gradient-free editor.
    result["audit_only"]=nonlinear_screen(origin,features,train)
    result["structural_unreachable"]=controls(train)["structurally_unretrievable"]
    result["elapsed_seconds"]=time.monotonic()-PROCESS_START
    put_json(args.output,result)


def fit(args):
    train,mu,scale,model,features=model_and_data(args.data,args.mode,args.seed)
    dev,retain=shard(args.data,"dev"),shard(args.data,"retain")
    prepare(dev,mu,scale)
    prepare(retain,mu,scale)
    reference={}
    def score(theta,head):
        dev_metrics=score_policy(features,theta,head,dev)
        retention=score_policy(features,theta,head,retain)
        if not reference:
            if bool(theta.ne(0).any()):
                raise ValueError("first candidate must be shared post-SVD incumbent")
            reference.update(keep=retention,theta=theta.tolist(),head=head.tolist())
        difference=worst_delta(retention,reference["keep"])
        return dev_metrics["utility"],difference >= -0.05-1e-12, {
            "dev":brief(dev_metrics),"retain":brief(retention),"worst_retain_delta":difference}
    editor=None
    if args.method=="wsp":
        from .agent_edit import propose
        def editor(origin,diagnostics,train_probe):
            return propose(origin,diagnostics,model.edit_names,train_probe)
        editor.uses_train_probes = True
    result=fit_arm(args.method,model.initial_edit_vector(),features,train,dev,
                   config=FitConfig(),score=score,editor=editor)
    record=base_record(train,model,args.seed)
    empirical=FiniteBellman(train)
    record.update(method=args.method,dev_hash=dev["hash"],retain_hash=retain["hash"],
                  config=PROTOCOL["training"],fit=result.report,mean=mu.tolist(),scale=scale.tolist(),
                  theta=result.theta.tolist(),head=result.head.tolist(),keep_theta=reference["theta"],
                  keep_head=reference["head"],finite_edges=empirical.edges.tolist(),finite_q=empirical.q.tolist(),
                  reachable_audit={k:controls(train)[k] for k in ("structurally_unretrievable",)},
                  elapsed_seconds=time.monotonic()-PROCESS_START)
    put_json(args.output,record)


def confirm(args):
    # This process reads only the sealed models and the held-out shard.
    seal=json.loads(args.seal.read_text())
    if len(seal["files"]) != 27 or seal["files"].get(args.fit.name)!=digest(args.fit):
        raise ValueError("confirmation requires the complete 27-arm selection seal")
    record=json.loads(args.fit.read_text())
    checked={key:value for key,value in record["sources"].items() if key in {
        "campaign.py","dynamics.py","ndu.py","adapt.py","agent_edit.py"}}
    if any(digest(HERE/key)!=value for key,value in checked.items()) or record["protocol_hash"]!=digest(HERE/"protocol.json"):
        raise ValueError("scientific source differs from seal")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(record["seed"])
    test=shard(args.data,"test")
    prepare(test,np.asarray(record["mean"]),np.asarray(record["scale"]))
    model=RetrievalFlow(test["x"].shape[-1],mode=record["mode"])
    features=features_for(model)
    def score(k):
        return score_policy(features,torch.tensor(record[k+"theta"],dtype=torch.float64),
                            torch.tensor(record[k+"head"],dtype=torch.float64),test)
    chosen,keep=score(""),score("keep_")
    base=controls(test)
    detector=FiniteBellman.__new__(FiniteBellman)
    detector.edges=np.asarray(record["finite_edges"])
    detector.q=np.asarray(record["finite_q"])
    base["empirical_bellman"]=policy_result(detector.predict(test),test)
    delta=worst_delta(chosen,keep)
    result=dict(mode=record["mode"],method=record["method"],seed=record["seed"],fit_hash=digest(args.fit),
                selection_seal=digest(args.seal),test_hash=test["hash"],query_id=test["query_id"].tolist(),
                actor=test["group"].tolist(),chosen=chosen,keep=keep,controls=base,worst_actor_delta=delta,
                worst_vs_common_stop=worst_delta(chosen,base["immediate_stop"]),
                success=chosen["utility"]>=.60 and chosen["r1"]>=.70 and delta>=-.05-1e-12,
                elapsed_seconds=time.monotonic()-PROCESS_START)
    put_json(args.output,result)


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument("phase",choices=["diagnose","fit","confirm"])
    parser.add_argument("data",type=Path)
    parser.add_argument("output",type=Path)
    parser.add_argument("--mode",choices=PROTOCOL["modes"],default="fixed")
    parser.add_argument("--method",choices=PROTOCOL["methods"],default="keep")
    parser.add_argument("--seed",type=int,choices=PROTOCOL["seed"],default=PROTOCOL["seed"][0])
    parser.add_argument("--fit",type=Path)
    parser.add_argument("--seal",type=Path)
    args=parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    {"diagnose":diagnostic,"fit":fit,"confirm":confirm}[args.phase](args)


if __name__=="__main__":
    main()
