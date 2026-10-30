"""Exact-input time refinement and independent leaky-integral checks."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT / "experiments/hcsn_free_boundary_v1/data/study001/irregular.npz"
DATA_SHA = "3850c5d956e30fdd2a7215378aa8c6054dbee5f622cb8991f2120d3cb7e062f3"
FACTORS = (1, 2, 4)
SEEDS = (9201, 9202, 9203)
MODELS = ("distribution_free_dual", "distribution_conditional_dual", "two_gates", "transformer", "lif_snn")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def utc():
    return datetime.now(timezone.utc).isoformat()


def refine(x, dt, y, factor):
    if factor not in FACTORS:
        raise ValueError("Only registered exact binary refinements are allowed")
    refined_x = np.repeat(x, factor, axis=1)
    refined_dt = np.repeat(dt / factor, factor, axis=1)
    refined_y = np.full((len(x), x.shape[1] * factor), -100, dtype=y.dtype)
    refined_y[:, -1] = y[:, -1]
    return refined_x, refined_dt, refined_y


def oracle(x, dt):
    """Original label state before query and an independent weighted-sum value."""
    values, durations = x[:, :, 0].astype(np.float64), dt.astype(np.float64)
    mask = x[:, :, 1] == 1
    memory = np.zeros(len(x), dtype=np.float64)
    for position in range(x.shape[1]):
        keep = np.exp(-0.2 * durations[:, position])
        injected = -np.expm1(-0.2 * durations[:, position]) * values[:, position]
        memory = np.where(mask[:, position], keep * memory + injected, memory)
    data_dt = np.where(mask, durations, 0.0)
    remaining = data_dt.sum(1, keepdims=True) - data_dt.cumsum(1)
    weights = -np.expm1(-0.2 * data_dt) * np.exp(-0.2 * remaining)
    independent = (weights * values).sum(1)
    return memory, independent


def semantic_checks(x, dt, y):
    if x.shape[1:] != (32, 64) or dt.shape != x.shape[:2] or y.shape != dt.shape:
        raise ValueError("Unexpected original irregular dimensions")
    if not (np.all(y[:, :-1] == -100) and np.all(y[:, -1] >= 0) and
            np.all(x[:, :-1, 1] == 1) and np.all(x[:, -1, 1] == 0) and
            np.all(x[:, :-1, 2] == 0) and np.all(x[:, -1, 2] == 1) and
            np.all(x[:, -1, 0] == 0)):
        raise ValueError("Original data/query contract differs")
    original, independent = oracle(x, dt)
    allowed = 5e-12 * (1 + np.abs(original))
    rows = []
    for factor in FACTORS:
        xx, dd, yy = refine(x, dt, y, factor)
        result, weighted = oracle(xx, dd)
        endpoints = dd.astype(np.float64).cumsum(1)[:, factor-1::factor]
        original_endpoints = dt.astype(np.float64).cumsum(1)
        query_duration = np.where(xx[:, :, 2] == 1, dd, 0).astype(np.float64).sum(1)
        after_zero_input_query = result * np.exp(-0.2 * query_duration)
        checks = dict(
            input_piecewise_constant_exact=np.array_equal(xx[:, ::factor], x) and
                all(np.array_equal(xx[:, offset::factor], x) for offset in range(factor)),
            original_interval_endpoints_exact=np.array_equal(endpoints, original_endpoints),
            total_physical_time_exact=np.array_equal(dd.astype(np.float64).sum(1), dt.astype(np.float64).sum(1)),
            leaky_semigroup_within_fixed_tolerance=bool(np.all(np.abs(result-original) <= allowed)),
            independent_closed_form_matches=bool(np.all(np.abs(weighted-result) <= allowed)),
            original_labels_recovered=bool(np.all((original > 0).astype(np.int64) == y[:, -1])),
            refined_labels_identical=bool(np.all((result > 0).astype(np.int64) == yy[:, -1])),
            final_zero_input_query_preserves_label=bool(np.all((after_zero_input_query > 0).astype(np.int64) == y[:, -1])),
            exactly_one_final_query_supervision=bool(np.all((yy >= 0).sum(1) == 1) and np.all(yy[:, :-1] == -100)))
        rows.append(dict(factor=factor, length=xx.shape[1], checks=checks,
            maximum_semigroup_absolute_error=float(np.max(np.abs(result-original))),
            maximum_independent_absolute_error=float(np.max(np.abs(weighted-result))),
            minimum_absolute_label_state=float(np.min(np.abs(result)))))
    return dict(passed=all(all(row["checks"].values()) for row in rows), samples=len(x),
        original_length=32, factors=rows, tolerance="absolute <=5e-12*(1+abs(original_state))",
        original_vs_independent_maximum_error=float(np.max(np.abs(original-independent))),
        query_contract="Label integrates31 data intervals; final zero-input query interval does not change its sign. All32 durations are refined and preserved.")


def verify(protocol):
    for category in ("source_files_sha256", "references_sha256"):
        for name, expected in protocol[category].items():
            if sha(ROOT / name) != expected:
                raise ValueError("Registered source/reference changed: " + name)
    if sha(DATA) != protocol["data"]["sha256"]:
        raise ValueError("Frozen irregular dataset changed")
