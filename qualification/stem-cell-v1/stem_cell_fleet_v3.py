"""Bounded physical CPU experiment: one reviewed Granite97 feature -> 64..4096 independent Cell heads.

Deterministic, untrained int16 rank-8 parameters. No independent authority,
no model forward here, no task labels, no generalization or GPU claims.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import struct
import sys
import time

WIDTH = 384
RANK = 8
PARAMS = 2 * WIDTH * RANK + 2 * WIDTH + 2  # 6914
SIZES = (64, 256, 1024, 4096)
Q24 = 1 << 24
MAX_SLOTS = 256
TOP_K = 32
MASK = 0xFFFFFFFF
PROFILE = 'hepta.stem.cell-fleet.lcg-int16-rank8.v3'

class FleetError(ValueError):
    pass


def scalar_stream(n: int) -> array:
    if type(n) is not int or n not in SIZES:
        raise FleetError('unsupported independently allocated Cell count')
    if sys.byteorder != 'little' or array('h').itemsize != 2:
        raise FleetError('canonical little-endian int16 host required')
    bank = array('h')
    for cell in range(n):
        state = (0x9E3779B9 ^ ((cell + 1) * 0x85EBCA6B)) & MASK
        for j in range(PARAMS - 1):
            state = (1664525 * state + 1013904223) & MASK
            bank.append(((state >> 24) % 127) - 63)
        # Every cell has a distinct independent, addressable final parameter.
        bank.append(cell - 2048)
    if len(bank) != n * PARAMS:
        raise FleetError('incomplete physical parameter census')
    return bank


def pool_q24(raw: bytes, rows: int) -> tuple[float, ...]:
    if type(rows) is not int or not 1 <= rows <= MAX_SLOTS or len(raw) != rows * WIDTH * 8:
        raise FleetError('noncanonical Q24 source shape')
    sums = [0] * WIDTH
    for i, (v,) in enumerate(struct.iter_unpack('>q', raw)):
        if abs(v) > 8 * Q24:
            raise FleetError('Q24 source outside bounded range')
        sums[i % WIDTH] += v
    return tuple(v / (rows * Q24) for v in sums)


def current_rss_kib() -> int:
    with open('/proc/self/statm', encoding='ascii') as handle:
        items = handle.read().split()
    if len(items) < 2:
        raise FleetError('host RSS unavailable')
    return int(items[1]) * os.sysconf('SC_PAGE_SIZE') // 1024


def _gate(bank: array, cell: int, pooled: tuple[float, ...]) -> float:
    base = cell * PARAMS + 2 * WIDTH * RANK
    s = math.fsum(bank[base + j] * pooled[j] for j in range(WIDTH))
    return s / (WIDTH * 64) + bank[base + WIDTH] / 128


def _head(bank: array, cell: int, pooled: tuple[float, ...], gate: float) -> float:
    base = cell * PARAMS
    a = [math.fsum(bank[base + k * WIDTH + j] * pooled[j]
                   for j in range(WIDTH)) / (WIDTH * 64) for k in range(RANK)]
    g = 1 / (1 + math.exp(-max(-40.0, min(40.0, gate))))
    outbase = base + 2 * WIDTH * RANK + WIDTH + 1
    total = 0.0
    for j in range(WIDTH):
        residual = math.fsum(bank[base + WIDTH * RANK + j * RANK + k] * a[k]
                             for k in range(RANK)) / (RANK * 64)
        total += bank[outbase + j] * (pooled[j] + g * residual)
    return total / (WIDTH * 64) + bank[outbase + WIDTH] / 16384


def forward(bank: array, n: int, pooled: tuple[float, ...]):
    if len(bank) != n * PARAMS or len(pooled) != WIDTH:
        raise FleetError('head input or physical parameter bank mismatch')
    gates = [_gate(bank, i, pooled) for i in range(n)]
    order = sorted(range(n), key=lambda i: (-gates[i], i))[:TOP_K]
    scores = [_head(bank, i, pooled, gates[i]) for i in order]
    if any(not math.isfinite(v) for v in (*gates, *scores)):
        raise FleetError('nonfinite Cell numerical result')
    return gates, order, scores


def calculate(raw: bytes, rows: int, *, feature_sha256: str,
              review_sha256: str, sizes=SIZES, warmups: int = 2,
              repeats: int = 8) -> dict:
    if type(warmups) is not int or type(repeats) is not int or not 0 <= warmups <= 16 or not 2 <= repeats <= 32:
        raise FleetError('invalid repetition budget')
    if hashlib.sha256(raw).hexdigest() != feature_sha256 or len(review_sha256) != 64:
        raise FleetError('unbound feature or review')
    pooled = pool_q24(raw, rows)
    result = []
    for n in sizes:
        before_rss = current_rss_kib()
        setup_start = time.process_time_ns()
        bank = scalar_stream(n)
        setup_cpu_ns = time.process_time_ns() - setup_start
        allocated_rss = current_rss_kib()
        bank_sha = hashlib.sha256(bank.tobytes()).hexdigest()
        for _ in range(warmups):
            forward(bank, n, pooled)
        timings = []
        checks = []
        for _ in range(repeats):
            start = time.perf_counter_ns()
            gates, selected, scores = forward(bank, n, pooled)
            elapsed = time.perf_counter_ns() - start
            if elapsed <= 0:
                raise FleetError('unobserved active-head work')
            timings.append(elapsed)
            checks.append((selected, scores))
        if any(k[0] != checks[0][0] or any(abs(a-b) > 1e-12 for a,b in zip(k[1],checks[0][1])) for k in checks[1:]):
            raise FleetError('non-reproducible Head execution')
        result.append({
            'cell_count': n, 'physically_allocated_head_parameters': len(bank),
            'per_cell_parameter_count': PARAMS, 'physically_allocated_head_bytes': len(bank)*2,
            'original_encoder_forwards_in_this_stage': 0,
            'actual_complete_gate_evaluations': n * (warmups + repeats),
            'actual_active_head_evaluations': TOP_K * (warmups + repeats),
            'physical_head_parameter_sha256': bank_sha,
            'rss_kib_before': before_rss, 'rss_kib_after_allocation': allocated_rss,
            'host_process_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            'parameter_setup_cpu_ns': setup_cpu_ns,
            'head_only_wall_ns_samples': timings,
            'head_only_p95_ns_descriptive': sorted(timings)[math.ceil(.95*len(timings))-1],
            'selected_cell_indices': checks[0][0],
            'selected_head_scores': checks[0][1],
            'complete_gate_score_sha256': hashlib.sha256(b''.join(struct.pack('>d',g) for g in gates)).hexdigest(),
        })
        del bank
    return {'schema': 'hepta.stem.cell-fleet-physical.v3',
            'parameter_profile': PROFILE, 'feature_sha256': feature_sha256,
            'review_sha256': review_sha256,
            'feature_rows': rows, 'head_width': WIDTH, 'rank': RANK,
            'warmups': warmups, 'repeats': repeats,
            'results': result,
            'physical_pretrained_encoder_forward_in_this_stage': False,
            'real_task_success_measured': False,
            'parameters_trained': False,
            'independent_model_issuer_signature_verified': False,
            'production_authorized': False, 'authority': 'DENY_ALL'}


def main():
    from granite97_feature_bridge_v2 import bridge, read_regular
    p = argparse.ArgumentParser()
    for key in ('source', 'export', 'review', 'output'):
        p.add_argument('--' + key, required=True)
    args = p.parse_args()
    state = bridge(read_regular(args.source, 65536),
                   read_regular(args.export, 2_500_000),
                   read_regular(args.review, 65536), now_ms=time.time_ns()//1_000_000)
    r = calculate(state.q24_blob, state.envelope.slot_count,
                  feature_sha256=state.replay['q24_blob_sha256'],
                  review_sha256=state.replay['review_sha256'])
    r['feature_envelope_key'] = state.replay['feature_envelope_key']
    out = Path(args.output)
    if out.exists() or out.is_symlink():
        raise FleetError('output exists')
    with out.open('xb') as fd:
        fd.write((json.dumps(r, sort_keys=True, allow_nan=False, separators=(',',':'))+'\n').encode())
        fd.flush(); os.fsync(fd.fileno())

if __name__ == '__main__':
    main()
