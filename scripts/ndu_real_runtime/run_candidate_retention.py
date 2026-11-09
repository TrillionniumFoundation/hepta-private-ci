"""Freeze and execute a Linux candidate-memory comparison with no new fitting.

Selection uses catalog metadata, before any private reference is opened. Each
source contributes one episode group with every required family. Paired arms
share all inputs; EpisodeHost owns isolation and effects. Failures never retry.
"""

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback

from ndu_real_materials.common import (
    binding,
    read_bound,
    read_relative,
    strict_json,
    write_json,
)
from ndu_real_materials.coverage import FAMILIES, ROLES
from .candidate_retention_report import generate
from .candidate_runtime import PROFILE_SCHEMA
from .controllers import ControlPlan
from .episode import EpisodeHost
from .metering import _usage, canonical_sha, file_sha

SCHEMA = "ndu.real.candidate-retention-request.v1"
SCHEDULE = ["PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "RENDER_IMAGE"]
REPOSITORY = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_pin(value, material_root):
    path = Path(value["path"])
    return (
        read_bound(path.parent, {**value, "path": path.name})
        if path.is_absolute()
        else read_bound(material_root, value)
    )


def required_source_paths():
    return {
        path.relative_to(REPOSITORY).as_posix()
        for package in ("ndu_real_runtime", "ndu_real_materials")
        for path in (REPOSITORY / "scripts" / package).glob("*.py")
        if not path.name.startswith("test_")
    } | {"experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py"}


def verify_sources(request):
    paths = [row["path"] for row in request["source_pins"]]
    require(
        len(set(paths)) == len(paths) and required_source_paths() <= set(paths),
        "Incomplete or duplicate frozen execution source pins",
    )
    for row in request["source_pins"]:
        read_bound(REPOSITORY, row)
    config = request["config"]
    require(
        Path(config["repository_root"]).resolve() == REPOSITORY
        and Path(config["scripts_root"]).resolve() == REPOSITORY / "scripts",
        "Execution roots differ from the checked implementation",
    )


def ocr_inventory(config):
    executable = shutil.which(config["tesseract"])
    require(executable is not None, "Frozen OCR executable is unavailable")
    libraries = Path(config["ocr_library_dir"]).resolve(strict=True)
    paths = sorted(path for path in libraries.rglob("*") if not path.is_dir())
    require(
        libraries.is_dir() and len(paths) <= 256,
        "OCR library inventory exceeds its bound",
    )
    paths = [Path(executable), Path(config["tessdata_dir"]) / "eng.traineddata", *paths]
    require(
        all(path.is_file() and path.stat().st_size <= 128 * 1024**2 for path in paths),
        "OCR inventory requires bounded regular files",
    )
    return {
        str(path): {"sha256": file_sha(path), "bytes": path.stat().st_size}
        for path in paths
    }


def select_cases(catalog, excluded, groups_per_role, salt):
    """Choose one complete episode per source without opening any task bytes."""
    require(
        set(catalog) == {"cases"} and isinstance(catalog["cases"], list),
        "A full catalog is required",
    )
    require(
        set(groups_per_role) == {"development", "retention_validation"},
        "Only development and retention-validation are released",
    )
    require(
        all(type(n) is int and 1 <= n <= 64 for n in groups_per_role.values()),
        "Bounded positive source counts required",
    )
    require(
        isinstance(salt, str) and 1 <= len(salt.encode()) <= 256,
        "Frozen selection salt required",
    )
    groups, roles, episodes, ids = defaultdict(lambda: defaultdict(dict)), {}, {}, set()
    for case in catalog["cases"]:
        require(
            set(case)
            == {
                "id",
                "source_id",
                "role",
                "task_family",
                "packet",
                "reference",
                "episode_group",
            },
            "Unexpected catalog fields",
        )
        cid, sid, role, episode, family = (
            case[k] for k in ("id", "source_id", "role", "episode_group", "task_family")
        )
        require(
            all(isinstance(x, str) and 0 < len(x) <= 256 for x in (cid, sid, episode)),
            "Bounded catalog identities required",
        )
        require(
            cid not in ids and role in ROLES and family in FAMILIES,
            "Duplicate case or unknown role/family",
        )
        require(
            roles.setdefault(sid, role) == role
            and episodes.setdefault(episode, (sid, role)) == (sid, role),
            "Source or episode crosses roles",
        )
        require(family not in groups[sid][episode], "Duplicate source/episode/family")
        ids.add(cid)
        groups[sid][episode][family] = case
    selected = []
    for role, count in groups_per_role.items():
        families = (
            set(FAMILIES) if role == "development" else {"text_image_complementary"}
        )
        available = {}
        for sid, by_episode in groups.items():
            if roles[sid] != role or sid in excluded:
                continue
            complete = [
                episode
                for episode, cases in by_episode.items()
                if families <= cases.keys()
            ]
            if complete:
                episode = min(
                    complete, key=lambda e: canonical_sha([salt, "episode", sid, e])
                )
                available[sid] = [by_episode[episode][f] for f in sorted(families)]
        require(
            len(available) >= count,
            f"Insufficient complete unexcluded source groups for {role}: {len(available)} < {count}",
        )
        chosen = sorted(
            available, key=lambda sid: canonical_sha([salt, "source", role, sid])
        )[:count]
        selected.extend(case for sid in chosen for case in available[sid])
    return selected


def exclusions(request, catalog, materials):
    manifest = strict_json(read_pin(request["exclusion_manifest"], materials))
    require(
        manifest.get("schema") == "ndu.real.selected-sources.v1",
        "Pinned collection selection manifest required",
    )
    cases = {case["id"]: case for case in catalog["cases"]}
    excluded = set()
    for role in ("training", "tuning"):
        declared, rows = manifest["groups"][role], manifest["cases"][role]
        require(
            declared
            and len(declared) == len(set(declared))
            and set(declared) == {row["source_id"] for row in rows},
            "Incomplete training/tuning source roster",
        )
        require(
            all(row["role"] == "train" and cases.get(row["id"]) == row for row in rows),
            "Collection exclusions differ from catalog or training role",
        )
        excluded.update(declared)
    require(
        len(request["excluded_source_groups"])
        == len(set(request["excluded_source_groups"]))
        and set(request["excluded_source_groups"]) == excluded,
        "Declared exclusions differ from the complete frozen training/tuning union",
    )
    require(request["exposure_ledgers"], "At least one pinned exposure ledger required")
    require(
        re.fullmatch(r"[0-9a-f]{64}", request["registry_sha256"]),
        "Frozen material registry identity required",
    )
    source_ids = {case["source_id"] for case in catalog["cases"]}
    for pin in request["exposure_ledgers"]:
        ledger = strict_json(read_pin(pin, materials))
        require(
            ledger.get("schema") == "ndu.real.researcher-exposure.v1"
            and isinstance(ledger.get("quarantined_source_groups"), list),
            "Unsupported exposure ledger",
        )
        require(
            ledger.get("registry_sha256") == request["registry_sha256"]
            and set(ledger["quarantined_source_groups"]) <= source_ids,
            "Exposure ledger belongs to a different registry or contains unknown source groups",
        )
        excluded.update(ledger["quarantined_source_groups"])
    return excluded, set(manifest["groups"]["training"])


def load_model(request, training_groups):
    import torch
    from .actor import parameter_sha
    from .neural import ReceiptPortfolioModel

    frozen, material_root = request["model"], request["config"]["material_root"]
    paths = {
        name: Path(frozen[name]["path"])
        for name in ("weights", "receipt", "deployment_profile")
    }
    require(
        all(path.is_absolute() for path in paths.values())
        and paths["receipt"] == paths["weights"].with_name("receipt.json")
        and paths["deployment_profile"]
        == paths["weights"].with_name("deployment-profile.json"),
        "Pinned model siblings must match the host loading paths",
    )
    raw = read_pin(frozen["weights"], material_root)
    receipt = strict_json(read_pin(frozen["receipt"], material_root))
    deployment = strict_json(read_pin(frozen["deployment_profile"], material_root))
    control = ControlPlan(**receipt["control"])
    records_raw = read_pin(request["training_records"], material_root)
    records = [strict_json(line) for line in records_raw.splitlines()]
    require(
        request["training_records"]["sha256"] == receipt["records"]["sha256"]
        and len(records_raw) == receipt["records"]["bytes"],
        "Original training record bytes differ from the model receipt",
    )
    require(
        records
        and len(records) <= 10000
        and all(row["split"] == "train" for row in records)
        and {row["source_group"] for row in records} == training_groups
        and len({row["record_id"] for row in records}) == len(records),
        "Original training rows do not bind the complete declared source roster",
    )
    require(
        len(training_groups) == receipt["records"]["source_groups"]
        and len({row["episode_id"] for row in records})
        == receipt["records"]["episodes"],
        "Training source/episode counts differ from the model receipt",
    )
    require(
        receipt.get("status") in {"CONTENT_PRETRAINED", "FITTED_NOT_ADOPTED"}
        and receipt["core"] == frozen["core"],
        "A completed frozen model receipt is required",
    )
    require(
        receipt["weights_sha256"] == frozen["weights"]["sha256"]
        and receipt["final_parameter_sha256"] == frozen["parameters_sha256"]
        and receipt["deployment_profile_sha256"]
        == frozen["deployment_profile"]["sha256"],
        "Model bytes, parameters or deployment receipt differs",
    )
    require(
        canonical_sha(asdict(control))
        == frozen["control_profile_sha256"]
        == receipt["control_profile_sha256"]
        == deployment["control_profile_sha256"]
        and control.memory_mode == "reset",
        "Frozen reset control profile differs",
    )
    require(
        deployment["weights_sha256"] == frozen["weights"]["sha256"]
        and deployment["core"] == frozen["core"],
        "Deployment model identity differs",
    )
    torch.set_num_threads(1)
    weights = torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True)
    model = ReceiptPortfolioModel(frozen["core"])
    schema = model.state_dict()
    require(
        set(weights) == set(schema)
        and all(
            isinstance(value, torch.Tensor)
            and value.shape == schema[name].shape
            and value.dtype == schema[name].dtype
            and bool(torch.isfinite(value).all())
            for name, value in weights.items()
        ),
        "Invalid complete finite model schema",
    )
    model.load_state_dict(weights, strict=True)
    require(
        parameter_sha(model) == frozen["parameters_sha256"],
        "Actual loaded model parameter digest differs",
    )
    return control, {
        "schema": "ndu.real.candidate-model-load.v1",
        "model": frozen,
        "actual_weights_sha256": hashlib.sha256(raw).hexdigest(),
        "actual_parameters_sha256": parameter_sha(model),
        "training_records": request["training_records"],
        "training_source_groups": sorted(training_groups),
        "torch_version": torch.__version__,
        "python": sys.executable,
        "training_executed": False,
        "independent_training_repeats": 0,
        "frozen_checkpoint_count": 1,
    }


