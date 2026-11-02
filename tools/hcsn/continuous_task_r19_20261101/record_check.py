"""Standard-library record integrity check; no candidate or NumPy imports."""

import hashlib
import itertools
import json
from pathlib import Path
import sys


def check():
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    result_path = root / sys.argv[1]
    result = json.loads(result_path.read_text())
    for item in freeze["files"]:
        raw = (root / item["path"]).read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    assert result["protocol"] == protocol
    for name, digest in result["source_sha256"].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    expected = set(itertools.product(range(len(protocol["profiles"])),
                                    map(tuple, protocol["meshes"]),
                                    result["candidate_parameters"], protocol["fd_steps"]))
    observed = set()
    coverage = {p: False for p in result["candidate_parameters"]}
    stable_count = passing_count = scalar_checks = 0
    for row in result["records"]:
        key = (row["profile"], (row["dx"], row["dt"]), row["parameter"], row["step"])
        assert key not in observed
        observed.add(key)
        assert row["passed"] == (row["maximum_scaled_error"] <= protocol["whole_array_scaled_fd_tolerance"])
        stable = all(s["right"] == s["left"] == 0 for s in row["branch_changes_plus_minus"])
        assert row["stable"] == stable
        stable_count += stable
        passing_count += row["passed"]
        scalar_checks += row["scalar_checks"]
        coverage[row["parameter"]] |= stable and row["passed"]
        case = next(c for c in result["cases"] if c["profile"] == row["profile"]
                    and (c["dx"], c["dt"]) == key[1])
        config = case["config"]
        expected_count = 2 * (round(config["horizon"] / row["dt"]) + 1) * (
            round((config["upper"] - config["lower"]) / row["dx"]) + 1)
        assert row["scalar_checks"] == expected_count
    assert observed == expected and coverage == result["stable_passing_coordinate_coverage"]
    assert all(c["primal_maximum_absolute_error"] <= protocol["primal_absolute_tolerance"]
               and c["derivatives_finite"] for c in result["cases"])
    jumps = {str(mesh): any((c["dx"], c["dt"]) == tuple(mesh)
                           and any(j["maximum_jump"] > 0 and j["derivative_jump_norm"] > 0
                                   for j in c["jump_records"]) for c in result["cases"])
             for mesh in protocol["meshes"]}
    assert jumps == result["nonzero_jump_mesh_coverage"]
    passed = all(r["passed"] for r in result["records"]) and all(coverage.values()) and all(jumps.values())
    assert passed == result["passed"]
    return dict(schema="hcsn-r19-independent-record-check-v1", integrity_passed=True,
                original_gradient_gate_passed=passed, records=len(observed), scalar_checks=scalar_checks,
                stable_records=stable_count, passed_records=passing_count,
                failed_records=len(observed) - passing_count,
                unstable_records=len(observed) - stable_count,
                all_failed_are_unstable=all(not r["stable"] for r in result["records"] if not r["passed"]),
                maximum_scaled_error=max(r["maximum_scaled_error"] for r in result["records"]),
                stable_maximum_scaled_error=max(r["maximum_scaled_error"] for r in result["records"] if r["stable"]),
                admission_maximum_scaled_error=max(r["admission_maximum_scaled_error"] for r in result["records"]),
                coordinate_coverage=coverage, jump_coverage=jumps, rejection_count=len(result["rejections"]),
                primal_maximum_absolute_error=max(c["primal_maximum_absolute_error"] for c in result["cases"]),
                inputs={result_path.name: hashlib.sha256(result_path.read_bytes()).hexdigest(),
                        "SOURCE_FREEZE.json": hashlib.sha256((root / "SOURCE_FREEZE.json").read_bytes()).hexdigest()},
                limitations=["record-only integrity and aggregate recomputation; per-scalar FD arrays are not stored",
                             "does not independently re-execute numerical solvers or establish global differentiability"])


if __name__ == "__main__":
    report = check()
    target = Path(__file__).resolve().parent / sys.argv[2]
    with target.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
