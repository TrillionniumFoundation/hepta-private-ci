"""Authenticated three-condition preparation barrier and label-free inference.

Local research driver; child replay uses the declared POSIX CPU-accounting
runtime. No inference starts until every preparation is sealed or explicitly
unavailable. Original outcome files are read for authentication, never emitted
as query outcomes or used to fit during inference.
"""

import argparse
import json
from pathlib import Path
import re
import sys
import time

import numpy as np

from cell_action_cohort import ActionCohort
from cell_action_inference import predict_action_rows
from cell_action_prepare import (CODE_FILES as HEAD_FILES, action_protocol, inventory,
    prepare_action_curve, sha_file, verify_action_prepared, write_json)
from operational_feature_availability import load_available_features
from operational_region_evidence import capture, verify_pins
from prospective_action_inputs import PROJECT_ROLES, TASK


CONDITIONS = ("identifier_overlap3", "identifier_hash770", "granite_clean_field770")
ROLES = ("train", "tuning", "calibration", "holdout")
CODE_FILES = tuple(sorted(set(HEAD_FILES) | {Path(__file__).name, "operational_feature_availability.py",
    "operational_region_evidence.py", "operational_field_plan.py", "bind_operational_field_labels.py",
    "prospective_action_inputs.py", "long_document_sources.py"}))


def _code():
    return {name: sha_file(Path(__file__).with_name(name)) for name in CODE_FILES}


def _runtime():
    return {"python": sys.version, "numpy": np.__version__, "platform": sys.platform}


def _manifest(root, pins, inventories, *, nested=False):
    root = Path(root).resolve()
    raw = capture(root/"manifest.json", pins)
    manifest = json.loads(raw)
    files = manifest["files"] if nested else manifest
    if not isinstance(files, dict) or not files:
        raise ValueError("complete input inventory required")
    for name, record in files.items():
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name == "manifest.json":
            raise ValueError("input inventory path escapes its root")
        blob = capture(root/relative, pins)
        if record != {"sha256": pins[str(root/relative)], "bytes": len(blob)}:
            raise ValueError("input inventory bytes differ")
    inventories[str(root)] = sorted([*files, "manifest.json"])
    _check_inventory(root, inventories[str(root)])


def _check_inventory(root, names):
    paths = list(Path(root).rglob("*"))
    if Path(root).is_symlink() or any(p.is_symlink() for p in paths):
        raise ValueError("ordinary immutable input/output inventory required")
    if sorted(p.relative_to(root).as_posix() for p in paths if p.is_file()) != names:
        raise ValueError("input inventory has extra or missing files")


def _validate_dataset(data):
    if (data.get("selected_tasks") != [TASK] or data.get("all_proposed_actions_retained") is not True
            or data.get("post_outcome_candidate_selection") is not False):
        raise ValueError("complete prospectively selected action dataset required")
    rows = {r["source_id"]: r for r in data["rows"]}
    if not rows or len(rows) != len(data["rows"]):
        raise ValueError("nonempty unique source rows required")
    seen, groups = set(), set()
    for group in data["proposal_registry"]:
        if group["group_id"] in groups or PROJECT_ROLES.get(group["repo"]) != group["split"]:
            raise ValueError("unique groups in frozen whole-project roles required")
        groups.add(group["group_id"])
        keys = set()
        for action in group["actions"]:
            label, source = action["label"], action["source_id"]
            if action["key"] in keys or (label is not None and (type(label) is not int or label not in (0, 1))):
                raise ValueError("unique candidate keys and binary-or-unknown outcomes required")
            keys.add(action["key"])
            if source is not None:
                row = rows.get(source)
                if (source in seen or row is None or row["group_id"] != group["group_id"]
                        or row["repo"] != group["repo"] or row["split"] != group["split"] or row["labels"] != {TASK: label}):
                    raise ValueError("source rows and complete proposal registry disagree")
                seen.add(source)
    if seen != set(rows):
        raise ValueError("unregistered source rows")


