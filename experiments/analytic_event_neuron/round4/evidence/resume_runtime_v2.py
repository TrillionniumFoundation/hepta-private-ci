"""Serial operational recovery; preserve completed science and every old attempt."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from ..freeze import verify
from ..runtime_learning import SEEDS
from ..runtime_study import REGISTRATION
from .resume_runtime import dataset_identity, sha, write


def run(root):
    root = Path(root).resolve()
    frozen = verify(root)
    output = root / "runtime_recovery_v2"
    output.mkdir(exist_ok=True)
    if (output / "SCHEDULE.json").exists() or (root / "RUNTIME_RESULTS.json").exists():
        raise FileExistsError("Preserve this orchestration attempt before restarting; completed phases must never be overwritten")
    incidents = [root / name for name in ("RUNTIME_INTERRUPTION.json", "RUNTIME_SECOND_INTERRUPTION.json")]
    original = json.loads(incidents[0].read_text())
    json.loads(incidents[1].read_text())
    attempts = {a["seed"]: a for a in original["attempts"] if a["phase"] == "confirm"}
    if set(attempts) != set(SEEDS) - {1213}:
        raise ValueError("All four original interrupted cohorts must remain available")
    protected = {}
    previous_receipts = {}
    for seed, label in ((1213, "runtime_confirm_1213"), (1427, "runtime_confirm_1427_recovery1"),
                        (1823, "runtime_confirm_1823_recovery1")):
        path = root / "execution" / (label + "_COMPLETED.json")
        receipt = json.loads(path.read_text())
        if receipt["returncode"] != 0:
            raise ValueError("Previously completed confirmation failed")
        previous_receipts[label] = {"path": str(path.relative_to(root)), "sha256": sha(path)}
        directory = root / "runtime_confirmation" / f"seed_{seed}"
        for item in directory.rglob("*"):
            if item.is_file():
                protected[str(item.relative_to(root))] = sha(item)
    for phase, label, path in (
            ("audit", "runtime_audit_1213_recovery2", root / "runtime_confirmation/seed_1213/AUDIT.json"),
            ("qualify", "runtime_qualify_1213", root / "runtime_qualification/seed_1213/QUALIFICATION.json")):
        receipt_path = root / "execution" / (label + "_COMPLETED.json")
        if json.loads(receipt_path.read_text())["returncode"] != 0 or json.loads(path.read_text())["passed"] is not True:
            raise ValueError("Completed seed 1213 audit/qualification required")
        previous_receipts[label] = {"path": str(receipt_path.relative_to(root)), "sha256": sha(receipt_path)}
    for item in (root / "runtime_qualification/seed_1213").rglob("*"):
        if item.is_file():
            protected[str(item.relative_to(root))] = sha(item)
    # Keep the interrupted v1 orchestration exact. Its absent completion is not filled in.
    if (root / "runtime_recovery/COMPLETED.json").exists():
        raise ValueError("The interrupted v1 orchestration must not acquire a fabricated completion")
    for item in (root / "runtime_recovery").rglob("*"):
        if item.is_file():
            protected[str(item.relative_to(root))] = sha(item)
    for item in (root / "runtime_confirmation/seed_2017").rglob("*"):
        if item.is_file():
            protected[str(item.relative_to(root))] = sha(item)
    if (root / "runtime_confirmation/seed_1619").exists():
        raise FileExistsError("Preserve the incomplete seed 1619 second attempt before executing its unchanged cohort")
    state = {str(seed): {"confirm": "complete" if seed in (1213, 1427, 1823) else "pending",
                         "audit": "complete" if seed == 1213 else "pending",
                         "qualify": "complete" if seed == 1213 else "pending"} for seed in SEEDS}
    plan = [(2017, "score", "runtime_score_2017_recovery2"),
            (1619, "confirm", "runtime_confirm_1619_recovery2")]
    for seed in SEEDS:
        if seed != 1213:
            plan += [(seed, "audit", f"runtime_audit_{seed}_recovery2"),
                     (seed, "qualify", f"runtime_qualify_{seed}_recovery2")]
    plan.append((None, "summary", "runtime_summary_recovery2"))
    schedule = {"schema": "hepta.round4.recovery-schedule.v2", "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": frozen["source_commit"], "freeze_sha256": sha(root / "FREEZE.json"),
                "orchestrator_sha256": sha(__file__), "maximum_simultaneous_heavy_phases": 1,
                "plan": [{"seed": seed, "phase": phase, "label": label} for seed, phase, label in plan],
                "interruption_receipts": {str(path.relative_to(root)): sha(path) for path in incidents},
                "protected_files_sha256": protected, "previous_completed_wrappers": previous_receipts,
                "successful_confirmations_1213_1427_1823_reexecuted": False,
                "complete_2017_worker_reexecuted": False, "only_full_policy_reexecution_seed": 1619,
                "scientific_source_model_data_order_selection_and_gates_unchanged": True,
                "original_v1_incomplete_receipts_preserved": True,
                "execution": "Serial attached children under a root-owned live process. No detached process and no parallel heavy scientific phase.",
                "timing": "Shared-host observations spanning different resource contention; no isolated hardware latency or sum of nested times.",
                "failure_policy": "Stop immediately, retain all outputs and wrappers, and never overwrite any phase or invent missing completions.",
                "mandatory_seeds": list(SEEDS)}
    write(output / "SCHEDULE.json", schedule)
    events = (output / "EVENTS.jsonl").open("x")
    receipts, identities, failures = {}, {}, []
    started = time.perf_counter_ns()

    def event(kind, **details):
        item = {"utc": datetime.now(timezone.utc).isoformat(), "event": kind, **details}
        events.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
        events.flush()
        os.fsync(events.fileno())
        temp = output / "PROGRESS.pending.json"
        temp.write_text(json.dumps({"state": state, "failures": failures, "last_event": item}, sort_keys=True, indent=2) + "\n")
        os.replace(temp, output / "PROGRESS.json")
        print(json.dumps(item, sort_keys=True), flush=True)

    def identity(seed):
        path = output / f"DATASET_IDENTITY_seed_{seed}.json"
        if path.exists():
            value = json.loads(path.read_text())
            if (value.get("passed") is not True or not value["registered_case_ids_exact_and_in_original_order"]
                    or any(sha(root / "runtime_confirmation" / f"seed_{seed}" / name) != item["recovered_sha256"]
                           for name, item in value["comparisons"].items())):
                raise ValueError("Existing identity receipt differs from the current original cohort")
            identities[str(seed)] = {"path": str(path.relative_to(root)), "sha256": sha(path), "passed": True,
                                     "all_npz_bytes_identical": value["all_npz_bytes_identical"]}
        else:
            identities[str(seed)] = dataset_identity(root, seed, attempts[seed], output)

    def phase(seed, name, label):
        if any((root / "execution" / (label + suffix)).exists() for suffix in ("_STARTED.json", "_COMPLETED.json", ".log")):
            raise FileExistsError("Exclusive wrapper already exists: " + label)
        if name == "score":
            child = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.evidence.recover_worker_score",
                     "--run-dir", str(root), "--seed", str(seed)]
        else:
            child = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.runtime_study", name,
                     "--run-dir", str(root)]
            if seed is not None:
                child += ["--seed", str(seed)]
        command = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.evidence.execute", "--run-dir", str(root),
                   "--label", label, "--", *child]
        if seed is not None:
            state[str(seed)]["confirm" if name == "score" else name] = "running"
        event("launched", seed=seed, phase=name, label=label, command=command)
        with (output / (label + ".driver.log")).open("xb") as log:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=False)
        path = root / "execution" / (label + "_COMPLETED.json")
        if result.returncode != 0 or not path.exists():
            raise RuntimeError(f"Phase {label} failed or has no completion receipt: {result.returncode}")
        receipt = json.loads(path.read_text())
        if receipt["command"] != child or receipt["returncode"] != 0:
            raise ValueError("Completed wrapper does not bind its requested command")
        receipts[label] = {"path": str(path.relative_to(root)), "sha256": sha(path), "returncode": 0,
                           "wall_ns": receipt["wall_ns"], "children_user_seconds": receipt["children_user_seconds"],
                           "children_system_seconds": receipt["children_system_seconds"]}
        if name in ("confirm", "score"):
            identity(seed)
            summary = json.loads((root / "runtime_confirmation" / f"seed_{seed}" / "SUMMARY.json").read_text())
            if summary["independent_trajectories"] != REGISTRATION["confirmation_rows"] or summary["executions"] != REGISTRATION["confirmation_rows"] * len(REGISTRATION["arms"]):
                raise ValueError("Recovered confirmation is not the entire registered cohort")
            if name == "score":
                score = json.loads((output / "SCORING_RECOVERY_seed_2017.json").read_text())
                if (score["passed"] is not True or score["reexecuted_policy"] is not False
                        or score["count_completed_worker_native_cost_once_in_formal_cohort"] is not True
                        or summary["wall_ns"] is not None or summary["cpu_ns"] is not None):
                    raise ValueError("Complete-worker reuse or unknown original parent costs incorrectly represented")
        elif name in ("audit", "qualify"):
            folder = "runtime_confirmation" if name == "audit" else "runtime_qualification"
            file_name = "AUDIT.json" if name == "audit" else "QUALIFICATION.json"
            if json.loads((root / folder / f"seed_{seed}" / file_name).read_text())["passed"] is not True:
                raise ValueError("Frozen replay or qualification did not pass")
        elif json.loads((root / "RUNTIME_RESULTS.json").read_text()).get("complete") is not True:
            raise ValueError("Frozen runtime summary incomplete")
        if seed is not None:
            state[str(seed)]["confirm" if name == "score" else name] = "complete"
        event("completed", seed=seed, phase=name, label=label, receipt=receipts[label])

    try:
        event("recovery_started", schedule_sha256=sha(output / "SCHEDULE.json"))
        for seed in (1427, 1823):
            identity(seed)
        for seed, name, label in plan:
            phase(seed, name, label)
        unchanged = all(sha(root / relative) == expected for relative, expected in protected.items())
        if not unchanged:
            raise ValueError("Previously completed science or old interrupted receipts changed")
        verify(root)
        report = {"schema": "hepta.round4.runtime-recovery-completion.v2", "passed": True,
                  "finished_utc": datetime.now(timezone.utc).isoformat(), "elapsed_wall_ns": time.perf_counter_ns() - started,
                  "state": state, "failures": [], "completed_wrappers": receipts, "dataset_identity": identities,
                  "protected_files_unchanged": unchanged, "protected_files_sha256": protected,
                  "previous_completed_wrappers": previous_receipts, "schedule_sha256": sha(output / "SCHEDULE.json"),
                  "interruption_receipts": schedule["interruption_receipts"],
                  "scoring_recovery_receipt": {"path": "runtime_recovery_v2/SCORING_RECOVERY_seed_2017.json",
                                               "sha256": sha(output / "SCORING_RECOVERY_seed_2017.json")},
                  "runtime_results_sha256": sha(root / "RUNTIME_RESULTS.json"),
                  "discarded_partial_attempts_are_additional_work_not_new_independent_samples": True,
                  "reused_complete_2017_worker_counted_once_in_formal_cohort": True,
                  "original_interrupted_parent_total_wall_ns": None, "original_interrupted_parent_total_cpu_ns": None,
                  "scopes_overlap_and_nested_times_must_not_be_added": True, "native_energy": None, "financial_cost": None}
        write(output / "COMPLETED.json", report)
        event("recovery_finished", passed=True, completion_sha256=sha(output / "COMPLETED.json"))
        return 0
    except BaseException as error:
        failures.append({"message": repr(error)})
        event("failure", message=repr(error))
        write(output / "FAILED.json", {"schema": "hepta.round4.runtime-recovery-failure.v2", "passed": False,
                                      "failures": failures, "state": state, "completed_wrappers": receipts,
                                      "elapsed_wall_ns": time.perf_counter_ns() - started})
        raise
    finally:
        events.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(args.run_dir))
