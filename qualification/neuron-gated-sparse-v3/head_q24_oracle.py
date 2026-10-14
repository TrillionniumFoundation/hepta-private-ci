#!/usr/bin/env python3
"""Independent integer oracle for the research Rust F32->Q24 linear Head.

This verifies only a versioned quantized readout over the actual native Q24
activation. It cannot certify full F32 policy output, sigmoid/calibration,
signed model install, learned utility, or authorization.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

Q = 1 << 24
MAX_I64 = (1 << 63) - 1
MIN_I64 = -(1 << 63)


def require(value: bool, reason: str) -> None:
    if not value:
        raise ValueError(reason)


def q24_from_f32(value: float) -> int:
    require(type(value) is float and math.isfinite(value) and -8 <= value <= 8,
            'nonfinite or out-of-range F32 Head')
    # Python float represents every source IEEE-754 float32 value exactly;
    # scaling by power-of-two 2^24 is exact in binary64 for |f32| <= 8.
    return round(value * Q)  # Python round uses ties to even.


def q24_mul(a: int, b: int) -> int:
    require(type(a) is int and type(b) is int, 'invalid signed Q24 operand')
    product = a * b
    magnitude = abs(product)
    quotient, remainder = divmod(magnitude, Q)
    up = remainder * 2 > Q or (remainder * 2 == Q and quotient % 2 == 1)
    value = (quotient + int(up)) * (1 if product >= 0 else -1)
    require(MIN_I64 <= value <= MAX_I64, 'native Q24 Head multiply exceeds i64')
    return value


def q24_head(weights_q24: list[int], bias_q24: int, activation: list[int]) -> int:
    require(type(weights_q24) is list and type(activation) is list and
            len(weights_q24) == len(activation) and len(weights_q24) > 0,
            'Q24 Head geometry mismatch')
    accumulator = bias_q24
    for a, b in zip(activation, weights_q24):
        accumulator += q24_mul(a, b)
        require(MIN_I64 <= accumulator <= MAX_I64, 'native Q24 Head sum exceeds i64')
    return accumulator


def verify_native_head(path: Path, native: dict[str, Any]) -> dict[str, Any]:
    from safetensors.torch import load_file
    tensors = load_file(str(path), device='cpu')
    w = tensors['head.weight'].reshape(-1).tolist()
    bias = tensors['head.bias'].reshape(-1).tolist()
    require(len(bias) == 1 and len(w) == native['width'], 'native Head dimensions drift')
    head_q24 = [q24_from_f32(value) for value in w]
    bias_q24 = q24_from_f32(bias[0])
    rows = native['frontier']
    require(type(rows) is list and len(rows) == native['original_tick_count'] and rows,
            'missing Q24 Head native frontier')
    all_deltas = []
    for i, row in enumerate(rows):
        require(row['sequence'] == i + 1 and
                len(row['activation_q24']) == len(w), 'native head trace/width drift')
        result = q24_head(head_q24, bias_q24, row['activation_q24'])
        require(result == row.get('quantized_head_logit_q24'),
                'native Rust Q24 Head mismatch with independent integer oracle')
        # Compute reference F32 Head over native Q24 activation using Python
        # floating arithmetic (not a bitwise Torch/F32-policy equivalence test).
        f32_result = math.fsum(
            [bias[0]] + [weight * (activation/Q)
                         for weight, activation in zip(w, row['activation_q24'])])
        all_deltas.append(abs(f32_result - result/Q))
    return {
        'schema':'hepta.neuron.research-q24-head-integer-oracle.v1',
        'matched_step_count':len(rows),
        'all_native_head_logits_match_independent_integer_oracle':True,
        'max_f32_over_native_activation_vs_q24_head_logit_gap':max(all_deltas),
        'quantized_head_rounding':'signed-nearest-ties-to-even-Q24',
        'full_original_f32_policy_execution_verified':False,
        'native_head_calibration_verified':False,
        'native_q24_model_production_qualification':False,
        'ndu_eligible':False,
    }
