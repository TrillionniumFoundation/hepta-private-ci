"""Arithmetic replay of the generic probe; no numerical LCP re-solving."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

from .record_check import close, flat


def check(run):
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "GENERIC_PROTOCOL.json").read_text())
    for item in json.loads((root / "SOURCE_FREEZE.json").read_text())["files"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    result = json.loads((run / "RESULTS.json").read_text())
    assert result["protocol"] == protocol and result["generic_math_qualification"] is False
    assert result["original_r19_whole_array_gate"] is result["full_gradient_gate"] is False
    seen, decisions, scalar_count, largest = set(), [], 0, 0.
    coverage = {name: False for name in result["nonzero_coordinate_coverage"]}
    for entry, record in zip(result["raw_files"], result["records"]):
        packed = (run / entry["path"]).read_bytes()
        assert len(packed) == entry["bytes"] and hashlib.sha256(packed).hexdigest() == entry["sha256"]
        raw = gzip.decompress(packed)
        assert hashlib.sha256(raw).hexdigest() == entry["raw_sha256"]
        item = json.loads(raw)
        assert item["record"] == record
        key = (record["profile"], record["parameter"], record["sign"])
        assert key not in seen
        seen.add(key)
        if record["status"] == "failed":
            assert record["passed"] is False
            decisions.append(False)
            continue
        original, values, tangent = [list(flat(item[k])) for k in ("original_values", "values", "tangent")]
        assert len(original) == len(values) == len(tangent) == 5002
        close(max(abs(v - o) for v, o in zip(values, original)), record["primal_parity"])
        close(max(map(abs, tangent)), record["maximum_derivative"])
        coverage[record["parameter"]] = coverage.get(record["parameter"], False) or record["maximum_derivative"] > 1e-10
        passed = record["primal_parity"] <= protocol["primal_tolerance"]
        assert len(record["checks"]) == len(item["shifted_values"]) == len(protocol["steps"])
        for step, shifted, stored in zip(protocol["steps"], item["shifted_values"], record["checks"]):
            actual = list(flat(shifted))
            assert len(actual) == len(values) and stored["step"] == step
            error = max(abs((a - v) / step - z) for a, v, z in zip(actual, values, tangent))
            close(error, stored["derivative_error"])
            assert (error <= protocol["one_sided_tolerance"]) == stored["passed"]
            passed = passed and stored["passed"]
            largest, scalar_count = max(largest, error), scalar_count + len(actual)
        assert passed == record["passed"]
        decisions.append(passed)
    assert len(seen) == len(result["records"]) == len(result["raw_files"]) == 78
    assert seen == {(p, name, sign) for p in range(3) for name in coverage for sign in (-1., 1.)}
    assert all(decisions) == result["numerical_finite_step_gate"]
    assert coverage == result["nonzero_coordinate_coverage"]
    return dict(schema="hcsn-r20-generic-raw-replay-v1", integrity_passed=True, attempts=len(seen),
        completed=sum(r["status"] == "completed" for r in result["records"]), scalar_positions=scalar_count,
        maximum_derivative_error=largest, numerical_finite_step_gate=result["numerical_finite_step_gate"],
        nonzero_coordinate_coverage=coverage, generic_math_qualification=False,
        limitation="Replays complete saved arrays and arithmetic, not independent numerical LCP solution/classification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x") as stream:
        json.dump(check(args.run), stream, indent=2)
        stream.write("\n")
