"""Optional post-observation input encoder, reusing the unchanged DS math core.

This uses FP64 explicitly for input encoding into two FP32 parts. It is neither
a single-FP32-input contract nor a whole-SNN low-precision implementation.
"""

import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
import warnings

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "precision"))
import ds_kernel as ds
from fresh import check_freeze
from development import error


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(suffix, payload):
    path = ROOT / ("R13_GRID_PRECISION.split64." + suffix)
    assert not path.exists(), path
    data = (json.dumps(payload, indent=2, allow_nan=False) + "\n").encode()
    path.write_bytes(gzip.compress(data, mtime=0) if suffix.endswith(".gz") else data)


def encode_fp64(value):
    """Explicit FP64-only encoding boundary; the math kernel receives hi/lo."""
    original = np.float64(value)
    hi = np.float32(original)
    lo = np.float32(original - np.float64(hi))
    return ds.dm.DS(hi, lo)


def evaluate_split64(theta, state):
    """Full financial values/Jacobian in log-distance coordinates, FP32 output.

    Derivatives describe the continuous HX formula at the encoded point, not
    derivatives through the finite input-encoding map.
    """
    theta, state = np.asarray(theta, dtype=np.float64), np.float64(state)
    if theta.shape != (9,) or not np.isfinite(theta).all() or not np.isfinite(state):
        raise ValueError("Expected nine finite parameters and finite state")
    if state < 0 or np.any(theta < ds.k.LOWER) or np.any(theta > ds.k.UPPER):
        raise ValueError("Outside original parameter box or nonnegative state")
    basis = np.eye(10, dtype=np.float32)
    model = ds.MODEL([ds.Dual(encode_fp64(v), basis[i]) for i, v in enumerate(theta)])
    x = ds.Dual(encode_fp64(state), basis[-1])
    equity = model.equity(x)
    f, g = model.first_hit(x, model.m)
    debt = model.c / model.R + model.discount * model.q * (1 - f)
    debt += (model.alpha * model.b / model.m - model.c / model.R) * g
    outputs = [model.b, equity, f, g, debt]
    return (np.asarray([a.v.h + a.v.l for a in outputs], dtype=np.float32),
            np.asarray([a.g.h + a.g.l for a in outputs], dtype=np.float32))


def check_row(row):
    started = time.perf_counter()
    theta, state = row["theta_original"], row["state_original"]
    encoded = [encode_fp64(v) for v in theta + [state]]
    original = np.asarray(theta + [state], dtype=np.float64)
    decoded = np.array([np.float64(v.h) + np.float64(v.l) for v in encoded])
    result = dict(seed=row["seed"], center_index=row["index"], state=state,
                  encoded_hi=[float(v.h) for v in encoded],
                  encoded_lo=[float(v.l) for v in encoded],
                  encoding_error=error(decoded, original))
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        try:
            values, jac = evaluate_split64(theta, state)
            if not np.isfinite(values).all() or not np.isfinite(jac).all():
                raise ValueError("nonfinite output")
            ve = error(values, np.asarray(row["reference_original"]))
            je = error(jac, np.asarray(row["reference_original_jacobian"]))
            result.update(actual=values.tolist(), jacobian=jac.tolist(),
                          value_error=ve, jacobian_error=je,
                          passed=bool(ve <= 8e-7 and je <= 2e-5))
        except (ValueError, ArithmeticError) as exc:
            result.update(error=str(exc), passed=False)
        result["warnings"] = sorted(set(str(w.message) for w in seen))
    result["seconds"] = time.perf_counter() - started
    return result


def summary(rows):
    return dict(rows=len(rows), passed=sum(r["passed"] for r in rows),
                warnings=sum(bool(r["warnings"]) for r in rows),
                rejected=sum("error" in r for r in rows),
                max_value_error=max(r.get("value_error", 0) for r in rows),
                max_jacobian_error=max(r.get("jacobian_error", 0) for r in rows),
                max_input_encoding_error=max(r["encoding_error"] for r in rows),
                seconds=sum(r["seconds"] for r in rows))


def main():
    source = ROOT / "R13_GRID_PRECISION.json.gz"
    original = json.loads(gzip.decompress(source.read_bytes()))
    frozen = check_freeze()
    specification = dict(
        status="Post-observation adapter verification; not an independent task confirmation",
        source_sha256=sha(Path(__file__)), ds_freeze_sha256=frozen,
        archived_reference_sha256=sha(source),
        input="Original FP64 values explicitly encoded as FP32 hi plus FP32 lo using FP64 subtraction",
        computation="Unchanged frozen DS MODEL, Dual and math primitives; no FP64 core fallback",
        output="FP32 values and 5x10 continuous sensitivities at the encoded point",
        storage="Two FP32 components per scalar: 64 bit payload, not single-FP32 input/storage",
        gates=dict(value=8e-7, jacobian=2e-5),
        sequence="First all eight original-input failures; if all pass, evaluate all other archived grid points without changing adapter",
        reference="Archived independent 80-digit R11 literal values/Jacobians at original FP64 inputs; main original Jacobian step 1e-18; eight diagnostic failures additionally half-step checked",
        exclusions="No whole-SNN FP32, speed, new confirmation, continuous-box accuracy, or policy-quality claim",
    )
    write("protocol.json", specification)
    failures = [r for r in original["rows"] if not r["original_input_comparison_pass"]]
    first = [check_row(r) for r in failures]
    write("first8.json", dict(specification=specification, summary=summary(first), rows=first))
    print("first8", json.dumps(summary(first)), flush=True)
    if not all(r["passed"] for r in first):
        return
    rows = first.copy()
    for i, row in enumerate(original["rows"]):
        if not row["original_input_comparison_pass"]:
            continue
        result = check_row(row)
        rows.append(result)
        if i % 56 == 0 or not result["passed"]:
            print(i, row["seed"], result.get("value_error"), result.get("jacobian_error"), result["passed"], flush=True)
    assert check_freeze() == frozen
    assert sha(source) == specification["archived_reference_sha256"]
    assert sha(Path(__file__)) == specification["source_sha256"]
    rows.sort(key=lambda r: (r["seed"], r["center_index"]))
    result = dict(specification=specification, summary=summary(rows), rows=rows)
    write("json.gz", result)
    write("json", {k: v for k, v in result.items() if k != "rows"})
    print(json.dumps(result["summary"], indent=2), flush=True)


if __name__ == "__main__":
    main()
