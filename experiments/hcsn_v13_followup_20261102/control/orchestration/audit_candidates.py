"""Artifact arithmetic and preselected actual TRAIN target replay; no TEST use."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
from experiments.hcsn_v13_followup_20261102.joint_core.campaign import configure
from experiments.hcsn_v13_followup_20261102.control.value_fit import load, load_packet, tree
from experiments.hcsn_v13_followup_20261102.control.runtime import feature, sha
from experiments.hcsn_v8_execution_20261101.scheduler.planning import Plan, Read
from experiments.hcsn_v7_support_20261101.content_interface.content_interface import Modality


def audit(run, out):
    plan = json.loads((run / "PLAN.json").read_text())
    sealed = json.loads((run / "CANDIDATES.json").read_text())
    checks, rows, maximum = 0, [], 0.

    def require(ok, label):
        nonlocal checks
        checks += 1
        if not bool(ok): raise AssertionError(label)

    require(sealed["test_opened"] is False and len(sealed["models"]) == 36, "complete untouched-TEST roster")
    packets = {(task, split): load_packet(run / f"{task}-{split}.npz")
               for task in plan["protocol"]["tasks"] for split in ("train", "val")}
    for item in sealed["models"]:
        directory = run / item["directory"]
        for name, digest in item["files"].items(): require(sha(directory / name) == digest, "frozen actual candidate bytes")
        model, norm, reader, metadata = load(directory)
        require(all(torch.isfinite(p).all() for p in reader.parameters()), "all learned reader parameters finite")
        require(len(metadata["losses"]) == 128 and np.isfinite(metadata["losses"]).all(), "all fixed optimizer losses finite")
        require(np.isfinite(metadata["value_mean"]).all() and np.isfinite(metadata["value_scale"]).all()
                and np.min(metadata["value_scale"]) > 0, "train-only reader normalization finite/positive")
        for key in ("stop_calibration", "future_calibration"):
            p = np.asarray(metadata[key]["rates"])
            require(p.shape == (5,) and np.isfinite(p).all() and np.all((0 <= p) & (p <= 1)), "calibration probability domain")
        selected, counts = [], {"train": 0, "val": 0}
        with gzip.open(directory / "FUTURE_TARGETS.jsonl.gz", "rt") as stream:
            for row in map(json.loads, stream):
                split = row["split"]
                require(split in counts, "targets only declared TRAIN/VAL roles")
                counts[split] += 1
                require(0 <= row["object"] < len(packets[item["task"], split]["labels"]), "actual object index")
                p = np.asarray(row["future_probabilities"])
                require(p.shape == (model.classes,) and np.isfinite(p).all() and np.all(p >= 0)
                        and abs(p.sum()-1) < 1e-12, "actual target class probabilities finite/normalized")
                label = int(row["label_for_training_only"])
                require(label == int(packets[item["task"], split]["labels"][row["object"]]), "exact declared role label")
                require(row["correct"] == int(p.argmax() == label), "actual future correctness arithmetic")
                current, future = row["current"], row["future"]
                require(future[:len(current)] == current and 1 <= len(future)-len(current) <= 2,
                        "exact ordered descendant, bounded horizon")
                if split == "train" and row["object"] == 0: selected.append(row)
        require(counts["train"] == metadata["training_rows"] and counts["val"] == metadata["calibration_rows"], "complete target counts")
        require(sum(metadata["future_calibration"]["counts"]) == counts["val"], "future calibration bins cover actual rows")
        nodes = tree(model, norm, packets[item["task"], "train"], 0, metadata["train_prior"])
        for row in selected:
            current = tuple(tuple(x) for x in row["current"])
            future = tuple(tuple(x) for x in row["future"])
            actual = np.asarray(nodes[future]["p"])
            expected = np.asarray(row["future_probabilities"])
            maximum = max(maximum, float(abs(actual-expected).max()))
            require(np.allclose(actual, expected, atol=1e-15, rtol=0), "actual preselected neural future replay")
            steps = future[len(current):]
            plan_steps = Plan(tuple(Read(Modality(m), level) for m, level in steps))
            history = [tensor[0].tolist() for tensor in nodes[current]["history"]]
            values = feature(history, nodes[current]["p"], plan_steps)
            require(hashlib.sha256(values.tobytes()).hexdigest() == row["feature_sha256"], "actual current-only reader feature replay")
        rows.append({"task": item["task"], "family": item["family"], "seed": item["seed"],
                     "target_counts": counts, "replayed_actual_train_tree_updates": len(nodes)-1,
                     "replayed_target_records": len(selected)})
    result = {"schema": "hcsn-v13-new-reader-artifact-audit.v1", "checks": checks, "all_checks_passed": True,
              "rows": rows, "maximum_replayed_probability_difference": maximum, "test_opened": False,
              "candidates_sha256": sha(run / "CANDIDATES.json"),
              "scope": "All saved weight/target arithmetic and finite domains; actual preselected TRAIN object0 same-implementation neural replay. Not a second independent neural implementation or quality confirmation."}
    with out.open("x") as stream: json.dump(result, stream, indent=2); stream.write("\n")
    print(json.dumps({key: result[key] for key in ("checks", "all_checks_passed", "maximum_replayed_probability_difference")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True); parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); configure(); audit(args.run, args.out)
