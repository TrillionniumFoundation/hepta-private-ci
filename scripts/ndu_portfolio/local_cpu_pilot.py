"""Explicit desktop CPU pilot, gated by this campaign's observed Kaggle failure.

This entry point never changes or invokes the cloud CUDA guard. The caller must
launch it in a native 200% CPU / 16 GiB memory cgroup and supply a distinct request
and CPU/bfloat16 profile. It reuses verified materials and an existing pinned
venv, with no pip installation or official image transfer. No task is scheduled
by importing this module. Native ownership and scientific acceptance stay false.
"""

import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import sys
import time

from .cloud_evidence import (
    Commands,
    LIMIT,
    artifact_manifest,
    pack_evidence,
    sha,
    verify_source,
    write,
)


PROVIDER = "heptaruntime-desktop-cpu"
DEFAULT_PYTHON = (
    "/home/qian-qi/work/hepta-sixline-ndu-728b0437-20261105/venv/bin/python"
)
MEMORY = 16 * 1024**3
NATIVE = (
    "experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit."
)
VERSIONS = {
    "torch": "2.8.0+cpu",
    "torchvision": "0.23.0+cpu",
    "numpy": "2.3.5",
    "Pillow": "13.0.0",
    "transformers": "4.57.3",
    "diffusers": "0.35.2",
    "accelerate": "1.12.0",
    "safetensors": "0.7.0",
    "num2words": "0.5.14",
}
STAGES = {
    "cpu_preflight": 30,
    "verify_existing_pool": 30,
    "plan": 15,
    "models": 420,
    "cpu_generator_smoke": 180,
    "collect": 600,
    "score_collect": 20,
    "fit": 150,
    "evaluate": 420,
    "score_evaluate": 20,
}


def fallback_evidence(
    root,
    manifest_path,
    pin,
    request_id,
    source_sha,
    cpu_request_id,
    result_name="BOOTSTRAP_RESULT.json",
    probe_name="ACTUAL_PREINSTALLED_DEVICE.json",
):
    """Only explicit observations qualify; an unverified GPU report is insufficient."""
    root = Path(root).resolve()
    if (
        not isinstance(cpu_request_id, str)
        or not cpu_request_id
        or cpu_request_id == request_id
        or not request_id
        or sha(manifest_path) != pin
    ):
        raise ValueError(
            "Distinct CPU request and externally pinned current Kaggle evidence required"
        )
    manifest = json.loads(Path(manifest_path).read_text())
    if (
        manifest["schema"] != "hepta-artifact-manifest-v1"
        or manifest["request_id"] != request_id
    ):
        raise ValueError("Kaggle artifact manifest belongs to another request")
    files = {}
    for row in manifest["files"]:
        relative = PurePosixPath(row["path"])
        path = root / relative
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or row["path"] in files
            or path.is_symlink()
            or not path.resolve().is_relative_to(root)
        ):
            raise ValueError("Unsafe or repeated Kaggle artifact path")
        if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
            raise ValueError("Kaggle artifact differs from the pinned manifest")
        files[row["path"]] = row
    if sum(row["bytes"] for row in files.values()) > LIMIT:
        raise ValueError("Kaggle artifact set exceeds the registered 64 MiB cap")
    for name in (result_name, probe_name):
        if name not in files or files[name]["bytes"] > 2 * 1024**2:
            raise ValueError(
                "Both bounded result and actual-device probe must share the artifact manifest"
            )
    result = json.loads((root / result_name).read_text())
    probe = json.loads((root / probe_name).read_text())
    if any(
        row.get("request_id") != request_id or row.get("source_sha") != source_sha
        for row in (result, probe)
    ):
        raise ValueError(
            "Old or unrelated Kaggle source/request cannot enable this fallback"
        )
    if (
        result.get("provider") != "kaggle-batch"
        or result.get("experiment_status") != "Failed"
    ):
        raise ValueError("A completed GPU experiment cannot enable CPU fallback")
    actual, smi = probe.get("torch", {}), probe.get("nvidia_smi", {})
    if (
        not isinstance(actual, dict)
        or not isinstance(smi, dict)
        or not isinstance(actual.get("version"), str)
        or not actual["version"]
        or actual.get("is_available") is not False
        or type(actual.get("device_count")) is not int
        or actual["device_count"] != 0
        or smi.get("available") is not False
        or smi.get("path") is not None
        or smi.get("return_code") not in (None, 127)
    ):
        raise ValueError(
            "Current delivered runtime must explicitly report no CUDA and absent nvidia-smi"
        )
    return {
        "kaggle_request_id": request_id,
        "kaggle_source_sha": source_sha,
        "artifact_manifest_sha256": pin,
        "result_sha256": files[result_name]["sha256"],
        "probe_sha256": files[probe_name]["sha256"],
        "actual_probe": probe,
        "scope": "delivered_runtime_only; driver_repairability_not_assessed",
    }


