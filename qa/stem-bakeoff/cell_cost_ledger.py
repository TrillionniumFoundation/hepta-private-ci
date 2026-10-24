"""Consolidate pinned measured costs without deduplicating separate model runs.

Registry JSON declares datasets/receipts (path, sha256), owners, feature phases,
study resource summaries, operational acquisitions, serving scenarios, and
optional inclusive rollups. References use JSON pointers; '*' sums an array of
measured values. Time references explicitly declare ns or ms. Rollups replace
their covered budget components, while all original breakdowns remain visible.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def sha_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pointers(value, pointer):
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("JSON pointer required")
    values = [value]
    for key in pointer.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        following = []
        for item in values:
            if key == "*" and isinstance(item, list):
                following.extend(item)
            elif isinstance(item, dict) and key in item:
                following.append(item[key])
            elif isinstance(item, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and int(key) < len(item):
                following.append(item[int(key)])
            else:
                raise ValueError("completed receipt lacks referenced field: " + pointer)
        values = following
    return values


def one(value, pointer):
    values = pointers(value, pointer)
    if len(values) != 1:
        raise ValueError("one exact referenced value required")
    return values[0]


def number(value, reference, *, duration=False):
    if reference is None:
        return None
    if duration:
        if set(reference) != {"pointer", "unit"} or reference["unit"] not in ("ns", "ms"):
            raise ValueError("measured time reference must declare ns or ms")
        pointer, multiplier = reference["pointer"], 1 if reference["unit"] == "ns" else 1_000_000
    else:
        pointer, multiplier = reference, 1
    values = pointers(value, pointer)
    if any(type(x) not in ((int, float) if duration else (int,))
           or not math.isfinite(x) or x < 0 for x in values):
        raise ValueError("nonnegative finite measurements required; booleans are not counters")
    return sum(values) * multiplier


def load_registry(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    registry = json.loads(raw)
    if registry.get("schema") != "hepta.cell-cost-registry.v1":
        raise ValueError("explicit cost registry schema required")
    pins, datasets, receipts = {str(path): hashlib.sha256(raw).hexdigest()}, {}, {}
    for kind, destination in (("datasets", datasets), ("receipts", receipts)):
        entries = registry.get(kind, {})
        if not isinstance(entries, dict) or len(entries) > 512:
            raise ValueError("bounded explicitly named artifacts required")
        for name, spec in entries.items():
            target = Path(spec["path"])
            target = target if target.is_absolute() else path.parent / target
            if (target.is_symlink() or not target.is_file() or not 0 < target.stat().st_size <= 128 * 1024**2
                    or not re.fullmatch(r"[0-9a-f]{64}", spec["sha256"]) or sha_file(target) != spec["sha256"]):
                raise ValueError("referenced completed artifact is missing or changed: " + name)
            destination[name] = json.loads(target.read_bytes())
            pins[str(target.resolve())] = spec["sha256"]
    for name, spec in registry.get("receipts", {}).items():
        for pointer, dataset in spec.get("dataset_bindings", {}).items():
            if dataset not in datasets or one(receipts[name], pointer) != registry["datasets"][dataset]["sha256"]:
                raise ValueError("receipt dataset hash differs from pinned label/source dataset")
        for pointer, target in spec.get("receipt_bindings", {}).items():
            if target not in receipts or one(receipts[name], pointer) != registry["receipts"][target]["sha256"]:
                raise ValueError("receipt-to-receipt hash binding differs")
    return registry, receipts, pins


def summarize(registry_path, output):
    implementation = sha_file(__file__)
    registry, receipts, pins = load_registry(registry_path)
    owners, lifecycle_keys, budgets, features, studies, serving, acquisitions = {}, set(), {}, [], [], [], []
    source_fields, logical_tasks = set(), {}

    def component(name, category, wall, cpu, *, wall_in_parent=False):
        if name in budgets:
            raise ValueError("duplicate cost component")
        budgets[name] = {"category": category, "wall_ns": wall, "cpu_ns": cpu,
                         "wall_in_parent": wall_in_parent}

    for spec in registry.get("owners", []):
        name, receipt_id = spec["id"], spec["receipt"]
        report = receipts[receipt_id]
        key = (registry["receipts"][receipt_id]["sha256"], spec["load_pointer"])
        instances = one(report, spec["instances_pointer"])
        if name in owners or key in lifecycle_keys or type(instances) is not int or instances != 1:
            raise ValueError("one explicit unique physical owner lifecycle required")
        lifecycle_keys.add(key)
        load = one(report, spec["load_pointer"])
        wall = number(load, {"pointer": "/wall_ns", "unit": "ns"}, duration=True)
        cpu = number(load, {"pointer": "/cpu_ns", "unit": "ns"}, duration=True)
        members = spec["members"]
        if not members:
            raise ValueError("owner lifecycle must bind its completed member reports")
        for member, pointer in members.items():
            if member not in receipts or (pointer is None and member != receipt_id):
                raise ValueError("unbound owner member")
            if pointer is not None and one(report, pointer) != registry["receipts"][member]["sha256"]:
                raise ValueError("member report does not belong to this owner lifecycle")
        owners[name] = {"receipt": receipt_id, "member_reports": list(members), "model_load_wall_ns": wall,
            "model_load_cpu_ns": cpu, "loaded_model_storage": load.get("loaded_model"),
            "expected_physical_forward_calls": number(report, spec["forward_calls_pointer"]),
            "accounted_physical_forward_calls": 0}
        component("owner:" + name, "model_load", wall, cpu)

    for spec in registry.get("features", []):
        report, receipt_id, owner = receipts[spec["receipt"]], spec["receipt"], spec.get("owner")
        if not registry["receipts"][receipt_id].get("dataset_bindings"):
            raise ValueError("feature receipt needs an explicit dataset binding")
        key = (registry["receipts"][receipt_id]["sha256"], spec["forward_calls"])
        if key in source_fields:
            raise ValueError("same physical forward receipt charged twice")
        source_fields.add(key)
        calls = number(report, spec["forward_calls"])
        if owner is not None:
            if owner not in owners or receipt_id not in owners[owner]["member_reports"]:
                raise ValueError("feature phase lacks an explicit owner lifecycle binding")
            owners[owner]["accounted_physical_forward_calls"] += calls
        elif calls != 0:
            raise ValueError("positive model forwards require a physical owner lifecycle")
        wall = number(report, spec.get("stage_wall"), duration=True)
        cpu = number(report, spec.get("stage_cpu"), duration=True)
        features.append({"id": spec["id"], "receipt": receipt_id, "owner": owner,
            "physical_forward_calls": calls, "encoding_stage_wall_ns": wall, "encoding_stage_cpu_ns": cpu,
            "model_only_forward_wall_ns": number(report, spec.get("forward_wall"), duration=True),
            "model_only_forward_cpu_ns": number(report, spec.get("forward_cpu"), duration=True),
            "footprint_observations": {k: number(report, p) for k, p in spec.get("footprints", {}).items()}})
        component("feature:" + spec["id"], "encoding_stage", wall, cpu)
    if any(x["accounted_physical_forward_calls"] != x["expected_physical_forward_calls"] for x in owners.values()):
        raise ValueError("owner total forwards are not fully accounted, including controls/failed recorded attempts")

    used_studies = set()
    for spec in registry.get("studies", []):
        report = receipts[spec["receipt"]]
        identity = (report.get("study_plan_sha256"), report.get("summary_sha256"))
        if (report.get("schema") != "hepta.calibrated-label-resource-ledger.v1" or identity in used_studies
                or not registry["receipts"][spec["receipt"]].get("dataset_bindings")):
            raise ValueError("unique completed all-attempt study resource ledger required")
        used_studies.add(identity)
        h = report["head_cost"]
        for field in ("full_preparation_wall_ns", "full_preparation_cpu_ns", "evaluation_wall_ns",
                      "evaluation_parent_cpu_ns", "fresh_process_child_cpu_ns"):
            number(h, "/" + field)
        for row in report["per_task_seed_budget"]:
            key = (spec["task_namespace"], row["task"])
            if key in logical_tasks and logical_tasks[key] != row["family"]:
                raise ValueError("logical task family changed across feature conditions")
            logical_tasks[key] = row["family"]
        studies.append({"id": spec["id"], "receipt": spec["receipt"], "task_namespace": spec["task_namespace"],
            "head_cost": h, "label_stages": report["label_stages"],
            "per_task_seed_budget": report["per_task_seed_budget"],
            "gradient_source_selection_sha256": report["gradient_source_selection_sha256"],
            "nested_training_and_calibration_already_in_preparation": True})
        component("prepare:" + spec["id"], "head_preparation_including_all_search", h["full_preparation_wall_ns"], h["full_preparation_cpu_ns"])
        component("evaluate:" + spec["id"], "head_evaluation_parent", h["evaluation_wall_ns"], h["evaluation_parent_cpu_ns"])
        component("fresh:" + spec["id"], "fresh_child_cpu", None, h["fresh_process_child_cpu_ns"], wall_in_parent=True)

    acquired_attempts = set()
    for spec in registry.get("operational_acquisitions", []):
        report = receipts[spec["receipt"]]
        if report.get("schema") != "hepta.operational-label-and-execution-ledger.v1":
            raise ValueError("all-attempt operational ledger required")
        attempts = {v["summary_sha256"] for v in report["conditions"].values()}
        if attempts & acquired_attempts or not registry["receipts"][spec["receipt"]].get("dataset_bindings"):
            raise ValueError("operational attempts are duplicated or lack a dataset binding")
        acquired_attempts.update(attempts)
        c = report["all_attempt_costs"]
        wall = number(c, "/summed_observed_test_wall_ns") + number(c, "/summed_observed_build_wall_ns")
        acquisitions.append({"id": spec["id"], "receipt": spec["receipt"], "all_attempt_costs": c,
                             "label_pools": report["label_pools"]})
        component("acquisition:" + spec["id"], "operational_command_work", wall, c["child_cpu_ns"])

    for spec in registry.get("serving", []):
        report = receipts[spec["receipt"]]
        serving.append({"id": spec["id"], "receipt": spec["receipt"],
            "logical_learned_tasks": number(report, spec["logical_tasks"]),
            "physical_instances": number(report, spec["physical_instances"]),
            "scenario": one(report, spec["scenario_pointer"]),
            "replicas_are_additional_learned_tasks": False})
        if "work_wall" in spec or "work_cpu" in spec:
            component("serving:" + spec["id"], "serving_sample_work",
                      number(report, spec.get("work_wall"), duration=True),
                      number(report, spec.get("work_cpu"), duration=True))
    observations = [{"id": spec["id"], "receipt": spec["receipt"], "scope": spec["scope"],
                     "value": one(receipts[spec["receipt"]], spec["pointer"]), "included_in_additive_budget": False}
                    for spec in registry.get("observations", [])]
    for spec in registry.get("activities", []):
        report = receipts[spec["receipt"]]
        component("activity:" + spec["id"], spec["scope"],
                  number(report, spec.get("wall"), duration=True),
                  number(report, spec.get("cpu"), duration=True))
    excluded, rollups = set(), {}
    for spec in registry.get("inclusive_rollups", []):
        covers = set(spec["covers"])
        if not covers or len(covers) != len(spec["covers"]) or not covers <= budgets.keys() or covers & excluded:
            raise ValueError("inclusive rollup covers missing or already covered budget components")
        report = receipts[spec["receipt"]]
        name = "rollup:" + spec["id"]
        component(name, spec["scope"], number(report, spec.get("wall"), duration=True),
                  number(report, spec.get("cpu"), duration=True))
        excluded.update(covers)
        rollups[name] = sorted(covers)
    active = {k: v for k, v in budgets.items() if k not in excluded}
    totals = {}
    for metric in ("wall_ns", "cpu_ns"):
        relevant = {k: v[metric] for k, v in active.items() if metric != "wall_ns" or not v["wall_in_parent"]}
        totals[metric] = {"sum_measured": sum(v for v in relevant.values() if v is not None),
                          "unmeasured_components": [k for k, v in relevant.items() if v is None]}
    result = {"schema": "hepta.consolidated-cell-cost-ledger.v1", "registry_sha256": sha_file(registry_path),
        "source_sha256": implementation, "artifact_bindings": pins, "owners": owners, "feature_phases": features,
        "artifact_file_bytes": {path: Path(path).stat().st_size for path in pins},
        "dataset_artifacts": registry.get("datasets", {}),
        "studies": studies, "operational_acquisitions": acquisitions, "serving_scenarios": serving,
        "observations": observations, "budget_components": budgets, "inclusive_rollup_covers": rollups,
        "active_budget_component_ids": list(active), "measured_work_totals": totals,
        "logical_tasks": [{"namespace": n, "task": t, "family": f} for (n, t), f in sorted(logical_tasks.items())],
        "logical_task_count": len(logical_tasks), "distinct_family_names": sorted(set(logical_tasks.values())),
        "label_stage_counts_are_summed_across_conditions": False,
        "rss_peaks_summed": False, "energy_joules": None,
        "timing_context": registry["timing_context"],
        "wall_scope": "Sum of measured stage/command wall work, not end-to-end concurrent elapsed or isolated latency.",
        "cost_scope": "Only explicitly registered completed artifacts; nulls retain unmeasured costs. Activities must declare disjoint work; inclusive timings replace covered components. Nested study breakdowns and historical forward totals are not charged twice."}
    if sha_file(__file__) != implementation or any(sha_file(path) != expected for path, expected in pins.items()):
        raise ValueError("cost evidence changed during consolidation")
    with Path(output).open("xb") as stream:
        stream.write(canonical(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = summarize(args.registry, args.output)
    print(json.dumps({"owners": len(report["owners"]), "logical_tasks": report["logical_task_count"],
                      "measured_work_totals": report["measured_work_totals"]}, sort_keys=True))