def freeze(request, output):
    require(
        request["schema"] == SCHEMA
        and re.fullmatch(r"[0-9a-f]{40}", request["source_commit"]),
        "Frozen request/source identity required",
    )
    require(
        re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["experiment_id"]),
        "Bounded experiment identity required",
    )
    require(
        type(request["max_workers"]) is int and 1 <= request["max_workers"] <= 2,
        "At most two workers are supported",
    )
    verify_sources(request)
    config, materials = request["config"], Path(request["config"]["material_root"])
    catalog = strict_json(read_pin(request["catalog"], materials))
    excluded, training_groups = exclusions(request, catalog, materials)
    selected = select_cases(
        catalog, excluded, request["groups_per_role"], request["selection_salt"]
    )
    # Selection is complete above. Reference values below bind identity only.
    index_raw = read_relative(
        materials, "private/reference-index.v2.json", limit=8 * 1024**2
    )
    require(
        hashlib.sha256(index_raw).hexdigest() == config["reference_index_sha256"],
        "Reference index changed",
    )
    index = strict_json(index_raw)
    require(
        index["schema"] == "ndu.real.reference-index.v2"
        and index["rubric"]["sha256"] == config["rubric_sha256"],
        "Reference/rubric profile differs",
    )
    read_bound(materials, index["rubric"])
    control, model_receipt = load_model(request, training_groups)
    require(
        config["episode_wall_seconds"] == 60
        and config["latency_weight"] == control.latency_weight,
        "Both arms require the same frozen 60-second objective",
    )
    write_json(output / "MODEL.json", model_receipt)
    write_json(
        output / "CONTROL.json",
        {
            "control": asdict(control),
            "episode_wall_seconds": 60.0,
            "fixed_schedule": SCHEDULE,
            "seed": 0,
        },
    )
    control_binding = binding(output / "CONTROL.json", output)
    episodes, jobs = [], []
    for case in selected:
        require(
            index["case_roles"][case["id"]] == case["role"]
            and index["cases"][case["id"]] == case["reference"],
            "Catalog and private role/reference binding differ",
        )
        packet = strict_json(read_bound(materials, case["packet"]))
        reference = strict_json(read_bound(materials, case["reference"]))
        require(
            packet["case_id"] == case["id"]
            and all(
                reference[key] == case[other]
                for key, other in (
                    ("case_id", "id"),
                    ("role", "role"),
                    ("source_group", "source_id"),
                    ("episode_group", "episode_group"),
                )
            ),
            "Original source/episode identity differs",
        )
        pair_id = (
            request["experiment_id"]
            + "-"
            + canonical_sha([case["id"], request["selection_salt"]])[:20]
        )
        order = (
            ("current_only", "bounded")
            if int(canonical_sha([pair_id, "order"])[0], 16) % 2 == 0
            else ("bounded", "current_only")
        )
        pair_jobs = []
        for mode in order:
            profile = {
                "schema": PROFILE_SCHEMA,
                "mode": mode,
                "max_entries": 128,
                "max_serialized_bytes": 524288,
            }
            expected = {
                "original_operation_id": pair_id + "-" + mode,
                "pair_id": pair_id,
                "case_id": case["id"],
                "source_group_id": case["source_id"],
                "episode_group": case["episode_group"],
                "split": case["role"],
                "task_family": case["task_family"],
                "source_sha256": reference["source_image"]["sha256"],
                "source_width": packet["source_size"]["width"],
                "source_height": packet["source_size"]["height"],
                "weights_sha256": request["model"]["weights"]["sha256"],
                "parameters_sha256": request["model"]["parameters_sha256"],
                "control_profile_sha256": request["model"]["control_profile_sha256"],
                "control_plan_sha256": control_binding["sha256"],
                "public_case_sha256": case["packet"]["sha256"],
                "candidate_memory_profile": profile,
                "candidate_memory_profile_sha256": canonical_sha(profile),
            }
            episodes.append(expected)
            pair_jobs.append({"case": case, "expected": expected})
        jobs.append(pair_jobs)
    plan = {
        "schema": "ndu.real.candidate-retention-plan.v1",
        "source_commit": request["source_commit"],
        "source_pins": request["source_pins"],
        "request_sha256": canonical_sha(request),
        "catalog": request["catalog"],
        "exclusion_manifest": request["exclusion_manifest"],
        "training_records": request["training_records"],
        "exposure_ledgers": request["exposure_ledgers"],
        "registry_sha256": request["registry_sha256"],
        "excluded_source_groups": sorted(excluded),
        "groups_per_role": request["groups_per_role"],
        "selection_salt": request["selection_salt"],
        "control_plan": control_binding,
        "ocr_inventory": ocr_inventory(config),
        "evaluator_sha256": config["evaluator_sha256"],
        "reference_index_sha256": config["reference_index_sha256"],
        "rubric_sha256": config["rubric_sha256"],
        "model": request["model"],
        "episodes": episodes,
        "paired_run_order": [
            [job["expected"]["original_operation_id"] for job in pair] for pair in jobs
        ],
        "independent_training_repeats": 0,
        "frozen_checkpoint_count": 1,
        "scientific_acceptance": "HOLD",
    }
    require(
        file_sha(REPOSITORY / "scripts/ndu_real_materials/evaluator.py")
        == config["evaluator_sha256"],
        "Frozen evaluator implementation differs",
    )
    write_json(output / "PLAN.json", plan)
    return plan, jobs


