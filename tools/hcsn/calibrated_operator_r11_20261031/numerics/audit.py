"""Run the frozen full-HX matrix; preserve every result in a new evidence file."""

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import scipy

import kernel
import reference

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scaled_error(actual, expected):
    return float(np.max(abs(actual - expected) / np.maximum(1., abs(expected))))


def run(destination):
    if destination.exists():
        raise ValueError("Evidence already exists; choose a fresh output path")
    start = time.perf_counter()
    protocol = json.loads((ROOT / "PROTOCOL_V3.json").read_text())
    rows, rejection_rows, reference_cache = [], [], {}
    for case in protocol["cases"]:
        theta = np.array(case["theta"])
        for mode in protocol["modes"]:
            quantized = theta if mode == "float64" else theta.astype(np.float32).astype(float)
            boundary = float(reference.fields(quantized, 100.)[0])
            limit = min(1e-4, 1e-3 * quantized[2] * np.sqrt(quantized[6]))
            states = [("log_distance", x) for x in protocol["log_distances"]]
            states += [("log_distance", limit * u) for u in protocol["join_multipliers"]]
            a = (quantized[0] - quantized[1] - quantized[2] ** 2 / 2) / quantized[2] ** 2
            zt = np.sqrt(a * a + 2 * (quantized[0] + quantized[5]) / quantized[2] ** 2)
            new_limit = min(.002, .02 * quantized[2] * np.sqrt(quantized[6]), .05 / (1 + abs(a) + zt))
            states += [("log_distance", new_limit * u) for u in protocol["join_multipliers"]]
            states += [("asset", 100.), ("asset", boundary * (1 + 1e-6))]
            case_rows = []
            for coordinate, state in states:
                input_state = state if mode == "float64" else float(np.float32(state))
                key = (tuple(quantized), input_state, coordinate)
                if key not in reference_cache:
                    ref = np.asarray(reference.fields(quantized, input_state, coordinate), dtype=float)
                    jac = reference.jacobian(quantized, input_state, coordinate)
                    half = reference.jacobian(quantized, input_state, coordinate, "5e-19")
                    reference_cache[key] = ref, half, scaled_error(jac, half)
                ref, jac, halving = reference_cache[key]
                row = dict(case=case["name"], mode=mode, coordinate=coordinate, state=input_state,
                           quantized_theta=quantized.tolist(), reference=ref.tolist(),
                           reference_jacobian=jac.tolist(), reference_halving_error=halving)
                try:
                    values, tangent = kernel.evaluate(theta, state, coordinate=coordinate, mode=mode)
                    ve, je = scaled_error(values, ref), scaled_error(tangent, jac)
                    row.update(actual=values.tolist(), jacobian=tangent.tolist(), value_error=ve, jacobian_error=je,
                               passed=bool(ve <= protocol["gates"][mode]["value_scaled"]
                                           and je <= protocol["gates"][mode]["jacobian_scaled"]
                                           and halving <= protocol["reference_halving_scaled_max"]))
                except (ValueError, ArithmeticError) as error:
                    row.update(passed=False, error=str(error))
                rows.append(row)
                case_rows.append(row)
            print(case["name"], mode, sum(r["passed"] for r in case_rows), "/", len(case_rows), flush=True)
    for name, values in protocol["unqualified_extremes"].items():
        for value in values:
            for mode in protocol["modes"]:
                theta = kernel.BASE.copy()
                theta[kernel.NAMES.index(name)] = value
                try:
                    kernel.evaluate(theta, 100., mode=mode)
                    rejection_rows.append(dict(parameter=name, value=value, mode=mode, rejected=False))
                except ValueError as error:
                    rejection_rows.append(dict(parameter=name, value=value, mode=mode, rejected=True, reason=str(error)))
    # A full mixed interface VJP and realized FP32 secants, at fixed V.
    quantized = kernel.BASE.astype(np.float32).astype(float)
    values, tangent = kernel.evaluate(kernel.BASE, 100., mode="mixed32")
    ref_jac = reference.jacobian(quantized, 100.)
    cotangent = np.array([.2, -.3, .4, -.5, .6], np.float32)
    vjp = tangent.T @ cotangent
    ref_vjp = ref_jac.T @ cotangent.astype(float)
    secants = []
    for rel in protocol["cast_secant_relative_steps"]:
        numeric = []
        for i in range(10):
            vector = np.r_[quantized, 100.]
            step = rel * max(abs(vector[i]), .01)
            plus, minus = vector.astype(np.float32), vector.astype(np.float32)
            plus[i], minus[i] = np.float32(vector[i] + step), np.float32(vector[i] - step)
            yp, _ = kernel.evaluate(plus[:9], plus[-1], mode="mixed32")
            ym, _ = kernel.evaluate(minus[:9], minus[-1], mode="mixed32")
            numeric.append((yp.astype(float) - ym.astype(float)) / (float(plus[i]) - float(minus[i])))
        numeric = np.asarray(numeric).T
        secants.append(dict(relative_step=rel, jacobian=numeric.tolist(), error=scaled_error(numeric, tangent)))
    cast = dict(cotangent=cotangent.tolist(), vjp=vjp.tolist(), reference_vjp=ref_vjp.tolist(),
                vjp_error=scaled_error(vjp, ref_vjp), secants=secants,
                interpretation="FP32 quantization is not mathematically differentiable; AD uses the standard cast convention and differentiates the full FP64 function at represented input values.")
    cast["passed"] = bool(cast["vjp_error"] <= protocol["gates"]["mixed32"]["jacobian_scaled"]
                           and max(r["error"] for r in secants) <= protocol["cast_secant_scaled_max"])
    summary = {}
    for mode in protocol["modes"]:
        part = [r for r in rows if r["mode"] == mode]
        by_case = {c["name"]: all(r["passed"] for r in part if r["case"] == c["name"]) for c in protocol["cases"]}
        summary[mode] = dict(passed_rows=sum(r["passed"] for r in part), total_rows=len(part),
                             passed_cases=sum(by_case.values()), total_cases=len(by_case), cases=by_case,
                             max_value_error=max(r.get("value_error", float("inf")) for r in part),
                             max_jacobian_error=max(r.get("jacobian_error", float("inf")) for r in part))
    result = dict(schema="hcsn-full-hx-numerics-r11-evidence-v3", protocol_sha256=sha(ROOT / "PROTOCOL_V3.json"),
                  environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                   autodiff="local scalar forward-mode Dual; JAX is not installed or rerun"),
                  source_sha256={n: sha(ROOT / n) for n in ("kernel.py", "reference.py", "audit.py")},
                  output_order=list(kernel.OUTPUTS), jacobian_columns=list(kernel.NAMES) + ["state"],
                  summary=summary, rows=rows, extreme_rejections=rejection_rows, cast_interface=cast,
                  elapsed_seconds=time.perf_counter() - start)
    result["qualified_registered_fixtures"] = bool(summary["float64"]["passed_cases"] == len(protocol["cases"])
            and summary["mixed32"]["passed_cases"] == len(protocol["cases"]) and cast["passed"]
            and all(r["rejected"] for r in rejection_rows))
    destination.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"summary": summary, "cast_passed": cast["passed"], "qualified_registered_fixtures": result["qualified_registered_fixtures"]}, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "RESULTS.json")
    args = parser.parse_args()
    evidence = run(args.output)
    raise SystemExit(0 if evidence["qualified_registered_fixtures"] else 1)
