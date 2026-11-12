"""Prospective B/C development probes through the original CTRL macro runtime.

Reuses an already fitted real checkpoint; never retrains, opens sealed roles,
injects a host, signs an owner receipt, resumes an actor or grants adoption.
"""

import argparse
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


METHODS = ("tuned-fixed", "conditional")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path, expected=None):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate JSON key")
            value[key] = item
        return value

    def reject_constant(value):
        raise ValueError("Nonfinite JSON constant: " + value)

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON float")
        return result

    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16_777_216:
        raise ValueError("Bounded regular input required")
    raw = path.read_bytes()
    if expected is not None and sha(raw) != expected:
        raise ValueError("Input differs from external byte pin")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant, parse_float=finite_float)


def save(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def load_native(registration):
    """Use the original source/context/checkpoint admission, with no test host."""
    repo, training = Path(registration["repository"]), Path(registration["training_run"])
    original = read(training / "FROZEN.json", registration["training_freeze_sha256"])
    pins = [*original["collection_plan"]["source_pins"],
        {"path": str(repo / "scripts/ctrl_macro_study.py"), "sha256": original["driver_sha256"]},
        {"path": str(repo / "scripts/ctrl_macro_analysis.py"), "sha256": original["analysis_sha256"]}]
    for pin in pins:
        path = Path(pin["path"])
        if (path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 67_108_864
                or sha(path.read_bytes()) != pin["sha256"]):
            raise ValueError("Original native source pin changed before import")
    source = repo / "scripts/ctrl_macro_study.py"
    sys.path[:0] = [str(repo / "scripts"), str(repo)]
    spec = importlib.util.spec_from_file_location("rv_original_ctrl_study", source)
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    modules = driver.modules(str(repo))
    _, frozen, context = driver.thaw(SimpleNamespace(repository=str(repo), run_dir=str(training),
        freeze_sha256=registration["training_freeze_sha256"]), modules)
    raw = (training / "CHECKPOINT.json").read_bytes()
    if sha(raw) != registration["checkpoint_sha256"]:
        raise ValueError("Original fitted checkpoint changed")
    model = modules["macro_policy"].load(raw, sha(raw), context=context)
    cold = read(training / "COLD_LOAD.json")
    if (cold["checkpoint_sha256"] != sha(raw) or cold.get("fresh_process") is not True
            or cold.get("context_sha256") != modules["context_digest"](context)):
        raise ValueError("Original independent cold-load record missing")
    return modules, frozen, context, model, raw


def validate_partitions(phases, collection, model):
    """Check declared source/image separation; hashes do not authenticate owners."""
    if set(phases) != {"B", "C"} or any(not phases[k] for k in phases):
        raise ValueError("Nonempty B and C rosters required")
    occupied, physical, groups = {}, {}, defaultdict(set)
    rows = []
    for pair in collection["pairs"]:
        # A frozen training collection cannot silently contribute B/C cases.
        if type(pair) is not dict or pair.get("split") not in ("train", "calibration"):
            raise ValueError("Original collection must contain train/calibration only")
        rows.append((pair["split"], pair["case"]))
    for phase in ("B", "C"):
        contexts = set()
        for row in phases[phase]:
            case = row["case"]
            key = (row["source_id"], row["case_id"], row["seed"])
            if (case["role"] != "development" or row["source_id"] != case["source_id"]
                    or row["case_id"] != case["id"] or key in contexts
                    or type(row["seed"]) is not int or row["read_condition"] != "original"):
                raise ValueError("Original unsealed development cases required")
            contexts.add(key)
            rows.append((phase, case))
    for split, case in rows:
        source, pin = case["source_id"], case["source_sha256"]
        if not isinstance(source, str) or not source or not isinstance(pin, str) or len(pin) != 64:
            raise ValueError("Source identity and full image digest required")
        if any(c not in "0123456789abcdef" for c in pin):
            raise ValueError("Invalid image digest")
        if source in occupied and occupied[source] != (split, pin):
            raise ValueError("Source crosses partitions or changes bytes")
        if pin in physical and physical[pin] != source:
            raise ValueError("One physical image has multiple source aliases")
        occupied[source], physical[pin] = (split, pin), source
        groups[split].add(source)
    if (groups["train"] != set(model.data["fit_sources"])
            or groups["calibration"] != set(model.data["calibration_sources"])):
        raise ValueError("Actual checkpoint fitting sources differ from collection")
    if any(model.data["source_bindings"].get(source) != occupied[source][1]
            for source in groups["train"] | groups["calibration"]):
        raise ValueError("Actual checkpoint source image bytes differ from collection")
    return {key: sorted(value) for key, value in groups.items()}


def freeze(request, expected, output):
    registration = read(request, expected)
    if set(registration) != {"repository", "training_run", "training_freeze_sha256",
            "checkpoint_sha256", "phases", "minimum_observed_gain"}:
        raise ValueError("Unexpected registration fields")
    gain = registration["minimum_observed_gain"]
    if type(gain) not in (float, int) or not math.isfinite(gain) or gain < 0:
        raise ValueError("A finite nonnegative descriptive selection margin is required")
    native = load_native(registration)
    modules, frozen, _, model, _ = native
    groups = validate_partitions(registration["phases"], frozen["collection_plan"], model)
    root = Path(output).resolve()
    for location in frozen["collection_plan"]["config"]["runtime_roots"]:
        runtime = Path(location).resolve()
        if root == runtime or root in runtime.parents or runtime in root.parents:
            raise ValueError("Evidence output must be outside actor-readable roots")
    root.mkdir(parents=True, exist_ok=False)
    protocol = {"registration": registration, "request_sha256": expected,
        "driver_sha256": sha(Path(__file__).read_bytes()), "source_partitions": groups,
        "methods": list(METHODS), "frozen_at_ns": time.time_ns(),
        "planned": {p: len(registration["phases"][p]) * len(METHODS) for p in ("B", "C")},
        "scope": "source-disjoint unsealed development_B/C; historical exposure not authenticated",
        "full_cost_observed": False, "native_owner_authenticated": False,
        "fresh_source_confirmation": False, "production_admission": False}
    protocol["execution_plan_sha256s"] = {}
    for phase in ("B", "C"):
        plan = execution_plan(protocol, phase, root, native)
        plan_pin = modules["digest"](plan)
        modules["macro_execution_plan"].validate_plan(plan, plan_pin)
        save(root / (phase + "_PLAN.json"), plan)
        protocol["execution_plan_sha256s"][phase] = plan_pin
    pin = save(root / "FROZEN.json", protocol)
    return {"freeze_sha256": pin, "source_partitions": groups}


def execution_plan(frozen, phase, root, native):
    modules, training, context, model, checkpoint = native
    plan = training["collection_plan"]
    control = modules["ControlPlan"](**read(plan["profile"]["control_plan"])["control"])
    profiles, arms = {}, []
    for policy in METHODS:
        deployment = {"schema": "ndu.real.macro-deployment.v1", "policy": policy,
            "context": context.to_wire(), "weights_sha256": plan["profile"]["model_sha256"],
            "control_sha256": modules["digest"](asdict(control)),
            "checkpoint_utf8": checkpoint.decode(), "checkpoint_sha256": sha(checkpoint),
            "read_seconds_bound": training["read_seconds_bound"],
            "finalizer_seconds_reserve": training["finalizer_seconds_reserve"]}
        path = root / (phase + "-" + policy + "-deployment.json")
        pin = save(path, deployment)
        profiles[policy] = {**plan["profile"], "macro_policy": {"path": str(path), "sha256": pin}}
        arms.append({"arm_id": policy, "content_mode": "off",
            "control_mode": "on" if policy == "conditional" else "off", "policy": policy,
            "content_sha256": plan["profile"]["model_sha256"],
            "critic_context_sha256": modules["context_digest"](context)})
    cases = frozen["registration"]["phases"][phase]
    cohort = {"schema": "ndu.real.macro-cohort.v1",
        "contexts": [{k: row[k] for k in ("source_id", "case_id", "seed")} for row in cases],
        "arms": arms, "partitions": {"fit": model.data["fit_sources"],
            "calibration": model.data["calibration_sources"],
            "evaluation": sorted({r["source_id"] for r in cases})},
        "shared": modules["macro_execution_plan"].shared_context(plan["config"], control),
        "one_off_costs": {name: dict.fromkeys(("fit", "calibration", "tuning")) for name in METHODS},
        "factorial": None}
    return {"schema": "ndu.real.macro-execution-plan.v1", "cohort": cohort,
        "cohort_sha256": modules["digest"](cohort), "config": plan["config"],
        "registered_cases": deepcopy(cases), "profiles": profiles,
        "action_budget_seconds": plan["action_budget_seconds"], "source_pins": plan["source_pins"],
        "observer_sha256": training["observer_sha256"]}


def summarize(report, plan):
    rows = report["rows"]
    expected = {(r["source_id"], r["case_id"], r["seed"], arm)
                for r in plan["registered_cases"] for arm in METHODS}
    observed = [(r["source_id"], r["case_id"], r["seed"], r["arm_id"]) for r in rows]
    planned = len(plan["registered_cases"]) * len(METHODS)
    if (not planned or report["evidence_kind"] != "native_macro"
            or len(expected) != planned or len(observed) != planned or set(observed) != expected):
        raise ValueError("Original native planned denominator required")
    incomplete = sum(row["status"] != "COMPLETED" for row in rows)
    groups, pairs = defaultdict(list), defaultdict(dict)
    for row in rows:
        for field in ("quality", "task_cost"):
            value = row[field]
            if value is None and row["status"] != "COMPLETED":
                continue
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < 0 or field == "quality" and value > 1):
                raise ValueError("Quality must be in [0,1]; cost must be finite and nonnegative")
        key = (row["source_id"], row["case_id"], row["seed"])
        if row["arm_id"] not in METHODS or row["arm_id"] in pairs[key]:
            raise ValueError("Unregistered or duplicate paired arm")
        pairs[key][row["arm_id"]] = row
    if any(set(pair) != set(METHODS) for pair in pairs.values()):
        raise ValueError("Missing registered arm")
    if not incomplete:
        for key, pair in pairs.items():
            utilities = {}
            for arm, row in pair.items():
                utilities[arm] = row["quality"] - row["task_cost"]
            groups[key[0]].append(utilities["conditional"] - utilities["tuned-fixed"])
    source_means = {s: sum(v) / len(v) for s, v in groups.items()}
    return {"planned": planned, "statuses": dict(Counter(r["status"] for r in rows)),
        "incomplete": incomplete, "planned_source_clusters": len({r["source_id"] for r in rows}),
        "source_mean_observed_latency_net_differences": source_means,
        "observed_latency_net_difference": None if incomplete else sum(source_means.values()) / len(source_means),
        "full_cost_observed": False, "efficacy_qualified": False,
        "qualification_status": "HOLD_NOT_EVALUATED", "adoption": "NOT_REQUESTED", "owner_decision": None}


