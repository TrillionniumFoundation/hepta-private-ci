"""Execute one frozen fit, selection, or selected evaluation per bounded job.

Each block is one task/training seed. The original 170-run campaign receives
zero completion credit. A claim is local to this study root; history import is
evidence recovery, never a global lease or permission to replay an attempt.
"""

import argparse
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import tarfile
import time

from .mechanism_contract import digest, file_sha, load_contract, read_json, select_group, utc_now, write_json


def claim_directory(path, payload):
    """mkdir is exclusive; an incomplete claim remains unknown, not unstarted."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()
    write_json(path / "started.json", payload)


def import_history(study, histories, identity):
    receipts = []
    for history in histories:
        history = Path(history).resolve()
        if history == study.resolve():
            raise ValueError("History must be a prior evidence copy, not the active study")
        if read_json(history / "study.json")["identity"] != identity:
            raise ValueError("History belongs to a different frozen study")
        copied = []
        for category in ("attempts", "evaluations", "blocks"):
            source = history / category
            if not source.exists():
                continue
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError("History cannot contain symlinks")
                relative = path.relative_to(history)
                destination = study / relative
                if path.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                elif path.is_file():
                    expected = file_sha(path)
                    if destination.exists():
                        if file_sha(destination) != expected:
                            raise ValueError("Conflicting immutable history: " + str(relative))
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        with destination.open("xb") as target, path.open("rb") as origin:
                            shutil.copyfileobj(origin, target)
                        if file_sha(destination) != expected:
                            raise ValueError("History copy changed")
                    copied.append(dict(path=str(relative), sha256=expected))
        receipt = dict(history_path=str(history), copied=copied, identity=identity,
                       scope="Cross-lease evidence recovery only; not distributed mutual exclusion")
        receipts.append(receipt)
        target = study / "history-imports" / (digest(receipt) + ".json")
        if not target.exists():
            write_json(target, receipt)
    return receipts


def read_attempt(study, fit, identity):
    path = study / "attempts" / fit["fit_id"]
    if not path.exists():
        return dict(status="UNSTARTED", identity=identity, fit=fit)
    terminal = path / "terminal.json"
    if not terminal.exists():
        return dict(status="UNKNOWN", identity=identity, fit=fit,
                    reason="Attempt claimed without terminal; replay prohibited")
    result = read_json(terminal)
    if result.get("identity") != identity or result.get("fit") != fit or result.get("phase") != "fit":
        raise ValueError("Attempt receipt identity mismatch: " + fit["fit_id"])
    if result["status"] == "COMPLETED":
        checkpoint = path / "checkpoint.pt"
        if not checkpoint.is_file() or file_sha(checkpoint) != result.get("checkpoint_sha256"):
            raise ValueError("Completed checkpoint missing or changed")
        completion = path / "process-completion.json"
        if not completion.exists():
            return dict(result, status="UNKNOWN", reason="Missing supervisor process completion")
        process = read_json(completion)
        if process["returncode"] != 0 or process["timed_out"]:
            return dict(result, status="UNKNOWN", reason="Worker terminal and process completion disagree")
    return result


def supervised_worker(job, timeout_seconds):
    output = Path(job["attempt_path"])
    write_json(output / "job.json", job)
    wall, usage = time.monotonic(), resource.getrusage(resource.RUSAGE_CHILDREN)
    env = os.environ.copy()
    env["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    timed_out = False
    with (output / "stdout.log").open("xb") as stdout, (output / "stderr.log").open("xb") as stderr:
        process = subprocess.Popen([sys.executable, "-B", "-m", "qualification.hcsn_regenerative.mechanism_worker",
                                    "--job", str(output / "job.json")],
                                   cwd=Path(__file__).resolve().parents[2], env=env, stdout=stdout, stderr=stderr,
                                   start_new_session=True)
        write_json(output / "worker-process.json", dict(pid=process.pid, started_at=utc_now(), timeout_seconds=timeout_seconds))
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = dict(at=utc_now(), returncode=process.returncode, timed_out=timed_out,
                   supervised_wall_seconds=time.monotonic() - wall,
                   child_user_cpu_seconds=after.ru_utime - usage.ru_utime,
                   child_system_cpu_seconds=after.ru_stime - usage.ru_stime,
                   timeout_seconds=timeout_seconds, maximum_termination_drain_seconds=10,
                   full_physical_energy_joules=None,
                   scope="Entire child process including import/setup. Worker CPU/wall are nested, not additional.")
    write_json(output / "process-completion.json", receipt)
    if not (output / "terminal.json").exists():
        attempted = completed = examples = 0
        evaluation_examples = {}
        journal = output / "journal.jsonl"
        if journal.exists():
            for line in journal.read_text().splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "optimizer_update_started":
                    attempted = max(attempted, event["update"])
                if event.get("event") == "optimizer_update_completed":
                    completed = max(completed, event["update"])
                    examples += event["examples"]
                if event.get("event") == "evaluation_batch_completed":
                    phase = event["phase"]
                    evaluation_examples[phase] = max(evaluation_examples.get(phase, 0), event["cumulative_examples"])
        write_json(output / "terminal.json", dict(schema="hcsn-mechanism-attempt-terminal-v1", identity=job["identity"],
            fit=job["fit"], phase=job["phase"], status="TIMEOUT" if timed_out else "UNKNOWN",
            reason="Worker ended without a terminal; no retry permitted", finished_at=utc_now(),
            optimizer_updates_attempted=attempted, optimizer_updates_completed=completed,
            training_examples_completed=examples, evaluation_examples_completed=evaluation_examples,
            counters_are_lower_bounds=True, worker_wall_seconds=None, worker_process_cpu_seconds=None,
            full_physical_energy_joules=None))
    terminal = read_json(output / "terminal.json")
    if terminal["status"] == "COMPLETED" and (process.returncode != 0 or timed_out):
        return dict(terminal, status="UNKNOWN", reason="Worker terminal and process completion disagree")
    return terminal


def summarize(study, roster, identity):
    counts = {name: 0 for name in ("UNSTARTED", "COMPLETED", "FAILED", "TIMEOUT", "UNKNOWN")}
    totals = dict(optimizer_updates_completed=0, training_examples_completed=0,
                  validation_examples_completed=0, test_examples_completed=0,
                  supervised_fit_wall_seconds=0., supervised_evaluation_wall_seconds=0.,
                  supervised_child_cpu_seconds=0., worker_nested_wall_seconds=0.)
    costs_missing = []
    for fit in roster:
        terminal = read_attempt(study, fit, identity)
        counts[terminal["status"]] += 1
        totals["optimizer_updates_completed"] += terminal.get("optimizer_updates_completed", 0)
        totals["training_examples_completed"] += terminal.get("training_examples_completed", 0)
        totals["validation_examples_completed"] += terminal.get("evaluation_examples_completed", {}).get("validation", 0)
    evaluations, completed_training_units = [], {}
    for category in ("attempts", "evaluations"):
        directory = study / category
        if not directory.exists():
            continue
        for attempt in sorted(p for p in directory.iterdir() if p.is_dir()):
            process_path, terminal_path = attempt / "process-completion.json", attempt / "terminal.json"
            if process_path.exists():
                process = read_json(process_path)
                key = "supervised_fit_wall_seconds" if category == "attempts" else "supervised_evaluation_wall_seconds"
                totals[key] += process["supervised_wall_seconds"]
                totals["supervised_child_cpu_seconds"] += process["child_user_cpu_seconds"] + process["child_system_cpu_seconds"]
            else:
                costs_missing.append(str(attempt.relative_to(study)))
            if terminal_path.exists():
                terminal = read_json(terminal_path)
                totals["worker_nested_wall_seconds"] += terminal.get("worker_wall_seconds") or 0.
                if category == "evaluations":
                    evaluations.append(dict(attempt=attempt.name, status=terminal["status"]))
                    totals["test_examples_completed"] += sum(count for phase, count in terminal.get("evaluation_examples_completed", {}).items() if phase.startswith("test-"))
                    if terminal["status"] == "COMPLETED" and process_path.exists() and read_json(process_path)["returncode"] == 0:
                        fit = terminal["fit"]
                        key = fit["task"] + "/" + fit["arm"]
                        completed_training_units.setdefault(key, []).append(fit["training_seed"])
    complete_test_attempts = sum(len(values) for values in completed_training_units.values())
    return dict(schema="hcsn-mechanism-study-progress-v1", at=utc_now(), identity=identity,
                registered_fit_count=len(roster), counts=counts, totals=totals, evaluations=evaluations,
                attempts_with_missing_complete_process_cost=costs_missing,
                all_registered_fits_completed=counts["COMPLETED"] == len(roster),
                selected_test_attempts_completed=complete_test_attempts,
                selected_test_attempts_registered=len(roster) // 2,
                entire_training_and_evaluation_matrix_completed=counts["COMPLETED"] == len(roster) and complete_test_attempts == len(roster) // 2,
                completed_training_seed_units_by_task_arm=completed_training_units,
                cost_sum_scope="Exclusive child-process fit/evaluation costs; worker nested wall is diagnostic and must not be added",
                preparation_cost_source="bundle metadata builder totals, counted once per bundle, not once per arm/block",
                full_physical_energy_joules=None, deployment_cost_gate="HOLD", original_campaign_completion_credit=0,
                independent_training_seeds_per_task_arm=4, episode_seeds_per_selected_fit=2,
                benefit_admission="EXPLORATORY_ONLY", retention_gate="BLOCKED_NO_EXTERNAL_RETENTION_TASK")


def ensure_group(study, group, identity, device):
    block = study / "blocks" / group[0]["group_id"]
    if not block.exists():
        claim_directory(block, dict(at=utc_now(), identity=identity, fits=group, first_device=device,
            uniqueness_scope="Statistical group only; one external owner submits sequential bounded jobs"))
    else:
        claim = read_json(block / "started.json")
        if claim["identity"] != identity or claim["fits"] != group:
            raise ValueError("Existing statistical block identity differs")
    return block


def export_operation(study, label, paths, receipt):
    """Each bounded job exports its full new attempt and immutable group records."""
    exports = study / "exports"
    exports.mkdir(exist_ok=True)
    archive, receipt_path = exports / (label + ".tar.gz"), exports / (label + ".json")
    if archive.exists() or receipt_path.exists():
        raise FileExistsError("Operation already exported; do not replay or replace evidence")
    started, cpu = time.monotonic(), time.process_time()
    with archive.open("xb") as stream, tarfile.open(fileobj=stream, mode="w:gz") as tar:
        tar.add(study / "study.json", arcname="study.json")
        for path in paths:
            if path.exists():
                tar.add(path, arcname=str(path.relative_to(study)))
    result = dict(receipt, archive=dict(path=str(archive), sha256=file_sha(archive), bytes=archive.stat().st_size),
                  export_wall_seconds=time.monotonic() - started, export_process_cpu_seconds=time.process_time() - cpu,
                  export_scope="Nested inside native cloud job. Merge all prior operation exports for cross-lease recovery.")
    write_json(receipt_path, result)
    return result


def execute_one_fit(study, plan, bundle, plan_path, fit, group, roster, identity, device):
    block = ensure_group(study, group, identity, device)
    if (block / "selection-lock.json").exists():
        raise ValueError("Training cannot start after the group selection lock")
    previous = read_attempt(study, fit, identity)
    if previous["status"] != "UNSTARTED":
        raise ValueError("Fit already claimed (" + previous["status"] + "); no replay permitted")
    started, cpu = time.monotonic(), time.process_time()
    attempt = study / "attempts" / fit["fit_id"]
    claim_directory(attempt, dict(at=utc_now(), identity=identity, fit=fit, block=block.name))
    job = dict(bundle=str(bundle), plan=str(plan_path), attempt_path=str(attempt), identity=identity,
               fit=fit, phase="fit", device=device)
    terminal = supervised_worker(job, plan["max_fit_wall_seconds"])
    event = dict(at=utc_now(), identity=identity, fit=fit, status=terminal["status"],
                 supervisor_wall_seconds=time.monotonic() - started,
                 supervisor_own_cpu_seconds=time.process_time() - cpu,
                 cost_scope="Supervisor wall includes child; own CPU excludes child. Native outer job cost is separate scope.",
                 formal_fits_newly_started=1, full_physical_energy_joules=None)
    write_json(block / "fit-events" / (fit["fit_id"] + ".json"), event)
    event["study_progress"] = summarize(study, roster, identity)
    return export_operation(study, fit["fit_id"], [attempt, block], event)


def select_block(study, plan, group, roster, identity, device):
    block = ensure_group(study, group, identity, device)
    if (block / "selection-lock.json").exists():
        raise ValueError("Selection is already locked; do not select again")
    terminals = {fit["fit_id"]: read_attempt(study, fit, identity) for fit in group}
    if any(value["status"] == "UNSTARTED" for value in terminals.values()):
        raise ValueError("All twenty registered fits require terminal or explicit unknown history before selection")
    started, cpu = time.monotonic(), time.process_time()
    lock = select_group(plan, group, terminals, identity)
    lock.update(created_at=utc_now(), fit_terminal_file_sha256={fit["fit_id"]: file_sha(study / "attempts" / fit["fit_id"] / "terminal.json")
                for fit in group if (study / "attempts" / fit["fit_id"] / "terminal.json").exists()})
    lock["fit_process_completion_file_sha256"] = {fit["fit_id"]: file_sha(study / "attempts" / fit["fit_id"] / "process-completion.json")
                for fit in group if (study / "attempts" / fit["fit_id"] / "process-completion.json").exists()}
    write_json(block / "selection-lock.json", lock)
    receipt = dict(at=utc_now(), identity=identity, group_id=block.name, phase="selection",
                   selection_lock_sha256=file_sha(block / "selection-lock.json"),
                   selected_fit_ids=[value["fit_id"] for value in lock["selected"].values()],
                   all_registered_arms_selected=lock["all_registered_arms_selected"],
                   strongest_full_registered_set_eligible=lock["strongest_full_registered_set_eligible"],
                   selection_wall_seconds=time.monotonic() - started, selection_process_cpu_seconds=time.process_time() - cpu,
                   full_physical_energy_joules=None, formal_fits_newly_started=0)
    write_json(block / "selection-receipt.json", receipt)
    finalize_block(study, plan, group, roster, identity)
    paths = [block]
    for fit in group:
        attempt = study / "attempts" / fit["fit_id"]
        paths += [attempt / name for name in ("started.json", "terminal.json", "process-completion.json")]
    return export_operation(study, "select-" + block.name, paths, receipt)


def validate_selection_lock(study, plan, group, identity):
    """Recompute choices from immutable training evidence, never from test scores."""
    block = study / "blocks" / group[0]["group_id"]
    lock_path, receipt_path = block / "selection-lock.json", block / "selection-receipt.json"
    if not lock_path.exists() or not receipt_path.exists():
        raise ValueError("Test requires the complete group selection lock first")
    lock, receipt, lock_sha = read_json(lock_path), read_json(receipt_path), file_sha(lock_path)
    if (receipt.get("identity") != identity or receipt.get("group_id") != group[0]["group_id"]
            or receipt.get("selection_lock_sha256") != lock_sha):
        raise ValueError("Selection lock differs from its original receipt SHA or identity")
    terminals = {fit["fit_id"]: read_attempt(study, fit, identity) for fit in group}
    if any(value["status"] == "UNSTARTED" for value in terminals.values()):
        raise ValueError("Selection evidence omits registered fits")
    for field, filename in (("fit_terminal_file_sha256", "terminal.json"),
                            ("fit_process_completion_file_sha256", "process-completion.json")):
        actual = {fit["fit_id"]: file_sha(study / "attempts" / fit["fit_id"] / filename)
                  for fit in group if (study / "attempts" / fit["fit_id"] / filename).exists()}
        if lock.get(field) != actual:
            raise ValueError("Training evidence changed after selection: " + filename)
    expected = select_group(plan, group, terminals, identity)
    for key, value in expected.items():
        if lock.get(key) != value:
            raise ValueError("Selection field is not derived from the frozen validation evidence: " + key)
    if (receipt.get("selected_fit_ids") != [value["fit_id"] for value in expected["selected"].values()]
            or receipt.get("all_registered_arms_selected") != expected["all_registered_arms_selected"]
            or receipt.get("strongest_full_registered_set_eligible") != expected["strongest_full_registered_set_eligible"]):
        raise ValueError("Selection receipt choices differ from validation evidence")
    return lock, lock_sha


def finalize_block(study, plan, group, roster, identity):
    block = study / "blocks" / group[0]["group_id"]
    lock_path = block / "selection-lock.json"
    if not lock_path.exists() or (block / "terminal.json").exists():
        return
    lock, _ = validate_selection_lock(study, plan, group, identity)
    tests = {}
    for arm, selected in lock["selected"].items():
        attempt = study / "evaluations" / selected["fit_id"]
        if not attempt.exists():
            return
        if not (attempt / "terminal.json").exists():
            tests[arm] = dict(status="UNKNOWN", reason="Claimed evaluation without terminal; no replay")
        else:
            terminal = read_json(attempt / "terminal.json")
            if terminal["identity"] != identity or terminal["fit"]["fit_id"] != selected["fit_id"]:
                raise ValueError("Evaluation identity differs from selection")
            completion = attempt / "process-completion.json"
            if terminal["status"] == "COMPLETED" and (not completion.exists() or read_json(completion)["returncode"] != 0 or read_json(completion)["timed_out"]):
                terminal = dict(terminal, status="UNKNOWN", reason="Evaluation terminal and native process completion disagree")
            tests[arm] = terminal
    terminals = {fit["fit_id"]: read_attempt(study, fit, identity) for fit in group}
    result = dict(schema="hcsn-mechanism-block-terminal-v1", at=utc_now(), identity=identity, group_id=block.name,
                  training_terminal_status={key: value["status"] for key, value in terminals.items()},
                  selection_lock_sha256=file_sha(lock_path), selected_test_status={key: value["status"] for key, value in tests.items()},
                  all_registered_arms_selected=lock["all_registered_arms_selected"],
                  strongest_full_registered_set_eligible=lock["strongest_full_registered_set_eligible"],
                  complete=len(tests) == len(plan["arms"]) and all(row["status"] == "COMPLETED" for row in tests.values()),
                  full_physical_energy_joules=None, original_campaign_completion_credit=0,
                  group_scope="One statistical training-seed block across multiple bounded native jobs")
    write_json(block / "terminal.json", result)
    write_json(block / "study-progress.json", summarize(study, roster, identity))


def execute_selected_fit(study, plan, bundle, plan_path, fit, group, roster, identity, device):
    block = ensure_group(study, group, identity, device)
    lock_path = block / "selection-lock.json"
    lock, lock_sha = validate_selection_lock(study, plan, group, identity)
    selected = lock["selected"].get(fit["arm"])
    if lock["identity"] != identity or not selected or selected["fit_id"] != fit["fit_id"]:
        raise ValueError("Requested fit was not selected for test")
    evaluation = study / "evaluations" / fit["fit_id"]
    if evaluation.exists():
        raise ValueError("Evaluation already claimed; no replay permitted")
    started, cpu = time.monotonic(), time.process_time()
    claim_directory(evaluation, dict(at=utc_now(), identity=identity, fit=fit, selection_lock_sha256=lock_sha))
    job = dict(bundle=str(bundle), plan=str(plan_path), attempt_path=str(evaluation), identity=identity,
               fit=fit, phase="selected_test", device=device, selection_lock=str(lock_path),
               selection_lock_sha256=lock_sha, checkpoint_path=str(study / "attempts" / fit["fit_id"] / "checkpoint.pt"))
    terminal = supervised_worker(job, plan["max_fit_wall_seconds"])
    receipt = dict(at=utc_now(), identity=identity, fit=fit, status=terminal["status"], phase="selected_test",
                   selection_lock_sha256=lock_sha, supervisor_wall_seconds=time.monotonic() - started,
                   supervisor_own_cpu_seconds=time.process_time() - cpu,
                   cost_scope="Supervisor wall includes child; own CPU excludes child. Native outer job cost is separate scope.",
                   full_physical_energy_joules=None, formal_fits_newly_started=0)
    write_json(block / "test-events" / (fit["fit_id"] + ".json"), receipt)
    finalize_block(study, plan, group, roster, identity)
    receipt["study_progress"] = summarize(study, roster, identity)
    return export_operation(study, "test-" + fit["fit_id"], [evaluation, block], receipt)


def execute_group(study, plan, bundle, plan_path, group, roster, identity, device, continue_unstarted=False):
    """Compose the exact same bounded operations for local tests/long-lived owners.

    The cloud CLI deliberately executes only one of these operations per job.
    """
    block = ensure_group(study, group, identity, device)
    if (block / "terminal.json").exists() or ((block / "selection-lock.json").exists() and not continue_unstarted):
        raise ValueError("Block is already claimed or terminal")
    for fit in group:
        if read_attempt(study, fit, identity)["status"] == "UNSTARTED":
            execute_one_fit(study, plan, bundle, plan_path, fit, group, roster, identity, device)
        elif not continue_unstarted:
            raise ValueError("Existing attempt requires explicit continuation of unstarted items")
    if not (block / "selection-lock.json").exists():
        select_block(study, plan, group, roster, identity, device)
    lock = read_json(block / "selection-lock.json")
    for arm in plan["arms"]:
        if arm in lock["selected"]:
            fit = next(row for row in group if row["fit_id"] == lock["selected"][arm]["fit_id"])
            if not (study / "evaluations" / fit["fit_id"]).exists():
                execute_selected_fit(study, plan, bundle, plan_path, fit, group, roster, identity, device)
    finalize_block(study, plan, group, roster, identity)
    return read_json(block / "terminal.json")

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--fit-range", help="Stable half-open roster interval containing exactly one fit")
    action.add_argument("--fit-ids", help="Exactly one stable fit ID")
    action.add_argument("--select-group", help="Lock all ten arm choices after every fit in this twenty-fit group has ended")
    action.add_argument("--evaluate-fit", help="Evaluate one already selected checkpoint, after its group lock")
    parser.add_argument("--history", action="append", default=[], type=Path)
    args = parser.parse_args(argv)
    bundle, plan_path, study = args.bundle.resolve(), args.plan.resolve(), args.output.resolve()
    plan, _, _, roster, identity = load_contract(bundle, plan_path)
    chosen = []
    if args.fit_range:
        start, stop = map(int, args.fit_range.split(":"))
        if start < 0 or stop > len(roster) or stop != start + 1:
            raise ValueError("A Colab-bounded job starts exactly one fit, with the full 480-second budget")
        chosen = roster[start:stop]
    elif args.fit_ids:
        chosen = [fit for fit in roster if fit["fit_id"] == args.fit_ids]
        if len(chosen) != 1:
            raise ValueError("Exactly one known fit ID is required")
    elif args.evaluate_fit:
        chosen = [fit for fit in roster if fit["fit_id"] == args.evaluate_fit]
        if len(chosen) != 1:
            raise ValueError("Unknown selected fit ID")
    group_id = chosen[0]["group_id"] if chosen else args.select_group
    group = [fit for fit in roster if fit["group_id"] == group_id]
    if len(group) != 20:
        raise ValueError("Unknown twenty-fit statistical group")
    if study.exists():
        if not (study / "study.json").is_file() or read_json(study / "study.json")["identity"] != identity:
            raise ValueError("Existing output is not this frozen study")
    else:
        study.mkdir(parents=True)
        write_json(study / "study.json", dict(created_at=utc_now(), identity=identity, plan=plan, ordered_fit_roster=roster,
                                              owner_rule="One external owner, sequential bounded operations; no global multi-lease exclusion"))
    import_history(study, args.history, identity)
    if args.select_group:
        result = select_block(study, plan, group, roster, identity, args.device)
    elif args.evaluate_fit:
        result = execute_selected_fit(study, plan, bundle, plan_path, chosen[0], group, roster, identity, args.device)
    else:
        result = execute_one_fit(study, plan, bundle, plan_path, chosen[0], group, roster, identity, args.device)
    print(json.dumps(dict(identity=identity, operation=result), allow_nan=False))
    return 0 if result.get("status", "COMPLETED") == "COMPLETED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
