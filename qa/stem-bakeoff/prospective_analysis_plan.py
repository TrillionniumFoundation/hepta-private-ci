"""Freeze source-only scoring support and contrasts before prospective inference."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_learning_models import canonical
from operational_feature_availability import capture_feature_bundle
from operational_region_evidence import capture, verify_pins


CONDITIONS = ("identifier_overlap3", "identifier_hash770", "granite_clean_field770")
BUDGETS, SEEDS = (8, 32, 64), (7, 17, 29)
ARMS = ("prior_only", "exact", "bm25", "dense_nearest", "prototype", "linear", "gated", "residual")
CONTROLS = ("parameters_off", "shuffled_parameters")
CODE = ("prospective_analysis_plan.py", "prospective_analysis_artifacts.py", "prospective_action_analysis.py",
        "prospective_action_ranking.py", "prospective_action_compare.py", "cell_group_metrics.py",
        "cell_learning_models.py", "operational_feature_availability.py", "operational_region_evidence.py",
        "prospective_action_learning_run.py")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def code_hashes():
    return {name: sha(Path(__file__).with_name(name).read_bytes()) for name in CODE}


def source_digest(row):
    return sha(canonical({key: value for key, value in row.items() if key not in ("labels", "outcome_provenance")}))


def fixed_contrasts():
    contrasts = []
    for budget in BUDGETS:
        for feature in CONDITIONS:
            pairs = (("gated", "linear"), ("residual", "linear"), ("selected", "prior_only"),
                     ("linear", "prior_only"), ("selected", "raw_jaccard"), ("selected", "command_hash"))
            for left, right in pairs:
                contrasts.append({"budget": budget, "left": [feature, left],
                    "right": [None if right in ("raw_jaccard", "command_hash") else feature, right]})
        for arm in ("linear", "gated", "selected"):
            contrasts.append({"budget": budget, "left": ["granite_clean_field770", arm],
                              "right": ["identifier_hash770", arm]})
    return contrasts


def make_plan(inputs, input_sha256, condition_records, raw_jaccard):
    """Pure plan construction; the filesystem entry point authenticates feature inputs."""
    tasks, rows = inputs["selected_tasks"], inputs["rows"]
    if (inputs.get("all_labels_unobserved") is not True or len(tasks) != 1
            or any(row["labels"] != {tasks[0]: None} for row in rows)
            or len({r["source_id"] for r in rows}) != len(rows)):
        raise ValueError("unique source-only rows with entirely unobserved labels required")
    proposals = [{"group_id": group, "repo": binding["project"], "split": binding["role"],
                  "actions": binding["actions"]} for group, binding in sorted(inputs["case_bindings"].items())]
    holdout = [g["group_id"] for g in proposals if g["split"] == "holdout"]
    if len(holdout) != 48 or set(condition_records) != set(CONDITIONS):
        raise ValueError("exact three feature conditions and all48 prospective groups required")
    sources = {r["source_id"]: r for r in rows}
    proposed = {a["source_id"]: g for g in proposals for a in g["actions"] if a["source_id"] is not None}
    if len(proposed) != sum(a["source_id"] is not None for g in proposals for a in g["actions"]) or set(proposed) != set(sources):
        raise ValueError("unique complete proposed-source mapping required")
    for source, group in proposed.items():
        if any(sources[source][key] != group[key] for key in ("group_id", "repo", "split")):
            raise ValueError("source rows differ from proposal roles")
    for name, record in condition_records.items():
        available = record["feature_available_source_ids"]
        expected = [r["source_id"] for r in rows if r["source_id"] in set(available)]
        if (available != expected or len(set(available)) != len(available)
                or record["width"] != (3 if name == "identifier_overlap3" else 770)
                or record["holdout_source_ids"] != [s for s in available if sources[s]["split"] == "holdout"]):
            raise ValueError("complete ordered feature availability differs")
    expected_raw = condition_records["identifier_overlap3"]["holdout_source_ids"]
    if set(raw_jaccard) != set(expected_raw) or any(
            type(v) is not float or not np.isfinite(v) or not 0 <= v <= 1 for v in raw_jaccard.values()):
        raise ValueError("one finite source-only Jaccard score per available holdout action required")
    return {"schema": "hepta.prospective-action-analysis-plan.v1", "input_dataset_sha256": input_sha256,
        "task_id": tasks[0], "governing_protocol_sha256": inputs["governing_protocol_sha256"],
        "rows": [{"source_id": r["source_id"], "group_id": r["group_id"], "repo": r["repo"],
                  "split": r["split"], "source_digest": source_digest(r)} for r in rows],
        "proposal_shape": proposals, "expected_holdout_group_ids": holdout,
        "conditions": condition_records, "raw_jaccard": raw_jaccard,
        "budgets": list(BUDGETS), "seeds": list(SEEDS), "arms": list(ARMS), "controls": list(CONTROLS),
        "contrasts": fixed_contrasts(), "bootstrap": {"replicates": 2000, "seed": 104729,
            "units": ["whole_bug", "whole_project"], "fixed_fit_seeds_are_independent_cases": False},
        "threshold": .7, "top_k": [1, 2, 3], "all_arms_reported": True,
        "selection_source": "independent_tuning_repositories_only", "outcomes_or_predictions_used": False,
        "unknown_outcomes_are_negative": False, "quality_qualified": False, "authority": "DENY_ALL"}


def freeze_plan(inputs_path, feature_specs, output, *, expected_inputs_sha256):
    started, cpu, pins = time.perf_counter_ns(), time.process_time_ns(), {}
    implementation = code_hashes()
    raw = capture(inputs_path, pins, 64*1024**2)
    if sha(raw) != expected_inputs_sha256 or set(feature_specs) != set(CONDITIONS):
        raise ValueError("independently pinned inputs and exact feature conditions required")
    inputs, records, jaccard = json.loads(raw), {}, {}
    for name in CONDITIONS:
        spec = feature_specs[name]
        data, report, values, mask, _, raw_files, consumed = capture_feature_bundle(
            spec["directory"], inputs_path, spec["report_sha256"])
        if data != inputs:
            raise ValueError("features do not belong to captured pre-label inputs")
        pins.update(consumed)
        holdout = mask & np.asarray([r["split"] == "holdout" for r in inputs["rows"]])
        records[name] = {"feature_identity": report["feature_identity"], "width": int(values.shape[1]),
            "feature_report_path": str(Path(spec["directory"]).resolve()/"report.json"),
            "feature_report_sha256": spec["report_sha256"], "feature_archive_sha256": report["feature_archive_sha256"],
            "feature_manifest_sha256": sha(raw_files["manifest.json"]),
            "feature_available_source_ids": [r["source_id"] for r, keep in zip(inputs["rows"], mask) if keep],
            "holdout_source_ids": [r["source_id"] for r, keep in zip(inputs["rows"], holdout) if keep],
            "holdout_feature_tensor_sha256": sha(values[holdout].tobytes())}
        if name == "identifier_overlap3":
            jaccard = {r["source_id"]: float(value[0]) for r, value, keep in zip(inputs["rows"], values, holdout) if keep}
    plan = make_plan(inputs, expected_inputs_sha256, records, jaccard)
    plan["code_sha256"] = implementation
    verify_pins(pins)
    if code_hashes() != plan["code_sha256"]:
        raise ValueError("analysis implementation changed during plan construction")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/"plan.json").write_bytes(canonical(plan)+b"\n")
    receipt = {"plan_sha256": sha((output/"plan.json").read_bytes()), "input_files": pins,
        "wall_ns": time.perf_counter_ns()-started, "cpu_ns": time.process_time_ns()-cpu,
        "scope": "inclusive input/feature verification and plan write; excludes receipt self-write",
        "encoder_calls": 0, "private_updates": 0, "model_scores_or_outcomes_read": False}
    (output/"receipt.json").write_bytes(canonical(receipt)+b"\n")
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("inputs", "inputs-sha256", "features-json", "output"):
        parser.add_argument("--"+name, required=True)
    args = parser.parse_args()
    freeze_plan(args.inputs, json.loads(Path(args.features_json).read_bytes()), args.output,
                expected_inputs_sha256=args.inputs_sha256)


if __name__ == "__main__":
    main()
