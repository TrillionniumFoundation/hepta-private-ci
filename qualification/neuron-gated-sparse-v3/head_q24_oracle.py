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


def independent_same_activation_head_margin(logit_q24: int,
                                             activation_q24: list[int]) -> tuple[str, int]:
    """Sufficient research-only sign guarantee for ideal F32 linear weights.

    Bias quantization <= 0.5 LSB; each channel incurs at most
    abs(x_real)*0.5 <= 4 coefficient-rounding LSB plus 0.5 native product
    rounding LSB. Therefore twice the absolute margin <= 9*width+1.
    Strictly outside that limit, the ideal F32-weight linear Head has the
    same sign as the quantized Head on the EXACT SAME native Q24 activation.
    This does not prove Torch accumulation, state equivalence, or authority.
    """
    require(type(logit_q24) is int and MIN_I64 <= logit_q24 <= MAX_I64,
            'invalid i64 Q24 margin logit')
    require(type(activation_q24) is list and 5 <= len(activation_q24) <= 256,
            'invalid Q24 margin activation width')
    require(all(type(x) is int and -(8*Q) <= x <= 8*Q for x in activation_q24),
            'Q24 margin requires bounded original activation')
    twice_margin = 9 * len(activation_q24) + 1
    if 2 * abs(logit_q24) <= twice_margin:
        status = 'QUANTIZATION_AMBIGUOUS_ABSTAIN'
    elif logit_q24 > 0:
        status = 'ACCEPT_POSITIVE_RESEARCH_ONLY'
    else:
        status = 'ACCEPT_NEGATIVE_RESEARCH_ONLY'
    return status, twice_margin


def verify_native_head(path: Path, native: dict[str, Any]) -> dict[str, Any]:
    from safetensors.torch import load_file
    tensors = load_file(str(path), device='cpu')
    w = tensors['head.weight'].reshape(-1).tolist()
    bias = tensors['head.bias'].reshape(-1).tolist()
    require(len(bias) == 1 and len(w) == native['width'], 'native Head dimensions drift')
    head_q24 = [q24_from_f32(value) for value in w]
    bias_q24 = q24_from_f32(bias[0])
    require(native.get('head_sign_margin_profile') ==
            'hepta.neuron.same-activation-head-sign-margin.v1'
            and native.get('head_margin_abstention_is_research_only') is True
            and native.get('head_margin_authorized_for_final_use') is False,
            'native Head margin missing, mismatched or claimed final-use')
    rows = native['frontier']
    require(type(rows) is list and len(rows) == native['original_tick_count'] and rows,
            'missing Q24 Head native frontier')
    margin_counts = {
        'ACCEPT_POSITIVE_RESEARCH_ONLY': 0,
        'ACCEPT_NEGATIVE_RESEARCH_ONLY': 0,
        'QUANTIZATION_AMBIGUOUS_ABSTAIN': 0,
    }
    all_deltas = []
    for i, row in enumerate(rows):
        require(row['sequence'] == i + 1 and
                len(row['activation_q24']) == len(w), 'native head trace/width drift')
        result = q24_head(head_q24, bias_q24, row['activation_q24'])
        require(result == row.get('quantized_head_logit_q24'),
                'native Rust Q24 Head mismatch with independent integer oracle')
        status, margin_twice = independent_same_activation_head_margin(
            result, row['activation_q24'])
        require(row.get('head_sign_margin_status') == status and
                row.get('head_sign_margin_twice_q24_lsb') == margin_twice,
                'native Rust Head sign margin disagrees with independent integer oracle')
        margin_counts[status] += 1
        # Compute reference F32 Head over native Q24 activation using Python
        # floating arithmetic (not a bitwise Torch/F32-policy equivalence test).
        f32_result = math.fsum(
            [bias[0]] + [weight * (activation/Q)
                         for weight, activation in zip(w, row['activation_q24'])])
        all_deltas.append(abs(f32_result - result/Q))
    return {
        'schema':'hepta.neuron.research-q24-head-integer-oracle.v2',
        'matched_step_count':len(rows),
        'all_native_head_logits_match_independent_integer_oracle':True,
        'max_f32_over_native_activation_vs_q24_head_logit_gap':max(all_deltas),
        'head_sign_margin_counts':margin_counts,
        'all_native_head_sign_margins_match_independent_integer_oracle':True,
        'head_margin_is_only_same_activation_ideal_linear_reference':True,
        'quantized_head_rounding':'signed-nearest-ties-to-even-Q24',
        'full_original_f32_policy_execution_verified':False,
        'native_head_calibration_verified':False,
        'native_q24_model_production_qualification':False,
        'ndu_eligible':False,
    }
