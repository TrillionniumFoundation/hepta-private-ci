"""Frozen same-graph controls; all new confirmation outcomes retained."""
import argparse
import gc
import json
import os
from pathlib import Path
import sys
import time

import jax
import jax.numpy as jnp
import numpy as np
from sklearn.linear_model import LogisticRegression

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
from benchmarks.models import parameter_count
from next.common import classification_metrics, measure_latency, predict_model, predictor, train_model
from next.full_kernel import as_jax_table
from third.encoder.models import init_model, make_apply, matched_width
from third.encoder.prepare import CACHE, sha, verify_freeze


def run(dataset):
    verify_freeze()
    assert json.loads((HERE/"validation.json").read_text())["passed"]
    protocol = json.loads((HERE/"protocol.json").read_text())
    manifest = json.loads((HERE/(dataset+"_manifest.json")).read_text())
    feature_path = CACHE/(dataset+"_features.npz")
    assert sha(feature_path) == manifest["features_sha256"]
    assert manifest["freeze_sha256"] == sha(HERE/"freeze.json")
    raw = np.load(feature_path)
    splits = ("train", "validation", "test", "corrupted_test")
    data = {name: {key: raw[name+"_"+key] for key in ("x", "dt", "y")} for name in splits}
    classes = int(data["train"]["y"].max())+1
    table_np = dict(np.load(ROOT/"next/full_kernel/baseline_table.npz"))
    table = as_jax_table(table_np)
    table_bytes = sum(a.nbytes for a in table_np.values())
    folder = HERE/"checkpoints"/dataset
    folder.mkdir(parents=True, exist_ok=True)
    destination = HERE/(dataset+"_results.json")
    if destination.exists():
        result = json.loads(destination.read_text())
        assert result["freeze_sha256"] == sha(HERE/"freeze.json")
        assert not result["complete"], "Use analysis for a completed frozen study"
        for row in result["runs"]:
            assert sha(HERE/row["checkpoint_file"]) == row["checkpoint_sha256"]
            assert sha(HERE/row["prediction_file"]) == row["prediction_sha256"]
        linear = dict(np.load(folder/"linear.npz"))
    else:
        start = time.perf_counter()
        start_cpu = time.process_time()
        reference = LogisticRegression(C=1., max_iter=1000, solver="lbfgs")
        reference.fit(data["train"]["x"][:, -1], data["train"]["y"])
        linear = dict(coef=reference.coef_.astype(np.float32), intercept=reference.intercept_.astype(np.float32))
        np.savez_compressed(folder/"linear.npz", **linear)
        metrics = {name: classification_metrics(values["x"][:, -1]@linear["coef"].T+linear["intercept"], values["y"])
                   for name, values in data.items()}
        result = dict(dataset=dataset, freeze_sha256=sha(HERE/"freeze.json"),
                      features_sha256=sha(feature_path), protocol=protocol, complete=False,
                      environment=dict(jax=jax.__version__, numpy=np.__version__, affinity=sorted(os.sched_getaffinity(0)),
                                       devices=[str(d) for d in jax.devices()]),
                      fixed_operator_bytes=int(table_bytes), runs=[],
                      linear_reference=dict(metrics=metrics, fit_and_evaluation_wall_seconds=time.perf_counter()-start,
                                            fit_and_evaluation_cpu_seconds=time.process_time()-start_cpu,
                                            parameter_count=linear["coef"].size+linear["intercept"].size,
                                            checkpoint_sha256=sha(folder/"linear.npz")))
        destination.write_text(json.dumps(result, indent=2)+"\n")
    done = {(r["regime"], r["kind"], r["seed"]) for r in result["runs"]}
    linear_jax = {key: jnp.asarray(value) for key, value in linear.items()}
    for regime in protocol["regimes"]:
        applies = {kind: make_apply(kind, table, linear_jax if regime == "linear_plus_dynamic" else None)
                   for kind in protocol["models"]}
        for seed in protocol["training_seeds"]:
            rotation = seed % len(protocol["models"])
            kinds = protocol["models"][rotation:]+protocol["models"][:rotation]
            for kind in kinds:
                if (regime, kind, seed) in done:
                    continue
                verify_freeze()
                start_wall = time.perf_counter()
                start_cpu = time.process_time()
                width, count = matched_width(kind, 64, classes, protocol["parameter_target"])
                params = init_model(kind, jax.random.PRNGKey(seed), 64, width, classes)
                assert parameter_count(params) == count
                apply = applies[kind]
                learned, history, timing = train_model(params, apply, data["train"], data["validation"],
                    seed, steps=protocol["updates"], batch_size=protocol["batch_size"], lr=protocol["learning_rate"])
                # Selection is completed before either confirmation condition is evaluated.
                logits = {name: predict_model(apply, learned, data[name]) for name in ("validation", "test", "corrupted_test")}
                metrics = {name: classification_metrics(value, data[name]["y"]) for name, value in logits.items()}
                stem = regime+"_"+kind+"_seed"+str(seed)
                checkpoint = folder/(stem+".npz")
                prediction = folder/(stem+"_predictions.npz")
                np.savez_compressed(checkpoint, **{k: np.asarray(v) for k, v in learned.items()})
                np.savez_compressed(prediction, **logits)
                latency = {"batch"+str(batch): measure_latency(apply, learned, data["test"], batch, repeats=20)
                           for batch in (1, 32)}
                row = dict(regime=regime, kind=kind, seed=seed, width=width, trainable_parameters=count,
                           frozen_bypass_parameters=int(linear["coef"].size+linear["intercept"].size) if regime == "linear_plus_dynamic" else 0,
                           fixed_operator_bytes=int(table_bytes) if kind in ("full_hx", "same_call_sigmoid") else 0,
                           persistent_state_scalars=3*width if kind not in ("gru", "transformer") else width if kind == "gru" else None,
                           history=history, timing=timing, metrics=metrics, logits_latency=latency,
                           checkpoint_file=str(checkpoint.relative_to(HERE)), checkpoint_sha256=sha(checkpoint),
                           prediction_file=str(prediction.relative_to(HERE)), prediction_sha256=sha(prediction),
                           total_run_wall_seconds=time.perf_counter()-start_wall,
                           total_run_cpu_seconds=time.process_time()-start_cpu)
                result["runs"].append(row)
                destination.write_text(json.dumps(result, indent=2)+"\n")
                print(json.dumps(dict(dataset=dataset, regime=regime, kind=kind, seed=seed, run=len(result["runs"]),
                                      test=metrics["test"]["accuracy"], corrupted=metrics["corrupted_test"]["accuracy"],
                                      seconds=row["total_run_wall_seconds"])), flush=True)
            # Keep only this study's bounded device state between independent seeds.
            predictor.cache_clear()
            jax.clear_caches()
            gc.collect()
    expected = len(protocol["models"])*len(protocol["regimes"])*len(protocol["training_seeds"])
    assert len(result["runs"]) == expected
    assert sha(feature_path) == result["features_sha256"]
    result["complete"] = True
    result["total_head_cpu_seconds"] = sum(r["total_run_cpu_seconds"] for r in result["runs"])
    result["total_head_wall_seconds"] = sum(r["total_run_wall_seconds"] for r in result["runs"])
    destination.write_text(json.dumps(result, indent=2)+"\n")
    print("COMPLETE", dataset, len(result["runs"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", choices=("ag_news", "cifar10", "all"))
    args = parser.parse_args()
    for name in ("ag_news", "cifar10") if args.dataset == "all" else (args.dataset,):
        run(name)