def resource_snapshot(proc_path="/proc/self/cgroup", mount="/sys/fs/cgroup"):
    """Read inherited native cgroup ceilings; never create or relax a cgroup."""
    rows = [line.split(":", 2) for line in Path(proc_path).read_text().splitlines()]
    current = next((row[2] for row in rows if row[:2] == ["0", ""]), None)
    if current is None or ".." in PurePosixPath(current).parts:
        raise ValueError("A readable cgroup-v2 native unit is required")
    mount = Path(mount).resolve()
    path = mount / current.lstrip("/")
    if not path.resolve().is_relative_to(mount):
        raise ValueError("Native cgroup path escapes its mount")
    levels, cpus, memory = [], [], []
    while True:
        item = {"path": str(path)}
        for field in (
            "cpu.max",
            "memory.max",
            "memory.current",
            "memory.peak",
            "cpu.stat",
        ):
            file = path / field
            if file.is_file():
                item[field] = file.read_text().strip()
        if "cpu.max" in item:
            quota, period = item["cpu.max"].split()
            if quota != "max":
                cpus.append(int(quota) / int(period))
        if item.get("memory.max", "max") != "max":
            memory.append(int(item["memory.max"]))
        levels.append(item)
        if path == mount:
            break
        path = path.parent
    result = {
        "self_cgroup": current,
        "ancestors": levels,
        "cpu_quota_cores": min(cpus) if cpus else None,
        "memory_max_bytes": min(memory) if memory else None,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "do_not_sum_ancestor_counters": True,
        "scope": "observed_kernel_cgroup_limits; not_native_owner_authentication",
    }
    if (
        not cpus
        or not memory
        or not 0 < min(cpus) <= 2
        or not 0 < min(memory) <= MEMORY
    ):
        raise ValueError(
            "Native aggregate CPU<=2 and memory<=16GiB ceilings must already exist"
        )
    return result


def check_profile(profile):
    if (
        profile.get("device") != "cpu"
        or profile.get("dtype") != "bfloat16"
        or type(profile.get("threads")) is not int
        or profile["threads"] != 2
    ):
        raise ValueError(
            "This separate profile requires explicit cpu/bfloat16/2 threads"
        )


def cpu_preflight(output):
    result = {
        "provider": PROVIDER,
        "device": "cpu",
        "dtype": "bfloat16",
        "verified": False,
        "gpu_execution_verified": False,
        "scientific_acceptance": False,
        "executable": sys.executable,
        "versions": {},
        "pretrained_models_executed": False,
    }
    try:
        result["resources"] = resource_snapshot()
        for name, expected in VERSIONS.items():
            result["versions"][name] = importlib.metadata.version(name)
            if result["versions"][name] != expected:
                raise ValueError("Existing CPU venv version differs: " + name)
        import torch

        if (
            torch.__version__ != VERSIONS["torch"]
            or torch.version.cuda is not None
            or torch.cuda.is_available()
        ):
            raise ValueError(
                "Existing venv is not the separately declared CPU Torch build"
            )
        from experiments.multimodal_output_portfolio.joint_hepta_20261029.v3.decision_audit.acquire_models import (
            MODELS,
        )

        torch.set_num_threads(2)
        value = torch.ones((4, 4), device="cpu", dtype=torch.bfloat16)
        result.update(
            actual_device=str(value.device),
            actual_dtype=str(value.dtype),
            actual_sum=float((value @ value).sum()),
            model_pins=MODELS,
            torch_threads=torch.get_num_threads(),
        )
        if result["actual_sum"] != 64.0:
            raise ValueError("Actual CPU bfloat16 arithmetic failed")
        result["verified"] = True
    except Exception as error:
        result["error"] = {"type": type(error).__name__, "message": str(error)}
        raise
    finally:
        write(output, result)


