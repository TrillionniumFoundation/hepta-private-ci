"""Recompute calibration from saved heads; preserve pre-audit training evidence."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import jax
import jax.numpy as jnp
import numpy as np
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from benchmarks.models import apply_model
from encoder.run_heads import ece


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path,
                        default=Path("/tmp/hcsn-encoder-assets/frozen_features.npz"))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    original = args.output/"pre_audit_head_results.json"
    results = json.loads(original.read_text())
    corrected = copy.deepcopy(results)
    raw = np.load(args.features)
    audit = {"original_results_sha256": sha(original),
             "original_run_heads_source_sha256":
             "adeb28cd68ea3650a8d69598c4bdccaa54135d824f9205f2965c1fde5a29534e",
             "current_run_heads_source_sha256": sha(Path(__file__).with_name("run_heads.py")),
             "feature_sha256": sha(args.features), "training_repeated": False,
             "purpose": "Correct metadata and metric bin partitions; replay saved predictions only",
             "checks": []}
    assert audit["feature_sha256"] == results["metadata"]["feature_sha256"]
    predictors = {}
    for run in corrected["runs"]:
        kind = run["kind"]
        checkpoint = args.output/run["checkpoint_file"]
        assert sha(checkpoint) == run["checkpoint_sha256"]
        params = {k:jnp.asarray(v) for k,v in np.load(checkpoint).items()}
        if kind not in predictors:
            predictors[kind] = jax.jit(lambda p,x,dt,k=kind: apply_model(p,x,dt,k))
        logits = predictors[kind](params, jnp.asarray(raw["test_x"]),
                                  jnp.asarray(raw["test_dt"]))
        probability = np.asarray(jax.nn.softmax(logits))
        accuracy = float(np.mean(probability.argmax(1) == raw["test_y"]))
        assert abs(accuracy-run["test"]["accuracy"]) < 1e-12
        previous = run["test"]["ece"]
        run["test"]["ece"] = ece(probability, raw["test_y"])
        audit["checks"].append(dict(kind=kind, seed=run["seed"],
            checkpoint_hash_matches=True, test_accuracy_reproduced=accuracy,
            original_ece=previous, corrected_ece=run["test"]["ece"]))
    linear = LogisticRegression(C=1., max_iter=1000, solver="lbfgs")
    linear.fit(raw["train_x"][:,-1], raw["train_y"])
    count = int(linear.coef_.size+linear.intercept_.size)
    assert count == 65
    corrected["linear_reference"]["parameter_count"] = count
    for split in ("validation", "test"):
        probability = linear.predict_proba(raw[split+"_x"][:,-1])
        accuracy = float(np.mean(probability.argmax(1) == raw[split+"_y"]))
        assert accuracy == corrected["linear_reference"][split]["accuracy"]
        corrected["linear_reference"][split]["ece"] = ece(probability, raw[split+"_y"])
    manifest = json.loads((args.output/"feature_manifest.json").read_text())
    fingerprints = {s:{r["normalized_text_sha256"] for r in rows}
                    for s,rows in manifest["selection"].items()}
    intersections = {a+"_"+b:len(fingerprints[a]&fingerprints[b])
                     for a,b in (("train","dev"),("train","test"),("dev","test"))}
    assert max(intersections.values()) == 0
    audit["selected_split_exact_text_overlap"] = intersections
    audit["linear_actual_parameters"] = count
    audit["max_ece_absolute_change"] = max(abs(r["original_ece"]-r["corrected_ece"])
                                           for r in audit["checks"])
    audit["timing_finding"] = ("The first update can turn weakly typed parameters into "
        "strong float32 values, causing a second JIT compilation. warm_training_seconds "
        "excludes only step zero and is not pure warm training time. Historical timing "
        "values are retained and must not support speed/efficiency conclusions.")
    audit["corruption_finding"] = ("Only local feature blocks are dropped after the "
        "complete truncated sentence has been encoded. The global mean remains; Gaussian "
        "noise also affects that retained global feature. This is not raw-input missingness.")
    audit["all_checks_passed"] = True
    corrected["metadata"]["post_audit"] = {
        "record":"audit_results.json", "raw_record":"pre_audit_head_results.json",
        "all_neural_checkpoint_accuracies_reproduced":True,
        "training_timing_usable_for_speed_comparison":False,
        "corruption_scope":audit["corruption_finding"],
        "changes":["Linear reference parameter count 130 -> 65",
                   "Nonoverlapping integer ECE bins; predictions and model parameters unchanged"]}
    (args.output/"head_results.json").write_text(json.dumps(corrected,indent=2)+"\n")
    audit["corrected_results_sha256"] = sha(args.output/"head_results.json")
    (args.output/"audit_results.json").write_text(json.dumps(audit,indent=2)+"\n")
    print(json.dumps({k:v for k,v in audit.items() if k != "checks"},indent=2))


if __name__ == "__main__":
    main()
