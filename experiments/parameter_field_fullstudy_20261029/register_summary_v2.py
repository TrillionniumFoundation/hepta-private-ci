"""Metadata/hash-only registration for aggregate analysis and literal finalization.

Scientific JSON payloads, arrays and checkpoints are hashed, never decoded here.
The unchanged admitted report still performs its complete semantic loader checks.
No worker, endpoint role, score, fit, or external publication is started.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import resource
import time

from . import analysis_launch_v2 as launcher
from .finalize_v2 import controller_quiescence
from .launch_v2 import arguments, validate_queue, verify_controller, verify_job
from .register_followups_v2 import (ROOT, PREFIX, SEEDS, PROTOCOL_SHA, checked,
    committed_sources, descriptor, encode, read, require, tree_artifacts)
from .resource_v2 import file_hash, load_registration, whole_phase_lock
from .run_v2 import verify_files

HISTORY_SHA = "2848a9fc4b3092b79c3bff158b4c966bce5941760c0ea531eb7b4cb45c31c785"
METHODS = ("ordinary", "field12", "full_current_state", "history6")


def add(artifacts, path):
    item = descriptor(path)
    require(item["path"] not in artifacts or artifacts[item["path"]] == item["sha256"], "Conflicting artifact identity")
    artifacts[item["path"]] = item["sha256"]
    return item


def source_closure(path, expected, sources, artifacts, seen):
    item = add(artifacts, path)
    require(item["sha256"] == expected, "Source freeze identity differs")
    if item["path"] in seen:
        return read(path)
    seen.add(item["path"])
    for sibling in ("BUNDLE.json", "REGISTRATION_COST.json"):
        candidate = Path(path).parent / sibling
        if candidate.is_file():
            add(artifacts, candidate)
    freeze = read(path)
    verify_files(freeze, ROOT)
    for name, sha in freeze["source_files"].items():
        require(name not in sources or sources[name] == sha, "Scientific source closures disagree")
        sources[name] = sha
    for name, sha in freeze.get("artifacts", {}).items():
        require(add(artifacts, name)["sha256"] == sha, "Ancestor artifact differs")
    parents = [freeze[key] for key in ("scientific_parent", "actual_source_A") if key in freeze]
    parents += list(freeze.get("training_parents", {}).values())
    for parent in parents:
        source_closure(parent["path"], parent["sha256"], sources, artifacts, seen)
    return freeze


def stems():
    return [f"schedule-{schedule}-{prefix}-step-{step}" for schedule in range(6000, 6004)
            for prefix in ("baseline", "balanced") for step in range(0, 288, 48)]


def ab_ids(phase):
    schedules = range(6000, 6004) if phase == "A" else range(106000, 106016)
    modes = METHODS if phase == "A" else METHODS + ("fixed_taper",)
    return [f"seed-{seed}-schedule-{schedule}-{mode}" for seed in SEEDS for schedule in schedules for mode in modes]


def c_ids():
    return [f"{mode}-seed-{seed}-{method}" for seed in range(801, 809)
            for mode in ("ordinary", "dual") for method in ("ordinary", "field12", "frozen")]


def exact_names(directory, pattern, expected):
    directory = Path(directory)
    actual = {p.name for p in directory.glob(pattern) if p.is_file()}
    require(actual == set(expected), "Fixed file population differs: " + str(directory) + " / " + pattern)


def payload_population(root, stages, artifacts):
    """Verify all fixed core paths without parsing BANK/PATHS/COMPLETE/ENDPOINTS."""
    for phase in ("A", "B"):
        identities = ab_ids(phase)
        for run in stages[phase]["runs"]:
            seed = run["seed"]
            directory = root / f"stage_{phase}/seed-{seed}"
            paths = directory / "paths"
            mine = [name for name in identities if name.startswith(f"seed-{seed}-")]
            exact_names(paths, "*.state", [name + ".state" for name in mine])
            exact_names(paths, "*.json", [name + ".json" for name in mine] + ["PATHS.json"])
            run["paths"] = add(artifacts, paths / "PATHS.json")
            if phase == "A":
                bank = directory / "bank"
                run["bank"] = add(artifacts, bank / "BANK.json")
                exact_names(bank, "*.state", [stem + ".state" for stem in stems()])
                names = [f"{stem}-action-{a}.npz" for stem in stems() for a in range(4)]
                names += [f"{mode}-{kind}.npz" for mode in METHODS[1:] for kind in ("head", "bank")]
                exact_names(bank, "*.npz", names)
                add(artifacts, bank / "trace.jsonl.gz")
                run["bank_outputs"] = {stem: [add(artifacts, bank / f"{stem}-action-{a}.npz") for a in range(4)] for stem in stems()}
    c_stage = root / "stage_C"
    warm = [f"{mode}-seed-{seed}.pt.gz" for seed in [701, 702, *range(801, 809)] for mode in ("ordinary", "dual")]
    ends = [f"{mode}-seed-{seed}-{policy}" for seed in range(801, 809) for mode in ("ordinary", "dual") for policy in ("baseline", "field")]
    exact_names(c_stage / "warmstarts", "*.pt.gz", warm)
    exact_names(c_stage / "endpoints", "*.pt.gz", [name + ".pt.gz" for name in ends])
    exact_names(c_stage / "endpoints", "*.trace.json.gz", [name + ".trace.json.gz" for name in ends])
    for mode in ("ordinary", "dual"):
        add(artifacts, c_stage / f"heads/{mode}/HEAD.json")
    for seed in SEEDS:
        directory = root / f"stage_R/seed-{seed}"
        names = [f"{stem}-action-{a}" for stem in stems() for a in range(4)]
        exact_names(directory, "*.bin.gz", [name + ".bin.gz" for name in names])
        exact_names(directory, "*.trace.json.gz", [name + ".trace.json.gz" for name in names])
        witness = root / f"stage_W/seed-{seed}"
        states = ["original-parent.state", "reflected-parent.state"]
        states += [f"action-{a}-{kind}.state" for a in range(4) for kind in ("first", "terminal")]
        exact_names(witness, "*.state", states)
        exact_names(witness, "*.npz", ["projection.npz", *[f"action-{a}-outputs.npz" for a in range(4)]])
    for phase in ("A", "B", "C"):
        ids = c_ids() if phase == "C" else ab_ids(phase) + [f"seed-{seed}-frozen" for seed in SEEDS]
        folder = "endpoint_evaluation" if phase == "C" else "endpoints"
        exact_names(root / f"stage_{phase}/{folder}/scores", "*.npz", [f"{name}-{role}.npz" for name in ids for role in ("task", "clean")])


def access_metadata(root, phase, job, artifacts):
    flags, stage = arguments(job["argv"]), root / ("stage_" + phase)
    kind = "qualification" if phase == "B" else "final"
    access_path = stage / ("QUALIFICATION_ACCESS_FREEZE.json" if phase == "B" else "FINAL_ACCESS_FREEZE.json")
    checkpoint_path = stage / "ENDPOINT_CHECKPOINTS.json"
    access, checkpoints = read(access_path), read(checkpoint_path)
    scorer = read(flags["--freeze"])
    source = add(artifacts, flags["--source-manifest"])
    manifest = add(artifacts, checkpoint_path)
    expected = ab_ids("B") if phase == "B" else c_ids()
    require(access.get("phase") == checkpoints.get("phase") == kind
            and access.get("source_manifest_sha256") == source["sha256"]
            and access.get("checkpoint_manifest_sha256") == manifest["sha256"]
            and access.get("scorer_freeze_sha256") == job["freeze_sha256"]
            and access.get("scorer_registered_commit") == scorer["registered_commit"]
            and access.get("allowed_roles") == [kind + "_task", kind + "_clean"]
            and access.get("required_checkpoint_ids") == sorted(expected)
            and checkpoints.get("training_complete") is True, "Endpoint access provenance differs")
    entries = checkpoints["checkpoints"]
    require(len(entries) == len(expected) and {entry["id"] for entry in entries} == set(expected), "Incomplete endpoint access population")
    for entry in entries:
        target = checked(stage, entry)
        name = entry["id"]
        if phase == "B":
            seed = name.split("-")[1]
            expected_path = stage / f"seed-{seed}/paths/{name}.state"
        else:
            mode, unused, seed, method = name.split("-")
            suffix = "baseline" if method == "ordinary" else "field"
            expected_path = stage / (f"warmstarts/{mode}-seed-{seed}.pt.gz" if method == "frozen" else f"endpoints/{mode}-seed-{seed}-{suffix}.pt.gz")
        require(target == expected_path, "Endpoint access checkpoint identity differs")
        add(artifacts, target)
    return add(artifacts, access_path)


def collect(args, registration):
    root = args.root
    require(file_hash(args.queue) == args.expected_queue_sha256, "Final queue identity differs")
    queue = read(args.queue)
    jobs = validate_queue(queue, root)
    require(queue.get("finalize") is True and {j["id"] for j in jobs} == launcher.JOB_IDS, "Full final queue is required")
    require(not launcher.active_workers(root), "Registered workers remain active")
    sources, artifacts, seen, freezes, stages, seals = {}, {}, set(), {}, {}, {}
    require(descriptor(args.controller_freeze)["sha256"] == args.controller_freeze_sha256, "Controller source freeze differs")
    verify_controller(type("Args", (), {"freeze": args.controller_freeze})(), registration)
    source_closure(args.controller_freeze, args.controller_freeze_sha256, sources, artifacts, seen)
    execution_path = root / "controller/EXECUTION.json"
    execution, start = read(execution_path), read(root / "controller/START.json")
    require(execution.get("complete") is True and execution.get("source_freeze_sha256") == args.controller_freeze_sha256
            and start.get("source_freeze_sha256") == args.controller_freeze_sha256
            and start.get("amendment_sha256") == registration["_sha256"]
            and execution.get("oom_admission_paused") is False and set(execution["jobs"]) == launcher.JOB_IDS,
            "Controller did not seal the full registered run")
    artifacts.update(tree_artifacts(root / "controller"))
    seals[str(execution_path)] = add(artifacts, execution_path)["sha256"]
    for job in jobs:
        verify_job(job, registration)
        flags = arguments(job["argv"])
        freeze = source_closure(flags["--freeze"], job["freeze_sha256"], sources, artifacts, seen)
        freezes[job["id"]] = descriptor(flags["--freeze"])
        result = execution["jobs"][job["id"]]
        complete_path = root / job["completion"]
        item = add(artifacts, complete_path)
        require(result.get("complete") is True and result.get("exit_code") == 0
                and result.get("completion") == {**item, "path": job["completion"]}
                and read(root / "controller" / (job["id"] + ".RESULT.json")) == result
                and read(root / "controller" / (job["id"] + ".START.json"))["job"] == job,
                "Controller job completion or source definition differs")
        seals[str(complete_path)] = item["sha256"]
        phase = job["phase"]
        stages.setdefault(phase, {"status": "COMPLETE", "runs": []})
        if job["id"].endswith("_endpoint"):
            stages[phase]["endpoint"] = item
            training = freeze["training_parents"][phase]
            matches = [j for j in jobs if j["phase"] == phase and not j["id"].endswith("_endpoint")]
            require(all(j["freeze_sha256"] == training["sha256"]
                    and Path(arguments(j["argv"])["--freeze"]).resolve() == Path(training["path"]).resolve() for j in matches),
                    "Scorer actual training parent differs from controller")
            continue
        operation = read(complete_path)  # Operation receipt has provenance/cost metadata, no scientific outcomes.
        require(operation.get("complete") is True and operation.get("post_execution_storage_check") is True
                and operation.get("attempt_id") == "attempt02" and operation.get("phase") == phase
                and operation.get("seed") == job.get("seed") and operation.get("registered_commit") == freeze["registered_commit"]
                and operation.get("source_freeze_sha256") == job["freeze_sha256"]
                and operation.get("operational_amendment_sha256") == registration["_sha256"]
                and operation.get("scientific_protocol_sha256") == PROTOCOL_SHA
                and operation.get("scientific_source_bytes_unchanged") is True, "Operation gate or source ancestry differs")
        seed = job.get("seed")
        expected = root / (f"stage_{phase}/COMPLETE.json" if seed is None else f"stage_{phase}/seed-{seed}/COMPLETE.json")
        target = checked(root, operation["scientific_complete"])
        require(target == expected, "Scientific completion path differs")
        science = add(artifacts, target)
        seals[str(target)] = science["sha256"]
        stages[phase]["runs"].append({"seed": seed, "operation": item, "complete": science})
    require(set(stages) == set(launcher.PHASES) and len(seals) == 26, "Scientific completion seal population differs")
    for phase in launcher.PHASES:
        stages[phase]["runs"].sort(key=lambda row: row["seed"] or 0)
        expected = set(SEEDS) if phase in ("A", "B", "R") else {None}
        require(len(stages[phase]["runs"]) == len(expected) and {r["seed"] for r in stages[phase]["runs"]} == expected,
                "Scientific operation population differs")
        artifacts.update(tree_artifacts(root / ("stage_" + phase)))
    artifacts.update(tree_artifacts(root / "operations"))
    payload_population(root, stages, artifacts)
    access = [access_metadata(root, phase, next(j for j in jobs if j["id"] == phase + "_endpoint"), artifacts) for phase in ("B", "C")]
    add(artifacts, args.queue)
    add(artifacts, args.amendment)
    for path in sorted((ROOT / PREFIX).glob("*.py")):
        sources[str(path.relative_to(ROOT))] = file_hash(path)
    require(file_hash(ROOT / PREFIX / "PROTOCOL.json") == PROTOCOL_SHA, "Original scientific protocol drift")
    return stages, sources, artifacts, seals, {"source_freezes": list(freezes.values()), "access_freezes": access,
        "controller": descriptor(execution_path), "controller_source_freeze": descriptor(args.controller_freeze), "queue": descriptor(args.queue)}


def historical_inputs(args, artifacts):
    historical = add(artifacts, args.historical_inputs)
    require(historical["sha256"] == args.expected_historical_sha256 == HISTORY_SHA, "Historical cost/integrity input differs")
    old = read(args.historical_inputs)
    require(old.get("schema") == "hepta.fullstudy.report-inputs.1"
            and old["integrity"]["historical_exact_regression_gate"].startswith("FAIL"), "Historical V5 failure must remain preserved")
    for item in old["engineering_preflights"] + [r["receipt"] for r in old["failed_attempts"]]:
        require(add(artifacts, item["path"]) == item, "Historical receipt bytes differ")
    return old, historical


def analysis_inputs(args, registration, stages, artifacts, provenance):
    old, historical = historical_inputs(args, artifacts)
    return {"schema": "hepta.fullstudy.report-inputs.1", "attempt_id": "attempt02", "raw_root": str(args.root),
        "protocol": add(artifacts, ROOT / PREFIX / "PROTOCOL.json"), "amendment": descriptor(args.amendment), "stages": stages,
        "engineering_preflights": old["engineering_preflights"], "failed_attempts": old["failed_attempts"], "integrity": old["integrity"],
        "resource_status": {"status": "SCIENTIFIC_EXECUTION_COMPLETE_AGGREGATE_PENDING", "controller": provenance["controller"],
            "previous_admission_status": old["resource_status"], "original_1GiB_2GiB_reserve_contract_passed": False},
        "registration_provenance": {**provenance, "historical_report_inputs": historical,
            "scientific_payloads_decoded_for_registration": False, "outcome_values_used_for_registration": False}}


def aggregate_completion(args, registration, artifacts, seals):
    require(args.analysis_freeze and args.analysis_freeze_sha256, "Actual aggregate source freeze is required")
    actual = add(artifacts, args.analysis_freeze)
    require(actual["sha256"] == args.analysis_freeze_sha256, "Aggregate source freeze identity differs")
    freeze = read(args.analysis_freeze)
    require(freeze.get("execution_kind") == "aggregate_analysis" and freeze.get("allowed_phases") == ["ANALYSIS"]
            and freeze.get("attempt_id") == "attempt02" and freeze.get("operational_amendment_sha256") == registration["_sha256"]
            and freeze.get("protocol_sha256") == PROTOCOL_SHA and freeze.get("required_scientific_seals") == seals,
            "Aggregate source ancestry/population differs")
    verify_files(freeze, ROOT)
    require(isinstance(freeze.get("analysis_id"), str) and freeze["analysis_id"].isalnum()
            and freeze.get("report_module") == __package__ + ".report_results"
            and all(str(PREFIX / (name + ".py")) in freeze["source_files"] for name in
                ("analysis_launch_v2", "report_results", "resource_v2", "resource_io_v2", "run_v2")),
            "Aggregate registered entrypoint/source closure differs")
    require(all(freeze.get("artifacts", {}).get(path) == sha for path, sha in artifacts.items() if path != actual["path"]),
            "Aggregate did not bind all completed scientific inputs")
    inputs = freeze["report_inputs"]
    require(add(artifacts, inputs["path"]) == inputs, "Aggregate inputs differ")
    control = args.root / "analysis_operations" / freeze["analysis_id"]
    require(not (control / "FAILED.json").exists(), "Failed aggregate cannot finalize evidence")
    complete, worker = read(control / "COMPLETE.json"), read(control / "WORKER_COMPLETE.json")
    expected = {"attempt_id": "attempt02", "phase": "ANALYSIS", "analysis_id": freeze["analysis_id"],
        "source_freeze_sha256": actual["sha256"], "registered_commit": freeze["registered_commit"],
        "operational_amendment_sha256": registration["_sha256"], "report_inputs_sha256": inputs["sha256"],
        "scheduled_gradient_microsteps": 0, "endpoint_scoring_performed": False, "refitting_performed": False}
    require(all(row.get("complete") is True and row.get("post_execution_storage_check") is True
            and all(row.get(k) == v for k, v in expected.items()) for row in (complete, worker)), "Aggregate operation did not complete")
    require(complete.get("worker_receipt") == descriptor(control / "WORKER_COMPLETE.json"), "Aggregate worker receipt differs")
    output = (args.root / freeze["output_relative"]).resolve()
    require(output.is_relative_to(args.root) and output != args.root, "Aggregate output escapes raw root")
    expected_outputs = [descriptor(output / name) for name in ("RESULTS.json", "REPORT.md")]
    require(complete.get("outputs") == expected_outputs, "Aggregate output population or bytes differ")
    for path in (control / "COMPLETE.json", control / "WORKER_COMPLETE.json", output / "RESULTS.json", output / "REPORT.md"):
        seals[str(path)] = add(artifacts, path)["sha256"]
    artifacts.update(tree_artifacts(control))
    artifacts.update(tree_artifacts(output))
    require(len(seals) == 30, "Finalizer requires all 26 science/controller and four aggregate seals")
    for sibling in ("BUNDLE.json", "REGISTRATION_COST.json"):
        candidate = Path(args.analysis_freeze).parent / sibling
        if candidate.is_file():
            add(artifacts, candidate)
    return actual


def write_bundle(output, payloads, metadata):
    payloads["BUNDLE.json"] = encode({"schema": "hepta.fullstudy.summary-registration-bundle.1", **metadata,
        "workers_started": 0, "scientific_payloads_decoded": False, "external_publications": 0,
        "files": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in payloads.items()}})
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    return descriptor(output / "BUNDLE.json")


def register(args):
    started_wall, started_cpu = time.monotonic(), time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    args.root, args.output = Path(args.root).resolve(), Path(args.output).resolve()
    args.amendment = Path(args.amendment).resolve()
    require(args.root.is_dir() and not args.output.exists() and not args.output.is_relative_to(args.root), "Unsafe or existing registration destination")
    registration = load_registration(args.amendment, args.amendment_sha256)
    require(args.root == Path(registration["raw_root"]).resolve(), "Raw root differs from operational registration")
    with controller_quiescence(args.root), whole_phase_lock(args.root):
        stages, sources, artifacts, seals, provenance = collect(args, registration)
        common = {"schema": "hepta.fullstudy.source-freeze.1", "registered_commit": args.source_commit,
            "source_registration_scope": "LOCAL_ONLY", "attempt_id": "attempt02", "protocol_sha256": PROTOCOL_SHA,
            "operational_amendment_sha256": registration["_sha256"], "source_files": sources,
            "created_at": datetime.now(timezone.utc).isoformat(), "outcome_values_used_for_registration": False}
        payloads = {}
        if args.stage == "analysis":
            require(args.analysis_id.isalnum(), "Analysis identity must be alphanumeric")
            spec = analysis_inputs(args, registration, stages, artifacts, provenance)
            raw = payloads["REPORT_INPUTS.json"] = encode(spec)
            inputs = {"path": str(args.output / "REPORT_INPUTS.json"), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            artifacts[inputs["path"]] = inputs["sha256"]
            freeze = {**common, "execution_kind": "aggregate_analysis", "allowed_phases": ["ANALYSIS"],
                "analysis_id": args.analysis_id, "report_module": __package__ + ".report_results", "output_relative": "aggregate_results",
                "report_inputs": inputs, "artifacts": artifacts, "required_scientific_seals": seals}
            payloads["ANALYSIS_SOURCE_FREEZE.json"] = encode(freeze)
        else:
            historical_inputs(args, artifacts)
            actual = aggregate_completion(args, registration, artifacts, seals)
            freeze = {**common, "execution_kind": "evidence_finalization", "allowed_phases": ["FINALIZE"],
                "actual_aggregate_source_freeze": actual, "artifacts": artifacts, "required_scientific_seals": seals}
            payloads["FINALIZER_SOURCE_FREEZE.json"] = encode(freeze)
        committed_sources(args.source_git_root, args.source_commit, sources)
        require(file_hash(args.queue) == args.expected_queue_sha256, "Final queue changed during registration")
        for name, sha in artifacts.items():
            if name != str(args.output / "REPORT_INPUTS.json"):
                require(file_hash(name) == sha, "Artifact changed during registration")
        bundle = write_bundle(args.output, payloads, {"stage": args.stage, "registered_commit": args.source_commit,
            "source_registration_scope": "LOCAL_ONLY", "required_completion_seals": len(seals)})
        child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
        cost = {"schema": "hepta.fullstudy.metadata-registration-cost.1", "stage": args.stage, "bundle": bundle,
            "wall_seconds": time.monotonic() - started_wall, "cpu_seconds": time.process_time() - started_cpu,
            "process_cpu_seconds_total": time.process_time(),
            "child_process_cpu_seconds": (child_end.ru_utime + child_end.ru_stime) - (child_start.ru_utime + child_start.ru_stime),
            "cpu_accounting": "cpu_seconds is parent delta; child_process_cpu_seconds is separate waited-child delta, including Git. process_cpu_seconds_total is not another additive component.",
            "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
            "scheduled_gradient_microsteps": 0, "endpoint_scoring_performed": False,
            "measurement_scope": "Validation, hashing, source verification and sealed bundle writes; excludes serialization/write/readback of this final cost receipt."}
        cost_path = args.output / "REGISTRATION_COST.json"
        with cost_path.open("xb") as stream:
            stream.write(encode(cost))
            stream.flush()
            os.fsync(stream.fileno())
        return {"bundle": bundle, "registration_cost": descriptor(cost_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("analysis", "finalizer"))
    for name in ("root", "queue", "expected-queue-sha256", "controller-freeze", "controller-freeze-sha256",
                 "amendment", "amendment-sha256", "source-git-root", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--historical-inputs", default=str(ROOT / PREFIX / "evidence/REPORT_INPUTS_BLOCKED.json"))
    parser.add_argument("--expected-historical-sha256", default=HISTORY_SHA)
    parser.add_argument("--analysis-id", default="analysis01")
    parser.add_argument("--analysis-freeze")
    parser.add_argument("--analysis-freeze-sha256")
    args = parser.parse_args()
    print(encode(register(args)).decode(), end="")


if __name__ == "__main__":
    main()
