#!/usr/bin/env python3
"""Fail-closed, research-only Q24 linear-Head sign margin reference.

Preconditions (checked by the caller): stored source coefficients are finite
IEEE754-F32 with |w_i|,|bias| <= 8; Q24 coefficients were made using
nearest/ties-even; native Q24 activations have |a_i|<=8*2**24; native
products each use Q24 nearest/ties-even; accumulation is exact unless its
checked i64 overflow rejects execution.

The sign guarantee applies to the *ideal real-arithmetic* linear readout using
those same stored F32 coefficients and the exact same Q24 activation vector.
It does NOT include floating Torch accumulation error, or mismatch of native
Neuron temporal/Top-K/state outputs with a floating surrogate. It grants no
Hepta routing, NDU, Cell selection, or other production authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Q = 1 << 24
H = 8*Q
Profile = Literal['ACCEPT_POSITIVE_RESEARCH_ONLY','ACCEPT_NEGATIVE_RESEARCH_ONLY','QUANTIZATION_AMBIGUOUS_ABSTAIN']

@dataclass(frozen=True)
class MarginDecision:
    status: Profile
    quantized_head_logit_q24: int
    uniform_margin_half_lsb_units: int
    width: int
    native_activation_source_attested: bool = False
    real_float_policy_parity_verified: bool = False
    ndu_eligible: bool = False
    production_qualification: bool = False


def classify_frozen_q24_head_sign(logit_q24: int, activation_q24: list[int]) -> MarginDecision:
    """Sufficient (not necessary) sign-invariance criterion in pure integers.

    Bound in Q24-LSB units = 0.5 bias + width*(4 coefficient error +
    0.5 product rounding) = (9*width+1)/2. Strict admission means
    2*abs(logit_q24) > 9*width+1. Otherwise *abstain*.
    """
    if type(logit_q24) is not int or not -(1<<63)<=logit_q24<1<<63:
        raise ValueError('invalid signed i64 Q24 logit')
    if type(activation_q24) is not list or not (5<=len(activation_q24)<=256):
        raise ValueError('unsupported frozen Q24 activation width')
    if any(type(x) is not int or not -H<=x<=H for x in activation_q24):
        raise ValueError('unbounded Q24 activation')
    n=len(activation_q24)
    if 2*abs(logit_q24) <= 9*n+1:
        status='QUANTIZATION_AMBIGUOUS_ABSTAIN'
    elif logit_q24>0:
        status='ACCEPT_POSITIVE_RESEARCH_ONLY'
    else:
        status='ACCEPT_NEGATIVE_RESEARCH_ONLY'
    return MarginDecision(status=status,quantized_head_logit_q24=logit_q24,
                          uniform_margin_half_lsb_units=9*n+1,width=n)
