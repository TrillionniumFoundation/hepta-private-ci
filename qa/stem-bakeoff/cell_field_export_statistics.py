"""Export post-seal source-level audit statistics without plaintext label files."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

from cell_field_score_v5 import decrypt_roles


def read(path):
    return json.loads(path.read_bytes())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export(version, run, data, protocol, evaluation, label_key):
    run, data, protocol, output = map(Path, (run, data, protocol, evaluation))
    plan, evaluation, audit = read(protocol), read(output/"evaluation.json"), read(output/"pre_label_audit.json")
    assert audit["all_replays_valid"] and evaluation["pre_label_audit_sha256"] == sha(output/"pre_label_audit.json")
    assert evaluation["protocol_sha256"] == sha(protocol)
    assert evaluation["pre_evaluation_seal_sha256"] == sha(run/"pre_evaluation_seal.json")
    manifest = {"schema": "hepta.cell-field-post-label-audit-inputs."+version,
        "protocol_sha256": sha(protocol), "evaluation_sha256": sha(output/"evaluation.json"),
        "pre_evaluation_seal_sha256": sha(run/"pre_evaluation_seal.json"),
        "pre_label_audit_sha256": sha(output/"pre_label_audit.json"), "exporter_sha256": sha(Path(__file__)),
        "source_roles": [], "metric_rows": [], "contrasts": [], "cost_records": [],
        "scope": "post-authorized-evaluation component/stratum and per-source sufficient statistics; no text or key; no model retuning",
        "bootstrap_order": {"tasks": plan["evaluation"]["tasks"], "splits": ["current", "future", "old"],
            "strata": [0, 1, 2, 3], "source_order": "np.unique(component IDs), lexical", "rng": "PCG64 seed20261025",
            "replicates": 10000, "within_stratum": "draw its component count with replacement, concatenate class0..3",
            "pairing": "mean the three paired seed loss differences per source before resampling; reuse role draws across all heads/contrasts",
            "quantile": "higher quantile at1-0.05/12"}}
    arrays = {}
    roles_by_split = {"current": "current_validation", "future": "future_test", "old": "old_test"}
    p = plan["evaluation"]

    def metric(task, head, seed, policy, split, predictions, role):
        labels = role["labels"]
        values = predictions[role["indices"]]
        prefix = f"{task}__{head}__{seed}__{policy}__{split}"
        arrays[prefix+"__nll"] = -np.log(np.maximum(values[np.arange(len(labels)), labels], np.finfo(float).tiny))
        arrays[prefix+"__correct"] = (np.argmax(values, axis=1) == labels).astype(np.uint8)
        arrays[prefix+"__brier"] = np.square(values-np.eye(4)[labels]).sum(axis=1)
        manifest["metric_rows"].append({"task": task, "head": head, "seed": seed, "policy": policy, "split": split,
            "nll_key": prefix+"__nll", "correct_key": prefix+"__correct", "brier_key": prefix+"__brier"})

    for task in p["tasks"]:
        inputs = read(run/task/"inputs.json")
        roles = decrypt_roles(data/task, inputs, plan, task, sha(protocol), label_key)
        for split, name in roles_by_split.items():
            prefix = task+"__"+split
            arrays[prefix+"__strata"] = roles[name]["labels"].astype(np.int8)
            arrays[prefix+"__components"] = roles[name]["components"]
            manifest["source_roles"].append({"task": task, "split": split,
                "strata_key": prefix+"__strata", "components_key": prefix+"__components", "rows": len(roles[name]["labels"])})
        for head in p["heads"]:
            for seed in p["seeds"]:
                fit = run/task/f"seed{seed}-{head}"
                with np.load(fit/"warmup/warmup.npz", allow_pickle=False) as source:
                    metric(task, head, seed, "warmup_old", "old", source["probabilities"], roles["old_test"])
                for policy in p["policies"]:
                    path = fit/"mpc"/policy
                    record = read(path/"result.json")
                    with np.load(path/"trajectory.npz", allow_pickle=False) as source:
                        for split, name in roles_by_split.items():
                            metric(task, head, seed, policy, split, source["terminal_probabilities"], roles[name])
                    checked = next(row for row in audit["rows"] if (row["task"], row["head"], row["seed"], row["policy"]) == (task, head, seed, policy))
                    manifest["cost_records"].append({"task": task, "head": head, "seed": seed, "policy": policy,
                        **{k: record[k] for k in ("status", "completed_steps", "registered_steps", "cpu_ns", "wall_ns")},
                        "valid_record": checked["valid_record"], "result_sha256": sha(path/"result.json")})
            for split, baseline in [("future", b) for b in p["primary_future_baselines"]]+[("old", "warmup_old")]:
                name = f"{task}__{head}__{baseline}__{split}__paired_delta"
                arrays[name] = np.stack([arrays[f"{task}__{head}__{seed}__{p['candidate']}__{split}__nll"]
                    -arrays[f"{task}__{head}__{seed}__{baseline}__{split}__nll"] for seed in p["seeds"]])
                manifest["contrasts"].append({"task": task, "head": head, "split": split,
                    "candidate": p["candidate"], "baseline": baseline, "paired_delta_key": name})
    destination = output/"audit_inputs.npz"
    if destination.exists() or (output/"audit_inputs.json").exists():
        raise ValueError("never overwrite a post-label audit export")
    with destination.open("xb") as stream:
        np.savez_compressed(stream, **arrays)
    manifest.update(arrays_sha256=sha(destination), arrays_bytes=destination.stat().st_size,
        metric_count=len(manifest["metric_rows"]), contrast_count=len(manifest["contrasts"]), cost_record_count=len(manifest["cost_records"]))
    with (output/"audit_inputs.json").open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return {"version": version, "directory": str(output), "arrays_sha256": manifest["arrays_sha256"],
        "manifest_sha256": sha(output/"audit_inputs.json"), "bytes": manifest["arrays_bytes"],
        "metric_count": manifest["metric_count"], "contrast_count": manifest["contrast_count"], "cost_record_count": manifest["cost_record_count"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v5", "v6"), required=True)
    for name in ("run", "data", "protocol", "evaluation"):
        parser.add_argument("--"+name, required=True)
    args = vars(parser.parse_args())
    print(json.dumps(export(**args, label_key=bytes.fromhex(sys.stdin.readline().strip()))))
