"""Aggregate SHA-bound V3 execution and verification costs without new inference.

An explicit index declares every registered job's disposition. Nested receipts
are checked but never recursively summed. This is accounting, not a gate.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


SCHEMA = "hepta.field-bridge.v3.execution-index.1"
STATES = {"complete", "failed", "not_started", "in_progress", "skipped_unqualified", "skipped_protocol"}
TRAINING = ("reference", "bank", "fit", "development", "audit", "final")


def require(value, message):
    if not value:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_text())


def leaves(value):
    if isinstance(value, dict):
        return {leaf for item in value.values() for leaf in leaves(item)}
    if isinstance(value, list):
        return {leaf for item in value for leaf in leaves(item)}
    return {value} if isinstance(value, str) else set()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return value.hexdigest()


def member(root, name):
    path = Path(name)
    require(not path.is_absolute() and ".." not in path.parts, "Unsafe relative evidence member")
    target = Path(root) / path
    require(target.resolve().is_relative_to(Path(root).resolve()) and not target.is_symlink(), "Evidence member escapes its root")
    return target


class Bindings:
    def __init__(self, base):
        self.base, self.checked = Path(base), {}

    def file(self, specification):
        require(isinstance(specification, dict) and set(specification) == {"path", "sha256"}, "A path and SHA256 binding are required")
        path = Path(specification["path"])
        path = (path if path.is_absolute() else self.base / path).resolve()
        require(path.is_file(), f"Bound artifact is missing: {path}")
        identity = sha(path)
        require(identity == specification["sha256"], f"Bound artifact changed: {path}")
        self.checked[str(path)] = identity
        return path

    def json(self, specification):
        return read(self.file(specification))

    def relative(self, root, name, identity):
        return self.file({"path": str(member(root, name)), "sha256": identity})


def jobs(protocol):
    result = {}
    for seed in protocol["seeds"]:
        for phase in TRAINING:
            key = f"training:{phase}:{seed}"
            result[key] = {"kind": "training", "phase": phase, "seed": seed, "directory": f"{phase}/{seed}"}
        for profile in protocol["runtime"]["profiles"]:
            for phase in ("bank", "fit", "audit", "confirm"):
                for role in (("primary", "retention") if phase == "confirm" else (None,)):
                    key = f"runtime:{phase}:{seed}:{profile}" + (f":{role}" if role else "")
                    directory = f"runtime/{phase}/{seed}-{profile}" + (f"/{role}" if role else "")
                    result[key] = {"kind": "runtime", "phase": phase, "seed": seed,
                                   "profile": profile, "role": role, "directory": directory}
    return result


def numeric(mapping, prefix=""):
    result = {}
    require(isinstance(mapping, dict), "Resource counters must be a dictionary")
    for key, value in mapping.items():
        name = prefix + key
        if isinstance(value, dict):
            result.update(numeric(value, name + "."))
        else:
            require(type(value) is int and value >= 0, f"Counter must be a nonnegative integer: {name}")
            result[name] = value
    return result


def authority(record):
    if "authority" in record:
        require(record["authority"] == "DENY_ALL" and record.get("native_owner_integration") is False,
                "Native authority differs from DENY_ALL / no owner integration")


def inventory(directory, complete, bindings, failed=False):
    require(isinstance(complete.get("files"), dict), "Completed evidence lacks its member inventory")
    expected = {*complete["files"], "COMPLETE.json"} | ({"FAILED.json"} if failed else set())
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    require(actual == expected, f"Completed inventory differs: {directory}")
    for name, identity in complete["files"].items():
        bindings.relative(directory, name, identity)


def provenance(item, spec, directory, root, source, protocol_sha, bindings):
    freeze = bindings.json(item["freeze"])
    start_path = bindings.file(item["start"])
    require(start_path == (directory / "START.json").resolve(), "START binding points outside the declared job")
    start = read(start_path)
    phase = spec["phase"] if spec["kind"] == "training" else "runtime-" + spec["phase"]
    require(start["phase"] == phase and start["seed"] == spec["seed"]
            and phase in freeze["allowed_phases"] and start["freeze_sha256"] == item["freeze"]["sha256"]
            and start["registered_commit"] == freeze["registered_commit"]
            and start["protocol_sha256"] == freeze["protocol_sha256"] == protocol_sha, "Stage provenance differs")
    require(start["source_files"] and all(freeze["source_files"].get(name) == value
            for name, value in start["source_files"].items()), "Incomplete stage source freeze")
    for name, value in freeze["source_files"].items():
        bindings.relative(source, name, value)
    for name, value in freeze.get("artifacts", {}).items():
        bindings.relative(root, name, value)
    if spec["kind"] == "runtime":
        require(start["profile"] == spec["profile"] and start["role"] == spec["role"]
                and start["native_library_sha256"] == freeze["native_library_sha256"], "Runtime scope/native binding differs")
        require(bindings.file(item["native"]) and item["native"]["sha256"] == freeze["native_library_sha256"], "Native binary changed")
    return start


def component(name, record, resources=None, wall_key="wall_ns", cpu_key="cpu_ns"):
    authority(record)
    counts = numeric(record["resources"] if resources is None else resources)
    durations = {key: value for key, value in counts.items() if key.endswith("_ns")}
    counts = {key: value for key, value in counts.items() if not key.endswith("_ns")}
    wall, cpu = record.get(wall_key), record.get(cpu_key)
    for value in (wall, cpu):
        require(value is None or type(value) is int and value >= 0, "Invalid recorded timer")
    return {"name": name, "counters": counts, "nested_timers_ns": durations,
            "recorded_component_wall_ns": wall, "recorded_component_cpu_ns": cpu}


def completed_costs(spec, directory, complete):
    if spec["kind"] == "training":
        return [component("top_level_training_phase", complete)]
    if spec["phase"] == "bank":
        require("resources" not in complete, "Runtime bank parent unexpectedly duplicates child costs")
        return [component(role, read(directory / role / "COMPLETE.json")) for role in ("runtime_fit", "runtime_select")]
    if spec["phase"] == "fit":
        fitted = read(directory / "READOUTS.json")
        for key in ("candidate_policies", "stage_head_fits", "native_tick_calls", "fit_wall_ns"):
            require(complete[key] == fitted[key], "Runtime fitting parent/readout counters differ")
        for model in fitted["models"].values():
            require(model.get("authority") == "DENY_ALL" and model.get("native_owner_integration") is False, "Fitted runtime model has excess authority")
        counts = {key: fitted[key] for key in ("candidate_policies", "stage_head_fits", "native_tick_calls", "native_ns")}
        return [component("runtime_fit_once", fitted, counts, "fit_wall_ns", "fit_python_cpu_ns")]
    selected = read(directory / "selected/COMPLETE.json")
    require(all(complete[key] == value for key, value in selected.items() if key != "files"), "Parent and selected runtime costs/metadata differ")
    require(complete.get("authority") == "DENY_ALL" and complete.get("native_owner_integration") is False, "Selected runtime authority missing")
    return [component("parent_selected_path_once", complete)]


def stage(item, spec, root, source, protocol_sha, bindings):
    state = item["status"]
    require(state in STATES, "Unknown stage disposition")
    directory = member(root, spec["directory"])
    result = {"id": item["id"], **spec, "status": state, "components": [], "cost_completeness": "not_executed"}
    if state.startswith("skipped_") or state == "not_started":
        require(not directory.exists(), "An omitted/not-started job has an execution directory")
        require(item.get("reason"), "An omitted/not-started stage needs an explicit reason")
        if state.startswith("skipped_"):
            decision = bindings.json(item["decision"])
            require(item.get("decision_field"), "Skipped qualification needs an explicit decision field")
            for key in item["decision_field"]:
                decision = decision[key]
            require(decision == item["decision_value"] and (state != "skipped_unqualified" or decision is False),
                    "Omission is unsupported by its qualification decision")
            result["decision"] = item["decision"]
            result["decision_field"], result["decision_value"] = item["decision_field"], decision
        result["reason"] = item["reason"]
        return result
    start = provenance(item, spec, directory, root, source, protocol_sha, bindings)
    result["started_monotonic_ns"] = start["started_monotonic_ns"]
    if state == "in_progress":
        require(not (directory / "COMPLETE.json").exists() and not (directory / "FAILED.json").exists(), "In-progress status hides a terminal receipt")
        result["cost_completeness"] = "unknown_in_progress"
        return result
    failed = state == "failed"
    require((directory / "FAILED.json").exists() == failed, "Failure status and preserved failure evidence differ")
    if failed:
        require(bindings.file(item["failure"]) == (directory / "FAILED.json").resolve(), "Wrong failure binding")
        result["failure"] = item["failure"]
    if (directory / "COMPLETE.json").exists():
        require(bindings.file(item["complete"]) == (directory / "COMPLETE.json").resolve(), "Wrong completion binding")
        complete = read(directory / "COMPLETE.json")
        inventory(directory, complete, bindings, failed)
        result["components"] = completed_costs(spec, directory, complete)
        result["cost_completeness"] = "recorded_completed_work" if failed else "complete_recorded_counters"
    else:
        require(failed, "Completed stage has no completion receipt")
        result["cost_completeness"] = "unknown_failed_work"
        if "failure_cost" in item:
            cost = bindings.json(item["failure_cost"])
            require(cost["failure_sha256"] == item["failure"]["sha256"] and cost["accounting_scope"] == "observed_lower_bound",
                    "Failure-cost recovery must bind the failure and remain a lower bound")
            result["components"] = [component("preserved_failure_lower_bound", cost)]
            result["cost_completeness"] = "lower_bound_failed_work"
    return result


def verification(item, bindings):
    receipt = bindings.json(item["receipt"])
    require(item.get("sources") and item.get("artifacts"), "Verification needs explicit producer-source and input-artifact bindings")
    source_hashes = {bindings.file(value).name: value["sha256"] for value in item["sources"]}
    for value in item["artifacts"]:
        bindings.file(value)
        require(value["sha256"] in leaves(receipt), "Verification input binding is absent from its receipt")
    for key in ("script_sha256", "auditor_source_sha256", "helper_source_sha256", "helpers_sha256"):
        if key in receipt:
            require(receipt[key] in source_hashes.values(), "Verification producer differs from the receipt")
    for name, value in receipt.get("reviewer_source_files", {}).items():
        require(source_hashes.get(name) == value, "Verification helper source is not bound")
    authority(receipt)
    state = item["status"]
    require(state in {"complete", "failed"}, "Verification must describe an executed attempt")
    if state == "complete":
        require(receipt.get("passed") is True or receipt.get("status") == "pass", "Verification success is not supported by its receipt")
    else:
        require(receipt.get("passed") is False or "error" in receipt, "Failed verification needs failure evidence")
    counts = numeric(receipt.get("verification_resources", {}))
    aliases = {"verification_gradient_microsteps": "scheduled_gradient_microsteps",
        "verification_least_squares_solves": "least_squares_solves", "ridge_heads_rebuilt": "ridge_heads_rebuilt",
        "verification_native_ticks": "native_tick_calls", "generator_forward_calls": "generator_forward_calls",
        "observer_forward_calls": "observer_forward_calls", "source_corpus_loads": "source_corpus_loads"}
    for name, target in aliases.items():
        if name in receipt:
            value = numeric({target: receipt[name]})[target]
            require(target not in counts or counts[target] == value, "Duplicated verification counters conflict")
            counts[target] = value
    for name in ("verification_observer_digit_forwards", "actual_observer_batch_calls", "actual_observer_digit_examples"):
        if name in receipt:
            counts.update(numeric(receipt[name], name + "."))
    logical = {name: receipt[name] for name in ("logical_observer_image_pairs", "logical_observer_batch_calls",
        "logical_observer_digit_examples", "observer_batch_cache_hits") if name in receipt}
    durations = {"wall_ns": receipt.get("verification_wall_ns"), "cpu_ns": receipt.get("verification_cpu_ns")}
    if durations["wall_ns"] is None and "elapsed_seconds" in receipt:
        durations["wall_ns"] = round(receipt["elapsed_seconds"] * 1_000_000_000)
    if "verification_native_ns" in receipt:
        counts["native_ns"] = receipt["verification_native_ns"]
    return {"id": item["id"], "kind": item["kind"], "status": state, "receipt": item["receipt"],
        "components": [component("independent_verification_once", durations, counts)],
        "logical_work_and_cache": numeric(logical), "new_training_evidence": False,
        "cost_completeness": "recorded_verification" if state == "complete" else "unknown_failed_work"}


def totals(entries):
    groups = {}
    for entry in entries:
        key = entry["kind"]
        target = groups.setdefault(key, {"counters": Counter(), "nested_timers_ns": Counter(),
            "recorded_component_wall_sum_ns": 0, "recorded_component_cpu_sum_ns": 0, "components_without_wall_timer": 0})
        for part in entry["components"]:
            target["counters"].update(part["counters"])
            target["nested_timers_ns"].update(part["nested_timers_ns"])
            for metric in ("wall", "cpu"):
                value = part[f"recorded_component_{metric}_ns"]
                if value is not None:
                    target[f"recorded_component_{metric}_sum_ns"] += value
            target["components_without_wall_timer"] += part["recorded_component_wall_ns"] is None
    return groups


def aggregate(index, base):
    require(index["schema"] == SCHEMA, "Unknown execution-index schema")
    bindings = Bindings(base)
    protocol = bindings.json(index["protocol"])
    require(protocol["runtime"]["authority"] == "DENY_ALL" and protocol["runtime"]["native_owner_integration"] is False, "Protocol grants unexpected authority")
    root, source = Path(index["run_root"]).resolve(), Path(index["source_root"]).resolve()
    expected = jobs(protocol)
    identifiers = [item["id"] for item in index["stages"]]
    require(len(set(identifiers)) == len(identifiers) and set(identifiers) == set(expected),
            "Every registered job needs exactly one disposition; implicit retries are forbidden")
    rows = [stage(item, expected[item["id"]], root, source, index["protocol"]["sha256"], bindings) for item in index["stages"]]
    declared_starts = {(member(root, expected[item["id"]]["directory"]) / "START.json").resolve()
        for item in index["stages"] if item["status"] not in {"not_started", "skipped_unqualified", "skipped_protocol"}}
    additional = {bindings.file(value) for value in index.get("nonstudy_start_files", [])}
    require(all(read(path).get("verification_only") is True for path in additional),
            "An additional START must explicitly identify verification-only work")
    require({path.resolve() for path in root.rglob("START.json")} == declared_starts | additional,
            "Unaccounted execution attempt or unexpected START receipt")
    verifications, seen, verification_ids = [], set(), set()
    for item in index["verification"]:
        identity = item["receipt"]["sha256"]
        require(identity not in seen and item["id"] not in verification_ids, "An independent verification receipt was charged twice")
        seen.add(identity)
        verification_ids.add(item["id"])
        verifications.append(verification(item, bindings))
    elapsed = None
    if index.get("operational_timing"):
        timer = bindings.json(index["operational_timing"])
        require(timer["schema"] == "hepta.field-bridge.v3.operational-span.1" and timer["clock_domain"]
                and timer["run_root"] == str(root), "Operational elapsed span lacks a common clock/run binding")
        begin, end = timer["started_monotonic_ns"], timer["finished_monotonic_ns"]
        require(type(begin) is type(end) is int and 0 <= begin <= end, "Invalid operational elapsed span")
        elapsed = {"elapsed_ns": end - begin, "scope": timer["scope"], "receipt": index["operational_timing"]}
    unresolved = [row["id"] for row in rows if row["status"] in {"not_started", "in_progress"}]
    unknown = [row["id"] for row in rows + verifications if "failed" in row["cost_completeness"] or "unknown" in row["cost_completeness"]]
    return {"schema": "hepta.field-bridge.v3.execution-ledger.1", "accounting_validation_passed": True,
        "authority": "DENY_ALL", "native_owner_integration": False, "scientific_outcome_claims": False,
        "stages": rows, "verification": verifications, "scientific_costs": totals(rows), "verification_costs": totals(verifications),
        "accounting_scope": index["accounting_scope"],
        "stage_status_counts": dict(Counter(row["status"] for row in rows)), "unresolved_stages": unresolved,
        "unknown_or_lower_bound_cost_attempts": unknown, "all_stage_dispositions_terminal": not unresolved,
        "operational_elapsed": elapsed, "bound_files": bindings.checked,
        "timing_interpretation": "Component wall sums are cumulative worker durations, may overlap across processes and exclude untimed setup. Nested timers overlap parent durations. No elapsed time or FLOPs are inferred from either sum.",
        "failure_interpretation": "Failed work without complete counters is unknown or a bound observed lower bound; no failure is assigned zero by default. No retry is authorized by this ledger."}


def template(run, source, protocol):
    p = read(protocol)
    return {"schema": SCHEMA, "run_root": str(Path(run).resolve()), "source_root": str(Path(source).resolve()),
        "protocol": {"path": str(Path(protocol).resolve()), "sha256": sha(protocol)},
        "accounting_scope": "Registered V3 scientific phases and explicitly listed independent verification receipts. Environment setup/builds and synthetic implementation contracts are excluded unless separately listed; missing counters are not inferred.",
        "stages": [{"id": key, "status": "not_started", "reason": "Disposition must be filled from a bound phase receipt or qualification decision."} for key in jobs(p)],
        "verification": [], "nonstudy_start_files": [], "operational_timing": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--template", action="store_true")
    for name in ("run", "source", "protocol"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "Refusing to overwrite an execution index or ledger")
    if args.template:
        require(all((args.run, args.source, args.protocol)) and args.index is None, "Template needs run, source, protocol only")
        result = template(args.run, args.source, args.protocol)
    else:
        require(args.index is not None, "A bound execution index is required")
        result = aggregate(read(args.index), args.index.parent)
        result.update(index_sha256=sha(args.index), script_sha256=sha(__file__))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"output": str(args.out), "sha256": sha(args.out)}))


if __name__ == "__main__":
    main()
