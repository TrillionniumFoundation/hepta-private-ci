"""Independent standard-library checks of prospective followup records only."""

import hashlib
import itertools
import json
from pathlib import Path
import re
import sys


PARAMETERS = ("sigma", "wait_cost", "recovery_cost", "reset_x", "reset_fee_0",
              "reset_fee_1", "retention_0", "retention_1", "reward_base_0",
              "reward_base_1", "reward_amplitude_0", "reward_amplitude_1", "reward_slope")


def check(result_name):
    root = Path(__file__).resolve().parent
    result_path = root / result_name
    result = json.loads(result_path.read_text())
    protocol = json.loads((root / "FOLLOWUP_PROTOCOL.json").read_text())
    freeze = json.loads((root / "FOLLOWUP_SOURCE_FREEZE.json").read_text())
    assert result["protocol"] == protocol and result["source_freeze"] == freeze
    assert len(freeze["files"]) == 11
    for item in freeze["files"]:
        raw = (root / item["path"]).read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], item["path"]
    assert any(item["path"] == "CONFIRMATION.json" for item in freeze["files"])
    original = json.loads((root / "CONFIRMATION.json").read_text())
    assert original["passed"] is False and result["original_registered_gate"] is False
    assert result["original_result"] == "CONFIRMATION.json"
    expected_cases = set(itertools.product(range(len(protocol["profiles"])), map(tuple, protocol["meshes"])))
    cases = {(c["profile"], (c["dx"], c["dt"])): c for c in result["cases"]}
    assert len(cases) == len(result["cases"]) == 6 and set(cases) == expected_cases
    expected = set(itertools.product(range(len(protocol["profiles"])), map(tuple, protocol["meshes"]),
                                     PARAMETERS, protocol["fd_steps"]))
    observed, witness_errors = set(), []
    coverage = {name: False for name in PARAMETERS}
    scalar_checks = stable_count = passing_count = 0
    for row in result["records"]:
        key = (row["profile"], (row["dx"], row["dt"]), row["parameter"], row["step"])
        assert key not in observed
        observed.add(key)
        case = cases[(key[0], key[1])]
        config = case["config"]
        shape = [round(config["horizon"] / row["dt"]) + 1, 2,
                 round((config["upper"] - config["lower"]) / row["dx"]) + 1]
        assert row["shape"] == shape and row["scalar_checks"] == shape[0] * shape[1] * shape[2]
        witness = row["witness"]
        assert len(witness["location"]) == 3
        assert all(isinstance(i, int) and 0 <= i < n for i, n in zip(witness["location"], shape))
        fd = (witness["plus"] - witness["minus"]) / (2 * row["step"])
        scaled = abs(witness["tangent"] - fd) / max(1., abs(witness["tangent"]), abs(fd))
        assert abs(fd - witness["central_difference"]) <= 1e-14
        assert abs(scaled - witness["maximum_scaled_error"]) <= 1e-14
        witness_errors.append(scaled)
        assert row["passed"] == (scaled <= protocol["whole_array_scaled_fd_tolerance"])
        assert len(row["branch_changes_plus_minus"]) == 2
        stable = all(s["left"] == s["right"] == 0 for s in row["branch_changes_plus_minus"])
        assert row["stable"] == stable
        assert set(row["full_array_sha256"]) == {"plus", "minus", "tangent"}
        assert all(re.fullmatch("[0-9a-f]{64}", digest) for digest in row["full_array_sha256"].values())
        scalar_checks += row["scalar_checks"]
        stable_count += stable
        passing_count += row["passed"]
        coverage[row["parameter"]] |= stable and row["passed"]
    assert observed == expected and len(observed) == 156
    gates = dict(all_whole_array_bounds=passing_count == len(observed),
                 primal_parity=all(c["primal_maximum_absolute_error"] <= protocol["primal_absolute_tolerance"]
                                  for c in result["cases"]), stable_coordinate_coverage=all(coverage.values()))
    assert gates == result["gates"] and coverage == result["stable_coordinate_coverage"]
    assert result["passed"] == all(gates.values())
    return dict(schema="hcsn-r19-independent-small-step-record-check-v1", integrity_passed=True,
                followup_gate_passed=all(gates.values()), original_gate_passed=False,
                freeze_files_verified=len(freeze["files"]), cases=len(cases), records=len(observed),
                scalar_checks=scalar_checks, worst_cell_operands_recomputed=len(witness_errors),
                maximum_witness_scaled_error=max(witness_errors), stable_records=stable_count,
                passed_records=passing_count, failed_records=len(observed) - passing_count,
                coverage=coverage, gates=gates,
                original_result_sha256=hashlib.sha256((root / "CONFIRMATION.json").read_bytes()).hexdigest(),
                followup_result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest(),
                limitations=["Worst-cell arithmetic, record coverage and frozen byte identities verified",
                             "Whole-array maxima and SHA256 values cannot be independently rederived from unarchived arrays",
                             "No numerical re-execution; no action-switch, continuum or full-neural derivative qualification"])


if __name__ == "__main__":
    report = check(sys.argv[1])
    output = Path(__file__).resolve().parent / sys.argv[2]
    with output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
