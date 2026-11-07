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
