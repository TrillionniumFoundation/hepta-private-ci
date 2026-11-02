"""Standard-library raw array replay; no independent numerical re-solving."""

import argparse
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time


def flat(value):
    if isinstance(value, list):
        for item in value:
            yield from flat(item)
    else:
        yield value


def close(actual, recorded):
    assert abs(actual - recorded) <= 1e-10 * (1 + abs(actual)), (actual, recorded)


def check(run):
    started = time.process_time()
    root = Path(__file__).resolve().parent
    protocol = json.loads((root / "PROTOCOL.json").read_text())
    freeze = json.loads((root / "SOURCE_FREEZE.json").read_text())
    for item in freeze["files"]:
        raw = (root / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["sha256"], item["path"]
    inputs = []
    for item in json.loads((root / "INPUT_IDENTITIES.json").read_text())["files"]:
        raw = (root.parents[2] / item["path"]).read_bytes()
        assert len(raw) == item["bytes"] and hashlib.sha256(raw).hexdigest() == item["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item["git_blob"]
        if item["path"].endswith(("CONFIRMATION.json", "FOLLOWUP_RESULTS.json")):
            assert json.loads(raw)["passed"] is False
        inputs.append(item["path"])
    result = json.loads((run / "RESULTS.json").read_text())
    assert result["protocol"] == protocol and result["source_freeze"] == freeze
    assert result["original_r19_whole_array_gate"] is False
    assert result["full_gradient_gate"] is False and result["production_activation"] is False
    key = lambda r: (r["family"], r["index"], r["dx"], r["dt"])
    expected = {(f, i, dx, dt) for f, i, (dx, dt) in itertools.product(
        ("affine_tie", "joint_smooth"), range(protocol["directions_per_family"]), protocol["meshes"])}
    listed = {key(r): r for r in result["records"]}
    assert len(listed) == len(result["records"]) == len(expected) and set(listed) == expected
    seen, rows, comparisons, numerical_checks, decisions = set(), 0, 0, 0, []
    maxima = {"affine_derivative_error": 0., "joint_remainder": 0., "homogeneity": 0.}
    for entry in result["raw_files"]:
        packed = (run / entry["path"]).read_bytes()
        assert len(packed) == entry["bytes"] and hashlib.sha256(packed).hexdigest() == entry["sha256"]
        raw = gzip.decompress(packed)
        assert hashlib.sha256(raw).hexdigest() == entry["raw_sha256"]
        batch = [json.loads(line) for line in raw.splitlines()]
        assert len(batch) == entry["rows"]
        for item in batch:
            record = item["record"]
            identity = key(record)
            assert identity in expected and identity not in seen and record == listed[identity]
            seen.add(identity)
            values, tangent, doubled = [list(flat(item[k])) for k in ("values", "tangent", "doubled_tangent")]
            count = (round(protocol["config_changes"]["horizon"] / record["dt"]) + 1) * 2 * (round(8 / record["dx"]) + 1)
            assert len(values) == len(tangent) == len(doubled) == count
            assert all(v == .5 for v in values)
            homogeneity = max(abs(a - 2 * b) for a, b in zip(doubled, tangent))
            close(homogeneity, record["homogeneity_error"])
            close(record["exact_primal_error"], 0.)
            case_decisions = []
            assert len(item["shifted_values"]) == len(record["checks"]) == len(protocol["steps"])
            for step, shifted, stored in zip(protocol["steps"], item["shifted_values"], record["checks"]):
                actual = list(flat(shifted))
                assert len(actual) == count and stored["step"] == step
                error = max(abs((a - v) / step - z) for a, v, z in zip(actual, values, tangent))
                remainder = max(abs(a - v - step * z) / step ** 2 for a, v, z in zip(actual, values, tangent))
                close(error, stored["derivative_error"])
                close(remainder, stored["remainder_over_step_squared"])
                field = "affine_derivative_error" if record["family"] == "affine_tie" else "joint_remainder"
                maxima[field] = max(maxima[field], error if field.startswith("affine") else remainder)
                passed = error <= protocol["affine_derivative_tolerance"] if record["family"] == "affine_tie" else remainder <= protocol["joint_remainder_bound"]
                assert passed == stored["passed"]
                case_decisions.append(passed)
                comparisons += 1
                numerical_checks += count
            passed = all(case_decisions) and homogeneity <= protocol["algebra_tolerance"] and record["directional_lcp_residual"] <= protocol["algebra_tolerance"]
            assert passed == record["passed"]
            decisions.append(passed)
            maxima["homogeneity"] = max(maxima["homogeneity"], homogeneity)
            rows += 1
    assert seen == expected and rows == 96 and comparisons == 192
    controls = result["analytic_controls"]
    assert len(controls["records"]) == 18 and len(controls["max_controls"]) == 4
    for record in controls["records"]:
        direct = max(abs(a - b) for a, b in zip(record["expected"], record["found"]))
        quotient = max(abs(a - b) for a, b in zip(record["quotient"], record["found"]))
        close(direct, record["direct_error"])
        close(quotient, record["one_sided_error"])
        decisions.append(direct <= 1e-11 and quotient <= 2e-4)
    decisions += [abs(r["expected"] - r["found"]) <= 1e-12 for r in controls["max_controls"]]
    matrix = protocol["config_changes"]["content_transition"]
    expect = [max(d, sum(m * s for m, s in zip(row, (.1, -.1)))) + max(-d, sum(m * s for m, s in zip(row, (-.1, .1)))) for d, row in zip((.1, -.1), matrix)]
    assert len(result["actual_admission_nonadditivity"]) == len(protocol["meshes"])
    for record in result["actual_admission_nonadditivity"]:
        summed = record["first_admission_sum"]
        positive, negative = record["positive_first_admission"], record["negative_first_admission"]
        assert len(list(flat(positive))) == len(list(flat(negative))) == len(list(flat(summed))) == 2 * (round(8 / record["dx"]) + 1)
        error = max(abs(v - expect[mode]) for mode, row in enumerate(summed) for v in row)
        assert all(abs(a + b - s) <= 1e-12 for a, b, s in zip(flat(positive), flat(negative), flat(summed)))
        close(error, record["error"])
        decisions.append(error <= protocol["algebra_tolerance"])
    assert len(set(result["infeasible_direction_rejections"])) == 10
    assert all(decisions) == result["passed"]
    return dict(schema="hcsn-r20-independent-raw-replay-v1", integrity_passed=True,
        campaign_passed=result["passed"], cases=rows, whole_array_comparisons=comparisons,
        scalar_difference_positions=numerical_checks, maxima=maxima, verified_inputs=inputs,
        cpu_seconds=time.process_time() - started,
        limitations=["Raw arithmetic replay, not independent numerical re-solving of every LCP",
                     "Directional residual summaries and old selected-branch differences are not independently re-solved",
                     "Original R19 gates and full gradient gate remain false"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with args.out.open("x") as stream:
        json.dump(check(args.run), stream, indent=2, allow_nan=False)
        stream.write("\n")
