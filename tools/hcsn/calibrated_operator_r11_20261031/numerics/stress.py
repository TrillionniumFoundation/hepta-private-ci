"""Fresh registered Latin-hypercube stress; never adapt the frozen kernel."""

import hashlib
import json
import time
from pathlib import Path

import numpy as np

import kernel
import reference

ROOT = Path(__file__).resolve().parent


def scaled(actual, expected):
    return float(np.max(abs(actual - expected) / np.maximum(1., abs(expected))))


def run():
    registration = ROOT / "STRESS_PROTOCOL.json"
    protocol = json.loads(registration.read_text())
    output = ROOT / "STRESS_RESULTS.json"
    if output.exists():
        raise ValueError("Stress evidence already exists")
    for name in ("kernel", "reference"):
        assert hashlib.sha256((ROOT / (name + ".py")).read_bytes()).hexdigest() == protocol[name + "_sha256"]
    start = time.perf_counter()
    rows, admission = [], []
    for number, original in enumerate(protocol["points"]):
        for mode in protocol["modes"]:
            theta = np.array(original) if mode == "float64" else np.array(original, np.float32).astype(float)
            try:
                initial, _ = kernel.evaluate(original, .1, coordinate="log_distance", mode=mode)
            except ValueError as error:
                admission.append(dict(point=number, mode=mode, admitted=False, theta=theta.tolist(), reason=str(error)))
                continue
            admission.append(dict(point=number, mode=mode, admitted=True, theta=theta.tolist()))
            a = (theta[0] - theta[1] - theta[2] ** 2 / 2) / theta[2] ** 2
            zt = np.sqrt(a * a + 2 * (theta[0] + theta[5]) / theta[2] ** 2)
            limit = min(.002, .02 * theta[2] * np.sqrt(theta[6]), .05 / (1 + abs(a) + zt))
            states = [("log_distance", 1e-8), ("log_distance", .75 * limit),
                      ("log_distance", 2.), ("asset", float(initial[0]) * np.exp(.2))]
            for coordinate, state in states:
                represented = state if mode == "float64" else float(np.float32(state))
                actual, jac = kernel.evaluate(original, state, coordinate=coordinate, mode=mode)
                ref = np.asarray(reference.fields(theta, represented, coordinate), float)
                ref_jac = reference.jacobian(theta, represented, coordinate)
                half_jac = reference.jacobian(theta, represented, coordinate, "5e-19")
                ve, je, he = scaled(actual, ref), scaled(jac, half_jac), scaled(ref_jac, half_jac)
                rows.append(dict(point=number, mode=mode, coordinate=coordinate, state=represented,
                    actual=actual.tolist(), reference=ref.tolist(), jacobian=jac.tolist(), reference_jacobian=half_jac.tolist(),
                    value_error=ve, jacobian_error=je, reference_halving_error=he,
                    passed=bool(ve <= protocol["gates"][mode]["value_scaled"] and je <= protocol["gates"][mode]["jacobian_scaled"]
                                and he <= protocol["reference_halving_scaled_max"])))
        if number % 16 == 15:
            print("points", number + 1, "admitted-mode-pairs", sum(r["admitted"] for r in admission),
                  "failed-numerical-rows", sum(not r["passed"] for r in rows), flush=True)
    summary = {}
    for mode in protocol["modes"]:
        ar = [r for r in admission if r["mode"] == mode]
        measured = [r for r in rows if r["mode"] == mode]
        failed_points = sorted(set(r["point"] for r in measured if not r["passed"]))
        summary[mode] = dict(proposed_points=len(ar), admitted_points=sum(r["admitted"] for r in ar),
            rejected_points=sum(not r["admitted"] for r in ar), numerical_failed_points=failed_points,
            numerical_passed_rows=sum(r["passed"] for r in measured), numerical_rows=len(measured),
            maximum_value_error=max((r["value_error"] for r in measured), default=None),
            maximum_jacobian_error=max((r["jacobian_error"] for r in measured), default=None),
            reference_halving_max=max((r["reference_halving_error"] for r in measured), default=None))
    result = dict(schema="hcsn-full-hx-independent-lhs-stress-results-v1",
                  protocol_sha256=hashlib.sha256(registration.read_bytes()).hexdigest(),
                  kernel_sha256=protocol["kernel_sha256"], reference_sha256=protocol["reference_sha256"],
                  source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  elapsed_seconds=time.perf_counter() - start, summary=summary, admission=admission, rows=rows,
                  no_kernel_tuning=True, all_admitted_numerical_fixtures_passed=all(r["passed"] for r in rows))
    with output.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    compact = {k: v for k, v in result.items() if k not in ("admission", "rows")}
    compact["failed_rows"] = [r for r in rows if not r["passed"]]
    compact["rejections"] = [r for r in admission if not r["admitted"]]
    with (ROOT / "STRESS_SUMMARY.json").open("x") as stream:
        json.dump(compact, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, indent=2))
    return result


if __name__ == "__main__":
    result = run()
    raise SystemExit(0 if result["all_admitted_numerical_fixtures_passed"] else 1)
