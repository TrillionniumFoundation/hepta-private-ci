"""Operational recovery only; every scientific phase uses the frozen CLI."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from ..freeze import verify
from ..runtime_learning import SEEDS
from ..runtime_study import REGISTRATION


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def dataset_identity(root, seed, attempt, output):
    """Acceptance requires the original cohort, not just the same seed label."""
    previous = root / attempt["retained_directory"]
    current = root / "runtime_confirmation" / f"seed_{seed}"
    comparisons = {}
    for name in ("DATA.npz", "PUBLIC.npz"):
        old_path, new_path = previous / name, current / name
        old_sha, new_sha = sha(old_path), sha(new_path)
        if old_sha != attempt["files"][name]["sha256"]:
            raise ValueError("Preserved interrupted cohort changed: " + str(old_path))
        with np.load(old_path, allow_pickle=False) as old, np.load(new_path, allow_pickle=False) as new:
            same_keys = set(old.files) == set(new.files)
            fields = {}
            for key in sorted(set(old.files) | set(new.files)):
                if key not in old.files or key not in new.files:
                    fields[key] = {"equal": False, "reason": "missing key"}
                    continue
                left, right = old[key], new[key]
                arrays_equal = np.array_equal(left, right, equal_nan=True) if left.dtype.kind in "fc" else np.array_equal(left, right)
                fields[key] = {"equal": bool(left.dtype == right.dtype and left.shape == right.shape and arrays_equal),
                               "dtype": str(left.dtype), "shape": list(left.shape)}
            exact = same_keys and all(item["equal"] for item in fields.values())
        comparisons[name] = {"preserved_sha256": old_sha, "recovered_sha256": new_sha,
                             "bytes_identical": old_sha == new_sha, "keys_identical": same_keys,
                             "all_arrays_dtype_shape_values_identical": exact, "fields": fields}
    with np.load(current / "DATA.npz", allow_pickle=False) as data:
        expected = [f"feedback4:confirmation:{seed}:{i}" for i in range(REGISTRATION["confirmation_rows"])]
        exact_ids = data["ids"].tolist() == expected
    result = {"schema": "hepta.round4.recovery-dataset-identity.v1", "seed": seed,
              "checked_utc": datetime.now(timezone.utc).isoformat(), "comparisons": comparisons,
              "registered_case_ids_exact_and_in_original_order": exact_ids,
              "no_replacement_cohort": exact_ids and all(x["all_arrays_dtype_shape_values_identical"] for x in comparisons.values()),
              "all_npz_bytes_identical": all(x["bytes_identical"] for x in comparisons.values()),
              "preserved_attempt": attempt["retained_directory"]}
    result["passed"] = result["no_replacement_cohort"]
    path = output / f"DATASET_IDENTITY_seed_{seed}.json"
    write(path, result)
    if not result["passed"]:
        raise ValueError("Recovered cohort differs from the preserved interrupted cohort")
    return {"path": str(path.relative_to(root)), "sha256": sha(path), "passed": True,
            "all_npz_bytes_identical": result["all_npz_bytes_identical"]}


def run(root):
    root = Path(root).resolve()
    frozen = verify(root)
    incident_path = root / "RUNTIME_INTERRUPTION.json"
    incident = json.loads(incident_path.read_text())
    attempts = {item["seed"]: item for item in incident["attempts"] if item["phase"] == "confirm"}
    if set(attempts) != set(SEEDS) - {1213}:
        raise ValueError("Recovery must retain all four registered unfinished confirmation cohorts")
    if (root / "RUNTIME_RESULTS.json").exists():
        raise FileExistsError("Completed runtime summary must not be rerun")
    successful = root / "execution/runtime_confirm_1213_COMPLETED.json"
    if json.loads(successful.read_text())["returncode"] != 0:
        raise ValueError("Seed 1213 successful confirmation is required")
    protected_dir = root / "runtime_confirmation/seed_1213"
    protected = {str(path.relative_to(root)): sha(path) for path in protected_dir.iterdir() if path.is_file()}
    if any(name.endswith(("native_replay.zip", "AUDIT.json")) for name in protected):
        raise ValueError("This recovery expects the interrupted 1213 audit to be preserved separately")
    output = root / "runtime_recovery"
    output.mkdir(exist_ok=False)
    started = time.perf_counter_ns()
    state = {str(seed): {"confirm": "complete" if seed == 1213 else "pending", "audit": "pending", "qualify": "pending"}
             for seed in SEEDS}
    schedule = {"schema": "hepta.round4.recovery-schedule.v1", "created_utc": datetime.now(timezone.utc).isoformat(),
                "source_commit": frozen["source_commit"], "freeze_sha256": sha(root / "FREEZE.json"),
                "orchestrator_sha256": sha(Path(__file__)), "original_schedule_sha256": sha(root / "EXECUTION_SCHEDULE.json"),
                "interruption_sha256": sha(incident_path), "maximum_confirmation_jobs": 4, "maximum_audit_jobs": 2,
                "maximum_qualification_jobs": 1, "successful_1213_confirmation_reexecuted": False,
                "scientific_source_model_data_order_selection_and_gates_unchanged": True,
                "execution": "Root-owned long-lived process; children remain attached to this live process. Detached launch was not durable.",
                "timing": "Mixed-concurrency shared-host descriptive measurements. Do not sum overlapping wall times or nested wrapper scopes.",
                "failure_policy": "Stop launching phases on any failure; allow already running wrappers to finish and retain all evidence; no summary on failure.",
                "mandatory_seeds": list(SEEDS)}
    write(output / "SCHEDULE.json", schedule)
    events = (output / "EVENTS.jsonl").open("x")
    active, receipts, identities, failures = [], {}, {}, []

    def event(kind, **extra):
        item = {"utc": datetime.now(timezone.utc).isoformat(), "event": kind, **extra}
        events.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
        events.flush()
        os.fsync(events.fileno())
        temporary = output / "PROGRESS.pending.json"
        temporary.write_text(json.dumps({"state": state, "active": [{k: job[k] for k in ("seed", "phase", "label")} for job in active],
                                         "failures": failures, "last_event": item}, sort_keys=True, indent=2) + "\n")
        os.replace(temporary, output / "PROGRESS.json")
        print(json.dumps(item, sort_keys=True), flush=True)

    def launch(seed, phase):
        suffix = "_recovery1" if phase == "confirm" else "_recovery2" if phase == "audit" and seed == 1213 else ""
        label = f"runtime_{phase}_{seed}{suffix}" if seed is not None else "runtime_summary"
        execution = root / "execution"
        if any((execution / (label + suffix)).exists() for suffix in ("_STARTED.json", "_COMPLETED.json", ".log")):
            raise FileExistsError("Exclusive wrapper label already exists: " + label)
        child = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.runtime_study", phase, "--run-dir", str(root)]
        if seed is not None:
            child += ["--seed", str(seed)]
        command = [sys.executable, "-m", "experiments.analytic_event_neuron.round4.evidence.execute", "--run-dir", str(root), "--label", label, "--", *child]
        log = (output / (label + ".driver.log")).open("xb")
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        except BaseException:
            log.close()
            raise
        job = {"seed": seed, "phase": phase, "label": label, "process": process, "log": log, "command": command}
        active.append(job)
        if seed is not None:
            state[str(seed)][phase] = "running"
        event("launched", seed=seed, phase=phase, label=label, command=command)

    def completed(job, returncode):
        job["log"].close()
        seed, phase, label = job["seed"], job["phase"], job["label"]
        path = root / "execution" / (label + "_COMPLETED.json")
        if returncode != 0 or not path.exists():
            raise RuntimeError(f"Frozen phase failed: {label}; returncode={returncode}; completion_receipt={path.exists()}")
        receipt = json.loads(path.read_text())
        expected = job["command"][job["command"].index("--") + 1:]
        if receipt["returncode"] != 0 or receipt["command"] != expected:
            raise ValueError("Wrapper completion does not bind its requested frozen command")
        receipts[label] = {"path": str(path.relative_to(root)), "sha256": sha(path), "returncode": 0,
                           "wall_ns": receipt["wall_ns"], "children_user_seconds": receipt["children_user_seconds"],
                           "children_system_seconds": receipt["children_system_seconds"]}
        if phase == "confirm":
            identities[str(seed)] = dataset_identity(root, seed, attempts[seed], output)
            summary = json.loads((root / "runtime_confirmation" / f"seed_{seed}" / "SUMMARY.json").read_text())
            if summary["independent_trajectories"] != REGISTRATION["confirmation_rows"] or summary["executions"] != REGISTRATION["confirmation_rows"] * len(REGISTRATION["arms"]):
                raise ValueError("Recovery did not execute the full mandatory cohort")
        elif phase in ("audit", "qualify"):
            path = root / ("runtime_confirmation" if phase == "audit" else "runtime_qualification") / f"seed_{seed}" / ("AUDIT.json" if phase == "audit" else "QUALIFICATION.json")
            if json.loads(path.read_text()).get("passed") is not True:
                raise ValueError("Frozen replay/qualification failed")
        elif phase == "summary":
            if json.loads((root / "RUNTIME_RESULTS.json").read_text()).get("complete") is not True:
                raise ValueError("Frozen summary incomplete")
        if seed is not None:
            state[str(seed)][phase] = "complete"
        event("completed", seed=seed, phase=phase, label=label, receipt=receipts[label])

    event("recovery_started", schedule_sha256=sha(output / "SCHEDULE.json"))
    summary_launched = False
    try:
        while True:
            for job in list(active):
                code = job["process"].poll()
                if code is None:
                    continue
                active.remove(job)
                try:
                    completed(job, code)
                except BaseException as error:
                    failure = {"seed": job["seed"], "phase": job["phase"], "label": job["label"], "message": repr(error)}
                    failures.append(failure)
                    if job["seed"] is not None:
                        state[str(job["seed"])][job["phase"]] = "failed"
                    event("failure", **failure)
            if not failures:
                try:
                    for seed in SEEDS:
                        current = state[str(seed)]
                        if current["confirm"] == "pending":
                            launch(seed, "confirm")
                    available = 2 - sum(job["phase"] == "audit" for job in active)
                    for seed in SEEDS:
                        current = state[str(seed)]
                        if available and current["confirm"] == "complete" and current["audit"] == "pending":
                            launch(seed, "audit")
                            available -= 1
                    if not any(job["phase"] == "qualify" for job in active):
                        for seed in SEEDS:
                            current = state[str(seed)]
                            if current["audit"] == "complete" and current["qualify"] == "pending":
                                launch(seed, "qualify")
                                break
                    if all(item["qualify"] == "complete" for item in state.values()) and not active and not summary_launched:
                        launch(None, "summary")
                        summary_launched = True
                except BaseException as error:
                    failures.append({"phase": "orchestration", "message": repr(error)})
                    event("failure", **failures[-1])
            if not active and (failures or summary_launched):
                break
            time.sleep(1)
        unchanged = all(sha(root / relative) == expected for relative, expected in protected.items())
        if not unchanged:
            failures.append({"phase": "protected_confirmation", "message": "Successful 1213 confirmation bytes changed"})
        verify(root)
        result = {"schema": "hepta.round4.runtime-recovery-completion.v1", "passed": not failures,
                  "finished_utc": datetime.now(timezone.utc).isoformat(), "elapsed_wall_ns": time.perf_counter_ns() - started,
                  "state": state, "failures": failures, "completed_wrappers": receipts,
                  "dataset_identity": identities, "successful_1213_confirmation_bytes_unchanged": unchanged,
                  "successful_1213_confirmation_sha256": sha(successful), "schedule_sha256": sha(output / "SCHEDULE.json"),
                  "interruption_sha256": sha(incident_path), "interrupted_work_is_additional_and_not_zero_cost": True,
                  "runtime_results_sha256": sha(root / "RUNTIME_RESULTS.json") if (root / "RUNTIME_RESULTS.json").exists() else None,
                  "scopes_overlap_and_nested_times_must_not_be_added": True, "native_energy": None, "financial_cost": None}
        write(output / "COMPLETED.json", result)
        event("recovery_finished", passed=result["passed"], completion_sha256=sha(output / "COMPLETED.json"))
        return 0 if result["passed"] else 1
    finally:
        events.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    sys.exit(run(args.run_dir))
