"""Apply the already-fixed v2 architecture to unchanged frozen encoder features."""

import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import jax
import jax.numpy as jnp
try:
    from .v2_models import init_model,apply_model,matched_width
    from .models import parameter_count
    from .run_v2 import make_trainer
    from .train import train_model,evaluate_dataset
    from .run_benchmarks import source_hashes
except ImportError:
    from v2_models import init_model,apply_model,matched_width
    from models import parameter_count
    from run_v2 import make_trainer
    from train import train_model,evaluate_dataset
    from run_benchmarks import source_hashes


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ece(prob,labels,bins=10):
    confidence=prob.max(1);correct=prob.argmax(1)==labels;total=0.
    for lower in np.linspace(0,1,bins,endpoint=False):
        mask=(confidence>=lower)&(confidence<lower+1/bins+1e-12)
        if mask.any():
            total+=mask.mean()*abs(correct[mask].mean()-confidence[mask].mean())
    return float(total)


def latency(p,kind,data,batch):
    predict=jax.jit(lambda pp,x,dt:apply_model(pp,x,dt,kind))
    x=jnp.asarray(data["x"][:batch]);dt=jnp.asarray(data["dt"][:batch])
    for _ in range(5):
        predict(p,x,dt).block_until_ready()
    times=[]
    for _ in range(50):
        start=time.perf_counter();predict(p,x,dt).block_until_ready()
        times.append(1000*(time.perf_counter()-start))
    return dict(batch_size=batch,median_ms=float(np.median(times)),
                p95_ms=float(np.percentile(times,95)),p99_ms=float(np.percentile(times,99)),
                examples_per_second=float(batch*1000/np.median(times)),
                includes_encoder=False,includes_jit_compilation=False)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--features",type=Path,default=Path("/tmp/hcsn-encoder-assets/frozen_features.npz"))
    args=parser.parse_args()
    folder=Path(__file__).parent;checkpoints=folder/"frozen_v2_checkpoints"
    checkpoints.mkdir(exist_ok=True)
    before=sha(args.features);raw=np.load(args.features)
    data={split:{key:raw[split+"_"+key] for key in ("x","dt","y")}
          for split in ("train","validation","test")}
    rng=np.random.default_rng(20261101)
    corrupt={k:v.copy() for k,v in data["test"].items()}
    keep=rng.random(corrupt["x"].shape[:2])>.2;keep[:,-1]=True
    corrupt["x"]=((corrupt["x"]+rng.normal(0,.15,corrupt["x"].shape))*keep[...,None]).astype(np.float32)
    result=dict(metadata=dict(feature_sha256=before,architecture_version=2,
        architecture_selection="Fixed by v2_protocol.json before observing text-head outcomes; no text-specific tuning",
        source_hashes=source_hashes(),steps=300,batch_size=32,learning_rate=.003,seeds=list(range(5)),
        shared_encoder_frozen=True,shared_training_only_pca=True,parameter_budget_target=6000,
        checkpoint_selection="Minimum validation loss at 50-update intervals",
        data_shapes={s:{k:list(v.shape) for k,v in values.items()} for s,values in data.items()},
        corrupted_test="Same 20% local-block dropout and Gaussian sigma0.15 as encoder/run_heads.py; global mean retained",
        limitation="Same small frozen text encoder features as v1; no backbone or multimodal claim"),runs=[],complete=False)
    start=time.perf_counter()
    for kind in ("hcsn","sigmoid"):
        width,count=matched_width(kind,64,2,budget=6000)
        trainer=make_trainer(kind)
        for seed in range(5):
            p=init_model(kind,jax.random.PRNGKey(seed),64,width,2)
            assert parameter_count(p)==count
            learned,history,timing=train_model(p,kind,data["train"],data["validation"],seed,
                steps=300,trainer=trainer)
            evaluate=trainer[3]
            row=dict(kind=kind,architecture_version=2,seed=seed,width=width,parameter_count=count,
                persistent_state_scalars=3*width,timing=timing,history=history,
                train=evaluate_dataset(evaluate,learned,data["train"]),
                validation=evaluate_dataset(evaluate,learned,data["validation"]),
                test=evaluate_dataset(evaluate,learned,data["test"]),
                corrupted_test=evaluate_dataset(evaluate,learned,corrupt))
            probability=[]
            for i in range(0,len(data["test"]["y"]),128):
                logits=apply_model(learned,jnp.asarray(data["test"]["x"][i:i+128]),
                                   jnp.asarray(data["test"]["dt"][i:i+128]),kind)
                probability.append(np.asarray(jax.nn.softmax(logits)))
            row["test"]["ece"]=ece(np.concatenate(probability),data["test"]["y"])
            row["latency_batch1"]=latency(learned,kind,data["test"],1)
            row["latency_batch32"]=latency(learned,kind,data["test"],32)
            checkpoint=checkpoints/f"{kind}_seed{seed}.npz"
            np.savez_compressed(checkpoint,**{k:np.asarray(v) for k,v in learned.items()})
            row["checkpoint_file"]=str(checkpoint.relative_to(folder));row["checkpoint_sha256"]=sha(checkpoint)
            result["runs"].append(row)
            (folder/"frozen_v2_results.json").write_text(json.dumps(result,indent=2))
            print(json.dumps(dict(kind=kind,seed=seed,test=row["test"]["accuracy"],
                                  corrupted=row["corrupted_test"]["accuracy"],params=count,state_scalars=3*width)),flush=True)
    summary={}
    for kind in ("hcsn","sigmoid"):
        runs=[r for r in result["runs"] if r["kind"]==kind]
        summary[kind]={}
        for split in ("test","corrupted_test"):
            values=np.array([r[split]["accuracy"] for r in runs])
            summary[kind][split]=dict(mean=float(values.mean()),sd=float(values.std(ddof=1)))
        summary[kind]["mean_warm_train_seconds"]=float(np.mean([r["timing"]["warm_training_seconds"] for r in runs]))
    lhs=np.array([r["test"]["accuracy"] for r in result["runs"] if r["kind"]=="hcsn"])
    rhs=np.array([r["test"]["accuracy"] for r in result["runs"] if r["kind"]=="sigmoid"])
    result["paired_hcsn_minus_sigmoid"]=dict(mean=float((lhs-rhs).mean()),
        sd=float((lhs-rhs).std(ddof=1)),deltas=(lhs-rhs).tolist(),
        note="Paired initial seeds share the same test set; seed SD is not full population uncertainty")
    result["summary"]=summary;result["feature_sha_after_training"]=sha(args.features)
    assert result["feature_sha_after_training"]==before
    result["complete"]=True;result["elapsed_seconds"]=time.perf_counter()-start
    (folder/"frozen_v2_results.json").write_text(json.dumps(result,indent=2))
    print(json.dumps(summary,indent=2),flush=True)


if __name__=="__main__":
    main()