def verify_pool(pool, output):
    from .pilot_data import load_pool

    _, admission = load_pool(pool)
    manifest = json.loads((Path(pool) / "CANDIDATES.json").read_text())
    write(
        output,
        {
            "admission": admission,
            "pool_use": "reuse_existing_verified_bytes",
            "official_download_performed": False,
            "metadata_regenerated": False,
            "prior_acquisition_receipt": manifest["acquisition_receipt"],
            "prior_acquisition_cost_included_in_this_run": False,
        },
    )


def retain_critical(evidence, output):
    """Keep original proof and actual small cost receipts even if the large pack fails."""
    paths = list(evidence.glob("*.meter.json"))
    paths += [
        evidence / name
        for name in (
            "SOURCE_MANIFEST.json",
            "CPU_PROFILE.json",
            "KAGGLE_ARTIFACT_MANIFEST.json",
            "FALLBACK_EVIDENCE.json",
            "CPU_PREFLIGHT.json",
            "POOL_REUSE.json",
        )
        if (evidence / name).is_file()
    ]
    paths += list((evidence / "kaggle-original").glob("*.json"))
    paths += [p for p in (evidence / "model-records").rglob("*") if p.is_file()]
    if sum(p.stat().st_size for p in paths) > 16 * 1024**2:
        raise ValueError("Critical receipt subset exceeds its bounded export allowance")
    retained = []
    for path in sorted(paths):
        target = output / "critical" / path.relative_to(evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        identity = sha(path)
        if sha(target) != identity:
            raise ValueError("Critical receipt changed while copying")
        retained.append(
            {
                "path": target.relative_to(output).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": identity,
            }
        )
    return retained


def run(args):
    started = time.process_time(), time.perf_counter()
    valid_budget = (
        type(args.budget_seconds) in (int, float)
        and math.isfinite(args.budget_seconds)
        and 60 <= args.budget_seconds <= 1740
    )
    deadline = started[1] + (args.budget_seconds if valid_budget else 5)
    output, work, source, pool = map(
        Path, (args.output, args.workspace, args.source_root, args.pool)
    )
    output.mkdir(parents=True, exist_ok=False)
    evidence = work / "evidence"
    models = work / "models"
    report = {
        "request_id": args.request_id,
        "source_sha": args.source_sha,
        "provider": PROVIDER,
        "experiment_status": "Failed",
        "scientific_acceptance": False,
        "native_owner_verified": False,
        "gpu_execution_verified": False,
        "worker_budget_seconds": args.budget_seconds if valid_budget else None,
        "declared_resources": {"cpu_quota_percent": 200, "memory_max_bytes": MEMORY},
        "artifact_complete": False,
        "stages": [
            {"name": name, "wall_cap_seconds": cap, "status": "not_started"}
            for name, cap in STAGES.items()
        ],
        "unknown_costs": [
            "energy",
            "prior_acquisition_excluded",
            "source_and_pool_transfer_before_worker",
            "final_export_write",
        ],
    }
    previous = {
        s: signal.getsignal(s) for s in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)
    }
    affinity = os.sched_getaffinity(0)

    def expired(_signal, _frame):
        raise TimeoutError("Total desktop CPU pilot wall deadline reached")

    def cancelled(signum, _frame):
        report["cancellation_signal"] = signum
        raise KeyboardInterrupt("Desktop CPU pilot cancellation")

    armed = False
    try:
        work.mkdir(parents=True, exist_ok=False)
        evidence.mkdir()
        if not valid_budget:
            raise ValueError(
                "CPU fallback budget must be finite and in [60,1740] seconds"
            )
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, args.budget_seconds)
        armed = True
        signal.signal(signal.SIGTERM, cancelled)
        signal.signal(signal.SIGINT, cancelled)
        verify_source(
            source, args.source_manifest, args.source_manifest_sha256, args.source_sha
        )
        report["fallback_evidence"] = fallback_evidence(
            args.kaggle_artifacts,
            args.kaggle_manifest,
            args.kaggle_manifest_sha256,
            args.kaggle_request_id,
            args.kaggle_source_sha,
            args.request_id,
            args.kaggle_result_path,
            args.kaggle_probe_path,
        )
        for src, name in (
            (args.source_manifest, "SOURCE_MANIFEST.json"),
            (args.profile, "CPU_PROFILE.json"),
            (args.kaggle_manifest, "KAGGLE_ARTIFACT_MANIFEST.json"),
        ):
            shutil.copyfile(src, evidence / name)
        if (
            sha(evidence / "KAGGLE_ARTIFACT_MANIFEST.json")
            != args.kaggle_manifest_sha256
        ):
            raise ValueError("Kaggle manifest changed after admission")
        originals = evidence / "kaggle-original"
        originals.mkdir()
        for name, digest_key, stored_name in (
            (args.kaggle_result_path, "result_sha256", "BOOTSTRAP_RESULT.json"),
            (args.kaggle_probe_path, "probe_sha256", "ACTUAL_PREINSTALLED_DEVICE.json"),
        ):
            target = originals / stored_name
            shutil.copyfile(Path(args.kaggle_artifacts) / name, target)
            if sha(target) != report["fallback_evidence"][digest_key]:
                raise ValueError("Kaggle proof bytes changed after admission")
        report["fallback_evidence"]["original_paths"] = {
            "result": args.kaggle_result_path,
            "probe": args.kaggle_probe_path,
        }
        write(evidence / "FALLBACK_EVIDENCE.json", report["fallback_evidence"])
        profile = json.loads(Path(args.profile).read_text())
        check_profile(profile)
        report["resources_before"] = resource_snapshot()
        if len(affinity) < 2:
            raise ValueError("The declared two-CPU affinity opportunity is unavailable")
        os.sched_setaffinity(0, set(sorted(affinity)[:2]))
        os.environ.update(
            PYTHONPATH=str(source / "scripts") + os.pathsep + str(source),
            PYTHONDONTWRITEBYTECODE="1",
            HF_HOME=str(work / "hf-cache"),
            OMP_NUM_THREADS="2",
            MKL_NUM_THREADS="2",
            OPENBLAS_NUM_THREADS="2",
        )
        commands = Commands(evidence, report, deadline)
        python = args.python
        worker = [python, "-B", "-m", "ndu_portfolio.local_cpu_pilot"]
        commands.execute(
            "cpu_preflight",
            worker + ["preflight", "--output", str(evidence / "CPU_PREFLIGHT.json")],
        )
        commands.execute(
            "verify_existing_pool",
            worker
            + [
                "verify-pool",
                "--pool",
                str(pool),
                "--output",
                str(evidence / "POOL_REUSE.json"),
            ],
        )
        plan = evidence / "PLAN.json"
        cli = [python, "-B", "-m", "ndu_portfolio.pilot_cli"]
        commands.execute(
            "plan",
            cli
            + [
                "plan",
                "--pool",
                str(pool),
                "--profile",
                args.profile,
                "--source-sha",
                args.source_sha,
                "--output",
                str(plan),
            ],
        )
        commands.execute(
            "models",
            [python, "-B", "-m", NATIVE + "acquire_models", "--root", str(models)],
        )
        smoke = evidence / "cpu-smoke"
        commands.execute(
            "cpu_generator_smoke",
            [
                python,
                "-B",
                "-m",
                NATIVE + "device_smoke",
                "--models",
                str(models),
                "--image",
                str(pool / "data/VizWiz_train_00000000/input.jpg"),
                "--output",
                str(smoke),
                "--source-sha",
                args.source_sha,
                "--device",
                "cpu",
                "--dtype",
                "bfloat16",
            ],
        )
        smoke_result = json.loads((smoke / "DEVICE_SMOKE.json").read_text())
        if (
            smoke_result["gpu_execution_verified"] is not False
            or smoke_result["backend"]["device"] != "cpu"
            or smoke_result["backend"]["dtype"] != "bfloat16"
        ):
            raise ValueError(
                "CPU smoke cannot be replaced by another numerical/device profile"
            )
        common = ["--pool", str(pool), "--plan", str(plan), "--plan-sha256", sha(plan)]
        for name, stage, prior in (
            ("collect", "collect", None),
            ("score_collect", "score", "collect"),
            ("fit", "fit", "score_collect"),
            ("evaluate", "evaluate", "fit"),
            ("score_evaluate", "score", "evaluate"),
        ):
            command = cli + [stage] + common + ["--output", str(evidence / name)]
            if stage in ("collect", "evaluate"):
                command += ["--models", str(models)]
            if prior:
                path = evidence / prior / "PHASE.json"
                command += ["--input", str(path), "--input-sha256", sha(path)]
            if stage == "score":
                command += ["--input-phase", prior]
            commands.execute(name, command)
        report["resources_after"] = resource_snapshot()
        report["experiment_status"] = "CompletedCpuEngineeringPilot"
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        try:
            for path in models.rglob("*.json*"):
                if path.name in (
                    "MANIFEST.json",
                    "ACQUISITION.json",
                    "ACQUISITION_ATTEMPTS.jsonl",
                    "INPUT_MANIFEST.json",
                ):
                    target = evidence / "model-records" / path.relative_to(models)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
            if (evidence / "CPU_PREFLIGHT.json").exists():
                report["actual_cpu_runtime"] = json.loads(
                    (evidence / "CPU_PREFLIGHT.json").read_text()
                )
            report["critical_receipts"] = retain_critical(evidence, output)
            report.update(
                launcher_cpu_seconds=time.process_time() - started[0],
                elapsed_wall_seconds=time.perf_counter() - started[1],
            )
            write(evidence / "CAMPAIGN.json", report)
            archive_cap = (
                LIMIT
                - sum(row["bytes"] for row in report["critical_receipts"])
                - 1024**2
            )
            report["evidence_pack"] = pack_evidence(
                {"execution": evidence, "reused_materials": pool},
                output / "evidence.tar.gz",
                deadline,
                cap=archive_cap,
            )
            report["artifact_complete"] = True
        except BaseException as error:
            report.update(
                experiment_status="Failed",
                artifact_complete=False,
                packaging_error={"type": type(error).__name__, "message": str(error)},
            )
            pack = output / "evidence.tar.gz"
            if pack.exists():
                if (
                    sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
                    > LIMIT - 1024**2
                ):
                    pack.unlink()
                else:
                    pack.rename(output / "evidence.partial.tar.gz")
        finally:
            if armed:
                signal.setitimer(signal.ITIMER_REAL, 0)
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            os.sched_setaffinity(0, affinity)
            report.update(
                launcher_cpu_seconds=time.process_time() - started[0],
                elapsed_wall_seconds=time.perf_counter() - started[1],
            )
            write(output / "CPU_RESULT.json", report)
            artifact_manifest(output, args.request_id)
    return 0 if report["experiment_status"] == "CompletedCpuEngineeringPilot" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("run")
    for field in (
        "source-root",
        "source-sha",
        "source-manifest",
        "source-manifest-sha256",
        "pool",
        "profile",
        "workspace",
        "output",
        "request-id",
        "kaggle-artifacts",
        "kaggle-manifest",
        "kaggle-manifest-sha256",
        "kaggle-request-id",
        "kaggle-source-sha",
    ):
        execute.add_argument("--" + field, required=True)
    execute.add_argument("--python", default=DEFAULT_PYTHON)
    execute.add_argument("--budget-seconds", type=float, default=1740)
    execute.add_argument("--kaggle-result-path", default="BOOTSTRAP_RESULT.json")
    execute.add_argument(
        "--kaggle-probe-path", default="ACTUAL_PREINSTALLED_DEVICE.json"
    )
    preflight = sub.add_parser("preflight")
    preflight.add_argument("--output", required=True)
    pool = sub.add_parser("verify-pool")
    pool.add_argument("--pool", required=True)
    pool.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "run":
        return run(args)
    if args.command == "preflight":
        cpu_preflight(args.output)
    else:
        verify_pool(args.pool, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
