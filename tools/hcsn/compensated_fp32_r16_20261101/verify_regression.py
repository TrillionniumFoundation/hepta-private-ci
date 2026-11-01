"""Fail CI on incomplete, nonfinite or out-of-tolerance frozen regressions.

The archived auditors are create-only diagnostic writers: their exit status alone
does not establish a numerical pass. This adapter independently checks each
reported financial value and Jacobian entry against the corresponding reference.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path


GATES = {"value_scaled": 8e-7, "jacobian_scaled": 2e-5}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    data = Path(path).read_bytes()
    return json.loads(gzip.decompress(data) if str(path).endswith(".gz") else data)


def scaled_errors(actual, expected, count):
    require(len(actual) == len(expected) == count, "Incomplete numerical vector")
    errors = []
    for value, reference in zip(actual, expected):
        require(math.isfinite(value) and math.isfinite(reference), "Nonfinite result")
        errors.append(abs(value - reference) / max(1, abs(reference)))
    return errors


def check_rows(rows, references, count):
    require(len(rows) == len(references) == count, "Incomplete financial rows")
    value_max, jacobian_max = 0.0, 0.0
    for actual, reference in zip(rows, references):
        require(actual.get("passed") is True, "Auditor reported a failed row")
        for key in ("case", "coordinate", "state"):
            require(actual[key] == reference[key], "Reordered or changed input: " + key)
        value_max = max(value_max, *scaled_errors(actual["values"], reference["reference"], 5))
        require(len(actual["jacobian"]) == len(reference["reference_jacobian"]) == 5,
                "Incomplete output Jacobian")
        for gradient, expected in zip(actual["jacobian"], reference["reference_jacobian"]):
            jacobian_max = max(jacobian_max, *scaled_errors(gradient, expected, 10))
    require(value_max <= GATES["value_scaled"], "Value tolerance failed")
    require(jacobian_max <= GATES["jacobian_scaled"], "Jacobian tolerance failed")
    return {"rows": count, "max_value_error": value_max, "max_jacobian_error": jacobian_max}


def verify(capsule, primitives, development, holdout):
    capsule = Path(capsule)
    protocol = read(capsule / "R16_VALIDATION_PROTOCOL_V1.json")
    for name, expected in protocol["candidate_source_sha256"].items():
        require(hashlib.sha256((capsule / name).read_bytes()).hexdigest() == expected,
                "Frozen candidate changed: " + name)
    for key, value in GATES.items():
        require(protocol["gates"][key] == development["gates"][key]
                == holdout["gates"][key] == value, "Financial tolerance changed")
    require(primitives["checks"] == len(primitives["rows"]) == 701,
            "Incomplete primitive diagnostics")
    require(primitives["passed"] is True, "Primitive diagnostics failed")
    require(primitives["diagnostic_scaled_gate"] == 5e-12, "Primitive gate changed")
    for row in primitives["rows"]:
        error = row["scaled_error"]
        require(math.isfinite(error) and 0 <= error <= 5e-12, "Primitive error failed")
    reference = read(capsule / "FROZEN_REFERENCE.json.gz")
    dev_result = check_rows(development["rows"], reference["rows"], 432)
    require(len({row["case"] for row in development["rows"]}) == 18,
            "Incomplete development cases")
    require(development["source_sha256"] == protocol["candidate_source_sha256"]["compensated_kernel.py"],
            "Development used another candidate")
    expected_seal = dict(protocol["candidate_source_sha256"])
    for name in ("R16_VALIDATION_PROTOCOL_V1.json", protocol["case_manifest"]):
        expected_seal[name] = hashlib.sha256((capsule / name).read_bytes()).hexdigest()
    require(expected_seal[protocol["case_manifest"]] == protocol["case_manifest_sha256"],
            "Validation case manifest changed")
    require(holdout["source_sha256_before"] == holdout["source_sha256_after"] == expected_seal,
            "Validation source or input seal changed")
    frozen_holdout = read(capsule / "R16_HOLDOUT_V1.json.gz")
    require(holdout["runner_sha256"] == frozen_holdout["runner_sha256"],
            "Validation runner changed")
    require(len(holdout["cases"]) == 128 and
            all(case["independently_valid"] for case in holdout["cases"]),
            "Frozen V1 domain classification changed")
    for case, expected in zip(holdout["cases"], frozen_holdout["cases"]):
        require(case["id"] == expected["id"] and case["theta"] == expected["theta"],
                "Frozen V1 parameters changed")
    counts = Counter(row["case"] for row in holdout["rows"])
    require(len(counts) == 128 and set(counts.values()) == {4}, "Incomplete V1 cases")
    require(len({(r["case"], r["coordinate"], r["state"]) for r in holdout["rows"]}) == 512,
            "Duplicate V1 input rows")
    for row in holdout["rows"]:
        error = row["oracle_halving_error"]
        require(row["oracle_halving_passed"] is True and math.isfinite(error)
                and 0 <= error <= 1e-12, "Independent reference did not converge")
    for row, expected in zip(holdout["rows"], frozen_holdout["rows"]):
        require(max(scaled_errors(row["reference"], expected["reference"], 5)) <= 1e-12,
                "Frozen V1 reference values changed")
        require(len(row["reference_jacobian"]) == 5, "Incomplete reference Jacobian")
        for gradient, frozen in zip(row["reference_jacobian"], expected["reference_jacobian"]):
            require(max(scaled_errors(gradient, frozen, 10)) <= 1e-12,
                    "Frozen V1 reference Jacobian changed")
    validation = check_rows(holdout["rows"], frozen_holdout["rows"], 512)
    return {"primitive_checks": 701, "development": dev_result, "frozen_v1_regression": validation,
            "scope": "Compensated FP32 finite regression; no new independent confirmation or ordinary FP32 admission"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capsule", "primitives", "development", "holdout"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.capsule, read(args.primitives), read(args.development),
                            read(args.holdout)), indent=2, allow_nan=False))