def _load(config_path):
    pins, inventories = {}, {}
    config_path = Path(config_path).resolve()
    config = json.loads(capture(config_path, pins, 1024**2))
    if set(config) != {"dataset", "dataset_sha256", "input_dataset_sha256", "features"} or set(config["features"]) != set(CONDITIONS):
        raise ValueError("exact authenticated three-condition configuration required")
    for key in ("dataset_sha256", "input_dataset_sha256"):
        if type(config[key]) is not str or re.fullmatch(r"[0-9a-f]{64}", config[key]) is None:
            raise ValueError("explicit dataset and pre-observation proposal SHA256 pins required")
    dataset = (config_path.parent/Path(config["dataset"])).resolve()
    raw = capture(dataset, pins, 64*1024**2)
    if pins[str(dataset)] != config["dataset_sha256"]:
        raise ValueError("configured dataset SHA differs")
    _manifest(dataset.parent, pins, inventories, nested=True)
    data = json.loads(raw)
    if data["input_dataset_sha256"] != config["input_dataset_sha256"]:
        raise ValueError("labelled dataset belongs to a different frozen proposal input")
    _validate_dataset(data)
    features = {}
    for name in CONDITIONS:
        spec = config["features"][name]
        if set(spec) != {"directory", "report_sha256"}:
            raise ValueError("exact feature alias directory/report pin required")
        directory = (config_path.parent/Path(spec["directory"])).resolve()
        _manifest(directory, pins, inventories)
        values, indices, report, availability = load_available_features(directory, dataset, expected_report_sha256=spec["report_sha256"])
        binding = json.loads(capture(directory/"label-binding.json", pins))
        if (binding != report["label_binding"] or binding != report["plan"]["label_attachment"]
                or binding["parent_dataset_sha256"] != config["input_dataset_sha256"]
                or binding["labelled_dataset_sha256"] != config["dataset_sha256"]
                or binding["feature_identity"] != report["feature_identity"] or report["condition"] != name
                or report["encoder_forward_calls"] != 0 or report["gradient_updates"] != 0
                or not all(binding[k] is True for k in ("numeric_payloads_byte_identical", "feature_availability_unchanged",
                                                       "all_source_versions_text_spans_order_identical"))
                or values.shape[1] != (3 if name == "identifier_overlap3" else 770)):
            raise ValueError("exact label-only feature alias with unchanged numeric/source identity required")
        features[name] = {"values": values, "indices": indices, "report": report, "availability": availability,
            "directory": str(directory), "report_sha256": spec["report_sha256"]}
    verify_pins(pins)
    return config, str(dataset), data, features, pins, inventories


def _counts(data, available_sources):
    accum = {"by_role": {}, "by_project": {}}
    for group in data["proposal_registry"]:
        for axis, key in (("by_role", group["split"]), ("by_project", group["repo"])):
            bucket = accum[axis].setdefault(key, {})
            memberships = {"proposed": True, "source_available": False, "feature_available": False,
                           "valid_outcome": False, "usable_labelled": False}
            for action in group["actions"]:
                source, valid = action["source_id"], action["label"] is not None
                flags = {"proposed": True, "source_available": source is not None,
                         "feature_available": source in available_sources, "valid_outcome": valid,
                         "usable_labelled": source in available_sources and valid}
                for field, flag in flags.items():
                    bucket[field+"_actions"] = bucket.get(field+"_actions", 0)+int(flag)
                    memberships[field] |= flag
            for field, flag in memberships.items():
                bucket[field+"_groups"] = bucket.get(field+"_groups", 0)+int(flag)
    return accum


def _cohorts(data, feature):
    rows = [data["rows"][int(i)] for i in feature["indices"]]
    result = {}
    for role in ROLES[:3]:
        selected = [i for i, row in enumerate(rows) if row["split"] == role and row["labels"][TASK] is not None]
        result[role] = (ActionCohort(feature["values"][selected], np.array([rows[i]["labels"][TASK] for i in selected]),
            tuple({k: rows[i][k] for k in ("source_id", "group_id", "text")} for i in selected), role) if selected else None)
    return result


