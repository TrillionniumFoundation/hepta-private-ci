"""Paired-seed frozen-encoder head benchmark; all choices fixed before test use."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import sys

import numpy as np
import jax
import jax.numpy as jnp
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.models import init_model, apply_model, parameter_count
from benchmarks.train import make_trainer, train_model, evaluate_dataset

WIDTHS = {"hcsn":39,"sigmoid":39,"gru":22,"transformer":23}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ece(prob, labels, bins=10):
    confidence = prob.max(1)
    correct = prob.argmax(1) == labels
    assignments = np.minimum((confidence*bins).astype(np.int64), bins-1)
    total = 0.
    for index in range(bins):
        mask = assignments == index
        if mask.any():
            total += mask.mean()*abs(correct[mask].mean()-confidence[mask].mean())
    return float(total)


def latency(params, kind, data, batch_size):
    predict = jax.jit(lambda p,x,dt: apply_model(p,x,dt,kind))
    x,dt = (jnp.asarray(data[k][:batch_size]) for k in ("x","dt"))
    for _ in range(5):
        predict(params,x,dt).block_until_ready()
    values = []
    for _ in range(50):
        start = time.perf_counter()
        predict(params,x,dt).block_until_ready()
        values.append(1000*(time.perf_counter()-start))
    return {"batch_size":batch_size,"median_ms":float(np.median(values)),
        "p95_ms":float(np.percentile(values,95)),"p99_ms":float(np.percentile(values,99)),
        "examples_per_second":float(batch_size*1000/np.median(values)),
        "includes_encoder":False,"includes_jit_compilation":False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features",type=Path,default=Path("/tmp/hcsn-encoder-assets/frozen_features.npz"))
    parser.add_argument("--output",type=Path,default=Path(__file__).parent)
    parser.add_argument("--steps",type=int,default=300)
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    checkpoints = args.output/"checkpoints"
    checkpoints.mkdir(exist_ok=True)
    feature_sha = sha(args.features)
    raw = np.load(args.features)
    data = {split:{key:raw[split+"_"+key] for key in ("x","dt","y")}
            for split in ("train","validation","test")}
    rng = np.random.default_rng(20261101)
    corrupt = {key:val.copy() for key,val in data["test"].items()}
    keep = rng.random(corrupt["x"].shape[:2])>.2
    # Keep the global mean feature available; corrupt only local blocks.
    keep[:,-1] = True
    corrupt["x"] = ((corrupt["x"]+rng.normal(0,.15,corrupt["x"].shape))*keep[...,None]).astype(np.float32)
    results = {"metadata":dict(feature_sha256=feature_sha,steps=args.steps,batch_size=32,
        learning_rate=.003,seeds=list(range(5)),widths=WIDTHS,
        parameter_budget_target=6000,architecture_selection="Fixed before observing test",
        checkpoint_selection="Minimum validation cross entropy every 50 steps",
        shared_encoder_frozen=True,shared_training_only_pca=True,
        environment={"jax":jax.__version__,"numpy":np.__version__,"device":str(jax.devices())},
        data_shapes={s:{k:list(v.shape) for k,v in vals.items()} for s,vals in data.items()},
        corrupted_test="20% local feature block dropout and Gaussian sigma0.15; global mean retained",
        training_timing_audit="warm_training_seconds excludes only the first step; a second JIT compilation may remain. Do not use for model speed comparisons",
        corruption_scope="Post-encoder feature perturbation; the global mean contains the complete truncated sentence, so this does not test missing raw text or modalities",
        limitation="Small sentence classification pilot, not full multimodal or backbone pretraining"),
        "runs":[],"complete":False}
    # A smaller reference baseline, not claimed to be parameter matched.
    linear = LogisticRegression(C=1.,max_iter=1000,solver="lbfgs")
    start = time.perf_counter()
    linear.fit(data["train"]["x"][:,-1],data["train"]["y"])
    baseline = {"kind":"mean_feature_logistic_reference",
                "parameter_count":int(linear.coef_.size+linear.intercept_.size),
                "train_seconds":time.perf_counter()-start,"C":1.}
    for split in ("validation","test"):
        probs = linear.predict_proba(data[split]["x"][:,-1])
        labels = data[split]["y"]
        baseline[split] = dict(accuracy=float(np.mean(probs.argmax(1)==labels)),
            loss=float(-np.log(np.maximum(probs[np.arange(len(labels)),labels],1e-30)).mean()),
            brier=float(np.mean(np.sum((probs-np.eye(2)[labels])**2,1))),ece=ece(probs,labels))
    results["linear_reference"] = baseline
    start_total = time.perf_counter()
    for kind,width in WIDTHS.items():
        trainer = make_trainer(kind,.003)
        for seed in range(5):
            params = init_model(kind,jax.random.PRNGKey(seed),64,width,2)
            learned,history,timing = train_model(params,kind,data["train"],data["validation"],
                seed,steps=args.steps,trainer=trainer)
            evaluation = trainer[-1]
            run = dict(kind=kind,seed=seed,width=width,parameter_count=parameter_count(params),
                timing=timing,history=history,train=evaluate_dataset(evaluation,learned,data["train"]),
                validation=evaluate_dataset(evaluation,learned,data["validation"]),
                test=evaluate_dataset(evaluation,learned,data["test"]),
                corrupted_test=evaluate_dataset(evaluation,learned,corrupt))
            probabilities = []
            for offset in range(0,len(data["test"]["y"]),128):
                logits=apply_model(learned,jnp.asarray(data["test"]["x"][offset:offset+128]),
                    jnp.asarray(data["test"]["dt"][offset:offset+128]),kind)
                probabilities.append(np.asarray(jax.nn.softmax(logits)))
            probability=np.concatenate(probabilities)
            run["test"]["ece"] = ece(probability,data["test"]["y"])
            run["latency_batch1"] = latency(learned,kind,data["test"],1)
            run["latency_batch32"] = latency(learned,kind,data["test"],32)
            target=checkpoints/f"{kind}_seed{seed}.npz"
            np.savez_compressed(target,**{key:np.asarray(value) for key,value in learned.items()})
            run["checkpoint_sha256"]=sha(target)
            run["checkpoint_file"]=str(target.relative_to(args.output))
            results["runs"].append(run)
            (args.output/"head_results.json").write_text(json.dumps(results,indent=2)+"\n")
            print(kind,seed,"test",run["test"]["accuracy"],"val",run["validation"]["accuracy"],flush=True)
    summary={}
    for kind in WIDTHS:
        rows=[r for r in results["runs"] if r["kind"]==kind]
        summary[kind]={}
        for field in ("test","corrupted_test"):
            values=np.array([r[field]["accuracy"] for r in rows])
            summary[kind][field] = dict(mean=float(values.mean()),sd=float(values.std(ddof=1)))
        summary[kind]["mean_warm_train_seconds"] = float(np.mean([r["timing"]["warm_training_seconds"] for r in rows]))
        summary[kind]["median_batch1_ms"] = float(np.median([r["latency_batch1"]["median_ms"] for r in rows]))
    lhs=np.array([r["test"]["accuracy"] for r in results["runs"] if r["kind"]=="hcsn"])
    rhs=np.array([r["test"]["accuracy"] for r in results["runs"] if r["kind"]=="sigmoid"])
    delta=lhs-rhs
    results["paired_hcsn_minus_sigmoid"] = dict(mean=float(delta.mean()),
        sd=float(delta.std(ddof=1)),deltas=delta.tolist(),
        note="Paired seeds share a fixed test set; seed SD is not a full population uncertainty estimate")
    results["summary"]=summary
    results["feature_sha_after_training"]=sha(args.features)
    assert results["feature_sha_after_training"]==feature_sha
    results["complete"]=True
    results["elapsed_seconds"]=time.perf_counter()-start_total
    (args.output/"head_results.json").write_text(json.dumps(results,indent=2)+"\n")
    print(json.dumps(summary,indent=2),flush=True)


if __name__ == "__main__":
    main()
