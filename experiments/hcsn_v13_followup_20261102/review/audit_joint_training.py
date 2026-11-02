"""Audit all formal joint fits without opening evaluation data or labels.

Reconstructs initialization and minibatch streams, checks actual final weights,
normalization, step logs and identities. This is not a second 128-step training
run and does not substitute for later heldout or execution-channel evaluation.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_v13_followup_20261102.joint_core.model import Model


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def state_digest(state):
    result = hashlib.sha256()
    for name, value in sorted(state.items()):
        result.update(name.encode()+value.detach().numpy().tobytes())
    return result.hexdigest()


def audit(root, run):
    torch.set_num_threads(1)
    checks, failed = 0, []

    def check(ok, label):
        nonlocal checks
        checks += 1
        if not ok and len(failed) < 30:
            failed.append(label)

    plan = json.loads((run/"PLAN.json").read_text())
    roster = json.loads((run/"CANDIDATES.json").read_text())
    p = plan["protocol"]
    check(roster["plan_sha256"] == sha(run/"PLAN.json") and roster["evaluation_opened"] is False, "candidate freeze binds untouched-evaluation training plan")
    for path, value in plan["source_sha256"].items():
        check(sha(root/path) == value, "frozen executed source")
    for path, value in plan["input_sha256"].items():
        check(sha(run/path) == value, "frozen TRAIN input archive")
    expected = {(task, family, seed) for task in p["tasks"] for family in p["families"] for seed in p["seeds"]}
    actual = {(item["task"], item["family"], item["seed"]) for item in roster["models"]}
    check(len(roster["models"]) == len(actual) == len(expected) == 36 and actual == expected, "all thirty-six predeclared fits")
    inputs = {}
    for task in p["tasks"]:
        with np.load(run/(task+"-TRAIN.npz"), allow_pickle=False) as z:
            x = z["x"].copy(); y = z["y"].copy()
            center, scale = z["center"].copy(), z["scale"].copy()
        check(x.shape[1:] == (6, 55) and y.shape == x.shape[:2], "actual class-target training tensor layout")
        check(hashlib.sha256(x.tobytes()).hexdigest() == plan["training_identities"][task]["x_sha256"] and
              hashlib.sha256(y.tobytes()).hexdigest() == plan["training_identities"][task]["y_sha256"], "training tensor/target identities")
        values = x.reshape(-1, 55)
        expected_center, expected_scale = np.zeros(55), np.ones(55)
        columns = list(range(32))+list(range(35, 51))
        expected_center[columns] = values[:, columns].mean(0)
        expected_scale[columns] = np.maximum(values[:, columns].std(0), 1e-5)
        check(np.array_equal(center, expected_center) and np.array_equal(scale, expected_scale), "normalization independently reconstructed from TRAIN only")
        inputs[task] = len(x), center, scale
    rows, initial_groups, stream_groups = [], {}, {}
    for item in roster["models"]:
        task, family, seed = item["task"], item["family"], item["seed"]
        directory = run/item["directory"]
        record = json.loads((directory/"TRAIN.json").read_text())
        check(sha(directory/"TRAIN.json") == item["train_metadata_sha256"] and sha(directory/"weights.pt") == item["weights_sha256"] == record["weights_sha256"], "candidate metadata and true weights bytes")
        check(sha(directory/"NORMALIZATION.npz") == record["normalization_sha256"], "normalization bytes identity")
        check(record["plan_sha256"] == sha(run/"PLAN.json") and record["source_sha256"] == plan["source_sha256"], "per-fit executed plan/source identity")
        check(record["evaluation_opened"] is False and record["classes"] == p["tasks"][task], "new class head task identity")
        with np.load(directory/"NORMALIZATION.npz", allow_pickle=False) as z:
            check(np.array_equal(z["center"], inputs[task][1]) and np.array_equal(z["scale"], inputs[task][2]), "every family shares exact TRAIN normalizer")
        training = record["training"]
        streamed = [json.loads(line) for line in (directory/"UPDATES.jsonl").read_text().splitlines()]
        check(training == streamed and [r["update"] for r in training] == list(range(1, 129)) and record["optimizer_updates"] == 128, "all actual update records agree, final-only128")
        check(all(np.isfinite(r["loss"]) and r["loss"] >= 0 for r in training), "finite actual class-CE losses")
        generator = torch.Generator().manual_seed(seed+100000)
        digest = hashlib.sha256()
        for _ in range(128):
            batch = torch.randint(inputs[task][0], (64,), generator=generator)
            digest.update(batch.numpy().tobytes())
        check(record["batch_stream_sha256"] == digest.hexdigest(), "independent exact minibatch stream reconstruction")
        stream_groups.setdefault((task, seed), set()).add(record["batch_stream_sha256"])
        torch.manual_seed(seed)
        initial = Model(family, p["tasks"][task])
        check(state_digest(initial.state_dict()) == record["initial_state_sha256"], "independent true initialization reconstruction")
        check(sum(v.numel() for v in initial.parameters()) == record["parameter_count"], "actual parameter count")
        final = torch.load(directory/"weights.pt", map_location="cpu", weights_only=True)
        check(set(final) == set(initial.state_dict()) and all(torch.isfinite(v).all() for v in final.values()), "complete finite final tensors")
        check(torch.equal(final["financial.boundary"], initial.state_dict()["financial.boundary"]), "financial boundary remains fixed declared law")
        if family in ("hx_full", "hx_margin", "ordinary_gate"):
            initial_groups.setdefault((task, seed), set()).add(record["initial_state_sha256"])
            gradients = [r["asset_encoder_gradient_norm"] for r in training]
            check(all(g is not None and np.isfinite(g) and g >= 0 for g in gradients) and max(gradients) > 0, "formal asset encoder receives nonzero finite class gradients")
            change = float((final["asset_drive.weight"]-initial.asset_drive.weight.detach()).norm())
            check(np.isclose(change, record["asset_encoder_weight_change_norm"], rtol=1e-12, atol=1e-12) and change > 0, "actual learned asset-encoder weight change")
        rows.append({"task": task, "family": family, "seed": seed, "updates": 128,
                     "parameter_count": record["parameter_count"], "initial_loss": training[0]["loss"], "final_loss": training[-1]["loss"]})
    check(all(len(v) == 1 for v in stream_groups.values()), "same per-task/seed batches across all families")
    check(all(len(v) == 1 for v in initial_groups.values()), "identical allocated initialization for all three HX/gate arms")
    return {"schema": "hcsn-v13-independent-joint-training-record-audit.v1", "checks": checks,
            "all_checks_passed": not failed, "failed_examples": failed, "fits": len(rows), "optimizer_updates": len(rows)*128,
            "rows": rows, "validation_or_test_loaded": False,
            "scope": "Actual frozen TRAIN tensors, initialization, exact batch streams, all step logs and final parameter identities; no second full fit or evaluation qualification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = audit(args.root, args.run)
    with args.out.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    print(json.dumps({k: v for k, v in value.items() if k != "rows"}))
    raise SystemExit(0 if value["all_checks_passed"] else 1)
