"""Finite real-study scheduling with immutable requests and complete attempt inventory."""

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import traceback

from ndu_real_materials.common import strict_json
from .episode import EpisodeHost
from .metering import _usage, atomic_json, canonical_sha, file_sha


def now():
    return datetime.now(timezone.utc).isoformat()


def ordered(values, salt):
    return sorted(values, key=lambda value: hashlib.sha256((salt + ":" + value).encode()).hexdigest())


def select_sources(catalog, design, excluded_groups=()):
    """Select by source identity before any model/tuning/pilot observation."""
    roles = {}
    for row in catalog:
        if row["role"] != "train" and row["source_id"] in excluded_groups:
            continue
        roles.setdefault(row["role"], {}).setdefault(row["source_id"], []).append(row)
    selected, groups = {}, {}
    spec = design["source_selection"]
    train = ordered(roles["train"], design["study_id"] + ":train")
    definitions = {
        "training": ("train", train[:spec["training_groups"]]),
        "tuning": ("train", train[spec["training_groups"]:spec["training_groups"]+spec["tuning_groups"]]),
        "pilot_new": ("development", ordered(roles["development"], design["study_id"] + ":development")[:spec["pilot_new_groups"]]),
        "pilot_retention": ("retention_validation", ordered(roles["retention_validation"], design["study_id"] + ":retention_validation")[:spec["pilot_retention_groups"]]),
    }
    for name, (role, identities) in definitions.items():
        selected[name], groups[name] = [], identities
        for identity in identities:
            rows = roles[role][identity]
            episode = ordered({row["episode_group"] for row in rows}, design["study_id"] + ":episode_group")[0]
            chosen = sorted((row for row in rows if row["episode_group"] == episode), key=lambda row: row["task_family"])
            expected = 1 if name == "pilot_retention" else 5
            if len(chosen) != expected or len({row["task_family"] for row in chosen}) != expected:
                raise ValueError("Selected source lacks the prospectively required family coverage")
            selected[name].extend(chosen)
    all_groups = [group for group_list in groups.values() for group in group_list]
    if len(all_groups) != len(set(all_groups)):
        raise ValueError("A source group crosses model-fitting/tuning/pilot roles")
    expected = {"training": spec["training_groups"], "tuning": spec["tuning_groups"],
                "pilot_new": spec["pilot_new_groups"], "pilot_retention": spec["pilot_retention_groups"]}
    if any(len(groups[name]) != number for name, number in expected.items()):
        raise ValueError("Insufficient independent registered sources")
    return {"schema": "ndu.real.selected-sources.v1", "groups": groups, "cases": selected}


