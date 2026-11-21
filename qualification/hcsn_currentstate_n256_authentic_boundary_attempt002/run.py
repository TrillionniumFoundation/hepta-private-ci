"""Execute the two frozen boundary builders once and stop before propagation."""

import hashlib
import importlib
import json
import os
import resource
import sys
import time
import traceback
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_boundary_attempt002 import (
    resource_guard,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = HERE / "RUN_OUTPUT"
ORACLE_FILE = OUTPUT / "ORACLE_BOUNDARY.bin"
CANDIDATE_FILE = OUTPUT / "CANDIDATE_BOUNDARY.bin"


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _json(path, value):
    temporary = Path(f"{path}.tmp")
    temporary.write_text(resource_guard.canonical(value))
    os.replace(temporary, path)


def _bytes(path, value):
    temporary = Path(f"{path}.tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def main():
    OUTPUT.mkdir(parents=False, exist_ok=False)
    started_wall = time.time()
    started_cpu = time.process_time()
    counters = {
        "authentic_distinct_input_file_accesses": 0,
        "npz_decodes": 0,
        "boundary_builds": 0,
        "container_encodes": 0,
        "exact_comparator_calls": 0,
        "dynamic_steps": 0,
        "dense_exponential_actions": 0,
        "sparse_exponential_actions": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
    }
    report = {
        "identity": "hcsn-n256-authentic-boundary-attempt002-20261121-c06d",
        "unique_execution_key": resource_guard.KEY,
        "result": "ERROR",
        "qualification": False,
        "all_closed": False,
        "counters": counters,
    }
    _json(
        OUTPUT / "START.json",
        {
            "identity": report["identity"],
            "unique_execution_key": resource_guard.KEY,
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
    )
    try:
        _json(OUTPUT / "PRE_RESOURCE.json", resource_guard.capture())
        admission = resource_guard.admit()
        _json(OUTPUT / "ADMISSION.json", admission)
        oracle = importlib.import_module(
            "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.oracle_boundary_builder"
        )
        candidate = importlib.import_module(
            "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.candidate_boundary_builder"
        )
        comparator = importlib.import_module(
            "qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2.compare_runner"
        )
        oracle_raw = oracle.build_boundary(ROOT)
        counters["authentic_distinct_input_file_accesses"] += 4
        counters["npz_decodes"] += 1
        counters["boundary_builds"] += 1
        counters["container_encodes"] += 1
        _bytes(ORACLE_FILE, oracle_raw)
        candidate_raw = candidate.build_boundary(ROOT)
        counters["authentic_distinct_input_file_accesses"] += 4
        counters["npz_decodes"] += 1
        counters["boundary_builds"] += 1
        counters["container_encodes"] += 1
        _bytes(CANDIDATE_FILE, candidate_raw)
        counters["exact_comparator_calls"] += 1
        report["exact_comparator"] = comparator.compare_published(
            ORACLE_FILE, CANDIDATE_FILE
        )
        report["result"] = "EXACT"
    except Exception as error:  # the original exception is part of the evidence
        report["result"] = (
            "RED" if ORACLE_FILE.is_file() and CANDIDATE_FILE.is_file() else "ERROR"
        )
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        report["traceback"] = traceback.format_exc()
    finally:
        try:
            _json(OUTPUT / "POST_RESOURCE.json", resource_guard.capture())
        except Exception as error:
            report["post_resource_error"] = f"{type(error).__name__}: {error}"
        report["outputs"] = {
            path.name: {"bytes": path.stat().st_size, "sha256": _sha(path)}
            for path in (ORACLE_FILE, CANDIDATE_FILE)
            if path.is_file()
        }
        report["wall_seconds"] = time.time() - started_wall
        report["cpu_seconds"] = time.process_time() - started_cpu
        report["maximum_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["numerical_modules"] = {
            name: name in sys.modules for name in ("numpy", "scipy", "torch")
        }
        _json(OUTPUT / "RUN.json", report)
    return 0 if report["result"] == "EXACT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