def event(root, value):
    with (root / "runner.jsonl").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_episode(request, root, job, frozen_ocr):
    root = Path(root)
    expected = job["expected"]
    operation = expected["original_operation_id"]
    wall, cpu = time.perf_counter(), _usage()
    record = {
        "original_operation_id": operation,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "Unknown",
        "retry_of": None,
    }
    event(root, {**record, "event": "started"})
    invariant_stage = "before_episode"
    try:
        verify_sources(request)
        require(
            ocr_inventory(request["config"]) == frozen_ocr,
            "OCR inventory changed before the episode",
        )
        invariant_stage = None
        profile = {
            "original_operation_id": operation,
            "weights": request["model"]["weights"]["path"],
            "model_sha256": expected["weights_sha256"],
            "training_receipt_sha256": request["model"]["receipt"]["sha256"],
            "core": request["model"]["core"],
            "controller": "tuned_fixed",
            "control_plan": str(root / "CONTROL.json"),
            "control_plan_sha256": expected["control_plan_sha256"],
            "candidate_memory": expected["candidate_memory_profile"],
        }
        result = EpisodeHost(
            request["config"], job["case"], profile, root / "episodes" / operation
        ).run()
        record["status"] = result["terminal_status"]
        invariant_stage = "after_episode"
        verify_sources(request)
        require(
            ocr_inventory(request["config"]) == frozen_ocr,
            "OCR inventory changed during the episode",
        )
        invariant_stage = None
    except Exception as error:
        record.update(
            status="Failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
        if invariant_stage is not None:
            record["comparison_invariant_failure"] = invariant_stage
    record.update(
        wall_seconds=time.perf_counter() - wall,
        cpu_seconds=_usage() - cpu,
        energy_joules=None,
        provider_charges=None,
        finished_at=datetime.now(timezone.utc).isoformat(),
    )
    path = root / "attempts" / (operation + ".json")
    write_json(path, record)
    event(
        root,
        {
            "event": "finished",
            "original_operation_id": operation,
            "status": record["status"],
            "receipt": binding(path, root),
        },
    )
    return record


def run_pair(request, root, pair, plan_sha):
    raw = read_relative(root, "PLAN.json", limit=8 * 1024**2)
    require(
        hashlib.sha256(raw).hexdigest() == plan_sha,
        "Original pre-execution plan changed",
    )
    frozen_ocr = strict_json(raw)["ocr_inventory"]
    return [run_episode(request, root, job, frozen_ocr) for job in pair]


def evidence(root, expected):
    directory = root / "episodes" / expected["original_operation_id"]
    item = {"original_operation_id": expected["original_operation_id"]}
    attempt = root / "attempts" / (expected["original_operation_id"] + ".json")
    item["attempt"] = binding(attempt, root) if attempt.is_file() else None
    for key, relative in (
        ("result", "result.json"),
        ("trajectory", "trajectory.json"),
        ("public_case", "public/case.json"),
        ("initial_delivery", "delivery-00/delivery.json"),
    ):
        path = directory / relative
        item[key] = binding(path, root) if path.is_file() else None
    item["audits"], item["final_delivery"] = [], None
    try:
        if item["trajectory"] is not None:
            trajectory = strict_json(read_bound(root, item["trajectory"]))
            steps = trajectory["steps"]
            for step in steps:
                audit = step.get("candidate_audit")
                if audit is None:
                    item["audits"].append(None)
                    continue
                # Preserve the original actor digest even if its file is damaged.
                require(
                    audit["path"] == f"candidate-audit-{step['step']:02d}.json",
                    "Unexpected actor audit path",
                )
                item["audits"].append(
                    {
                        **audit,
                        "path": (directory / "actor-output" / audit["path"])
                        .relative_to(root)
                        .as_posix(),
                    }
                )
            path = directory / f"delivery-{len(steps):02d}" / "delivery.json"
            item["final_delivery"] = binding(path, root) if path.is_file() else None
    except Exception as error:
        item["collection_error"] = {"type": type(error).__name__, "message": str(error)}
    return item


def run(request_path, output):
    request = strict_json(Path(request_path).read_bytes())
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), _usage()
    receipt = {
        "schema": "ndu.real.candidate-retention-run.v1",
        "status": "Failed",
        "source_commit": request.get("source_commit"),
        "training_executed": False,
        "energy_joules": None,
        "provider_charges": None,
        "scientific_acceptance": "HOLD",
    }
    try:
        write_json(output / "REQUEST.json", request)
        (output / "runner.jsonl").touch(exist_ok=False)
        (output / "attempts").mkdir()
        plan, jobs = freeze(request, output)
        plan_sha = file_sha(output / "PLAN.json")
        receipt.update(
            weights_sha256_before=strict_json((output / "MODEL.json").read_bytes())[
                "actual_weights_sha256"
            ],
            model_load=binding(output / "MODEL.json", output),
        )
        records = []
        with ProcessPoolExecutor(
            max_workers=request["max_workers"],
            mp_context=multiprocessing.get_context("spawn"),
        ) as pool:
            futures = {
                pool.submit(run_pair, request, str(output), pair, plan_sha): pair
                for pair in jobs
            }
            for future in as_completed(futures):
                try:
                    records.extend(future.result())
                except Exception as error:
                    for job in futures[future]:
                        operation = job["expected"]["original_operation_id"]
                        path = output / "attempts" / (operation + ".json")
                        record = (
                            strict_json(path.read_bytes())
                            if path.is_file()
                            else {
                                "original_operation_id": operation,
                                "status": "Unknown",
                                "error": str(error),
                                "wall_seconds": None,
                                "cpu_seconds": None,
                            }
                        )
                        records.append(record)
        receipt.update(
            planned_episodes=len(plan["episodes"]),
            source_group_count=len(
                {row["source_group_id"] for row in plan["episodes"]}
            ),
            terminal_status_counts=dict(Counter(r["status"] for r in records)),
            attempts=records,
            plan_sha256=plan_sha,
            independent_training_repeats=0,
            frozen_checkpoint_count=1,
        )
        # All worker/actor lifetimes have ended before the independent rescore.
        manifest = {
            "schema": "ndu.real.candidate-retention-evidence.v1",
            "plan_sha256": plan_sha,
            "episodes": [evidence(output, expected) for expected in plan["episodes"]],
        }
        write_json(output / "EVIDENCE.json", manifest)
        require(
            not any(row.get("comparison_invariant_failure") for row in records),
            "Episode comparison invariant failed; REPORT withheld, original host and attempt evidence preserved",
        )
        verify_sources(request)
        require(
            ocr_inventory(request["config"]) == plan["ocr_inventory"],
            "Frozen OCR inventory changed",
        )
        for pin in (
            request["catalog"],
            request["exclusion_manifest"],
            request["training_records"],
            *request["exposure_ledgers"],
        ):
            read_pin(pin, request["config"]["material_root"])
        for pin in request["model"].values():
            if isinstance(pin, dict):
                read_pin(pin, request["config"]["material_root"])
        report = generate(
            output,
            request["config"]["material_root"],
            plan_sha,
            file_sha(output / "EVIDENCE.json"),
        )
        write_json(output / "REPORT.json", report)
        receipt.update(
            status="Completed"
            if all(r["status"] != "Unknown" for r in records)
            else "Unresolved",
            planned_episodes=len(plan["episodes"]),
            terminal_status_counts=dict(Counter(r["status"] for r in records)),
            attempts=records,
            weights_sha256_after=file_sha(request["model"]["weights"]["path"]),
            source_pins_unchanged=True,
            plan_sha256=plan_sha,
            report_sha256=file_sha(output / "REPORT.json"),
            process_cost_accounting="Whole-run CPU/wall includes episode envelopes and verification; do not add overlapping levels",
        )
    except Exception as error:
        receipt["error"] = {
            "type": type(error).__name__,
            "message": str(error),
            "traceback": traceback.format_exc(),
        }
    receipt.update(
        wall_seconds=time.perf_counter() - started, cpu_seconds=_usage() - cpu
    )
    write_json(output / "RUN_RECEIPT.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = run(args.request, args.output)
    print(
        json.dumps(
            {
                "status": receipt["status"],
                "planned_episodes": receipt.get("planned_episodes"),
                "scientific_acceptance": "HOLD",
            }
        )
    )
    return 0 if receipt["status"] == "Completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