def _verify_inputs(plan):
    if plan["code_sha256"] != _code() or plan["runtime"] != _runtime():
        raise ValueError("global learning implementation/runtime changed")
    verify_pins(plan["input_file_pins"])
    for root, names in plan["input_inventories"].items():
        _check_inventory(root, names)


def prepare_all(config_path, output_dir):
    start, cpu, implementation = time.perf_counter_ns(), time.process_time_ns(), _code()
    config, dataset, data, features, pins, inventories = _load(config_path)
    cohorts = {name: _cohorts(data, features[name]) for name in CONDITIONS}
    counts = {name: _counts(data, {data["rows"][int(i)]["source_id"] for i in features[name]["indices"]}) for name in CONDITIONS}
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.prospective-global-preparation.v1", "config_path": str(Path(config_path).resolve()),
        "dataset": dataset, "dataset_sha256": config["dataset_sha256"], "input_dataset_sha256": config["input_dataset_sha256"],
        "configuration": action_protocol(), "condition_order": list(CONDITIONS), "code_sha256": implementation,
        "runtime": _runtime(), "input_file_pins": pins, "input_inventories": inventories,
        "cohort_digests": {name: {role: c.digest() if c else None for role, c in items.items()} for name, items in cohorts.items()},
        "label_budget_scope": "full train pool stratification plus separate tuning/calibration pools; selected gradient budget is not total annotation cost"}
    write_json(root/"plan.json", plan)
    records = []
    for name in CONDITIONS:
        feature, items, child = features[name], cohorts[name], root/"preparations"/name
        bindings = {"dataset_sha256": config["dataset_sha256"], "feature_report_sha256": feature["report_sha256"],
                    "proposal_plan_sha256": config["input_dataset_sha256"]}
        missing = [role for role, cohort in items.items() if cohort is None]
        if missing:
            child.mkdir(parents=True)
            report_file, kind = "unavailable.json", "unavailable_marker"
            frozen = {"status": "unavailable", "reason": "empty_available_labelled_role", "roles": missing,
                      "feature_identity": feature["report"]["feature_identity"], "input_bindings": bindings, "runs": []}
            write_json(child/report_file, frozen)
            write_json(child/"seal.json", {"schema": "hepta.action-unavailable-seal.v1", "files": inventory(child)})
        else:
            report_file, kind = "frozen.json", "fitted_preparation"
            frozen = prepare_action_curve(*[items[role] for role in ROLES[:3]], feature_identity=feature["report"]["feature_identity"],
                output_dir=child, task_id=TASK, family_id="prospective_diagnostic_action", input_bindings=bindings)
        records.append({"name": name, "status": "complete" if frozen["runs"] else "unavailable",
            "reason": "empty_available_labelled_role" if missing else (None if frozen["runs"] else "no_available_gradient_budget"),
            "feature_identity": feature["report"]["feature_identity"], "feature_directory": feature["directory"],
            "feature_report_sha256": feature["report_sha256"], "prepared_dir": str(child), "preparation_kind": kind,
            "preparation_report_file": report_file, "preparation_report_sha256": sha_file(child/report_file),
            "preparation_seal_sha256": sha_file(child/"seal.json"), "input_bindings": bindings, "counts": counts[name],
            "available_run_keys": [{"seed": r["seed"], "budget": r["budget"]} for r in frozen["runs"]],
            "unavailable_budget_cells": frozen.get("unavailable", [])})
    _verify_inputs(plan)
    report = {"schema": "hepta.prospective-global-preparation-report.v1", "plan": plan, "conditions": records,
        "all_conditions_prepared_or_explicitly_unavailable": True, "inference_started": False,
        "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu,
        "cost_scope": "inclusive input authentication, all child preparation/search and final checks; do not add child costs again; excludes final report/seal writes",
        "quality_qualified": False, "authority": "DENY_ALL"}
    write_json(root/"report.json", report)
    write_json(root/"seal.json", {"schema": "hepta.prospective-global-preparation-seal.v1", "files": inventory(root)})
    return report


