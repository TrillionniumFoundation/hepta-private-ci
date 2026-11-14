"""Run source-isolated training, selection, calibration, and final evaluation.

Worker processes receive observations only. Reference scoring runs in the parent,
after each completed generation, and never enters an inference callback.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import time

import numpy as np
import torch

from backend import FlorenceBackend
from cells import FourCells
from cohort import iter_pairs, validate_splits
from evaluate import METHODS, cvar, evaluate, score_episode
from generation import run_episode
from policies import Policies
from verification import Verifier


WORKER = {}
PHASE_SPLITS = {"collect": "train", "selection": "dev", "calibration": "calibration", "test": "test"}


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_resume(rows, expected_keys, checkpoint_identities, split, budget):
    seen = set()
    for row in rows:
        key = (row.get("task_id"), row.get("method"), row.get("seed"), row.get("risk_weight"))
        if (key not in expected_keys or key in seen or row.get("split") != split
                or row.get("budget_cap") != budget or row.get("budget_unit") != "wall_seconds"
                or row.get("checkpoint_identities") != checkpoint_identities):
            raise ValueError("resume row differs from the frozen roster, split, budget, or checkpoints")
        seen.add(key)
    return seen


def risk_calibration_summary(rows):
    result = {}
    for method in sorted({row["method"] for row in rows}):
        group = [row for row in rows if row["method"] == method]
        valid, missing, invalid = [], 0, 0
        for row in group:
            probability = row.get("calibrated_risk")
            if probability is None:
                missing += 1
            elif type(probability) not in (float, int) or not np.isfinite(probability) or not 0 <= probability <= 1:
                invalid += 1
            else:
                valid.append((probability - row["score"]["severe"]) ** 2)
        result[method] = {"brier": float(np.mean(valid)) if valid else None, "available": len(valid),
                          "missing": missing, "invalid": invalid, "risk_coverage": len(valid) / len(group)}
    return result


def check_final_preconditions(work, cohort):
    work, cohort = Path(work), Path(cohort)
    selection = json.loads((work / "selection.json").read_text())
    if (selection.get("split") != "dev" or selection.get("test_used") is not False
            or selection.get("policy_weights_updated") is not False
            or selection.get("chosen_risk_weight") not in (0.0, 0.5, 1.0)):
        raise ValueError("a completed dev-only frozen policy selection is required")
    candidates = [point for point in selection.get("points", []) if point.get("method") == "ndu"]
    if ({point.get("risk_weight") for point in candidates} != {0.0, 0.5, 1.0}
            or any(abs(point["selection_score"] - point["quality"] + 0.5 * point["cvar"]) > 1e-9 for point in candidates)
            or max(candidates, key=lambda point: (point["selection_score"], -point["risk_weight"]))["risk_weight"]
            != selection["chosen_risk_weight"]):
        raise ValueError("selection does not match the fixed dev criterion")
    training = work / "training"
    for phase, split in (("selection", "dev"), ("calibration", "calibration")):
        receipt = json.loads((work / f"{phase}.run.json").read_text())
        identity = receipt["identity"]
        if phase == "calibration" and identity.get("combinations") != [
                [method, 23, selection["chosen_risk_weight"]] for method in METHODS]:
            raise ValueError("calibration used a different selected risk weight or method roster")
        if (receipt.get("status") != "complete" or identity.get("split") != split
                or identity.get("cohort_sha256") != sha(cohort / "manifest.json")
                or identity.get("checkpoint_sha256", {}).get("policies.pt") != sha(training / "policies.pt")
                or identity.get("checkpoint_sha256", {}).get("cells.pt") != sha(training / "cells.pt")
                or identity.get("checkpoint_sha256", {}).get("verifier.json") != sha(training / "verifier.json")
                or receipt.get("journal_sha256") != sha(work / f"{phase}.episodes.jsonl")):
            raise ValueError("selection/calibration provenance or checkpoint identity is stale")
    raw = Verifier.load(training / "verifier.json")
    calibrated = Verifier.load(training / "verifier-calibrated.json")
    report = json.loads((work / "calibration.json").read_text())
    if (calibrated.calibration.get("count", 0) <= 0 or not calibrated.calibration.get("digest")
            or report.get("split") != "calibration" or report.get("diagnostics") != calibrated.calibration
            or raw.train_digest != calibrated.train_digest
            or any(not np.array_equal(getattr(raw, name), getattr(calibrated, name))
                   for name in ("mean", "scale", "quality_weights", "severe_weights"))):
        raise ValueError("independent probability-only calibration is missing or changed trained weights")
    return selection


def initialize_worker(model, training, artifact_root, phase):
    training = Path(training)
    verifier_name = "verifier-calibrated.json" if phase == "test" else "verifier.json"
    checkpoints = ("cells.pt",) if phase == "collect" else ("cells.pt", "policies.pt", verifier_name)
    WORKER.update(backend=FlorenceBackend(model, threads=4),
                  cells=FourCells.load(training / "cells.pt"),
                  policies=Policies.load(training / "policies.pt") if phase != "collect" else None,
                  verifier=Verifier.load(training / verifier_name) if phase != "collect" else None,
                  artifact_root=artifact_root,
                  resident={"worker_pid": os.getpid(), "load_seconds": 0.0},
                  identities={name: sha(training / name) for name in checkpoints})
    WORKER["resident"].update(load_seconds=WORKER["backend"].load_seconds,
                              frozen_tensor_sha256=WORKER["backend"].frozen_before, threads=4)


def execute_job(job):
    observation, method, seed, risk_weight, partner, cap = job
    result = run_episode(WORKER["backend"], WORKER["cells"], WORKER["policies"], WORKER["verifier"],
                         observation, method, WORKER["artifact_root"], seed, cap, risk_weight, partner)
    result["checkpoint_identities"] = WORKER["identities"]
    result["resident_initialization"] = WORKER["resident"]
    return result


def execute(args, phase, split, combinations):
    """A resumable append-only receipt; changing checkpoints invalidates resume."""
    if PHASE_SPLITS.get(phase) != split:
        raise ValueError("phase and data split mismatch")
    pairs = list(iter_pairs(args.cohort, split))
    references = {reference["task_id"]: reference for _, reference in pairs}
    observations = [observation for observation, _ in pairs]
    training, output = Path(args.work) / "training", Path(args.work)
    journal = output / f"{phase}.episodes.jsonl"
    manifest_path = output / f"{phase}.run.json"
    verifier_name = "verifier-calibrated.json" if phase == "test" else "verifier.json"
    checkpoints = ("cells.pt",) if phase == "collect" else ("cells.pt", "policies.pt", verifier_name)
    identity = {"schema_version": 2, "phase": phase, "split": split, "budget_cap": args.budget,
                "workers": args.workers, "threads_per_worker": 4,
                "combinations": [list(c) for c in combinations], "sources": len(pairs),
                "cohort_sha256": sha(Path(args.cohort) / "manifest.json"),
                "checkpoint_sha256": {name: sha(training / name) for name in checkpoints},
                "implementation_sha256": {name: sha(Path(__file__).parent / name) for name in
                    ("backend.py", "cells.py", "policies.py", "verification.py", "generation.py",
                     "experiment.py", "evaluate.py", "cohort.py", "protocol.json")}}
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text())
        if existing["identity"] != identity:
            raise ValueError("resume identity changed; preserve previous receipts and use a new work directory")
        if existing.get("status") == "complete" and (not journal.exists() or existing.get("journal_sha256") != sha(journal)):
            raise ValueError("completed journal digest mismatch")
    if not manifest_path.exists():
        write_json(manifest_path, {"identity": identity, "status": "started", "started_unix": time.time()})
    previous = read_rows(journal) if journal.exists() else []
    expected = {(observation["task_id"], method, seed, risk) for observation in observations
                for method, seed, risk in combinations}
    seen = validate_resume(previous, expected, identity["checkpoint_sha256"], split, args.budget)
    jobs = []
    for index, observation in enumerate(observations):
        # Rotate method order across images to reduce systematic warm-up/order effects.
        rotated = combinations[index % len(combinations):] + combinations[:index % len(combinations)]
        for method, seed, risk_weight in rotated:
            key = (observation["task_id"], method, seed, risk_weight)
            if key not in seen:
                jobs.append((observation, method, seed, risk_weight, observations[(index + 1) % len(observations)], args.budget))
    started, rows = time.perf_counter(), list(previous)
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                             initializer=initialize_worker,
                             initargs=(args.model, str(training), str(output / "artifacts"), phase)) as executor:
        with journal.open("a") as stream:
            for episode in executor.map(execute_job, jobs, chunksize=1):
                episode["split"] = split
                episode["score"] = score_episode(episode, references[episode["task_id"]])
                stream.write(json.dumps(episode, allow_nan=False) + "\n")
                stream.flush()
                rows.append(episode)
                if len(rows) % 16 == 0:
                    print(json.dumps({"phase": phase, "episodes": len(rows),
                                      "total": len(pairs) * len(combinations),
                                      "failures": sum(bool(row["failures"]) for row in rows)}), flush=True)
    resident = {r["resident_initialization"]["worker_pid"]: r["resident_initialization"] for r in rows}
    write_json(manifest_path, {"identity": identity, "status": "complete", "completed_unix": time.time(), "episodes": len(rows),
                              "resumed": len(previous), "this_execution_seconds": time.perf_counter() - started,
                              "journal_sha256": sha(journal),
                              "actual_episode_seconds": sum(r["actual_wall_seconds"] for r in rows),
                              "worker_initializations": list(resident.values()),
                              "timing_scope": "parallel worker online wall sum is not batch elapsed; initialization, IPC scheduling and independent scoring are in batch elapsed"})
    return rows, list(references.values())


def collect(args):
    rows, _ = execute(args, "collect", "train", [("explore", seed, 0.5) for seed in (23, 41)])
    trajectories = []
    for row in rows:
        trajectory = row["trajectory"]
        if trajectory and trajectory["actions"]:
            trajectories.append({**trajectory, "split": "train", "task_id": row["task_id"],
                                 "terminal_quality": row["score"]["quality"], "terminal_loss": row["score"]["loss"]})
    training = Path(args.work) / "training"
    write_json(training / "trajectories.json", trajectories)
    torch.set_num_threads(4)
    policies = Policies().fit(trajectories)
    digest = policies.save(training / "policies.pt")
    verifier = Verifier.fit([{"generated": r["generated_for_verifier"], "quality": r["score"]["quality"],
                              "severe": r["score"]["severe"], "split": "train"} for r in rows])
    verifier.save(training / "verifier.json")
    write_json(training / "policy-training.json", {"policies_sha256": digest, "metadata": policies.training_metadata,
                                                  "attempted_episodes": len(rows), "used_trajectories": len(trajectories),
                                                  "generation_failures": sum(bool(r["failures"]) for r in rows)})
    print(json.dumps({"phase": "policies_fitted", "transitions": policies.training_metadata["transitions"],
                      "action_counts": policies.training_metadata["action_counts"]}), flush=True)


def select(args):
    combinations = [("base", 23, 0.5), ("static_cells", 23, 0.5)] + [("ndu", 23, risk) for risk in (0.0, 0.5, 1.0)]
    rows, _ = execute(args, "selection", "dev", combinations)
    points = []
    for method, seed, risk in combinations:
        group = [r for r in rows if (r["method"], r["seed"], r["risk_weight"]) == (method, seed, risk)]
        quality = float(np.mean([r["score"]["quality"] for r in group]))
        risk_value = cvar([r["score"]["loss"] for r in group])
        points.append({"method": method, "risk_weight": risk, "quality": quality, "cvar": risk_value,
                       "selection_score": quality - 0.5 * risk_value,
                       "seconds": float(np.mean([r["actual_wall_seconds"] for r in group]))})
    chosen = max((p for p in points if p["method"] == "ndu"), key=lambda p: (p["selection_score"], -p["risk_weight"]))
    selection = {"split": "dev", "criterion": "mean_quality - 0.5 * CVaR_0.9; ties lower risk weight",
                 "chosen_risk_weight": chosen["risk_weight"], "points": points,
                 "test_used": False, "policy_weights_updated": False}
    write_json(Path(args.work) / "selection.json", selection)
    print(json.dumps(selection), flush=True)


def calibrate(args):
    risk = json.loads((Path(args.work) / "selection.json").read_text())["chosen_risk_weight"]
    rows, _ = execute(args, "calibration", "calibration", [(method, 23, risk) for method in METHODS])
    path = Path(args.work) / "training" / "verifier.json"
    verifier = Verifier.load(path)
    report = verifier.calibrate([{"generated": r["generated_for_verifier"], "severe": r["score"]["severe"],
                                  "split": "calibration"} for r in rows])
    verifier.save(Path(args.work) / "training" / "verifier-calibrated.json")
    write_json(Path(args.work) / "calibration.json", {"split": "calibration", "source_groups": len({r["task_id"] for r in rows}),
               "episodes": len(rows), "diagnostics": report,
               "scope": "pooled probability calibration, no policy/quality/ranking updates; correlated outputs share sources"})
    print(json.dumps({"phase": "calibrated", "report": report}), flush=True)


def final_test(args):
    selection = check_final_preconditions(args.work, args.cohort)
    risk = selection["chosen_risk_weight"]
    rows, references = execute(args, "test", "test", [(method, 23, risk) for method in METHODS])
    for row in rows:
        row["calibrated_risk"] = row["verification"]["severe_probability"]
    report = evaluate(references, rows)
    report["calibration"] = risk_calibration_summary(rows)
    report["selection"] = json.loads((Path(args.work) / "selection.json").read_text())
    report["execution"] = {"episodes": len(rows), "failures": sum(bool(r["failures"]) for r in rows),
                           "argmax_changes": sum(c["argmax_changed"] for r in rows for c in r["controls"]),
                           "max_ledger_difference": max(abs(r["ledger_minus_wall_seconds"]) for r in rows),
                           "final_test_generation_after_selection_and_calibration": True}
    write_json(Path(args.work) / "report.json", report)
    print(json.dumps({k: report[k] for k in ("engineering_pass", "experiment_pass", "errors", "points", "execution")}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("collect", "select", "calibrate", "test"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--cohort", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--budget", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.workers <= 2 or args.budget <= 0:
        parser.error("one or two workers and a positive budget are required")
    validate_splits(args.cohort)
    {"collect": collect, "select": select, "calibrate": calibrate, "test": final_test}[args.phase](args)


if __name__ == "__main__":
    main()
