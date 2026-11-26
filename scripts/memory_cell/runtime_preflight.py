"""Capture host/runtime conditions before a fixed-reader model call.

The report is diagnostic provenance only.  The default reader thread settings
are unchanged; setting ``HEPTA_MEMORY_BOUNDED_THREADS=1`` opts into a separate
bounded-thread diagnostic (intra/inter-op and the common BLAS variables set to
one).  This module never changes data, model, or scoring inputs.
"""

from collections.abc import Mapping, MutableMapping
import os
from pathlib import Path
import subprocess


BOUNDED_THREADS_ENV = "HEPTA_MEMORY_BOUNDED_THREADS"
THREAD_ENV_VARS = ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
_RUNNER_METADATA_KEYS = {
    "ACTIONS_RUNNER_VERSION",
    "AWS_DEFAULT_REGION",
    "AWS_REGION",
    "AZURE_REGION",
    "CLOUD_REGION",
    "GITHUB_ACTIONS",
    "GITHUB_EVENT_NAME",
    "GITHUB_JOB",
    "GITHUB_REF",
    "GITHUB_REF_NAME",
    "GITHUB_REPOSITORY",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER",
    "GITHUB_SHA",
    "GITHUB_WORKFLOW",
    "GITHUB_WORKFLOW_REF",
    "ImageOS",
    "ImageVersion",
    "REGION",
    "RUNNER_ARCH",
    "RUNNER_ENVIRONMENT",
    "RUNNER_LOCATION",
    "RUNNER_NAME",
    "RUNNER_OS",
    "RUNNER_REGION",
    "RUNNER_TEMP",
    "RUNNER_ZONE",
}
_OUTPUT_LIMIT = 256 * 1024
_MEMINFO_LIMIT = 1024 * 1024


def bounded_threads_requested(environ: Mapping[str, str] | None = None) -> bool:
    """Return true only for an explicit diagnostic opt-in."""

    values = os.environ if environ is None else environ
    return values.get(BOUNDED_THREADS_ENV, "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }


def apply_bounded_thread_environment(
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, str]:
    """Set BLAS/OpenMP variables to one for an opted-in process only."""

    values = os.environ if environ is None else environ
    for name in THREAD_ENV_VARS:
        values[name] = "1"
    return {name: values[name] for name in THREAD_ENV_VARS}


def configure_torch(torch_module, *, bounded: bool) -> dict[str, object]:
    """Apply the existing default or the explicitly bounded torch settings."""

    intra_op = 1 if bounded else 2
    torch_module.set_num_threads(intra_op)
    if bounded:
        torch_module.set_num_interop_threads(1)
    return {
        "requested": bounded,
        "target_intra_op": intra_op,
        "target_inter_op": 1 if bounded else None,
        "effective_intra_op": torch_module.get_num_threads(),
        "effective_inter_op": torch_module.get_num_interop_threads(),
    }


def _run(command: tuple[str, ...]) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {
            "argv": list(command),
            "returncode": None,
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
        }
    return {
        "argv": list(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout[:_OUTPUT_LIMIT],
        "stderr": completed.stderr[:_OUTPUT_LIMIT],
    }


def _read_meminfo() -> dict[str, object]:
    path = Path("/proc/meminfo")
    try:
        raw = path.read_bytes()
    except OSError as error:
        return {"available": False, "error": f"{type(error).__name__}: {error}"}
    if len(raw) > _MEMINFO_LIMIT:
        raw = raw[:_MEMINFO_LIMIT]
    return {"available": True, "bytes": len(raw), "text": raw.decode(errors="replace")}


def _affinity() -> dict[str, object]:
    try:
        cpus = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError) as error:
        return {"available": False, "error": f"{type(error).__name__}: {error}"}
    return {"available": True, "count": len(cpus), "cpus": cpus}


def _runner_metadata(environ: Mapping[str, str]) -> dict[str, object]:
    values = {
        key: environ[key] for key in sorted(_RUNNER_METADATA_KEYS) if key in environ
    }
    region = {
        key: value
        for key, value in values.items()
        if key.upper().endswith(("REGION", "LOCATION", "ZONE"))
    }
    image = {
        key: value
        for key, value in values.items()
        if "IMAGE" in key.upper() or key == "RUNNER_OS"
    }
    return {"all": values, "region": region, "image": image}


def capture_runtime(
    torch_module,
    *,
    bounded: bool,
    thread_control: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Capture bounded host and runtime facts without touching experiment inputs."""

    values = os.environ if environ is None else environ
    torch_info = {"version": str(getattr(torch_module, "__version__", "unknown"))}
    for name, getter in (
        ("intra_op_threads", torch_module.get_num_threads),
        ("inter_op_threads", torch_module.get_num_interop_threads),
    ):
        try:
            torch_info[name] = getter()
        except (AttributeError, RuntimeError) as error:
            torch_info[name] = None
            torch_info[f"{name}_error"] = f"{type(error).__name__}: {error}"
    return {
        "schema": "hepta.memory.runtime-preflight.v1",
        "bounded_thread_diagnostic_requested": bounded,
        "thread_control": dict(thread_control or {}),
        "thread_environment": {name: values.get(name) for name in THREAD_ENV_VARS},
        "torch": torch_info,
        "commands": {
            "lscpu": _run(("lscpu",)),
            "nproc": _run(("nproc",)),
            "nproc_all": _run(("nproc", "--all")),
        },
        "affinity": _affinity(),
        "meminfo": _read_meminfo(),
        "runner": _runner_metadata(values),
    }