def verify_preparation(root):
    root = Path(root).resolve()
    seal = json.loads((root/"seal.json").read_bytes())
    if seal != {"schema": "hepta.prospective-global-preparation-seal.v1", "files": inventory(root)}:
        raise ValueError("global preparation seal differs")
    report = json.loads((root/"report.json").read_bytes())
    plan = json.loads((root/"plan.json").read_bytes())
    if report["plan"] != plan or [r["name"] for r in report["conditions"]] != list(CONDITIONS):
        raise ValueError("incomplete global preparation barrier")
    _verify_inputs(plan)
    for record in report["conditions"]:
        child = root/"preparations"/record["name"]
        if (str(child) != record["prepared_dir"] or sha_file(child/"seal.json") != record["preparation_seal_sha256"]
                or sha_file(child/record["preparation_report_file"]) != record["preparation_report_sha256"]):
            raise ValueError("child preparation binding differs")
        if record["preparation_kind"] == "fitted_preparation":
            frozen = verify_action_prepared(child)
            if (frozen["plan"]["feature_identity"] != record["feature_identity"] or frozen["plan"]["input_bindings"] != record["input_bindings"]
                    or frozen["plan"]["cohorts"] != plan["cohort_digests"][record["name"]] or frozen["plan"]["configuration"] != plan["configuration"]
                    or frozen["plan"]["task_id"] != TASK or record["status"] != ("complete" if frozen["runs"] else "unavailable")
                    or record["available_run_keys"] != [{"seed": r["seed"], "budget": r["budget"]} for r in frozen["runs"]]):
                raise ValueError("child fitted task, roles or protocol differs from global freeze")
        elif (record["preparation_kind"] != "unavailable_marker" or record["status"] != "unavailable"
                or json.loads((child/"seal.json").read_bytes()) !=
                    {"schema": "hepta.action-unavailable-seal.v1", "files": inventory(child)}):
            raise ValueError("unregistered preparation state")
    return report


def infer_all(prepared_root, output_dir):
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    prepared_root = Path(prepared_root).resolve()
    prepared = verify_preparation(prepared_root)
    _, _, data, features, pins, inventories = _load(prepared["plan"]["config_path"])
    if pins != prepared["plan"]["input_file_pins"] or inventories != prepared["plan"]["input_inventories"]:
        raise ValueError("authenticated inference inputs differ from complete preparation")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.prospective-global-inference.v1", "preparation_root": str(prepared_root),
        "preparation_report_sha256": sha_file(prepared_root/"report.json"), "preparation_seal_sha256": sha_file(prepared_root/"seal.json"),
        "dataset_sha256": prepared["plan"]["dataset_sha256"], "input_dataset_sha256": prepared["plan"]["input_dataset_sha256"],
        "all_three_preparations_verified_before_first_prediction": True, "query_outcomes_used_or_emitted": False,
        "no_fitting_or_metrics_in_inference": True}
    write_json(root/"plan.json", plan)
    records, child_cpu = [], 0
    for source in prepared["conditions"]:
        name, feature = source["name"], features[source["name"]]
        available = [data["rows"][int(i)] for i in feature["indices"]]
        selected = [i for i, row in enumerate(available) if row["split"] == "holdout"]
        record = {key: source[key] for key in ("name", "feature_identity", "feature_directory", "feature_report_sha256", "prepared_dir", "preparation_kind", "preparation_report_file",
            "preparation_report_sha256", "preparation_seal_sha256", "available_run_keys", "input_bindings")}
        record.update(status="unavailable", reason=source["reason"] if source["status"] != "complete" else "no_feature_available_holdout",
                      inference_dir=None, inference_report_sha256=None, inference_seal_sha256=None, rows=len(selected))
        if source["status"] == "complete" and selected:
            rows = [{k: available[i][k] for k in ("source_id", "group_id", "text")} for i in selected]
            child = root/"inferences"/name
            output = predict_action_rows(feature["values"][selected], rows, feature_identity=source["feature_identity"],
                prepared_dir=source["prepared_dir"], output_dir=child, input_bindings=source["input_bindings"])
            child_cpu += output["fresh_process_child_cpu_ns"]
            record.update(status="complete", reason=None, inference_dir=str(child),
                inference_report_sha256=sha_file(child/"report.json"), inference_seal_sha256=sha_file(child/"seal.json"),
                source_ids=output["source_ids"], group_ids=output["group_ids"], groups=len(set(output["group_ids"])))
        records.append(record)
    if verify_preparation(prepared_root) != prepared:
        raise ValueError("preparation changed during inference")
    report = {"schema": "hepta.prospective-global-inference-report.v1", "plan": plan, "conditions": records,
        **{k: plan[k] for k in ("preparation_root", "preparation_report_sha256", "preparation_seal_sha256")},
        "wall_ns": time.perf_counter_ns()-start, "cpu_ns": time.process_time_ns()-cpu, "fresh_process_child_cpu_ns": child_cpu,
        "cost_scope": "inclusive authentication, all child inference/controls/fresh replay and final checks; child wall already included, child CPU separate; excludes report/seal writes",
        "quality_qualified": False, "authority": "DENY_ALL"}
    write_json(root/"report.json", report)
    write_json(root/"seal.json", {"schema": "hepta.prospective-global-inference-seal.v1", "files": inventory(root)})
    return report


