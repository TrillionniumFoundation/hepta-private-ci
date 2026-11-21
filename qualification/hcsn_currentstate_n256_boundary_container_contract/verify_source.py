"""Verify the frozen source-only N256 boundary container contract."""

import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_boundary_container_contract import (
    static_inspector,
)


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    if request["schema"] != "hcsn-n256-boundary-container-contract-v1":
        raise ValueError("request schema")
    if request["parent_source_commit"] != "778b42b174a8bbe3d1735eda1f7e69128459156a":
        raise ValueError("parent source commit")
    if request["parent_source_tree"] != "b8e2f2c12bbc249801912f2596e6dfb82de6adc9":
        raise ValueError("parent source tree")
    if request["execution_allowed"] or request["numerical_execution_allowed"]:
        raise ValueError("authentic execution must remain disabled")
    if request["unique_execution_key"] is not None:
        raise ValueError("source-only stage must not have an execution key")
    boundary = request["boundary"]
    if boundary["coordinate_denominator"] != 68105:
        raise ValueError("boundary denominator")
    if boundary["mismatch_allowance"] != 0 or boundary["dtype"] != "<f8":
        raise ValueError("byte-exact gate")
    if any(request["source_only_counts"].values()):
        raise ValueError("authentic source-only counters")
    if request["boundary_compared"] or request["qualification"] or request["all_closed"]:
        raise ValueError("qualification claim")
    if request["c2_full_replay_completed_fits"] != 0:
        raise ValueError("C2 full replay claim")
    if request["hpca_update"] != "NoUpdate":
        raise ValueError("HPCA status")
    expected_files = {
        path.relative_to(ROOT).as_posix()
        for path in HERE.iterdir()
        if path.is_file() and path.name != "SOURCE_FREEZE.json"
    }
    if set(freeze["source_sha256"]) != expected_files:
        raise ValueError("complete source freeze")
    for relative, expected in freeze["source_sha256"].items():
        if _digest(ROOT / relative) != expected:
            raise ValueError(f"source digest: {relative}")
    static = static_inspector.verify()
    if static["authentic_boundary_calls"] != 0:
        raise ValueError("static authentic execution count")
    return {
        "status": "PASS_SOURCE_ONLY_BOUNDARY_CONTAINER_HOLD",
        "boundary_coordinates": 68105,
        "authentic_boundary_calls": 0,
        "qualification": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
