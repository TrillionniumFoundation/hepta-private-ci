"""Execute the finite prospectively frozen real pilot, retaining every original job."""

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import json
import os
from pathlib import Path
import time
import traceback

from ndu_real_materials.common import strict_json
from .matrix import pilot, tune
from .metering import _usage, atomic_json, canonical_sha, file_sha
from .study import collect, freeze, now, verify_plan
from .subprocess_supervisor import run_logged
from .training import FitConfig
from .training_grid import fit_grid, model_index
from .training_job_result import OUTER_SECONDS, admit, validate_output


def run_training_job(job, config, log_root):
    """The external parent envelope includes interpreter/import and receipt I/O."""
    directory = Path(log_root) / canonical_sha(job["job_id"])[:32]
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu, started_at = time.perf_counter(), _usage(), now()
    command = [job["command"]["executable"], *job["command"]["args"]]
    environment = dict(os.environ)
    environment.update(
        PYTHONPATH=os.pathsep.join(
            [config["pillow_path"], config["scripts_root"], config["repository_root"]]
        ),
        OMP_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    admitted = {
        "schema": "ndu.real.training-job-admission.v2",
        "original_operation_id": job["job_id"],
        "started_at": started_at,
        "command": command,
        "output": job["output"],
        "retry_of": None,
    }
    admission_sha = None
    error, code, supervision = None, None, None
    # Exclusive, unbuffered logs retain partial output without accumulating it.
    with (
        (directory / "stdout.log").open("xb", buffering=0) as stdout,
        (directory / "stderr.log").open("xb", buffering=0) as stderr,
    ):
        try:
            admitted = admit(job, config, started_at)
            admission_sha = atomic_json(directory / "admission.json", admitted)
            if Path(job["output"]).exists():
                raise RuntimeError(
                    "Original training output already exists; never implicitly rerun"
                )
            remaining = OUTER_SECONDS - (time.perf_counter() - started)
            supervision = run_logged(
                command,
                stdout=stdout,
                stderr=stderr,
                timeout=remaining,
                env=environment,
            )
            code, error = supervision["returncode"], supervision["error"]
        except BaseException as exception:
            error = {
                "type": type(exception).__name__,
                "message": str(exception),
                "traceback": traceback.format_exc(),
            }
    if admission_sha is None:
        atomic_json(directory / "admission-rejected.json", dict(admitted, error=error))
    artifact_validation, success = None, False
    try:
        if code == 0 and error is None:
            if supervision["policy"] != admitted["supervision"]["policy"]:
                raise ValueError("Executed supervisor policy differs from admission")
            artifact_validation = validate_output(
                admitted,
                exit_code=code,
                supervisor_wall_seconds=time.perf_counter() - started,
            )
            success = True
    except BaseException as exception:
        success = False
        error = {
            "type": type(exception).__name__,
            "message": str(exception),
            "traceback": traceback.format_exc(),
        }
    wall_seconds = time.perf_counter() - started
    if success and wall_seconds > OUTER_SECONDS:
        success = False
        error = {
            "type": "TimeoutError",
            "message": "Supervisor budget exhausted during result verification",
        }
    unresolved = admission_sha is not None and (
        code is None
        or (supervision is not None and not supervision["cleanup_complete"])
    )
    result = {
        **admitted,
        "schema": "ndu.real.training-job-result.v2",
        "admission_sha256": admission_sha,
        "finished_at": now(),
        "exit_code": code,
        "status": "completed" if success else "unresolved" if unresolved else "failed",
        "process_supervision": supervision,
        "error": error,
        "wall_seconds": wall_seconds,
        "cpu_seconds": _usage() - cpu,
        "receipt_sha256": (artifact_validation or {}).get("receipt_sha256"),
        "weights_sha256": (artifact_validation or {}).get("weights_sha256")
        if success
        else None,
        "artifact_validation": artifact_validation,
        "stdout_sha256": file_sha(directory / "stdout.log"),
        "stderr_sha256": file_sha(directory / "stderr.log"),
        "energy_joules": None,
        "provider_charges": None,
        "native_owner_authentication": "SEPARATE_REQUIRED",
    }
    atomic_json(directory / "result.json", result)
    print(
        json.dumps(
            {
                "event": "training_job_terminal",
                "operation": job["job_id"],
                "status": result["status"],
                "wall_seconds": result["wall_seconds"],
            }
        ),
        flush=True,
    )
    return result


def single_training(config, root, name, extra):
    output = Path(root) / "models" / name
    command = {
        "executable": config["python"],
        "args": [
            "-m",
            "ndu_real_runtime.training",
            "--output",
            str(output),
            "--seed",
            "271828",
            "--core",
            "ordinary",
            "--replicate-role",
            "collector",
            "--run-id",
            name,
            "--control-plan",
            str(Path(root) / "collector-control-plan.json"),
            "--latency-weight",
            str(config["latency_weight"]),
            *extra,
        ],
    }
    job = {"job_id": name, "command": command, "output": str(output)}
    result = run_training_job(job, config, Path(root) / "training-jobs")
    if result["status"] != "completed":
        raise RuntimeError(
            "Common collector could not complete; original attempt retained"
        )
    return output


def run_grid(root, records):
    root = Path(root)
    plan, _ = verify_plan(root)
    design, config = plan["design"], plan["execution"]
    if design["training"].get("observation_policy") == "matched_episodes":
        from .causal_b import run_matched_grid

        return run_matched_grid(root, records, design, config)
    training = design["training"]
    grid = fit_grid(
        str(records),
        file_sha(records),
        str(root / "models" / "independent"),
        python=config["python"],
        seeds=design["training_seeds"],
        head_lrs=training["head_learning_rates"],
        config=FitConfig(
            content_epochs=training["content_epochs"],
            fit_epochs=training["fit_epochs"],
            content_lr=training["content_learning_rate"],
            latency_weight=design["controller"]["latency_weight"],
        ),
        control_plan=root / "collector-control-plan.json",
    )
    atomic_json(root / "fit-plan.json", grid)
    atomic_json(root / "model-index.planned.json", model_index(grid))
    results = {}
    ledger = (root / "training-events.jsonl").open("x", buffering=1)

    def retain_event(value):
        ledger.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        ledger.flush()
        os.fsync(ledger.fileno())

    for phase in ("content", "fit"):
        jobs = [job for job in grid["jobs"] if job["phase"] == phase]
        with ProcessPoolExecutor(max_workers=design["budgets"]["max_workers"]) as pool:
            futures = {}
            for job in jobs:
                if any(
                    results[dependency]["status"] != "completed"
                    for dependency in job["depends_on"]
                ):
                    results[job["job_id"]] = {
                        "status": "blocked_by_failed_dependency",
                        "original_operation_id": job["job_id"],
                        "weights_sha256": None,
                        "receipt_sha256": None,
                    }
                    retain_event(
                        {
                            "event": "dependency_blocked",
                            "job_id": job["job_id"],
                            "at": now(),
                        }
                    )
                else:
                    retain_event(
                        {
                            "event": "dispatch_admitted",
                            "job_id": job["job_id"],
                            "at": now(),
                        }
                    )
                    futures[
                        pool.submit(
                            run_training_job, job, config, root / "training-jobs"
                        )
                    ] = job
            for future in as_completed(futures):
                job = futures[future]
                try:
                    results[job["job_id"]] = future.result()
                except BaseException as error:
                    results[job["job_id"]] = {
                        "status": "unresolved",
                        "original_operation_id": job["job_id"],
                        "error": str(error),
                        "weights_sha256": None,
                        "receipt_sha256": None,
                    }
                retain_event(
                    {
                        "event": "terminal_observed",
                        "job_id": job["job_id"],
                        "result": results[job["job_id"]],
                        "at": now(),
                    }
                )
        atomic_json(
            root / ("fit-" + phase + "-results.json"),
            {"phase": phase, "results": results},
        )
    ledger.close()
    index = {"schema": "ndu.real.model-index.v1", "content": [], "fits": []}
    for job in grid["jobs"]:
        result = results[job["job_id"]]
        row = {
            "core": job["core"],
            "seed": job["seed"],
            "memory_mode": job["memory_mode"],
            "observation_policy": job["observation_policy"],
            "paired_memory_group": job["paired_memory_group"],
            "directory": job["output"],
            "status": result["status"],
            "weights_sha256": result.get("weights_sha256"),
            "receipt_sha256": result.get("receipt_sha256"),
        }
        if job["phase"] == "fit":
            row.update(
                regime=job["regime"],
                controller=job["controller"],
                trial_index=job["trial_index"],
            )
        index["content" if job["phase"] == "content" else "fits"].append(row)
    atomic_json(root / "model-index.json", index)
    return index


def execute(config, design_path, root):
    root = Path(root)
    started, stage = time.perf_counter(), "bootstrap"
    result = {
        "schema": "ndu.real.pipeline-result.v1",
        "started_at": now(),
        "status": "started",
    }
    try:
        stage = "prospective-registration"
        plan = freeze(config, design_path, root)
        result["pilot_plan_sha256"] = file_sha(root / "PILOT_PLAN.json")
        stage = "bootstrap"
        design = plan["design"]
        control_path = root / "collector-control-plan.json"
        atomic_json(
            control_path,
            {
                "control": design["controller"],
                "episode_wall_seconds": design["budgets"]["episode_wall_seconds"],
                "fixed_schedule": design["fixed_schedule_candidates"][
                    min(1, len(design["fixed_schedule_candidates"]) - 1)
                ],
                "seed": design["behavior_collector_seed"],
            },
        )
        bootstrap = single_training(
            config, root, "common-collector-bootstrap", ["--bootstrap"]
        )
        stage = "collection-content"
        collect(root, "content", bootstrap / "weights.pt", control_path)
        stage = "collector-content-training"
        records = root / "training-content.jsonl"
        fitted = single_training(
            config,
            root,
            "common-collector-content",
            [
                "--content-only",
                "--records",
                str(records),
                "--expected-records-sha256",
                file_sha(records),
                "--content-epochs",
                str(design["training"]["content_epochs"]),
                "--content-lr",
                str(design["training"]["content_learning_rate"]),
            ],
        )
        stage = "collection-transitions"
        collect(root, "transitions", fitted / "weights.pt", control_path)
        common = root / "training-common.jsonl"
        with common.open("xb") as output:
            for path in (
                root / "training-content.jsonl",
                root / "training-transitions.jsonl",
            ):
                with path.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        output.write(block)
            output.flush()
            os.fsync(output.fileno())
        stage = "independent-training"
        run_grid(root, common)
        stage = "matched-search"
        tune(root, root / "model-index.json")
        stage = "real-pilot"
        pilot(root)
        result.update(
            status="execution_completed",
            final_stage=stage,
            learning_evidence_status="Inconclusive",
        )
    except BaseException as error:
        result.update(
            status="execution_failed",
            final_stage=stage,
            learning_evidence_status="Failed",
            error={
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
    result.update(
        finished_at=now(),
        wall_seconds=time.perf_counter() - started,
        scientific_admission="HOLD",
        adoption_authorized=False,
        confirmation_executed=False,
    )
    root.mkdir(parents=True, exist_ok=True)
    atomic_json(root / "PIPELINE_RESULT.json", result)
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "execution_completed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    args = parser.parse_args()
    return execute(strict_json(args.config.read_bytes()), args.design, args.root)


if __name__ == "__main__":
    raise SystemExit(main())