def verify_inference(root):
    root = Path(root).resolve()
    seal = json.loads((root/"seal.json").read_bytes())
    if seal != {"schema": "hepta.prospective-global-inference-seal.v1", "files": inventory(root)}:
        raise ValueError("global inference seal differs")
    report = json.loads((root/"report.json").read_bytes())
    plan = json.loads((root/"plan.json").read_bytes())
    if report["plan"] != plan or [r["name"] for r in report["conditions"]] != list(CONDITIONS):
        raise ValueError("incomplete inference report")
    prepared = Path(plan["preparation_root"])
    preparation = verify_preparation(prepared)
    if sha_file(prepared/"report.json") != plan["preparation_report_sha256"] or sha_file(prepared/"seal.json") != plan["preparation_seal_sha256"]:
        raise ValueError("global inference preparation binding differs")
    if any(report[k] != plan[k] for k in ("preparation_root", "preparation_report_sha256", "preparation_seal_sha256")):
        raise ValueError("top-level preparation linkage differs")
    for record, source in zip(report["conditions"], preparation["conditions"], strict=True):
        if any(record[k] != source[k] for k in ("feature_identity", "feature_directory", "feature_report_sha256", "prepared_dir",
                "preparation_report_sha256", "preparation_seal_sha256", "available_run_keys", "input_bindings")):
            raise ValueError("inference condition differs from the authenticated preparation")
        if record["status"] == "unavailable":
            if any(record[k] is not None for k in ("inference_dir", "inference_report_sha256", "inference_seal_sha256")):
                raise ValueError("unavailable condition cannot claim an inference artifact")
            continue
        child = root/"inferences"/record["name"]
        if (record["status"] != "complete" or str(child) != record["inference_dir"] or sha_file(child/"report.json") != record["inference_report_sha256"]
                or sha_file(child/"seal.json") != record["inference_seal_sha256"] or json.loads((child/"seal.json").read_bytes()) !=
                    {"schema": "hepta.action-label-free-inference-seal.v1", "files": inventory(child)}):
            raise ValueError("child inference binding or complete inventory differs")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="phase", required=True)
    first = commands.add_parser("prepare")
    first.add_argument("--config", required=True); first.add_argument("--output", required=True)
    second = commands.add_parser("infer")
    second.add_argument("--prepared", required=True); second.add_argument("--output", required=True)
    args = parser.parse_args()
    result = prepare_all(args.config, args.output) if args.phase == "prepare" else infer_all(args.prepared, args.output)
    print(json.dumps({"conditions": {r["name"]: r["status"] for r in result["conditions"]}, "report_sha256": sha_file(Path(args.output)/"report.json")}))
