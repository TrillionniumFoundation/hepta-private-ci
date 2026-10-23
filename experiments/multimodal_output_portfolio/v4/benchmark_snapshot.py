"""Physical cost comparison for the finite compiled policy research fast path.

Offline compilation is kept distinct from per-request lookup and toy emission.
This test is in no way a natural model/device/energy benchmark.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import time

from portfolio import Config, Controller, State, execute
from snapshot_policy import (compile_optimal_snapshot, current_source_digest,
                             rollout_snapshot)


def percentile(xs: list[float], q: float) -> float:
    if not xs or any(not math.isfinite(x) or x < 0 for x in xs):
        raise ValueError('invalid latency values')
    return sorted(xs)[max(0, math.ceil(len(xs) * q) - 1)]


def run() -> dict:
    cfg = Config(horizon=2, max_units_per_step=2, risk_aversion=0.5)
    initial = State((0, 0, 0, 0), 12)
    digest = current_source_digest()
    start_compile = time.perf_counter_ns()
    snap = compile_optimal_snapshot(initial, cfg, digest)
    compile_ms = (time.perf_counter_ns() - start_compile) / 1e6
    exact_ms, lookup_ms, emit_ms = [], [], []
    for seed in range(12):
        start = time.perf_counter_ns()
        Controller(cfg).solve(initial)
        exact_ms.append((time.perf_counter_ns() - start) / 1e6)
    for _ in range(1000):
        start = time.perf_counter_ns()
        snap.choose(initial, cfg, digest, 'FINITE_SYNTHETIC_DENY_ALL')
        lookup_ms.append((time.perf_counter_ns() - start) / 1e6)
    for seed in range(100):
        start = time.perf_counter_ns()
        out = rollout_snapshot(snap, cfg, digest, seed)
        emit_ms.append((time.perf_counter_ns() - start) / 1e6)
        expected = execute(initial, cfg, seed)
        if (out['outputs'] != expected['outputs']
            or out['paid_units'] != expected['spent']
            or out['external_fixture_loss'] != expected['external_fixture_loss']):
            raise AssertionError('independent output parity failed')
    root = Path(__file__).resolve().parent
    return {
        'schema': 'hepta.ndu-v4.compiled-fastpath-cost.v1',
        'scope': 'RESEARCH_ONLY_DENY_ALL_TOY_OUTPUT',
        'source_sha256': {p:hashlib.sha256((root / p).read_bytes()).hexdigest()
                          for p in ('portfolio.py','snapshot_policy.py','benchmark_snapshot.py')},
        'runner_unverified':os.getenv('RUNNER_NAME','local'),
        'git_head_unverified':os.getenv('GITHUB_SHA','not-set'),
        'host':platform.platform(),
        'python':platform.python_version(),
        'compiled_artifact_digest':snap.policy_sha256,
        'compiled_states':len(snap.entries),
        'offline_oracle_work':dict(snap.offline_work),
        'offline_compile_ms':compile_ms,
        'cold_exact_solver_samples':len(exact_ms),
        'cold_exact_solver_p50_ms':statistics.median(exact_ms),
        'cold_exact_solver_p95_ms':percentile(exact_ms,.95),
        'online_lookup_samples':len(lookup_ms),
        'online_lookup_p50_ms':statistics.median(lookup_ms),
        'online_lookup_p95_ms':percentile(lookup_ms,.95),
        'online_lookup_2ms_diagnostic':percentile(lookup_ms,.95)<=2.,
        'online_toy_rollout_samples':len(emit_ms),
        'online_toy_rollout_p95_ms':percentile(emit_ms,.95),
        'same_action_and_decoded_output':True,
        'no_pretrained_encoders_decoders_or_training':True,
    }


if __name__ == '__main__':
    print(json.dumps(run(), indent=2, sort_keys=True))
