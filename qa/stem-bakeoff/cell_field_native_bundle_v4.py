"""Bind actual research checkpoints and a frozen report for native rejection QA.

This exports an opaque float64 research bundle, not a native Q24 serving model.
It grants no reviewer trust, production publication, activation or new efficacy.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from cell_field_action_io import write_json
from cell_field_evaluate_v4 import verify_pre_label_seal
from cell_field_features import file_hash
from cell_learning_models import canonical


def _digest_definition(value):
    encoded = canonical(value)
    return {"definition_json": encoded.decode(), "comparison_sha256": hashlib.sha256(encoded).hexdigest()}


def _bundle(root, plan, candidate):
    rows = []
    for task in plan["tasks"]:
        for head in plan["head_modes"]:
            for seed in plan["seeds"]:
                directory = root / task / f"seed{seed}-{head}"
                relative = f"mpc/{plan['mpc']['candidate']}/terminal" if candidate else "warmup/checkpoint"
                checkpoint = directory / relative
                manifest = json.loads((checkpoint / "manifest.json").read_bytes())
                if candidate:
                    result = json.loads((directory / f"mpc/{plan['mpc']['candidate']}/result.json").read_bytes())
                    if result["status"] != "completed" or result["completed_steps"] != 8:
                        raise ValueError("cannot turn an incomplete fitted candidate into a complete payload")
                if file_hash(checkpoint / "state.npz") != manifest["payload_sha256"]:
                    raise ValueError("checkpoint payload identity mismatch")
                with np.load(checkpoint / "state.npz", allow_pickle=False) as archive:
                    tensors = {name: {"dtype": str(archive[name].dtype), "shape": list(archive[name].shape),
                                      "values": archive[name].tolist()} for name in sorted(archive.files)}
                rows.append({"task": task, "head": head, "seed": seed, "checkpoint_manifest": manifest,
                             "tensors": tensors, "origin": checkpoint.relative_to(root).as_posix()})
    with np.load(root / plan["tasks"][0] / "projected.npz", allow_pickle=False) as archive:
        projection = archive["projection"]
    for task in plan["tasks"][1:]:
        with np.load(root / task / "projected.npz", allow_pickle=False) as archive:
            if not np.array_equal(projection, archive["projection"]):
                raise ValueError("the frozen projection must be identical across tasks")
    return {"schema": "research-numpy-float64-bundle.v1", "candidate": plan["mpc"]["candidate"] if candidate else "warmup",
            "fits": rows, "projection": projection.tolist(), "encoder": plan["encoder"],
            "encoder_revision": plan["encoder_revision"], "optimizer_state_included": True,
            "serving_compatible": False, "authority": "DENY_ALL", "production_authority": False}


def build(run, protocol, report, output):
    root, protocol, report, output = map(Path, (run, protocol, report, output))
    verify_pre_label_seal(root, protocol)
    plan, evaluation = json.loads(protocol.read_bytes()), json.loads(report.read_bytes())
    if evaluation["protocol_sha256"] != file_hash(protocol):
        raise ValueError("scientific report protocol mismatch")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "candidate-parameters.json", _bundle(root, plan, True))
    write_json(output / "predecessor-parameters.json", _bundle(root, plan, False))
    source_datasets = {task: json.loads((root / task / "inputs.json").read_bytes())["input_hashes"]
                       for task in plan["tasks"]}
    write_json(output / "source-datasets.json", source_datasets)
    candidate = _digest_definition({key: plan[key] for key in ("models", "mpc", "evaluation")})
    comparisons = {}
    for name, split, threshold in (("task", "future", -0.001), ("retention", "old", 0.0), ("total_cost", None, 3.0)):
        definition = {"group": name, "protocol_sha256": file_hash(protocol),
            "frozen_evaluation": plan["evaluation"], "aggregation": "maximum over every registered constituent; no missing values",
            "operator": "strict_less" if name == "task" else "less_equal", "threshold": threshold,
            "observation_unit": "paired timed seed runs per fixed ratio" if split is None else
                                "minimum distinct source components among constituent contrasts"}
        comparison = {**_digest_definition(definition), "evidence_sha256": file_hash(report)}
        selected = (evaluation["cost_contrasts"] if split is None else
                    [r for r in evaluation["primary_contrasts"] if r["split"] == split])
        complete = (evaluation["census_complete"] and evaluation["cost_census_complete"]
                    and len(selected) == (8 if name == "task" else 4)
                    and all(r["status"] == "completed" for r in selected))
        if complete:
            upper = max(r["cpu_ratio"] if split is None else r["upper_bound"] for r in selected)
            estimate = upper if split is None else max(r["difference"] for r in selected)
            complete = bool(np.isfinite([upper, estimate]).all() and estimate <= upper)
        comparison["measurement"] = ({"status": "measured", "upper_bound": upper,
            "estimate": estimate, "lower_bound": 0.0 if split is None else -710.0,
            "observations": 3 if split is None else min(r["source_components"] for r in selected),
            "lower_bound_scope": "nonnegative measured CPU ratio" if split is None else
                                 "conservative NLL-difference support floor; not a bootstrap confidence endpoint"}
                                     if complete else {"status": "unavailable"})
        comparisons[name] = comparison
    result = {"schema": "hepta.actual-scientific-review-input.v4", "protocol_sha256": file_hash(protocol),
        "report_sha256": file_hash(report), "candidate_sha256": file_hash(output / "candidate-parameters.json"),
        "predecessor_sha256": file_hash(output / "predecessor-parameters.json"),
        "candidate_definition_sha256": candidate["comparison_sha256"],
        "candidate_definition_json": candidate["definition_json"], "comparisons": comparisons,
        "training_code_sha256": file_hash(root / "executed_source.json"),
        "runtime_sha256": file_hash(root / "run.json"),
        "runtime_identity_scope": "entire sealed run manifest, including exact environment and encoder receipts",
        "source_dataset_sha256": file_hash(output / "source-datasets.json"),
        "source_dataset_definition_json": (output / "source-datasets.json").read_text(),
        "candidate_format": "research-numpy-float64-bundle.v1", "all_registered_gates_met": evaluation["all_registered_gates_met"],
        "census_complete": evaluation["census_complete"], "cost_census_complete": evaluation["cost_census_complete"],
        "pre_evaluation_seal_sha256": file_hash(root / "pre_evaluation_seal.json"),
        "trust_scope": "explicit ephemeral research host/reviewer fixture; not installed production trust",
        "production_authority": False}
    write_json(output / "gate-input.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "protocol", "report", "output"):
        parser.add_argument("--" + name, required=True)
    result = build(**vars(parser.parse_args()))
    print(json.dumps({key: result[key] for key in ("candidate_sha256", "predecessor_sha256", "all_registered_gates_met")}))
