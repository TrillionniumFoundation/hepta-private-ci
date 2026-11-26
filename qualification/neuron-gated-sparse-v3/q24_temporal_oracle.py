#!/usr/bin/env python3
"""Independent exact-integer Q24 temporal arithmetic oracle.

ONLY arithmetic conformance. Synthetic examples are not model-training,
target-host resource, future utility or production eligibility evidence.
"""
from __future__ import annotations
import json
from typing import Any

Q = 1 << 24
H = 8 * Q


def q24_mul(left: int, right: int) -> int:
    product = left * right
    quotient, remainder = divmod(abs(product), Q)
    if 2 * remainder > Q or (2 * remainder == Q and quotient % 2):
        quotient += 1
    return -quotient if product < 0 else quotient


def q24_power(base: int, steps: int) -> int:
    assert 0 <= base <= Q and 1 <= steps <= 65_535
    result = Q
    while steps:
        if steps & 1:
            result = q24_mul(result, base)
        steps >>= 1
        if steps:
            base = q24_mul(base, base)
    return result


def gate_step(old: int, drive: int) -> tuple[int, int]:
    assert -H <= old <= H and -H <= drive <= H
    raw = Q // 2 + q24_mul(Q // 4, abs(drive) // 8)
    raw += q24_mul(Q // 8, abs(drive - old) // 16)
    gate = max(0, min(Q, raw))
    state = q24_mul(Q - gate, old) + q24_mul(gate, drive)
    return gate, max(-H, min(H, state))


def ssm_step(old: int, drive: int, previous_us: int | None, now_us: int) -> tuple[int, int, int]:
    steps = 1 if previous_us is None else (now_us - previous_us + 99) // 100
    assert 1 <= steps <= 65_535
    retention = q24_power(Q // 2, steps)
    state = q24_mul(retention, old) + q24_mul(Q // 2, drive)
    return steps, retention, max(-H, min(H, state))


def generate() -> dict[str, Any]:
    stimuli = [
        (1, 100, Q), (2, 200, -(Q // 2)), (3, 401, 3 * Q // 2),
        (4, 1301, -3 * Q), (5, 1302, 0),
    ]
    gate_state = 0
    ssm_state = 0
    previous_us = None
    rows = []
    for sequence, monotonic_us, drive in stimuli:
        gate, gate_state = gate_step(gate_state, drive)
        elapsed, retention, ssm_state = ssm_step(
            ssm_state, drive, previous_us, monotonic_us
        )
        rows.append({
            "sequence": sequence,
            "monotonic_us": monotonic_us,
            "drive_q24": drive,
            "gate_q24": gate,
            "v3_temporal_q24": gate_state,
            "ssm_elapsed_steps": elapsed,
            "ssm_retention_q24": retention,
            "ssm_temporal_q24": ssm_state,
        })
        previous_us = monotonic_us
    return {
        "schema": "hepta.neuron.temporal-arithmetic-golden.q24.v1",
        "warning": "synthetic arithmetic reference only; not host model evidence",
        "q24": Q,
        "envelope_q24": H,
        "gate_params_q24": [Q // 2, Q // 4, Q // 8],
        "ssm_params_q24": [Q // 2, Q // 2],
        "ssm_time_quantum_micros": 100,
        "rows": rows,
    }


def check() -> None:
    assert q24_mul(1, Q // 2) == 0
    assert q24_mul(3, Q // 2) == 2
    assert q24_mul(-3, Q // 2) == -2
    assert q24_mul(-1, Q // 2) == 0
    assert q24_power(Q, 65_535) == Q
    assert q24_power(Q // 2, 2) == Q // 4
    observed = generate()["rows"]
    assert [r["ssm_elapsed_steps"] for r in observed] == [1, 1, 3, 9, 1]
    assert [r["gate_q24"] for r in observed] == [
        9043968, 8786944, 9372322, 10464222, 8592647,
    ]
    assert [r["v3_temporal_q24"] for r in observed] == [
        9043968, -86216, 14020430, -26117006, -12740877,
    ]
    assert [r["ssm_temporal_q24"] for r in observed] == [
        8388608, 0, 12582912, -25141248, -12570624,
    ]


if __name__ == "__main__":
    check()
    print(json.dumps(generate(), sort_keys=True, indent=2))