def freeze(config, design_path, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    design = strict_json(Path(design_path).read_bytes())
    data, code = Path(config["material_root"]), Path(config["repository_root"])
    registration = strict_json((data / "registration-final.json").read_bytes())
    if file_sha(data / "private/reference-index.v2.json") != config["reference_index_sha256"]:
        raise ValueError("Final independent reference index differs from execution pin")
    catalog = strict_json((data / "pilot-catalog.json").read_bytes())["cases"]
    exposure_path = Path(config["source_exposure_ledger_path"])
    if file_sha(exposure_path) != config["source_exposure_ledger_sha256"]:
        raise ValueError("Previously disclosed source ledger differs from the frozen execution pin")
    exposure = strict_json(exposure_path.read_bytes())
    selected = select_sources(catalog, design, exposure["quarantined_source_groups"])
    source_files = sorted([*[p for p in (code / "scripts/ndu_real_runtime").glob("*.py")
                            if "test" not in p.stem and p.stem != "pilot_analysis"],
                           *[p for p in (code / "scripts/ndu_real_materials").glob("*.py") if "test" not in p.stem],
                           code / "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"])
    pins = [{"path": str(path), "sha256": file_sha(path), "bytes": path.stat().st_size} for path in source_files]
    selected_pin = atomic_json(output / "selected-sources.json", selected)
    plan = {"schema": "ndu.real.pilot-plan.v1", "registered_at": now(), "design": design,
            "execution_run_id": output.name,
            "design_sha256": file_sha(design_path), "selected_sources_sha256": selected_pin,
            "registration_sha256": file_sha(data / "registration-final.json"),
            "registry_sha256": registration["registry_sha256"], "reference_index_sha256": config["reference_index_sha256"],
            "source_exposure_ledger_sha256": config["source_exposure_ledger_sha256"],
            "quarantined_source_groups": exposure["quarantined_source_groups"],
            "rubric_sha256": config["rubric_sha256"], "source_pins": pins, "execution": config,
            "independent_fit_roster": [{"fit_id": f"pilot-fit-{index+1:02d}", "training_seed": seed,
                                        "fit_run_id": f"{output.name}-fit-{seed}"}
                                       for index, seed in enumerate(design["training_seeds"])],
            "confirmation_actor_access_authorized": False, "adoption_authorized": False}
    pin = atomic_json(output / "PILOT_PLAN.json", plan)
    print(json.dumps({"event": "pilot_plan_frozen", "plan_sha256": pin,
                      "source_groups": {name: len(values) for name, values in selected["groups"].items()},
                      "code_files": len(pins), "registered_at": plan["registered_at"]}), flush=True)
    return plan


def verify_plan(root):
    root = Path(root)
    plan = strict_json((root / "PILOT_PLAN.json").read_bytes())
    if file_sha(root / "selected-sources.json") != plan["selected_sources_sha256"]:
        raise ValueError("Selected sources changed after registration")
    for binding in plan["source_pins"]:
        if file_sha(binding["path"]) != binding["sha256"]:
            raise ValueError("Execution source changed after the prospective plan")
    return plan, strict_json((root / "selected-sources.json").read_bytes())


def execute_one(request_path):
    request_path = Path(request_path)
    request = strict_json(request_path.read_bytes())
    output = Path(request["output"])
    started_wall, started_cpu, started_at = time.perf_counter(), _usage(), now()
    if output.exists():
        raise RuntimeError("An admitted original execution already has state; reconcile it, do not rerun")
    try:
        result = EpisodeHost(request["config"], request["case"], request["profile"], output,
            training=request.get("training", False), exploration=request.get("exploration", ())).run()
    except BaseException as error:
        output.mkdir(parents=True, exist_ok=True)
        result = {"schema": "ndu.real.episode-result.v1", **request["profile"],
                  "case_id": request["case"]["id"], "source_group_id": request["case"]["source_id"],
                  "episode_group": request["case"]["episode_group"], "split": request["case"]["role"],
                  "task_family": request["case"]["task_family"], "terminal_status": "Failed", "gross_score": None,
                  "error": {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}}
        if not (output / "result.json").exists():
            atomic_json(output / "result.json", result)
    receipt = {"schema": "ndu.real.original-attempt.v1", "original_operation_id": request["profile"]["original_operation_id"],
               "request_sha256": file_sha(request_path), "result_sha256": file_sha(output / "result.json"),
               "started_at": started_at, "finished_at": now(), "wall_seconds": time.perf_counter()-started_wall,
               "cpu_seconds": _usage()-started_cpu, "cpu_scope": "task_process_and_reaped_children",
               "terminal_status": result["terminal_status"],
               "retry_of": request["profile"].get("retry_of"), "process_id": os.getpid(),
               "deployment_included": True, "external_evaluation_included": True,
               "energy_joules": None, "provider_charges": None, "native_owner_authentication": "SEPARATE_REQUIRED"}
    atomic_json(output / "original-attempt.json", receipt)
    return {"output": str(output), "attempt": receipt, "profile": request["profile"], "case_id": request["case"]["id"]}


def run_requests(root, phase, requests, workers, wall_budget):
    """Run every bounded requested original once; never discard failures or pending work."""
    root = Path(root)
    phase_root = root / phase
    phase_root.mkdir(parents=True, exist_ok=False)
    (phase_root / "requests").mkdir()
    request_paths = []
    for request in requests:
        operation = request["profile"]["original_operation_id"]
        path = phase_root / "requests" / (operation + ".json")
        atomic_json(path, request)
        request_paths.append(path)
    # Deterministic interleaving counters systematic host-load/order differences.
    request_paths = sorted(request_paths, key=lambda path: hashlib.sha256(path.name.encode()).hexdigest())
    atomic_json(phase_root / "admitted-inventory.json", {"registered_at": now(), "phase": phase,
        "planned": [{"request": str(path), "sha256": file_sha(path)} for path in request_paths],
        "maximum_workers": workers, "admission_deadline_seconds": wall_budget,
        "maximum_declared_drain_seconds": 360, "hard_phase_limit_enforced_by_parent_runtime": False})
    started, results, pending, cursor = time.perf_counter(), [], {}, 0
    with ProcessPoolExecutor(max_workers=workers) as pool, (phase_root / "events.jsonl").open("x", buffering=1) as ledger:
        while pending or cursor < len(request_paths):
            while len(pending) < workers and cursor < len(request_paths) and time.perf_counter()-started < wall_budget-90:
                path = request_paths[cursor]
                cursor += 1
                future = pool.submit(execute_one, str(path))
                pending[future] = path
                ledger.write(json.dumps({"event": "dispatched", "request": str(path), "at": now()}) + "\n")
                ledger.flush(); os.fsync(ledger.fileno())
            if not pending:
                break
            finished, _ = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
            for future in finished:
                path = pending.pop(future)
                try:
                    result = future.result()
                except BaseException as error:
                    result = {"request": str(path), "terminal_status": "Unresolved", "error": str(error),
                              "original_execution_must_not_be_retried_implicitly": True}
                results.append(result)
                ledger.write(json.dumps({"event": "terminal", "result": result, "at": now()}, allow_nan=False) + "\n")
                ledger.flush(); os.fsync(ledger.fileno())
                if len(results) % 20 == 0 or len(results) == len(request_paths):
                    print(json.dumps({"phase": phase, "completed_attempts": len(results), "planned": len(request_paths),
                                      "elapsed_seconds": time.perf_counter()-started}), flush=True)
    result = {"schema": "ndu.real.phase-result.v1", "phase": phase, "planned": len(request_paths),
              "dispatched": cursor, "completed_or_unresolved": len(results), "attempts": results,
              "not_started_requests": [str(path) for path in request_paths[cursor:]],
              "elapsed_wall_seconds": time.perf_counter()-started, "maximum_workers": workers,
              "admission_deadline_seconds": wall_budget, "maximum_declared_drain_seconds": 360,
              "scientific_admission": "HOLD"}
    atomic_json(phase_root / "phase-result.json", result)
    return result


def collect(root, stage, weights, control_plan):
    root = Path(root)
    plan, selected = verify_plan(root)
    design, requests = plan["design"], []
    profile = {"study_id": design["study_id"], "fit_id": "common-behavior-collector",
               "training_seed": design["behavior_collector_seed"], "fit_run_id": "common-collector-not-independent-fit",
               "regime": "frozen", "arm": "common_collector", "core": "ordinary", "controller": "tuned_fixed",
               "weights": str(Path(weights).resolve()), "model_sha256": file_sha(weights),
               "control_plan": str(Path(control_plan).resolve()), "policy_sha256": file_sha(control_plan),
               "episode_seed": 0, "retry_of": None}
    for case in selected["cases"]["training"]:
        operation = "collect-" + stage + "-" + canonical_sha([plan["execution_run_id"], case["id"]])[:32]
        sequence = ["STOP"] if stage == "content" else design["exploration_candidates"][int(hashlib.sha256(case["id"].encode()).hexdigest(), 16) % 3]
        requests.append({"config": plan["execution"], "case": case,
            "profile": {**profile, "original_operation_id": operation}, "output": str(root / "episodes" / operation),
            "training": True, "exploration": sequence})
    result = run_requests(root, "collection-" + stage, requests, design["budgets"]["max_workers"], design["budgets"]["phase_wall_seconds"])
    path = root / ("training-" + stage + ".jsonl")
    with path.open("x") as output:
        for attempt in result["attempts"]:
            if "output" not in attempt:
                continue
            rows = Path(attempt["output"]) / "training-rows.jsonl"
            if rows.exists():
                output.write(rows.read_text())
    print(json.dumps({"event": "collection_retained", "phase": stage, "records": str(path),
                      "sha256": file_sha(path), "planned": result["planned"]}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "collect"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--design", type=Path)
    parser.add_argument("--stage", choices=("content", "transitions"))
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--control-plan", type=Path)
    args = parser.parse_args()
    if args.command == "freeze":
        freeze(strict_json(args.config.read_bytes()), args.design, args.root)
    else:
        collect(args.root, args.stage, args.weights, args.control_plan)
    return 0
