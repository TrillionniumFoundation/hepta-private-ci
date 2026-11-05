"""Read-only arithmetic audit of frozen tools evidence; never imports its runner."""

import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import struct

HERE = Path(__file__).resolve().parent
RUN = HERE.parent / "run_20261105_001"
PACKAGE = HERE.parent.parent
ROOT = PACKAGE.parents[4]
checks, errors, identities = 0, [], {}


def check(condition, description):
    global checks
    checks += 1
    if not condition:
        errors.append(description)


def read(path):
    raw = path.read_bytes()
    identities[str(path.relative_to(ROOT))] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    return json.loads(raw)


def same(actual, expected, description, tolerance=1e-11):
    check(math.isclose(actual, expected, rel_tol=tolerance, abs_tol=tolerance), description)


def ce(values):
    minimum = min(values)
    return minimum - math.log(sum(math.exp(-2 * (x - minimum)) for x in values) / len(values)) / 2


def quantile(values, probability):
    ordered = sorted(values)
    location = (len(values) - 1) * probability
    lower = int(location)
    upper = min(lower + 1, len(values) - 1)
    return ordered[lower] + (location - lower) * (ordered[upper] - ordered[lower])


def arithmetic(node, environment):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.Name):
        return environment[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -arithmetic(node.operand, environment)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult)):
        left, right = arithmetic(node.left, environment), arithmetic(node.right, environment)
        return left + right if isinstance(node.op, ast.Add) else left * right
    raise ValueError("Recorded source is outside the registered arithmetic template")


def source_values(source):
    """Evaluate only whitelisted AST arithmetic, without executing Python source."""
    function = ast.parse(source).body[0]
    check(isinstance(function, ast.FunctionDef) and function.name == "solve", "recorded solve function")
    result = []
    for x in range(-11, 14):
        environment = {"x": x}
        for statement in function.body[:-1]:
            environment[statement.targets[0].id] = arithmetic(statement.value, environment)
        result.append(arithmetic(function.body[-1].value, environment))
    return result


