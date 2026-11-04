#!/usr/bin/env python3
"""Certify a finite-row lower RMSE bound without disclosing inputs or labels.

The private safetensors fixture supplies `inputs` and `targets_usd`.  All stored
IEEE values are treated as exact rationals.  This is not a generalization bound.
Only NumPy and Python's standard library are needed; no checkpoint is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from fractions import Fraction
import struct
import time

os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("OMP_NUM_THREADS", "2")
import numpy as np


def read_fixture(path: Path, expected_sha256: str):
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("PRIVATE_FIXTURE_HASH_MISMATCH")
    if not 8 < len(raw) <= 64 * 1024 * 1024:
        raise ValueError("FIXTURE_BYTE_BOUND")
    size = struct.unpack("<Q", raw[:8])[0]
    if not 0 < size <= min(1024 * 1024, len(raw) - 8):
        raise ValueError("FIXTURE_HEADER_BOUND")
    header = json.loads(raw[8:8 + size])

    def tensor(name):
        spec = header[name]
        dtype = {"F32": "<f4", "F64": "<f8"}.get(spec["dtype"])
        shape = spec["shape"]
        if dtype is None or not shape or any(type(n) is not int or n <= 0 for n in shape):
            raise ValueError("FIXTURE_TENSOR_TYPE")
        low, high = spec["data_offsets"]
        if type(low) is not int or type(high) is not int or not 0 <= low <= high <= len(raw) - 8 - size:
            raise ValueError("FIXTURE_TENSOR_BOUNDS")
        if high - low != math.prod(shape) * np.dtype(dtype).itemsize:
            raise ValueError("FIXTURE_TENSOR_SHAPE")
        return np.frombuffer(raw, dtype=dtype, count=math.prod(shape), offset=8 + size + low).reshape(shape).astype(np.float64)

    return tensor("inputs"), tensor("targets_usd")


def common_integer_array(values):
    """Represent every stored finite IEEE value as an integer / 2**exponent."""
    values = np.asarray(values, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("NONFINITE_INPUT")
    ratios = [v.as_integer_ratio() for v in values.reshape(-1).tolist()]
    exponent = max(den.bit_length() - 1 for _, den in ratios)
    integers = np.array([num << (exponent - (den.bit_length() - 1)) for num, den in ratios], dtype=object)
    return integers.reshape(values.shape), exponent


def integer_root_floor(value: int, degree: int) -> int:
    if value < 0 or degree < 1:
        raise ValueError("ROOT_DOMAIN")
    if value in (0, 1) or degree == 1:
        return value
    low, high = 0, 1 << ((value.bit_length() + degree - 1) // degree)
    while low + 1 < high:
        mid = (low + high) // 2
        if mid ** degree <= value:
            low = mid
        else:
            high = mid
    return low


def root_grid_bounds(value: Fraction, degree: int, digits: int = 24):
    """Integer bounds on root(value) * 10**digits; no floating rounding."""
    scale_power = 10 ** (digits * degree)
    floor = integer_root_floor(value.numerator * scale_power // value.denominator, degree)
    exact = floor ** degree * value.denominator == value.numerator * scale_power
    return floor, floor if exact else floor + 1


def grid_string(value: int, digits: int) -> str:
    sign = "-" if value < 0 else ""
    whole, part = divmod(abs(value), 10 ** digits)
    return f"{sign}{whole}.{part:0{digits}d}"


def certificate(inputs, targets_usd, radius=Fraction(1, 10), output_scale=Fraction(100), power=16, digits=24):
    x = np.asarray(inputs, dtype=np.float64)
    y = np.asarray(targets_usd, dtype=np.float64)
    if x.ndim != 2 or y.shape != (len(x),) or not 2 <= len(x) <= 128 or not 1 <= x.shape[1] <= 4096:
        raise ValueError("FINITE_DATA_SHAPE_BOUND")
    if radius <= 0 or output_scale <= 0 or power not in (1, 2, 4, 8, 16):
        raise ValueError("CERTIFICATE_PARAMETER_BOUND")
    n = len(x)
    q, exponent = common_integer_array(x)
    # X_centered = A / D exactly, with no rounded empirical mean.
    a = n * q - q.sum(axis=0)
    denominator = n * (1 << exponent)
    gram = a @ a.T
    gram_power = gram
    for _ in range(power.bit_length() - 1):
        gram_power = gram_power @ gram_power
    trace = sum(int(gram_power[i, i]) for i in range(n))
    # G = Xc Xc^T is PSD, so lambda_max(G)**power <= tr(G**power).
    trace_fraction = Fraction(trace, denominator ** (2 * power))
    std_power = (output_scale * radius) ** (2 * power) * trace_fraction / (n ** power)
    pred_low, pred_high = root_grid_bounds(std_power, 2 * power, digits)
    sigma_low, sigma_high = root_grid_bounds(trace_fraction, 2 * power, digits)
    yi, ye = common_integer_array(y)
    yi = [int(v) for v in yi]
    target_variance = Fraction(n * sum(v * v for v in yi) - sum(yi) ** 2, n * n * (1 << (2 * ye)))
    target_low, target_high = root_grid_bounds(target_variance, 2, digits)
    lower = max(0, target_low - pred_high)
    xc = x - x.mean(axis=0)
    singular = float(np.linalg.svd(xc, compute_uv=False)[0])
    return {
        "schema": "hepta.wsp.finite-readout-capacity-certificate.v1",
        "rows": n,
        "features": x.shape[1],
        "empirical_standard_deviation_ddof": 0,
        "joint_weight_and_intercept_l2_cap": str(radius),
        "output_scale": str(output_scale),
        "output_units": "USD",
        "gram_power": power,
        "proof_arithmetic": "EXACT_STORED_IEEE_RATIONALS_AND_INTEGER_MATRIX_MULTIPLICATION",
        "root_rounding": "OUTWARD_INTEGER_DECIMAL_GRID",
        "decimal_grid_digits": digits,
        "numerical_svd_singular_max": singular,
        "numerical_svd_prediction_sd_upper_bound_usd": float(output_scale * radius) * singular / math.sqrt(n),
        "certified_singular_max_upper_bound": grid_string(sigma_high, digits),
        "target_sd_lower_bound_usd": grid_string(target_low, digits),
        "target_sd_upper_bound_usd": grid_string(target_high, digits),
        "certified_prediction_sd_upper_bound_usd": grid_string(pred_high, digits),
        "certified_rmse_lower_bound_usd": grid_string(lower, digits),
        "intercept_treatment": "CENTERING_CANCELS_INTERCEPT; JOINT_CAP_IMPLIES_WEIGHT_CAP",
        "clipped_prediction_coverage": "ANY_FIXED_SCALAR_1_LIPSCHITZ_CLIPPING_MAP",
        "proof_scope": "THIS_EXACT_FINITE_INPUT_AND_TARGET_ARRAY_ONLY",
        "labels_previously_viewed": True,
        "out_of_sample_claim": False,
        "distributional_or_end_to_end_value_claim": False,
        "actual_weights_or_individual_labels_disclosed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--radius", default="0.1")
    parser.add_argument("--output-scale", default="100")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    start = time.perf_counter()
    inputs, targets = read_fixture(args.fixture, args.fixture_sha256)
    report = certificate(inputs, targets, Fraction(args.radius), Fraction(args.output_scale))
    report.update(private_input_sha256=args.fixture_sha256, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), numpy_version=np.__version__, wall_seconds=time.perf_counter() - start)
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
