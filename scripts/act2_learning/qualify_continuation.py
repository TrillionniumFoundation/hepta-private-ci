"""Real subprocess kill/recovery evidence for the controlled ACT2 GRU fixture."""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

import run
from continuation import Continuation, canonical, decode, digest
from sqlite_destination import BudgetExhausted


def worker(args):
    task = json.loads(args.task.read_text())
    continuation = (
        Continuation.restore if args.phase == "resume" else Continuation.start
    )(task, args.model, args.directory)
    identity = {
        "pid": os.getpid(),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "initial_sequence": continuation.state["sequence"],
        "initial_hidden": continuation.state["hidden"],
    }
    (args.directory / (args.phase + "-identity.json")).write_bytes(canonical(identity))
    started = time.perf_counter_ns()
    try:
        while continuation.step(
            crash_phase=args.crash_point if args.phase == "crash" else None
        ):
            pass
        status = "terminal"
    except BudgetExhausted:
        status = "budget_exhausted"
    report = continuation.report()
    report.update(status=status, worker_wall_ns=time.perf_counter_ns() - started)
    print(json.dumps(report))
    continuation.destination.db.close()


def execute(model, task_file, directory, folder, phase, crash_point=None):
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--phase",
        phase,
        "--directory",
        str(directory),
        "--task",
        str(task_file),
        "--model",
        str(model),
    ]
    if crash_point:
        command.extend(["--crash-point", crash_point])
    started = time.perf_counter_ns()
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=30, check=False
    )
    (folder / (phase + ".stdout")).write_text(completed.stdout)
    (folder / (phase + ".stderr")).write_text(completed.stderr)
    receipt = {
        "command": command,
        "exit_code": completed.returncode,
        "outer_wall_ns": time.perf_counter_ns() - started,
    }
    (folder / (phase + "-receipt.json")).write_bytes(canonical(receipt))
    expected = -9 if phase == "crash" else 0
    if completed.returncode != expected:
        raise AssertionError((phase, completed.returncode, completed.stderr))
    identity = json.loads((directory / (phase + "-identity.json")).read_text())
    return receipt, identity, None if phase == "crash" else json.loads(completed.stdout)