registration = read(RUN / "REGISTRATION.json")
completion = read(RUN / "COMPLETION.json")
remote = read(HERE / "REMOTE_READBACK.json")
wrapped = read(RUN / "tools/run/RESULT.json")
data = wrapped["data"]
meter = read(RUN / "tools/PROCESS_RECEIPT.json")
settings = registration["protocol"]["tools"]
check(wrapped["source_binding"] == registration["source_binding"], "source binding equality")
check(data["protocol"] == settings, "executed registered tool protocol")
check(registration["source_commit"] == completion["source_commit"] == remote["source_commit"], "source commit equality")
check(completion["source_bytes_unchanged"] is True, "completion source unchanged")
for name, expected in wrapped["source_binding"]["files"].items():
    raw = (ROOT / name).read_bytes()
    actual = {"sha256": hashlib.sha256(raw).hexdigest(), "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(), "bytes": len(raw)}
    check(actual == expected, "frozen local source: " + name)
for entry in remote["files"]:
    raw = (ROOT / entry["path"]).read_bytes()
    identity = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    check(not entry["isError"] and identity == entry["sha"], "fresh remote source: " + entry["path"])

records = []
for entry in data["record_files"]:
    path = RUN / "tools/run" / entry["path"]
    block = read(path)
    identity = identities[str(path.relative_to(ROOT))]
    check(identity == {"sha256": entry["sha256"], "bytes": entry["bytes"]}, "record block integrity")
    records.extend(block)
seeds, methods, inference = settings["seeds"], settings["training"], settings["inference"]
task_ids = [f"p{i}-b{n}" for i in range(len(settings["parameter_pairs"])) for n in range(3)]
keys = [(r["seed"], r["training"], r["inference"], r["task"]["id"]) for r in records]
expected = set(itertools.product(seeds, methods, inference, task_ids))
check(len(keys) == len(set(keys)) == 108 and set(keys) == expected, "complete unique 108-row census")
check(data["executed_seeds"] == seeds, "all registered seeds executed")
tariffs = settings["tariff"]
invocations, action_counts, tariff_totals = Counter(), Counter(), defaultdict(float)


def event_check(event, owner):
    action_counts[owner + "/" + event["action"]] += 1
    same(event["tariff"], tariffs[event["action"]], owner + " tariff")
    tariff_totals[owner] += event["tariff"]
    if "command" in event:
        invocations[owner] += 1
        check(event["command"][3] == event["action"], owner + " command action identity")
        check(event["metering"] == "exclusive_action", owner + " exclusive event")
        check(event["returncode"] is not None, owner + " waited command exit")
        check(event["wall_s"] >= 0 and event["parent_cpu_s"] >= 0 and event["child_cpu_s"] >= 0, owner + " nonnegative physical clocks")
        if event["status"] == "completed":
            check(event["returncode"] == 0 and event["output_schema_valid"] is True, owner + " successful schema")
            check(json.loads(event["stdout"]) == event["result"], owner + " raw output agrees with result")


def episode_check(row, owner):
    events = row["events"]
    for event in events:
        event_check(event, owner)
    check(sum(e["action"] == "ORACLE" for e in events) == 1 and events[-1]["action"] == "ORACLE", owner + " exactly one final oracle")
    same(row["tariff"], math.fsum(e["tariff"] for e in events), owner + " complete fee sum")
    same(row["return"], row["quality"] - row["tariff"], owner + " net return")
    same(row["child_cpu_s"], math.fsum(e.get("child_cpu_s", 0) for e in events), owner + " child CPU reconciliation")
    check(row["parent_cpu_s"] + 1e-10 >= sum(e.get("parent_cpu_s", 0) for e in events) + row["controller_cpu_s"], owner + " parent CPU enclosure")
    check(row["wall_s"] + 1e-9 >= sum(e.get("wall_s", 0) for e in events) + row["controller_wall_s"], owner + " wall enclosure")
    for prefix in ("initial", "final"):
        check(hashlib.sha256(row[prefix + "_source"].encode()).hexdigest() == row[prefix + "_sha256"], owner + " retained source bytes")
    expected_values = [row["task"]["scale"] * x + row["task"]["offset"] for x in range(-11, 14)]
    check(source_values(row["final_source"]) == expected_values, owner + " final AST arithmetic independently correct")
    check(row["physical_costs_monetized"] is False and row["monetary_cost"] is None, owner + " no invented price")
    check(row["peak_rss_bytes"] is None, owner + " episode RSS remains unknown")


for row in records:
    episode_check(row, "service")
    check([e["action"] for e in row["events"]] == ["REPAIR", "REPAIR", "STOP", "ORACLE"], "service identical executed sequence")
    check(row["quality"] == 1 and row["status"] == row["termination_reason"] == row["verification_status"] == "completed", "service successful explicit delivery")

training = {(r["seed"], r["method"]): r for r in data["training"]}
models = {(m["seed"], m["method"]): m for m in data["trained_models"]}
histories = [tuple(tuple(event) for event in h) for h in data["parameter_history_order"]]
history_index = {h: i for i, h in enumerate(histories)}
check(set(training) == set(models) == set(itertools.product(seeds, methods)), "complete six-fit roster")
training_audit = []
for seed in seeds:
    left, right = (training[seed, m] for m in methods)
    check(left["initial_parameter_sha256"] == right["initial_parameter_sha256"], "same initialization per seed")
    for method in methods:
        receipt, model = training[seed, method], models[seed, method]
        check(receipt["requested_updates"] == receipt["actual_updates"] == len(receipt["ce_trace"]) == 500, "500 retained updates per fit")
        check(receipt["no_update"] == 0, "no skipped fit updates")
        values = list(itertools.chain.from_iterable(model["logits"]))
        binary = struct.pack("<" + "d" * len(values), *values)
        identity = hashlib.sha256(binary).hexdigest()
        check(identity == model["sha256_little_endian"] == receipt["final_parameter_sha256"], "selected model bytes")
        check(identity != receipt["initial_parameter_sha256"], "nontrivial model update")
    a, b = (models[seed, m]["logits"] for m in methods)
    maximum = max(abs(x - y) for aa, bb in zip(a, b) for x, y in zip(aa, bb))
    disagreements = sum(max(range(3), key=aa.__getitem__) != max(range(3), key=bb.__getitem__) for aa, bb in zip(a, b))
    recorded = next(r for r in data["equivalence"] if r["seed"] == seed)
    same(maximum, recorded["max_parameter_difference"], "paired parameter discrepancy")
    check(disagreements == recorded["action_disagreements"] == 0, "zero full-state action disagreements")
    training_audit.append({"seed": seed, "updates_per_fit": 500, "updates_across_two_fits": 1000,
                           "maximum_parameter_difference": maximum, "action_disagreements": disagreements,
                           "flat_cpu_s": left["cpu_s"], "recursive_cpu_s": right["cpu_s"],
                           "recursive_to_flat_cpu_ratio": right["cpu_s"] / left["cpu_s"]})
for row in records:
    if row["inference"] == "dynamic":
        logits = models[row["seed"], row["training"]]["logits"]
        history = ()
        for action, outcome in row["history"]:
            chosen = max(range(3), key=logits[history_index[history]].__getitem__)
            check(("STOP", "CHECK", "REPAIR")[chosen] == action, "retained model selects executed dynamic action")
            history += ((action, outcome),)

recomputed_cells, contrasts = [], []
for matrix in data["matrices"]:
    seed = matrix["seed"]
    actual = {}
    for method, mode in itertools.product(methods, inference):
        group = [r for r in records if (r["seed"], r["training"], r["inference"]) == (seed, method, mode)]
        key = method + "/" + mode
        expected_cell = matrix["cells"][key]
        cell = {"seed": seed, "method": method, "inference": mode, "n": len(group),
                "quality": statistics.fmean(r["quality"] for r in group), "ce": ce([r["return"] for r in group]),
                "tariff": statistics.fmean(r["tariff"] for r in group), "wall_s": statistics.fmean(r["wall_s"] for r in group),
                "cpu_s": statistics.fmean(r["parent_cpu_s"] + r["child_cpu_s"] for r in group),
                "p95_wall_s": quantile([r["wall_s"] for r in group], .95), "p99_wall_s": quantile([r["wall_s"] for r in group], .99)}
        for name in ("n", "quality", "ce", "tariff", "wall_s", "cpu_s", "p95_wall_s", "p99_wall_s"):
            same(cell[name], expected_cell[name], "cell statistic " + name)
        actual[key] = cell
        recomputed_cells.append(cell)
    a, b, c, d = (actual[k]["ce"] for k in ("inherited_flat_ce/fixed", "recursive_ce/fixed", "inherited_flat_ce/dynamic", "recursive_ce/dynamic"))
    effects = {"training_on_fixed": b-a, "training_on_dynamic": d-c, "inference_on_flat": c-a, "inference_on_recursive": d-b, "interaction": d-c-b+a}
    for name, value in effects.items():
        same(value, matrix["effects"][name], "four-cell effect " + name)
    delta = actual["recursive_ce/fixed"]["cpu_s"] - actual["recursive_ce/dynamic"]["cpu_s"]
    recorded = matrix["break_even"]
    same(delta, recorded["observed_delta_per_service"], "observed CPU difference")
    check(recorded["services"] is None and recorded["complete_one_time_cost_known"] is False, "no qualified lifetime break-even")
    quotient = math.floor(recorded["one_time_cpu_s"] / delta) + 1 if delta > 0 else None
    check(quotient == recorded["services_measured_scope_only"], "measured-scope quotient arithmetic")
    contrasts.append({"seed": seed, "ce_effects": effects, "observed_recursive_cpu_saving_s": delta,
                      "qualified_break_even_services": None, "causal_service_saving_established": False})

for row in data["validation"]:
    episode_check(row, "model_qualification")
    check(row["status"] == "expired" and row["quality"] == 0 and row["events"][-1]["result"]["quality"] == 1, "expiry cannot deliver correct artifact")
    repairs = 0
    for action, outcome in row["history"]:
        if action == "CHECK":
            check(outcome == str(max(0, len(row["task"]["bugs"]) - repairs)), "model CHECK conformance")
        repairs += action == "REPAIR"
faults = data["qualification_faults"]
for row in faults:
    if "events" in row:
        episode_check(row, "failure_qualification")
    else:
        event_check(row, "failure_qualification")
check([r["status"] for r in faults] == ["failed", "failed", "timeout", "cancelled"], "all declared fault dispositions")
check("SyntaxError" in faults[0]["stderr"] and faults[0]["returncode"] == 1, "raw syntax failure")
check(faults[1]["stdout"] == "[]\n" and faults[1]["returncode"] == 0 and faults[1]["output_schema_valid"] is False, "raw zero-exit malformed result")
check("entered" in faults[2]["stdout"] and faults[2]["returncode"] == -9, "running timeout killed and reaped")
check(faults[3]["termination_reason"] == "cancelled" and not faults[3]["delivered"], "original cancellation retained")
for row in data["adaptive_reference"]:
    episode_check(row, "adaptive_reference")
ref_returns = [r["return"] for r in data["adaptive_reference"]]
same(ce(ref_returns), data["adaptive_reference_ce"], "actual adaptive tool CE equals exact declared reference")
check(data["model_conformance"] is True and data["fault_controls_passed"] is True, "reported engineering gates agree")
check(meter["exit_code"] == 0 and meter["child_reaped"] and not meter["timed_out"], "whole process completed and reaped")
log = RUN / "tools/process.log"
check(hashlib.sha256(log.read_bytes()).hexdigest() == meter["process_log_sha256"], "whole process raw log identity")
services_cpu = sum(r["parent_cpu_s"] + r["child_cpu_s"] for r in records)
reference_cpu = sum(r["parent_cpu_s"] + r["child_cpu_s"] for r in data["adaptive_reference"])
qualification_cpu = sum(r["parent_cpu_s"] + r["child_cpu_s"] for r in data["validation"] + faults)
same(qualification_cpu, data["qualification_cpu_s"], "once-only qualification CPU")
training_cpu = sum(r["cpu_s"] for r in data["training"])
subtotal = services_cpu + reference_cpu + qualification_cpu + training_cpu + data["once_only_setup_cpu_s"]
envelope = data["parent_cpu_s"] + data["child_cpu_s"]
check(meter["child_cpu_seconds"] >= envelope >= subtotal, "nonoverlapping CPU subtotals enclosed by complete process")
result = {"schema": "hepta.tools-detached-arithmetic-review.v1", "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
          "source_commit": registration["source_commit"], "checks": checks, "errors": errors, "passed": not errors,
          "service_rows": len(records), "raw_record_parts": len(data["record_files"]), "invocations_by_scope": dict(invocations),
          "action_counts": dict(action_counts), "tariff_by_scope": dict(tariff_totals), "training": training_audit,
          "total_optimizer_updates": sum(r["actual_updates"] for r in data["training"]), "cells": recomputed_cells, "contrasts": contrasts,
          "adaptive_reference_ce": ce(ref_returns), "learned_greedy_ce": ce([r["return"] for r in records]),
          "adaptive_reference_mean_tariff": statistics.fmean(r["tariff"] for r in data["adaptive_reference"]),
          "accounting_cpu_s": {"service": services_cpu, "adaptive_reference": reference_cpu, "qualification": qualification_cpu,
                               "training": training_cpu, "setup": data["once_only_setup_cpu_s"], "subtotals": subtotal,
                               "internal_envelope": envelope, "complete_child_envelope": meter["child_cpu_seconds"], "supervisor": meter["supervisor_cpu_seconds"]},
          "whole_process_wall_s": meter["wall_seconds"], "whole_process_reported_peak_rss_bytes": meter["child_peak_rss_bytes"],
          "full_cost_amortization_qualified": False, "new_algorithm_established": False, "input_identities": identities,
          "review_limits": ["Read-only evidence recomputation; no service, training or official rsEAC reexecution.",
                            "Reviewer helped implement the tool source; this is a separate arithmetic implementation, not independent authorship or administrative evaluation.",
                            "Identical RRSTOP service programs in all four cells; wall/CPU fluctuations do not establish a causal work saving.",
                            "Repeated known templates; each cell has only nine observations and three fit seeds overall.",
                            "Action research credits and the parent meter's physical-resource tariff are different reported scopes; neither is a measured monetary bill.",
                            "Provisioning and external acquisition prices remain unknown; no full-cost break-even is qualified."]}
with (HERE / "REVIEW.json").open("x", encoding="utf-8") as output:
    json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
    output.write("\n")
print(json.dumps({"passed": result["passed"], "checks": checks, "errors": errors,
                  "service_rows": len(records), "total_updates": result["total_optimizer_updates"],
                  "invocations": dict(invocations), "cpu": result["accounting_cpu_s"]}, indent=2))
raise SystemExit(0 if not errors else 1)
