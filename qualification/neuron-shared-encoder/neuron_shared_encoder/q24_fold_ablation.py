"""Shadow-only arithmetic ablation for the Rust fixed-Q24 static gate.

An input-independent multiplicative gate is algebraically foldable in real
arithmetic, but the deployed reference CPU driver rounds after gating and
again after readout. Folding introduces *a different rounding schedule*.
This module emulates the documented Rust Q24 arithmetic for regression only;
it does not authorize model artifacts, execution or any production change.
"""
from __future__ import annotations

from typing import Sequence

Q24 = 1 << 24
MAX_ABS_Q24 = 8 * Q24
I128_MIN = -(1 << 127)
I128_MAX = (1 << 127) - 1
MAX_DIM = 512


def _int(value: int, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f'{label} must be signed integer Q24')
    return value


def _checked_i128(value: int) -> int:
    if not I128_MIN <= value <= I128_MAX:
        raise OverflowError('signed i128 overflow')
    return value


def round_q48_to_q24(raw: int) -> int:
    """Rust equivalent: Euclidean floor + round-to-nearest/ties-to-even."""
    _checked_i128(_int(raw, 'raw'))
    floor, remainder = divmod(raw, Q24)
    rounded = floor + int(2 * remainder > Q24 or
                          (2 * remainder == Q24 and floor % 2 != 0))
    if not -MAX_ABS_Q24 <= rounded <= MAX_ABS_Q24:
        raise ValueError('Q24 numeric range exceeded')
    return rounded


def _validate_vector(values: Sequence[int], label: str) -> tuple[int, ...]:
    if not 1 <= len(values) <= MAX_DIM:
        raise ValueError(f'{label}: invalid Q24 dimension')
    verified = tuple(_int(v, label) for v in values)
    if any(not -MAX_ABS_Q24 <= v <= MAX_ABS_Q24 for v in verified):
        raise ValueError(f'{label}: coefficient outside Q24 bound')
    return verified


def static_gate_vs_folded_q24(
    features: Sequence[int],
    gates: Sequence[int],
    weights: Sequence[Sequence[int]],
    biases: Sequence[int],
) -> dict:
    """Return the two bounded Q24 execution paths without hiding rounding.

    Weights are readout-output-major, exactly as Rust dense_q24's rows.
    This is a numeric test of fixed gates, not a trained Head benchmark.
    """
    x = _validate_vector(features, 'features')
    gate = _validate_vector(gates, 'gates')
    intercept = _validate_vector(biases, 'biases')
    if len(x) != len(gate) or len(weights) != len(intercept):
        raise ValueError('incompatible feature/gate/readout geometry')
    matrix = tuple(_validate_vector(w, 'weights') for w in weights)
    if any(len(w) != len(x) for w in matrix):
        raise ValueError('incompatible readout width')
    gated = tuple(round_q48_to_q24(_checked_i128(a * b)) for a, b in zip(x, gate))
    original = []
    folded = []
    for row, bias in zip(matrix, intercept):
        original_sum = _checked_i128(bias * Q24)
        folded_sum = _checked_i128(bias * Q24)
        for feature, weight, gate_weight, gated_feature in zip(x, row, gate, gated):
            original_sum = _checked_i128(original_sum + _checked_i128(weight * gated_feature))
            folded_weight = round_q48_to_q24(_checked_i128(weight * gate_weight))
            folded_sum = _checked_i128(folded_sum + _checked_i128(folded_weight * feature))
        original.append(round_q48_to_q24(original_sum))
        folded.append(round_q48_to_q24(folded_sum))
    abs_error = [abs(a - b) for a, b in zip(original, folded)]
    return {
        'original_q24': original,
        'folded_q24': folded,
        'max_abs_error_q24_units': max(abs_error),
        'max_abs_error_real': max(abs_error) / Q24,
        'bit_identical': all(a == b for a, b in zip(original, folded)),
        'evidence_class': 'NUMERICAL_REGRESSION_NOT_RUST_RUNTIME',
        'production_admission': 'BLOCKED',
    }