def qualify(model_paths, output, include_long_task=False):
    if os.name != "posix":
        raise RuntimeError("SIGKILL qualification is POSIX-only")
    tasks = [
        next(
            t
            for t in run.tasks("confirm")
            if t["fault"] == fault and t["composition"] == 3
        )
        for fault in ("normal", "lost_reply", "prestaged")
    ]
    if include_long_task:
        tasks.append(
            next(
                t
                for t in run.tasks("confirm")
                if t["fault"] == "normal" and t["composition"] == 4
            )
        )
    crash_points = ("before_apply", "after_apply")
    frozen = {
        "reused_fixture_tasks": tasks,
        "new_independent_tasks": 0,
        "model_sha256": {str(path): digest(path.read_bytes()) for path in model_paths},
        "source_sha256": {
            path.name: digest(path.read_bytes())
            for path in Path(__file__).parent.glob("*.py")
        },
        "crash_points": crash_points,
        "expected_recovery_pairs": len(model_paths) * len(tasks) * len(crash_points),
        "criterion": "Exact reference state/effect equivalence, no false success or duplicates; original failed policies remain failed.",
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "FROZEN_MANIFEST.json").write_text(json.dumps(frozen, indent=2) + "\n")
    cases, references = [], []
    for model in model_paths:
        for task in tasks:
            folder = output / model.stem / f"{task['fault']}-keys-{task['composition']}"
            folder.mkdir(parents=True)
            task_file = folder / "task.json"
            task_file.write_bytes(canonical(task))
            try:
                ref_receipt, ref_identity, reference = execute(
                    model, task_file, folder / "reference", folder, "reference"
                )
                references.append(
                    {
                        "model": model.name,
                        "task_id": task["id"],
                        "receipt": ref_receipt,
                        "identity": ref_identity,
                        "report": reference,
                    }
                )
                reference_error = None
            except Exception as error:
                reference_error = repr(error)
            for crash_point in crash_points:
                case_folder = folder / crash_point
                case_folder.mkdir()
                case = {
                    "model": model.name,
                    "task_id": task["id"],
                    "fault": task["fault"],
                    "crash_point": crash_point,
                    "status": "FAIL",
                }
                cases.append(case)
                try:
                    if reference_error:
                        raise AssertionError(reference_error)
                    directory = case_folder / "interrupted"
                    receipt, killed_identity, _ = execute(
                        model, task_file, directory, case_folder, "crash", crash_point
                    )
                    with closing(
                        sqlite3.connect(
                            f"file:{directory / 'destination.db'}?mode=ro", uri=True
                        )
                    ) as owner:
                        raw = owner.execute(
                            "SELECT snapshot FROM act3_owner"
                        ).fetchone()[0]
                        effects = list(
                            owner.execute("SELECT operation,payload FROM applied")
                        )
                    pending = json.loads(raw)["state"]
                    decode(raw, pending["binding"])
                    expected_effects = (
                        []
                        if crash_point == "before_apply"
                        else [
                            (
                                pending["pending"]["operation"],
                                pending["pending"]["payload"],
                            )
                        ]
                    )
                    if (
                        pending["phase"] != "pending"
                        or pending["pending"]["action"] != "ensure"
                        or effects != expected_effects
                    ):
                        raise AssertionError(
                            "kill did not retain exact pending/effect boundary"
                        )
                    (case_folder / "interrupted-checkpoint.json").write_bytes(raw)
                    receipt.update(
                        pending_snapshot_sha256=digest(raw), original_effects=effects
                    )
                    resume_receipt, restored_identity, recovered = execute(
                        model, task_file, directory, case_folder, "resume"
                    )
                    equal = all(
                        reference[field] == recovered[field]
                        for field in (
                            "sequence",
                            "hidden",
                            "decisions",
                            "claimed",
                            "truth",
                            "effects",
                            "status",
                        )
                    )
                    no_double_advance = (
                        restored_identity["initial_hidden"] == pending["hidden"]
                        and restored_identity["initial_sequence"] == pending["sequence"]
                    )
                    identities = {
                        "reference": ref_identity,
                        "crash": killed_identity,
                        "resume": restored_identity,
                    }
                    distinct = len({value["pid"] for value in identities.values()}) == 3
                    same_uid = len({value["uid"] for value in identities.values()}) == 1
                    no_false_success = (
                        not recovered["claimed"] or recovered["truth"]["complete"]
                    )
                    passed = (
                        equal
                        and no_double_advance
                        and distinct
                        and no_false_success
                        and recovered["truth"]["duplicate_effects"] == 0
                    )
                    case.update(
                        status="PASS" if passed else "FAIL",
                        receipts={"crash": receipt, "resume": resume_receipt},
                        identities=identities,
                        reports={"reference": reference, "resume": recovered},
                        matches_uninterrupted=equal,
                        no_double_hidden_advance=no_double_advance,
                        distinct_processes=distinct,
                        same_uid=same_uid,
                        original_reference_complete=reference["truth"]["complete"],
                        no_false_success=no_false_success,
                    )
                except Exception as error:
                    case["error"] = repr(error)
                (case_folder / "CASE.json").write_text(
                    json.dumps(case, indent=2) + "\n"
                )
    sources = {
        path.name: digest(path.read_bytes())
        for path in Path(__file__).parent.glob("*.py")
    }
    source_stable = sources == frozen["source_sha256"]
    models_stable = {
        str(path): digest(path.read_bytes()) for path in model_paths
    } == frozen["model_sha256"]
    passed = (
        source_stable
        and models_stable
        and len(cases) == frozen["expected_recovery_pairs"]
        and all(case["status"] == "PASS" for case in cases)
    )
    result = {
        "status": "SCOPED_COLD_RECOVERY_PASS"
        if passed
        else "SCOPED_COLD_RECOVERY_FAIL",
        "reused_fixture_tasks": len(tasks),
        "new_independent_tasks": 0,
        "saved_models": len(model_paths),
        "planned_recovery_pairs": frozen["expected_recovery_pairs"],
        "recorded_recovery_cases": len(cases),
        "executed_recovery_pairs": sum("reports" in case for case in cases),
        "passed_recovery_pairs": sum(case["status"] == "PASS" for case in cases),
        "reference_model_task_runs": len(references),
        "original_reference_incomplete": sum(
            not item["report"]["truth"]["complete"] for item in references
        ),
        "cases": cases,
        "references": references,
        "source_sha256": sources,
        "source_stable": source_stable,
        "models_stable": models_stable,
        "scope": "same-UID controlled SQLite research; SIGKILL before effect and after commit; original saved GRU weights",
        "product_authority": False,
        "promotion": False,
        "full_operations_cost_qualified": False,
        "holds": [
            "independent trust domain",
            "product CellStateOwner/FinalUse integration",
            "concurrent owner",
            "host power loss",
            "cross-family learned benefit",
            "complete operation cost ledger",
        ],
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "status": result["status"],
                "pairs": len(cases),
                "passed": result["passed_recovery_pairs"],
                "original_reference_incomplete": result[
                    "original_reference_incomplete"
                ],
                "promotion": False,
            }
        )
    )
    return passed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    models = parser.add_mutually_exclusive_group(required=True)
    models.add_argument("--model", type=Path)
    models.add_argument(
        "--models",
        type=Path,
        help="Directory containing all eight archived GRU seeds 700..707",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--include-long-task",
        action="store_true",
        help="Also reuse original length-4 normal task to exercise seed707 regression",
    )
    parser.add_argument("--phase", choices=("reference", "crash", "resume"))
    parser.add_argument("--crash-point", choices=("before_apply", "after_apply"))
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--task", type=Path)
    arguments = parser.parse_args()
    if arguments.phase:
        worker(arguments)
    else:
        paths = (
            [arguments.model.resolve()]
            if arguments.model
            else [
                (arguments.models / f"B4_gru-seed-{seed}.npz").resolve()
                for seed in range(700, 708)
            ]
        )
        raise SystemExit(
            0
            if qualify(paths, arguments.output.resolve(), arguments.include_long_task)
            else 1
        )
