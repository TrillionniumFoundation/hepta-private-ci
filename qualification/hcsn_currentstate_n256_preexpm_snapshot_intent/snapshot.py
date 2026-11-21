"""Construct and compare current-source pre-exponential inputs without propagation."""

import hashlib
import io
import json
import os
import platform
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ATTEMPT002_ZIP = ROOT / (
    "qualification/hcsn_currentstate_n256_authentic_boundary_attempt002/"
    "evidence/originals/artifact.zip"
)
RUNTIME_RED_ZIP = ROOT / (
    "qualification/hcsn_currentstate_n256_runtime_matched_red_evidence/artifact.zip"
)
EXPECTED_BOUNDARY_SHA256 = (
    "e580e44a679ecf9e2588c989cd4d026e326e7364331c46d1927b00ccada78fd4"
)
UNIQUE_KEY = "hcsn-n256-preexpm-input-snapshot-20261121-c6bc-001"
DISCOUNT = 0.15


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read_member(archive, name):
    raw = archive.read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as handle:
        payload = handle.read(name)
    return raw, payload


def _host_before_numpy():
    cpuinfo = Path("/proc/cpuinfo").read_text(errors="replace")
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "python_executable": sys.executable,
        "python_executable_sha256": _sha(Path(sys.executable).read_bytes()),
        "cpuinfo_sha256": _sha(cpuinfo.encode()),
        "cpuinfo": cpuinfo,
        "thread_environment": {
            name: os.environ.get(name)
            for name in (
                "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS",
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
            )
        },
    }


def _arrays(boundary, np, decode_boundary):
    sections = decode_boundary(boundary)
    return {
        "extended_generator": np.frombuffer(
            sections["extended_generator"], dtype="<f8"
        ).reshape(257, 257),
        "initial": np.frombuffer(sections["initial"], dtype="<f8").reshape(5, 257),
        "lower_selector": np.frombuffer(
            sections["lower_selector"], dtype="<f8"
        ).reshape(257, 1),
        "discounted_selectors": np.frombuffer(
            sections["discounted_selectors"], dtype="<f8"
        ).reshape(257, 2),
    }


def _preexpm(generator, initial, selectors, discount, np):
    outputs = selectors.shape[1]
    dimension = generator.shape[0]
    augmented = np.zeros((dimension + outputs, dimension + outputs), dtype="float64")
    augmented[:dimension, :dimension] = generator - discount * np.eye(dimension)
    augmented[:dimension, dimension:] = selectors
    seed = np.concatenate(
        (initial, np.zeros((initial.shape[0], outputs), dtype="float64")), axis=1
    )
    return (
        np.ascontiguousarray(augmented, dtype="<f8").tobytes(order="C"),
        np.ascontiguousarray(seed, dtype="<f8").tobytes(order="C"),
    )


def _write(path, raw):
    path.write_bytes(raw)
    return {"bytes": len(raw), "sha256": _sha(raw)}


def execute(output):
    """Run the one admitted diagnostic; this function never calls an exponential."""
    if os.environ.get("HCSN_UNIQUE_EXECUTION_KEY") != UNIQUE_KEY:
        raise RuntimeError("unique execution key")
    host = _host_before_numpy()

    import numpy as np

    from qualification.hcsn_currentstate_n256_boundary_container_contract.boundary_codec import (
        decode_boundary,
    )

    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    attempt_zip, oracle = _read_member(ATTEMPT002_ZIP, "ORACLE_BOUNDARY.bin")
    _attempt_zip_2, candidate = _read_member(ATTEMPT002_ZIP, "CANDIDATE_BOUNDARY.bin")
    runtime_zip, rebuilt = _read_member(RUNTIME_RED_ZIP, "REBUILT_BOUNDARY.bin")
    boundaries = {"oracle": oracle, "candidate": candidate, "rebuilt": rebuilt}
    for name, raw in boundaries.items():
        if _sha(raw) != EXPECTED_BOUNDARY_SHA256:
            raise RuntimeError(f"{name} boundary identity")

    products = {}
    for name, boundary in boundaries.items():
        values = _arrays(boundary, np, decode_boundary)
        lanes = {
            "undiscounted": _preexpm(
                values["extended_generator"],
                values["initial"],
                values["lower_selector"],
                0.0,
                np,
            ),
            "discounted": _preexpm(
                values["extended_generator"],
                values["initial"],
                values["discounted_selectors"],
                DISCOUNT,
                np,
            ),
        }
        products[name] = lanes
        for lane, (augmented, seed) in lanes.items():
            _write(output / f"{name}-{lane}-augmented.bin", augmented)
            _write(output / f"{name}-{lane}-seed.bin", seed)

    comparisons = {}
    for peer in ("candidate", "rebuilt"):
        comparisons[peer] = {}
        for lane in ("undiscounted", "discounted"):
            oracle_augmented, oracle_seed = products["oracle"][lane]
            peer_augmented, peer_seed = products[peer][lane]
            comparisons[peer][lane] = {
                "augmented_byte_equal": oracle_augmented == peer_augmented,
                "seed_byte_equal": oracle_seed == peer_seed,
                "coordinates": (len(oracle_augmented) + len(oracle_seed)) // 8,
            }

    host["numpy_version"] = np.__version__
    host["numpy_config"] = np.__config__.show(mode="dicts")
    host["numpy_cpu_features"] = dict(
        sorted(np._core._multiarray_umath.__cpu_features__.items())
    )
    host["github"] = {
        name: os.environ.get(name)
        for name in (
            "GITHUB_REPOSITORY",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_RUN_ID",
            "GITHUB_SHA",
            "RUNNER_ARCH",
            "RUNNER_NAME",
            "RUNNER_OS",
        )
    }
    (output / "HOST.json").write_text(
        json.dumps(host, indent=2, sort_keys=True) + "\n"
    )
    result = {
        "schema": "hcsn-n256-preexpm-input-snapshot-result-v1",
        "identity": UNIQUE_KEY,
        "source_boundary_inputs": {
            "attempt002_zip_sha256": _sha(attempt_zip),
            "runtime_red_zip_sha256": _sha(runtime_zip),
            "boundary_sha256": EXPECTED_BOUNDARY_SHA256,
        },
        "comparisons": comparisons,
        "outputs": {
            path.name: {"bytes": path.stat().st_size, "sha256": _sha(path.read_bytes())}
            for path in sorted(output.glob("*.bin"))
        },
        "counters": {
            "boundary_decodes": 3,
            "preexpm_augmented_builds": 6,
            "preexpm_seed_builds": 6,
            "dynamic_steps": 0,
            "dense_exponential_actions": 0,
            "sparse_exponential_actions": 0,
            "scipy_imports": 0,
            "torch_calls": 0,
            "optimizer_steps": 0,
        },
        "scope": {
            "current_source_preexpm_inputs_byte_equal": all(
                item["augmented_byte_equal"] and item["seed_byte_equal"]
                for peer in comparisons.values()
                for item in peer.values()
            ),
            "original_oracle_run_preexpm_bytes_published": False,
            "expm_arithmetic_path_qualified": False,
            "n256_dynamic_qualified": False,
            "production_adoption": False,
            "all_closed": False,
            "cause_of_6901_red": "UNKNOWN",
        },
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    return result

