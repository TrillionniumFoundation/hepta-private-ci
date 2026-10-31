"""Recompute proper-moment calibration from actual retained features/weights."""

import argparse
from collections import Counter
import io
import json
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from .core import Audit, ce, read, sha


def run(output):
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=False)
    v3 = Path(__file__).resolve().parent.parent
    root = v3/"evidence/diagnostics_frozen_20261030"
    report, protocol = read(root/"critic_fit/FIT_VALIDATION.json"), read(root/"STUDY_PROTOCOL.json")
    paths = {"before": v3/"evidence/matrix_frozen_20261030/seed-17-width-32/dual.joint.dynamic/MODEL.pt",
             "after": root/"MODEL_CALIBRATED.pt"}
    states = {stage: torch.load(path, map_location="cpu", weights_only=True)["state_dict"] for stage, path in paths.items()}
    audit, metrics = Audit(v3, io.StringIO()), {}
    torch.set_num_threads(1)
    for role, directory_role in (("training", "fit"), ("validation", "analysis")):
        rows = []
        for source in range(protocol["sources_per_role"]):
            for prefix in range(len(protocol["prefixes"])):
                for continuation in protocol["continuations"]:
                    path = root/directory_role/f"source-{source:03d}"/f"prefix-{prefix}"/continuation/"DIAGNOSTICS.json"
                    rows.extend(read(path)["rows"])
        rows = [r for r in rows if r["critic_fit_available"]]
        counts = Counter(r["source_id"] for r in rows)
        data = np.load(root/f"critic_fit/{role.upper()}_FIT_DATA.npz", allow_pickle=False)
        for head in ("critic", "delivery_critic"):
            chosen = [row for row in rows if row["critic_fit_head"] == head]
            x = torch.tensor([r["critic_fit_features"] for r in chosen], dtype=torch.float32)
            y = torch.tensor([r["critic_fit_suffix_return"] for r in chosen], dtype=torch.float32)
            weights = torch.tensor([1/(len(counts)*counts[r["source_id"]]) for r in chosen], dtype=torch.float32)
            for index, value in enumerate((x, y, weights)):
                audit.check(np.array_equal(value.numpy(), data[f"state/{head}/{index}"]), "retained_source_uniform_fit_tensor", root)
            mass = weights/weights.sum()
            for stage, state in states.items():
                with torch.no_grad():
                    hidden = torch.tanh(F.linear(x, state[head+".0.weight"], state[head+".0.bias"]))
                    value = F.linear(hidden, state[head+".2.weight"], state[head+".2.bias"])[:, 0]
                    prediction, target = value.exp(), torch.exp(-2*y)
                    actual = {"proper_moment_loss": float((mass*(prediction-target*value)).sum()),
                              "weighted_moment_bias": float((mass*(prediction-target)).sum()),
                              "aggregate_ce_error": ce((-value/2).numpy(), mass.numpy())-ce(y.numpy(), mass.numpy()),
                              "samples": len(chosen)}
                for key, number in actual.items():
                    audit.near(report[stage][role][head][key], number, "independent_calibration_"+key, root, 3e-7)
                metrics[f"{stage}/{role}/{head}"] = actual
    pilot = v3/"evidence/matrix_20261030"
    status = read(pilot/"ATTEMPT_STATUS.json")
    audit.check(status["preserve_all_outputs"] and status["status"] == "interrupted_pilot_not_primary_matrix" and
                status["replacement_directory"] == "matrix_frozen_20261030", "superseded_attempt_explicitly_retained", pilot)
    pilot_traces = len(list(pilot.glob("seed-*-width-*/*/training/update-*/draw-*/TRAJECTORY.json")))
    audit.check(pilot_traces > 0, "superseded_attempt_raw_trajectories_present", pilot)
    result = {"schema": "hepta.v3.independent-calibration-audit.v1", "passed": not audit.errors,
              "errors": audit.errors, "checks": dict(audit.counts), "recomputed_metrics": metrics,
              "source_sha256": {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
              "fit_validation_sha256": sha(root/"critic_fit/FIT_VALIDATION.json"),
              "actual_checkpoint_sha256": {stage: sha(path) for stage, path in paths.items()},
              "retained_pilot_status_sha256": sha(pilot/"ATTEMPT_STATUS.json"),
              "retained_pilot_training_trajectories": pilot_traces,
              "scope": "actual feature/target/source weights and actual before/after critic parameters; no optimizer rerun or policy-improvement claim"}
    (output/"AUDIT.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"audit_passed": result["passed"], "metric_cells": len(metrics), "errors": len(audit.errors)}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.output)
    raise SystemExit(0 if result["passed"] else 1)
