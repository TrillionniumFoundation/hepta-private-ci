#!/usr/bin/env python3
"""Deterministic independent 4096-tick Q24 arithmetic-only sweep.

Arithmetic golden vectors are not trained-model accuracy, Rust run-time, or
target-host resource qualification. No root certificate or signing is implied.
"""
import hashlib
import json

from q24_temporal_oracle import H, Q, gate_step, ssm_step

MASK = (1 << 64) - 1


def splitmix64(seed: int):
    while True:
        seed = (seed + 0x9e3779b97f4a7c15) & MASK
        z = seed
        z = ((z ^ (z >> 30)) * 0xbf58476d1ce4e5b9) & MASK
        z = ((z ^ (z >> 27)) * 0x94d049bb133111eb) & MASK
        yield z ^ (z >> 31)


def produce(n: int = 4096) -> dict:
    draws = splitmix64(0x1337_babe_dead_beef)
    gstate = sstate = 0
    now = 0
    previous = None
    gate_bytes = bytearray()
    ssm_bytes = bytearray()
    clamps = 0
    max_elapsed = 0
    for _ in range(n):
        drive = next(draws) % (2 * H + 1) - H
        delta = next(draws) % 3000 + 1
        now += delta
        gate, gnext = gate_step(gstate, drive)
        steps, retention, snext = ssm_step(sstate, drive, previous, now)
        clamps += int(gnext in (-H, H)) + int(snext in (-H, H))
        for value in (gate, gnext):
            gate_bytes += int(value).to_bytes(8, "big", signed=True)
        for value in (steps, retention, snext):
            ssm_bytes += int(value).to_bytes(8, "big", signed=True)
        gstate, sstate, previous = gnext, snext, now
        max_elapsed = max(max_elapsed, steps)
        assert -H <= gstate <= H and -H <= sstate <= H
        assert 0 <= gate <= Q
    return {
        "schema": "hepta.neuron.q24-temporal-fuzz-digests.v1",
        "n": n,
        "splitmix64_seed": "0x1337babedeadbeef",
        "gate_stream_sha256": hashlib.sha256(gate_bytes).hexdigest(),
        "ssm_stream_sha256": hashlib.sha256(ssm_bytes).hexdigest(),
        "last_v3_temporal_q24": gstate,
        "last_ssm_temporal_q24": sstate,
        "max_elapsed_steps": max_elapsed,
        "clamp_visits": clamps,
        "qualification": "ARITHMETIC_ONLY_NOT_NATIVE_OR_TARGET_HOST",
    }


if __name__ == "__main__":
    print(json.dumps(produce(), sort_keys=True, indent=2))