def reconcile(root, phase, modules, frozen):
    plan = read(root / (phase + "_PLAN.json"))
    pin = frozen["execution_plan_sha256s"][phase]
    if modules["digest"](plan) != pin:
        raise ValueError("Execution plan differs from prospective freeze")
    report = modules["macro_execution"].reconcile(root / phase,
        expected_plan_sha256=pin)
    return report, summarize(report, plan)


def run_phase(root, phase, frozen, native):
    modules = native[0]
    if phase == "C":
        prior = read(root / "B_TERMINAL.json")
        report, summary = reconcile(root, "B", modules, frozen)
        if prior["status"] != "RECORDED" or prior["native_report_sha256"] != modules["digest"](report) or summary["incomplete"]:
            raise ValueError("Complete unchanged original B required before C")
    # Exclusive fsynced marker fences process-death retries; no power-loss claim.
    save(root / (phase + "_START.json"), {"phase": phase, "time_ns": time.time_ns(),
        "freeze_sha256": sha((root / "FROZEN.json").read_bytes()), "status": "MAY_HAVE_DISPATCHED"})
    began, cpu = time.perf_counter_ns(), time.process_time_ns()
    terminal = {"status": "UNKNOWN", "phase": phase, "production_admission": False}
    try:
        plan = read(root / (phase + "_PLAN.json"))
        pin = frozen["execution_plan_sha256s"][phase]
        if modules["digest"](plan) != pin:
            raise ValueError("Execution plan differs from prospective freeze")
        modules["macro_execution_plan"].validate_plan(plan, pin)
        modules["macro_execution_plan"].check_inputs(plan, root / phase)
        with (root / (phase + "_stdout.log")).open("x") as stdout, (root / (phase + "_stderr.log")).open("x") as stderr:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                report = modules["macro_execution"].execute(plan, root / phase, expected_plan_sha256=pin)
        summary = summarize(report, plan)
        save(root / (phase + "_SUMMARY.json"), summary)
        terminal.update(status="RECORDED", native_report_sha256=modules["digest"](report), summary=summary)
        if phase == "B":
            delta = summary["observed_latency_net_difference"]
            terminal["descriptive_reference_policy"] = "conditional" if delta is not None and delta > frozen["registration"]["minimum_observed_gain"] else "tuned-fixed"
    except BaseException as error:
        terminal["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        terminal.update(wall_ns=time.perf_counter_ns() - began, parent_cpu_ns=time.process_time_ns() - cpu,
            parent_cpu_scope="controller only; original actor costs remain in native terminals",
            full_cost_observed=False, energy_joules=None, provider_cost=None)
        save(root / (phase + "_TERMINAL.json"), terminal)
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "B", "C", "reconcile-B", "reconcile-C"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if args.stage == "freeze":
        if args.request is None:
            parser.error("freeze requires --request")
        result = freeze(args.request, args.expected_sha256, args.output)
    else:
        root = args.output.resolve()
        frozen = read(root / "FROZEN.json", args.expected_sha256)
        if frozen["driver_sha256"] != sha(Path(__file__).read_bytes()):
            raise ValueError("Phase driver differs from frozen source")
        native = load_native(frozen["registration"])
        validate_partitions(frozen["registration"]["phases"], native[1]["collection_plan"], native[3])
        result = reconcile(root, args.stage[-1], native[0], frozen)[1] if args.stage.startswith("reconcile-") else run_phase(root, args.stage, frozen, native)
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
