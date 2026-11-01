#!/usr/bin/env python3
"""Account recorded worker CPU, including the abandoned OOM attempt.

Publication-only, standard-library code. Never imports experiment code, loads
checkpoints/NPZs, generates data, or changes existing records. Run ``build`` only
after the formal run ends; ``selfcheck`` uses artificial receipts exclusively.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
import tempfile


STAGES = ("train", "evaluate", "recovery_fit", "recovery_confirm", "full_online_confirmation")
IDENTITY = ("task", "seed", "train_mode")
SOURCE = Path(__file__).resolve()


class LedgerError(ValueError):
    """A receipt cannot support the requested accounting."""


def require(condition, message):
    if not condition:
        raise LedgerError(message)


def number(value, name):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            "Expected finite nonnegative " + name)
    return float(value)


def close(left, right):
    return math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-6)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


class Inputs:
    """Keep an exact provenance list; reading twice never creates a charge."""

    def __init__(self, root):
        self.root, self.data, self.sources = Path(root).resolve(), {}, {}

    def relative(self, path):
        path = Path(path).resolve()
        require(path.is_relative_to(self.root), "Input escaped results root")
        return str(path.relative_to(self.root))

    def read(self, path):
        name = self.relative(path)
        if name not in self.data:
            raw = Path(path).read_bytes()
            self.data[name] = json.loads(raw)
            self.sources[name] = dict(path=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return self.data[name]


def job_identity(row):
    require(all(name in row for name in IDENTITY), "Missing process task/seed/train_mode")
    require(isinstance(row["task"], str) and type(row["seed"]) is int
            and row["train_mode"] in ("light", "value"), "Invalid process identity")
    key = tuple(row[name] for name in IDENTITY)
    expected_name = f"{key[0]}_s{key[1]}_{key[2]}"
    require(row.get("name", expected_name) == expected_name, "Process name disagrees with identity")
    return key


def command_identity(arguments):
    require(isinstance(arguments, list) and all(isinstance(x, str) for x in arguments),
            "Interruption worker args must be a string list")
    values = {}
    for flag, key in (("--task", "task"), ("--seed", "seed"), ("--mode", "train_mode")):
        require(arguments.count(flag) == 1, "Worker command has missing/duplicate " + flag)
        index = arguments.index(flag)
        require(index + 1 < len(arguments), "Worker command has no value for " + flag)
        values[key] = arguments[index + 1]
    try:
        values["seed"] = int(values["seed"])
    except ValueError as error:
        raise LedgerError("Worker seed is not an integer") from error
    return job_identity(values)


def completed_jobs(inputs, directory):
    records, identities = [], set()
    for path in sorted(directory.glob("*.json")):
        if path.name == "TOTAL.json":
            continue
        row = inputs.read(path)
        key = job_identity(row)
        require(key not in identities, "Duplicate completed process identity in " + str(directory))
        identities.add(key)
        require(type(row.get("exit_code")) is int, "Missing/invalid completed process exit code")
        user = number(row.get("cpu_user_seconds"), "wait4 user CPU")
        system = number(row.get("cpu_system_seconds"), "wait4 system CPU")
        records.append(dict(**dict(zip(IDENTITY, key)), source=inputs.relative(path),
            exit_code=row["exit_code"], cpu_user_seconds=user, cpu_system_seconds=system,
            cpu_seconds=user+system, wall_seconds=number(row.get("wall_seconds"), "worker wall time"),
            maximum_rss_kib=number(row.get("maximum_rss_kib"), "wait4 maximum RSS"),
            outcome="completed_successfully" if row["exit_code"] == 0 else "completed_failed",
            measurement_status="complete_process_lifetime_wait4"))
    return records


def stage_ledger(inputs, run, stage, protocol):
    directory = run / "receipts" / stage
    jobs = completed_jobs(inputs, directory)
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"],
                   ("value",) if stage.startswith("recovery_") else ("light", "value")))
    observed = {tuple(row[name] for name in IDENTITY) for row in jobs}
    require(observed <= expected, "Unexpected worker identity in " + stage)
    measured = sum(row["cpu_seconds"] for row in jobs)
    failed = sum(row["exit_code"] != 0 for row in jobs)
    total_path = directory / "TOTAL.json"
    total = inputs.read(total_path) if total_path.exists() else None
    if total is not None:
        require(total.get("stage") == stage, "TOTAL stage identity mismatch")
        require(total.get("jobs") == len(jobs) and total.get("failed") == failed,
                "TOTAL job/failure counts disagree with individual receipts in " + stage)
        require(close(number(total.get("process_cpu_seconds"), "TOTAL process CPU"), measured),
                "TOTAL CPU disagrees with individual receipts in " + stage)
    complete = total is not None and observed == expected
    return dict(stage=stage, expected_jobs=len(expected), recorded_jobs=len(jobs), failed_jobs=failed,
        coverage="complete" if complete else "incomplete",
        status=("complete_with_failed_processes" if failed else "complete") if complete else "lower_bound",
        observed_worker_cpu_seconds=measured,
        successful_completed_worker_cpu_seconds=sum(row["cpu_seconds"] for row in jobs if row["exit_code"] == 0),
        failed_completed_worker_cpu_seconds=sum(row["cpu_seconds"] for row in jobs if row["exit_code"] != 0),
        missing_identities=[dict(zip(IDENTITY, key)) for key in sorted(expected-observed)],
        launcher_total=total, launcher_total_is_crosscheck_only=True,
        elapsed_wall_seconds=number(total["wall_seconds"], "stage wall time") if total else None,
        job_wall_seconds_are_not_summed_as_elapsed=True,
        maximum_individual_worker_rss_kib=max((row["maximum_rss_kib"] for row in jobs), default=None),
        rss_scope="Maximum of individual process peaks, not concurrent aggregate peak memory",
        jobs=jobs)


def abandoned_ledger(inputs):
    """Only this canonical attempt is charged; root duplicate copies are ignored."""
    attempt = inputs.root / "formal_02/attempts/train_01_oom"
    directory = attempt / "receipts"
    require(directory.is_dir(), "Missing canonical abandoned-attempt receipts")
    jobs = completed_jobs(inputs, directory)
    completed = {tuple(row[name] for name in IDENTITY): row for row in jobs}
    path = attempt / "INTERRUPTION.json"
    interrupted = inputs.read(path)
    require(type(interrupted.get("launcher_pid")) is int and isinstance(interrupted.get("workers"), list),
            "Invalid interruption launcher/workers metadata")
    active, overlaps, pids, keys = [], [], set(), set()
    for worker in interrupted["workers"]:
        pid = worker.get("pid")
        require(type(pid) is int and pid > 0 and pid != interrupted["launcher_pid"] and pid not in pids,
                "Duplicate/invalid interruption worker PID")
        pids.add(pid)
        key = command_identity(worker.get("args"))
        require(key not in keys, "Multiple interrupted workers claim one scheduled job")
        keys.add(key)
        user = number(worker.get("user_cpu_seconds"), "/proc user CPU")
        system = number(worker.get("system_cpu_seconds"), "/proc system CPU")
        record = dict(**dict(zip(IDENTITY, key)), pid=pid, source=inputs.relative(path),
            cpu_user_seconds=user, cpu_system_seconds=system, cpu_seconds=user+system,
            measurement_status="lower_bound_at_interrupt_snapshot",
            observed_at_utc=interrupted.get("utc"), outcome="interrupted_before_observed_wait4_completion")
        if key in completed:
            require(record["cpu_seconds"] <= completed[key]["cpu_seconds"] + .02,
                    "Interrupted CPU exceeds the allegedly complete receipt for the same job")
            overlaps.append({**record, "charged_cpu_seconds": 0,
                "reason": "Same scheduled job has a complete wait4 receipt; snapshot is nested, not additive"})
        else:
            active.append(record)
    completed_cpu = sum(row["cpu_seconds"] for row in jobs)
    partial_cpu = sum(row["cpu_seconds"] for row in active)
    return dict(run="formal_02", attempt="train_01_oom", stage="train", status="abandoned_lower_bound",
        source_directory=inputs.relative(attempt), interruption_utc=interrupted.get("utc"),
        interruption_reason=interrupted.get("reason"), launcher_pid=interrupted["launcher_pid"],
        completed_processes=jobs, interrupted_process_snapshots=active,
        snapshots_excluded_as_already_covered=overlaps,
        complete_wait4_cpu_seconds=completed_cpu,
        failed_complete_wait4_cpu_seconds=sum(row["cpu_seconds"] for row in jobs if row["exit_code"] != 0),
        interrupted_cpu_lower_bound_seconds=partial_cpu,
        abandoned_attempt_cpu_lower_bound_seconds=completed_cpu+partial_cpu,
        charged_even_though_abandoned=True,
        ignored_duplicate_locations=["formal_02/receipts", "formal_02/fits", "formal_02/INTERRUPTION.json"],
        unobserved_tail="CPU after each /proc snapshot until termination/reaping is not observed; no estimate or zero is substituted",
        launcher_parent_cpu="not_measured")


def nested_timers(inputs, run):
    """Separate descriptive timer levels; none enters the top-level CPU sum."""
    collections = {}

    def append(category, enclosing_stage, path, cpu, wall, label=None):
        group = collections.setdefault(category, dict(enclosing_stage=enclosing_stage, records=[]))
        group["records"].append(dict(source=inputs.relative(path), label=label,
            cpu_seconds=number(cpu, category + " CPU"), wall_seconds=number(wall, category + " wall")))

    for path in sorted(run.glob("fits/*/SUMMARY.json")):
        row = inputs.read(path)
        append("training_group_bodies", "train", path, row["training_cpu_seconds"], row["training_wall_seconds"])
    for path in sorted(run.glob("evaluation/*/COST.json")):
        row = inputs.read(path)
        append("evaluation_group_bodies", "evaluate", path, row["total_cpu_seconds"], row["total_wall_seconds"])
        for index, condition in enumerate(row["records"]):
            for measurement in condition["measurements"]:
                append("evaluation_first_1_or_16_actor_measurements", "evaluate", path,
                    measurement["cpu_seconds"], measurement["wall_seconds"],
                    dict(condition=index, batch_size=measurement["batch_size"], phase=measurement["phase"]))
    for path in sorted(run.glob("recovery/fits/*/INDEX.json")):
        row = inputs.read(path)
        append("recovery_fit_group_bodies", "recovery_fit", path, row["cpu_seconds"], row["wall_seconds"])
    for path in sorted(run.glob("recovery/confirmation/*/PROCESS.json")):
        row = inputs.read(path)
        append("recovery_confirmation_group_bodies", "recovery_confirm", path, row["cpu_seconds"], row["wall_seconds"])
    for path in sorted(run.glob("recovery/confirmation/*/ACTUAL_EXECUTION.json")):
        for index, row in enumerate(inputs.read(path)["records"]):
            append("recovery_selected_actor_measurements", "recovery_confirm", path,
                   row["cpu_seconds"], row["wall_seconds"], index)
    for path in sorted(run.glob("full_online_confirmation/groups/*/INDEX.json")):
        row = inputs.read(path)
        append("full_online_group_bodies", "full_online_confirmation", path,
               row["group_cpu_seconds"], row["group_wall_seconds"])
        measured = sum(number(r["execution"]["actor_cpu_seconds"], "actual actor CPU") for r in row["records"])
        require(close(measured, row["nested_actor_cpu_seconds"]), "Online group actor sum disagrees with conditions")
        for index, condition in enumerate(row["records"]):
            actor = condition["execution"]
            append("full_online_full_cohort_actor_measurements", "full_online_confirmation", path,
                   actor["actor_cpu_seconds"], actor["actor_wall_seconds"], index)
    for collection in collections.values():
        collection.update(measurements=len(collection["records"]),
            sum_cpu_seconds_within_this_level=sum(row["cpu_seconds"] for row in collection["records"]),
            included_in_enclosing_worker_cpu=True, added_to_total=False,
            wall_times_are_separate_observations=True)
    return collections


def build(results, allow_incomplete=False):
    inputs = Inputs(results)
    run = inputs.root / "formal_03"
    if not allow_incomplete:
        missing = [stage for stage in STAGES if not (run / "receipts" / stage / "TOTAL.json").is_file()]
        require(not missing, "Formal stages are not all finished; no real ledger read. Missing TOTAL: " + ", ".join(missing))
    protocol = inputs.read(run / "PROTOCOL.json")
    stages = [stage_ledger(inputs, run, stage, protocol) for stage in STAGES]
    require(allow_incomplete or all(row["coverage"] == "complete" for row in stages),
            "Recorded formal worker matrix is incomplete")
    abandoned = abandoned_ledger(inputs)
    early_receipts = list((inputs.root / "formal_01/receipts").glob("**/*.json"))
    require(not early_receipts, "formal_01 unexpectedly has runtime receipts; it cannot be silently omitted")
    nested = nested_timers(inputs, run)
    successful = sum(row["successful_completed_worker_cpu_seconds"] for row in stages)
    failed = sum(row["failed_completed_worker_cpu_seconds"] for row in stages)
    waste = abandoned["abandoned_attempt_cpu_lower_bound_seconds"]
    complete = all(row["coverage"] == "complete" for row in stages)
    return dict(schema="hcsn.r15.publication.runtime-ledger.v1",
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        result_root=str(inputs.root), formal_run="formal_03", formal_stage_receipts_complete=complete,
        scope="Recorded formal worker process CPU plus canonical abandoned-attempt CPU lower bound. This is not a complete project-lifecycle or physical-energy total.",
        totals=dict(status="lower_bound", unit="process_CPU_seconds",
            formal_03_successful_completed_process_cpu_seconds=successful,
            formal_03_failed_completed_process_cpu_seconds=failed,
            formal_03_observed_completed_process_cpu_seconds=successful+failed,
            abandoned_attempt_complete_wait4_cpu_seconds=abandoned["complete_wait4_cpu_seconds"],
            abandoned_attempt_interrupted_process_cpu_lower_bound_seconds=abandoned["interrupted_cpu_lower_bound_seconds"],
            abandoned_attempt_cpu_lower_bound_seconds=waste,
            successful_failed_and_abandoned_cpu_lower_bound_seconds=successful+failed+waste,
            hours_lower_bound=(successful+failed+waste)/3600,
            arithmetic="Sum each unique completed worker once, plus disjoint interrupted-process snapshots from the canonical abandoned attempt. Never add TOTAL replicas or nested timers."),
        formal_03_stages=stages, abandoned_attempts=[abandoned], nested_timers_not_additive=nested,
        formal_01=dict(formal_training_status="not_started", counted_training_worker_cpu_seconds=0,
                       runtime_receipts_found=0, preparation_cpu="not_measured"),
        excluded_from_addition=["formal_02 root duplicate receipts/fits/INTERRUPTION", "stage TOTAL aggregates already represented by individual jobs",
            "group/body/actor/chunk timers nested inside worker lifetimes", "sum of concurrent job wall times", "sum of individual peak RSS as global peak memory"],
        unmeasured=dict(interrupted_worker_post_snapshot_tail_cpu="not_measured",
            launcher_parent_cpu="not_measured", unreceipted_analysis_publication_and_development_cpu="not_measured",
            gpu="not_measured", physical_energy_joules="not_measured", provider_bill="not_measured"),
        cost_claim="Synthetic read/time tariffs are not provider bills or energy. Lower-bound CPU cannot close a full-cost or energy-efficiency claim.",
        input_files=[inputs.sources[name] for name in sorted(inputs.sources)])


def selfcheck(output):
    """Artificial files prove no root-copy, aggregate, or nested-timer double count."""
    root = Path(tempfile.mkdtemp(prefix="hcsn-runtime-ledger-fixture-"))
    run = root / "formal_03"
    protocol = dict(tasks=["fixture"], seeds=[1], modes=["light", "value"])
    write(run / "PROTOCOL.json", protocol)
    for stage in STAGES:
        modes = ("value",) if stage.startswith("recovery_") else ("light", "value")
        failures = 0
        for mode in modes:
            failed = stage == "full_online_confirmation" and mode == "value"
            failures += failed
            name = "fixture_s1_" + mode
            write(run / "receipts" / stage / (name + ".json"),
                  dict(name=name, task="fixture", seed=1, train_mode=mode, exit_code=1 if failed else 0,
                       cpu_user_seconds=8, cpu_system_seconds=2, wall_seconds=15, maximum_rss_kib=100))
        write(run / "receipts" / stage / "TOTAL.json", dict(stage=stage, jobs=len(modes),
              failed=failures, process_cpu_seconds=10*len(modes), wall_seconds=18, workers=2))
    write(run / "fits/fixture_s1_light/SUMMARY.json", dict(training_cpu_seconds=2, training_wall_seconds=3))
    write(run / "evaluation/fixture_s1_light/COST.json", dict(total_cpu_seconds=2, total_wall_seconds=3,
          records=[dict(measurements=[dict(cpu_seconds=.5, wall_seconds=1, batch_size=1, phase="cold")])]))
    write(run / "recovery/fits/fixture_s1/INDEX.json", dict(cpu_seconds=2, wall_seconds=3))
    write(run / "recovery/confirmation/fixture_s1/PROCESS.json", dict(cpu_seconds=3, wall_seconds=4))
    write(run / "recovery/confirmation/fixture_s1/ACTUAL_EXECUTION.json", dict(records=[dict(cpu_seconds=1, wall_seconds=2)]))
    write(run / "full_online_confirmation/groups/fixture_s1_light/INDEX.json", dict(group_cpu_seconds=4,
          group_wall_seconds=6, nested_actor_cpu_seconds=1.5,
          records=[dict(execution=dict(actor_cpu_seconds=1.5, actor_wall_seconds=3))]))
    attempt = root / "formal_02/attempts/train_01_oom"
    completed = dict(name="fixture_s1_value", task="fixture", seed=1, train_mode="value", exit_code=-9,
                     cpu_user_seconds=4, cpu_system_seconds=1, wall_seconds=9, maximum_rss_kib=100)
    write(attempt / "receipts/fixture_s1_value.json", completed)
    workers = []
    for pid, seed, mode, cpu in ((10, 1, "light", 3), (11, 2, "light", 4), (12, 1, "value", 2)):
        workers.append(dict(pid=pid, args=["python", "campaign.py", "--task", "fixture", "--seed", str(seed), "--mode", mode],
                            status=["fixture"], user_cpu_seconds=cpu, system_cpu_seconds=0))
    write(attempt / "INTERRUPTION.json", dict(utc="fixture-time", reason="artificial OOM", launcher_pid=9,
                                             workers=workers, cgroup={}, cpu_receipt_note="fixture"))
    # These duplicate roots are intentionally impossible to parse as real receipts.
    write(root / "formal_02/receipts/duplicate.json", dict(must_never_be_read=True, cpu_seconds=999999))
    write(root / "formal_02/INTERRUPTION.json", dict(must_never_be_read=True, cpu_seconds=999999))
    ledger = build(root)
    totals = ledger["totals"]
    checks = dict(
        successful_and_failed_separate=totals["formal_03_successful_completed_process_cpu_seconds"] == 70 and totals["formal_03_failed_completed_process_cpu_seconds"] == 10,
        completed_kill_cpu_charged=totals["abandoned_attempt_complete_wait4_cpu_seconds"] == 5,
        live_cpu_only_lower_bound=totals["abandoned_attempt_interrupted_process_cpu_lower_bound_seconds"] == 7,
        completed_snapshot_not_double_counted=len(ledger["abandoned_attempts"][0]["snapshots_excluded_as_already_covered"]) == 1,
        final_total_includes_waste_and_no_nested_or_aggregate_duplicates=totals["successful_failed_and_abandoned_cpu_lower_bound_seconds"] == 92,
        root_duplicates_never_read=not any(row["path"] in ("formal_02/receipts/duplicate.json", "formal_02/INTERRUPTION.json") for row in ledger["input_files"]),
        all_nested_levels_separate=len(ledger["nested_timers_not_additive"]) == 8 and all(not row["added_to_total"] for row in ledger["nested_timers_not_additive"].values()),
        unmeasured_costs_not_invented=all(ledger["unmeasured"][name] == "not_measured" for name in ("gpu", "physical_energy_joules", "provider_bill")))
    write(root / "ARTIFICIAL_LEDGER.json", ledger)
    # A duplicate receipt must be rejected, not counted as a second process.
    original = run / "receipts/train/fixture_s1_light.json"
    duplicate = original.with_name("duplicate.json")
    shutil.copyfile(original, duplicate)
    try:
        build(root)
    except LedgerError:
        checks["duplicate_process_identity_rejected"] = True
    else:
        checks["duplicate_process_identity_rejected"] = False
    duplicate.unlink()
    total_path = run / "receipts/train/TOTAL.json"
    total = json.loads(total_path.read_text()); total["process_cpu_seconds"] += 1
    total_path.write_text(json.dumps(total))
    try:
        build(root)
    except LedgerError:
        checks["aggregate_mismatch_rejected"] = True
    else:
        checks["aggregate_mismatch_rejected"] = False
    total_path.unlink()
    try:
        build(root)
    except LedgerError:
        checks["default_refuses_unfinished_formal_run"] = True
    else:
        checks["default_refuses_unfinished_formal_run"] = False
    partial = build(root, allow_incomplete=True)
    checks["explicit_partial_stays_lower_bound"] = not partial["formal_stage_receipts_complete"] and partial["totals"]["status"] == "lower_bound"
    result = dict(schema="hcsn.r15.runtime-ledger.fixture.v1", fixture_root=str(root),
                  source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                  real_runtime_records_read=False, confirmation_data_accessed=False,
                  checks=checks, passed=all(checks.values()), expected_total_cpu_lower_bound_seconds=92)
    write(output, result)
    require(result["passed"], "Runtime ledger artificial fixture failed")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("build", "selfcheck"))
    parser.add_argument("--results", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true", help="Explicit partial ledger, retaining missing stages and lower-bound status")
    args = parser.parse_args()
    if args.action == "selfcheck":
        result = selfcheck(args.output)
        print(json.dumps(dict(passed=result["passed"], checks=len(result["checks"]), real_runtime_records_read=False)))
    else:
        require(args.results is not None, "build requires --results")
        result = build(args.results, args.allow_incomplete)
        write(args.output, result)
        print(json.dumps(dict(output=str(args.output), totals=result["totals"], formal_stage_receipts_complete=result["formal_stage_receipts_complete"])))


if __name__ == "__main__":
    main()
