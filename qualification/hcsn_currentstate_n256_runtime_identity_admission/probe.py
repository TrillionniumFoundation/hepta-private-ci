"""Read-only exact runtime admission; never executes the N256 candidate."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time
import zipfile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
NUMERIC_ROOTS = ("numpy", "scipy", "torch")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _numeric_modules() -> list[str]:
    return sorted(
        name
        for name in sys.modules
        if name in NUMERIC_ROOTS or name.startswith(tuple(root + "." for root in NUMERIC_ROOTS))
    )


def _distribution_identity(name: str) -> dict[str, str]:
    dist = importlib.metadata.distribution(name)
    files = list(dist.files or ())
    record_matches = [item for item in files if str(item).endswith(".dist-info/RECORD")]
    init_matches = [item for item in files if str(item) == f"{name}/__init__.py"]
    if len(record_matches) != 1 or len(init_matches) != 1:
        raise RuntimeError(f"ambiguous installed {name} identity")
    record = Path(dist.locate_file(record_matches[0]))
    init = Path(dist.locate_file(init_matches[0]))
    return {
        "version": dist.version,
        "record_sha256": _sha256(record),
        "init_sha256": _sha256(init),
    }


def _observe_runtime() -> dict[str, object]:
    return {
        "machine": platform.machine(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable_sha256": _sha256(Path(sys.executable)),
        "numpy": _distribution_identity("numpy"),
        "scipy": _distribution_identity("scipy"),
        "thread_environment": {
            key: os.environ.get(key)
            for key in ("MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    request = json.loads((HERE / "REQUEST.json").read_text(encoding="utf-8"))
    oracle_zip = ROOT / request["oracle_zip"]
    if _sha256(oracle_zip) != request["oracle_zip_sha256"]:
        raise RuntimeError("oracle ZIP identity mismatch")
    with zipfile.ZipFile(oracle_zip) as archive:
        oracle_snapshot = json.loads(archive.read("HOST_SNAPSHOT.json"))
    if oracle_snapshot["runtime_sha256"] != request["oracle_runtime_sha256"]:
        raise RuntimeError("oracle runtime receipt mismatch")
    before = _numeric_modules()
    observed = _observe_runtime()
    after = _numeric_modules()
    if before or after:
        raise RuntimeError(f"numeric module imported during identity probe: {after}")

    expected = request["expected_runtime"]
    comparisons = {
        "machine": observed["machine"] == expected["machine"],
        "python_version": observed["python_version"] == expected["python_version"],
        "python_executable_sha256": observed["python_executable_sha256"] == expected["python_executable_sha256"],
        "numpy_version": observed["numpy"]["version"] == expected["numpy_version"],
        "numpy_record_sha256": observed["numpy"]["record_sha256"] == expected["numpy_record_sha256"],
        "numpy_init_sha256": observed["numpy"]["init_sha256"] == expected["numpy_init_sha256"],
        "scipy_version": observed["scipy"]["version"] == expected["scipy_version"],
        "scipy_record_sha256": observed["scipy"]["record_sha256"] == expected["scipy_record_sha256"],
        "scipy_init_sha256": observed["scipy"]["init_sha256"] == expected["scipy_init_sha256"],
        "thread_environment": observed["thread_environment"] == expected["thread_environment"],
    }
    admitted = all(comparisons.values())
    result = {
        "schema": "hcsn-n256-runtime-identity-admission-result-v1",
        "identity": request["identity"],
        "oracle_runtime_sha256": request["oracle_runtime_sha256"],
        "observed": observed,
        "comparisons": comparisons,
        "mismatch_fields": sorted(key for key, value in comparisons.items() if not value),
        "admitted": admitted,
        "candidate_execution_authorized": admitted,
        "candidate_executed": false,
        "numeric_modules_imported": after,
        "candidate_model_calls": 0,
        "dynamic_steps": 0,
        "dense_expm_actions": 0,
        "sparse_expm_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "qualification": False,
        "production_adoption": False,
        "all_closed": False,
    }
    cost = {
        "wall_seconds": time.perf_counter() - started_wall,
        "cpu_seconds": time.process_time() - started_cpu,
        "oracle_zip_decodes": 1,
        "runtime_metadata_reads": 1,
        "candidate_model_calls": 0,
        "dynamic_steps": 0,
        "expm_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "RESULT.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output / "COST.json").write_text(json.dumps(cost, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

