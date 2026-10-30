"""Predeclared frozen text/image heads; no test-based architecture selection."""
import argparse
from functools import partial
import json
from pathlib import Path
import sys
import time

import jax
import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from benchmarks.v2_models import init_model,apply_model,matched_width
from benchmarks.models import parameter_count
from next.common import train_model,evaluate_model,measure_latency,classification_metrics
from feature_utils import FOLDER,CACHE,sha


def source_hashes():
    paths=[Path(__file__),ROOT/"benchmarks/v2_models.py",ROOT/"benchmarks/models.py",ROOT/"next/common.py"]
    return {str(p.relative_to(ROOT)):sha(p) for p in paths}


def run_dataset(dataset):
    feature_path=CACHE/(dataset+"_features.npz")
    before=sha(feature_path)
    raw=np.load(feature_path)
    data={split:{key:raw[split+"_"+key] for key in ("x","dt","y")}
          for split in ("train","validation","test","corrupted_test")}
    manifest=json.loads((FOLDER/(dataset+"_manifest.json")).read_text())
    assert before==manifest["features_sha256"]
    classes=int(data["train"]["y"].max())+1
    results=dict(metadata=dict(dataset=dataset,features_sha256=before,
        source_sha256=source_hashes(),protocol_sha256=sha(FOLDER/"protocol.json"),
        steps=300,batch_size=32,learning_rate=.003,seeds=list(range(5)),parameter_target=6000,
        classes=classes,shape_per_example=list(data["train"]["x"].shape[1:]),
        shared_encoder_frozen=True,shared_projection_frozen=True,
        corrupted_input="Raw-input corruption before the encoder; global feature recomputed",
        encoder_preparation_seconds=manifest["encoder_total_seconds"],
        projection_seconds=manifest["projection_seconds"],
        encoder_preparation_examples=manifest["encoder_total_examples"],
        environment=dict(jax=jax.__version__,numpy=np.__version__,devices=[str(d) for d in jax.devices()]),
        limitations=["Small fixed-budget unimodal experiments, not a full multimodal backbone",
                     "One fixed shared holdout; seed SD does not capture all dataset uncertainty",
                     "Shared CPU timing; not equal FLOPs, isolated hardware, or energy measurements"]),
        runs=[],complete=False)
    checkpoint_dir=FOLDER/"checkpoints"/dataset
    checkpoint_dir.mkdir(parents=True,exist_ok=True)
    reference=LogisticRegression(C=1.,max_iter=1000,solver="lbfgs")
    start=time.perf_counter();reference.fit(data["train"]["x"][:,-1],data["train"]["y"])
    linear=dict(kind="global_mean_logistic_reference",C=1.,
        parameter_count=int(reference.coef_.size+reference.intercept_.size),
        fit_seconds=time.perf_counter()-start)
    for split in data:
        probs=reference.predict_proba(data[split]["x"][:,-1])
        linear[split]=classification_metrics(np.log(np.maximum(probs,1e-30)),data[split]["y"])
    np.savez_compressed(checkpoint_dir/"linear_reference.npz",coef=reference.coef_,intercept=reference.intercept_)
    linear["checkpoint_file"]=str((checkpoint_dir/"linear_reference.npz").relative_to(FOLDER))
    linear["checkpoint_sha256"]=sha(checkpoint_dir/"linear_reference.npz")
    results["linear_reference"]=linear
    destination=FOLDER/(dataset+"_baseline_results.json")
    start_total=time.perf_counter()
    for kind in ("hcsn","sigmoid","gru","transformer"):
        width,count=matched_width(kind,64,classes,budget=6000)
        apply=partial(apply_model,kind=kind)
        for seed in range(5):
            params=init_model(kind,jax.random.PRNGKey(seed),64,width,classes)
            assert count==parameter_count(params)
            learned,history,timing=train_model(params,apply,data["train"],data["validation"],seed)
            metrics={split:evaluate_model(apply,learned,values) for split,values in data.items()}
            checkpoint=checkpoint_dir/(kind+"_seed"+str(seed)+".npz")
            np.savez_compressed(checkpoint,**{k:np.asarray(v) for k,v in learned.items()})
            row=dict(kind=kind,architecture_version=2 if kind in ("hcsn","sigmoid") else 1,
                seed=seed,width=width,parameter_count=count,history=history,timing=timing,metrics=metrics,
                checkpoint_file=str(checkpoint.relative_to(FOLDER)),checkpoint_sha256=sha(checkpoint),
                logits_latency_batch1=measure_latency(apply,learned,data["test"],1),
                logits_latency_batch32=measure_latency(apply,learned,data["test"],32))
            results["runs"].append(row)
            destination.write_text(json.dumps(results,indent=2)+"\n")
            print(dataset,kind,seed,metrics["test"]["accuracy"],metrics["corrupted_test"]["accuracy"],flush=True)
    summary={}
    for kind in ("hcsn","sigmoid","gru","transformer"):
        rows=[r for r in results["runs"] if r["kind"]==kind]
        summary[kind]={split:dict(mean=float(np.mean([r["metrics"][split]["accuracy"] for r in rows])),
                                 sd=float(np.std([r["metrics"][split]["accuracy"] for r in rows],ddof=1)))
                       for split in ("test","corrupted_test")}
        summary[kind]["mean_compilation_seconds"]=float(np.mean([r["timing"]["compilation_seconds"] for r in rows]))
        summary[kind]["mean_optimizer_execution_seconds"]=float(np.mean([r["timing"]["optimizer_execution_seconds"] for r in rows]))
    paired={}
    for split in ("test","corrupted_test"):
        lhs=np.array([r["metrics"][split]["accuracy"] for r in results["runs"] if r["kind"]=="hcsn"])
        rhs=np.array([r["metrics"][split]["accuracy"] for r in results["runs"] if r["kind"]=="sigmoid"])
        paired[split]=dict(deltas=(lhs-rhs).tolist(),mean=float((lhs-rhs).mean()),sd=float((lhs-rhs).std(ddof=1)))
    results.update(summary=summary,paired_hcsn_minus_sigmoid=paired,complete=True,
        elapsed_head_experiment_seconds=time.perf_counter()-start_total,
        features_sha256_after=sha(feature_path))
    assert results["features_sha256_after"]==before
    destination.write_text(json.dumps(results,indent=2)+"\n")
    print(json.dumps(dict(dataset=dataset,summary=summary,linear_test=linear["test"],paired=paired),indent=2),flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--dataset",choices=("ag_news","cifar10","all"),default="all")
    args=parser.parse_args()
    for name in (("ag_news","cifar10") if args.dataset=="all" else (args.dataset,)):
        run_dataset(name)
