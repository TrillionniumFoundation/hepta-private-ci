#!/usr/bin/env python3
"""Verify true norms of the private fixture heads with exact rational sums."""
from __future__ import annotations
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import struct

import numpy as np
import finite_readout_capacity_certificate as capacity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    capacity.read_fixture(args.fixture, args.fixture_sha256)
    raw = args.fixture.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.fixture_sha256:
        raise ValueError("FIXTURE_CHANGED")
    header_size = struct.unpack("<Q", raw[:8])[0]
    header = json.loads(raw[8:8 + header_size])

    def tensor(name):
        spec = header[name]
        dtype = {"F64": "<f8", "F32": "<f4"}[spec["dtype"]]
        count = int(np.prod(spec["shape"]))
        low, high = spec["data_offsets"]
        if not 0 <= low <= high <= len(raw) - 8 - header_size or high - low != count * np.dtype(dtype).itemsize:
            raise ValueError("HEAD_STORAGE_BOUND")
        return np.frombuffer(raw, dtype=dtype, count=count, offset=8 + header_size + low).copy()

    checks = []
    for name in ("parent", "exact18", "exact36", "exact54"):
        vector = np.r_[tensor(name + ".weight"), tensor(name + ".bias")]
        if vector.shape != (769,):
            raise ValueError("HEAD_SHAPE")
        for kind, values in (("STORED_F64_USD_FIXTURE", vector), ("F32_USD_NATIVE_GATE_CONVERSION", vector.astype(np.float32).astype(np.float64))):
            integers, exponent = capacity.common_integer_array(values)
            squared = Fraction(sum(int(v) ** 2 for v in integers), ((1 << exponent) * 100) ** 2)
            low, high = capacity.root_grid_bounds(squared, 2, 24)
            checks.append({"head": name, "representation": kind, "original_unit_norm_lower": capacity.grid_string(low, 24), "original_unit_norm_upper": capacity.grid_string(high, 24), "exact_norm_le_nominal_0p1": squared <= Fraction(1, 10) ** 2, "exact_norm_le_tolerance_0p100001": squared <= Fraction(100001, 1000000) ** 2})
    report = {"schema": "hepta.wsp.exact-head-norm-scope.v1", "fixture_sha256": args.fixture_sha256, "norm_scope": "JOINT_WEIGHT_AND_BIAS; USD_FIXTURE_NORM_DIVIDED_BY_100", "arithmetic": "EXACT_STORED_IEEE_RATIONALS", "operational_certificate_requires_true_norm_bound": True, "all_checked_heads_fit_0p100001": all(v["exact_norm_le_tolerance_0p100001"] for v in checks), "checks": checks, "not_a_universal_fp32_norm_admission_proof": True, "weights_and_labels_disclosed": False, "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "capacity_helper_sha256": hashlib.sha256(Path(capacity.__file__).read_bytes()).hexdigest()}
    with args.output.open("x") as stream:
        json.dump(report, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
