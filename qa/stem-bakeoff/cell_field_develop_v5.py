"""Explicit development-only configuration search on already disclosed V4 data."""

import argparse
import json
from pathlib import Path

import numpy as np

from cell_field_action_io import write_json, source_hashes
from cell_field_policy_v5 import execute_policy
from cell_field_state import CellTrainingState


def development_inputs(root, data, task, seed, head):
    run = root / task / f"seed{seed}-{head}"
    checkpoint = run / "warmup/checkpoint"
    manifest = json.loads((checkpoint / "manifest.json").read_bytes())
    state = CellTrainingState.load(checkpoint, manifest["bindings"], manifest["protocol"],
                                   manifest["contexts"], manifest["state_sha256"])
    with np.load(root / task / "training.npz", allow_pickle=False) as a:
        split = {role: (a[role+"_x"], a[role+"_y"]) for role in
                 ("current_train", "current_probe", "old_train", "old_probe")}
    with np.load(root / task / "projected.npz", allow_pickle=False) as a:
        features = a["features"]
    validation = json.loads((data/task/"validation_labels.json").read_bytes())["roles"]
    values = {role: (features[row["indices"]], np.asarray(row["labels"])) for role, row in validation.items()}
    anchor = json.loads((run / "warmup/result.json").read_bytes())["old_anchor"]
    return state, split, values, anchor


def nll(state, pair):
    x, y = pair
    p = state.head.predict_proba(x)
    return float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1)).mean())


def run(root, data, output):
    root, data, output = map(Path, (root, data, output))
    output.mkdir(parents=True, exist_ok=False)
    write_json(output/"executed_source.json",source_hashes())
    policies = ("myopic_full_h1", "myopic_guarded_h1", "loss2_h8", "response_h8_guarded")
    configs = [{"steps": 32, "dt": .02, "effort_price": rho, "action_bound": 4.,
                "old_weight": weight, "hard_retention": True, "backtracking": [1., .5, .25, .125, 0.]}
               for weight in (0., .5, 1.) for rho in (.03, .1, .3)]
    plan = {"scope": "development only; V4 outcomes were disclosed before this search",
        "data": str(data), "configurations": configs, "policies": list(policies),
        "selection": "lexicographic: candidate incomplete count, groups with old validation regression, groups CPU>3, mean paired current-validation difference vs H1; all V4 labels are development"}
    write_json(output/"plan.json", plan)
    rows, summaries = [], []
    for index, config in enumerate(configs):
        group = []
        for task in ("uci", "newsgroups"):
            for head in ("linear", "gated"):
                for seed in (7, 17, 29):
                    state, split, validation, anchor = development_inputs(root, data, task, seed, head)
                    warm_old = nll(state, validation["old_validation"])
                    for policy in policies:
                        result = execute_policy(state, split, anchor, policy, config)
                        row = {"configuration": index, "task": task, "head": head, "seed": seed,
                            **{k: result["record"][k] for k in ("policy", "status", "cpu_ns", "completed_steps")},
                            "current_nll": nll(result["state"], validation["current_validation"]),
                            "old_nll": nll(result["state"], validation["old_validation"]), "warmup_old_nll": warm_old}
                        rows.append(row)
                        group.append(row)
                        write_json(output/f"config{index}/{task}-{head}-{seed}-{policy}.json", result["record"])
        differences, retention, ratios = [], [], []
        for task in ("uci", "newsgroups"):
            for head in ("linear", "gated"):
                candidate = [r for r in group if r["task"]==task and r["head"]==head and r["policy"]=="response_h8_guarded"]
                baseline = [r for r in group if r["task"]==task and r["head"]==head and r["policy"]=="myopic_full_h1"]
                differences.append(float(np.mean([r["current_nll"] for r in candidate])-np.mean([r["current_nll"] for r in baseline])))
                retention.append(float(np.mean([r["old_nll"]-r["warmup_old_nll"] for r in candidate])))
                ratios.append(sum(r["cpu_ns"] for r in candidate)/sum(r["cpu_ns"] for r in baseline))
        incomplete = sum(r["completed_steps"]!=32 for r in group if r["policy"]=="response_h8_guarded")
        key = [incomplete, sum(v>0 for v in retention), sum(v>3 for v in ratios), float(np.mean(differences))]
        summary = {"configuration": index, "selection_key": key, "current_differences": differences,
                   "old_differences": retention, "cpu_ratios": ratios}
        summaries.append(summary)
        write_json(output/"progress.json", {"rows": rows, "summaries": summaries})
        print(json.dumps(summary), flush=True)
    selected = min(summaries, key=lambda s: (s["selection_key"], s["configuration"]))
    report = {"schema": "hepta.cell-field-development.v5", **plan, "rows": rows, "summaries": summaries,
              "selected_index": selected["configuration"], "selected_configuration": configs[selected["configuration"]],
              "scope_note": "selection is descriptive development, never independent validation or gate passage"}
    write_json(output/"development.json", report)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "data", "output"):
        p.add_argument("--"+name, required=True)
    run(**vars(p.parse_args()))
