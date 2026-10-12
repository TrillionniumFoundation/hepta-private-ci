"""Matched admitted-policy CPU batches. Not MCP, GUI or target-host qualification."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import random
import statistics
import time

from development_native import DecisionIR, NativeDecisionCache, PreparedDecision, Rule, interpret


def compare_batches(program, observations, *, repetitions=200, warmup=5):
    if (type(observations) is not tuple or not 1 <= len(observations) <= 32
            or type(repetitions) is not int or not 10 <= repetitions <= 2000
            or type(warmup) is not int or not 0 <= warmup <= 100):
        raise ValueError('invalid bounded benchmark')
    started = time.perf_counter_ns()
    source_paths = (Path(__file__), Path(__file__).with_name('development_native.py'))
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    clock = time.perf_counter_ns()
    reference = PreparedDecision(program)
    reference._check_batch(observations)
    typed_admission = time.perf_counter_ns() - clock
    expected = tuple(interpret(program, row) for row in observations)
    clock = time.perf_counter_ns()
    cache = NativeDecisionCache()
    native, _ = cache.compile(program)
    native_admission = time.perf_counter_ns() - clock
    runners = {'prepared_typed': reference.run_batch,
               'native_scalar_calls': lambda rows: tuple(native(row) for row in rows),
               'native_one_batch_call': native.run_batch}
    for runner in runners.values():
        for _ in range(warmup):
            if runner(observations) != expected:
                raise RuntimeError('warmup policy mismatch')
    timings = {name: [] for name in runners}
    verify_ns = 0
    names = tuple(runners)
    for repeat in range(repetitions):
        # Balanced deterministic rotation, not always measuring one backend first.
        order = names[repeat % len(names):] + names[:repeat % len(names)]
        for name in order:
            clock = time.perf_counter_ns()
            actions = runners[name](observations)
            timings[name].append(time.perf_counter_ns() - clock)
            clock = time.perf_counter_ns()
            if actions != expected:
                raise RuntimeError('same-policy batch mismatch')
            verify_ns += time.perf_counter_ns() - clock
    summaries = {}
    for name, values in timings.items():
        ordered = sorted(values)
        summaries[name] = {'batches': len(values), 'requests': len(values) * len(observations),
                           'batch_p50_ns': statistics.median(values),
                           'batch_p95_ns': ordered[math.ceil(.95 * len(values))-1],
                           'batch_p99_ns': ordered[math.ceil(.99 * len(values))-1],
                           'requests_per_second': len(values) * len(observations) * 1e9 / sum(values)}
    if sources != {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}:
        raise RuntimeError('source changed during benchmark')
    saving = summaries['prepared_typed']['batch_p50_ns'] - summaries['native_one_batch_call']['batch_p50_ns']
    # Compare both admissions; do not claim an amortization if there is no saving.
    setup_delta = max(0, native_admission - typed_admission)
    return {'batch_size': len(observations), 'summaries': summaries, 'raw_batch_ns': timings,
            'typed_admission_wall_ns': typed_admission, 'native_admission_wall_ns': native_admission,
            'incremental_admission_amortization_batches_p50': math.ceil(setup_delta / saving) if saving > 0 else None,
            'native_compilation': native.manifest, 'verification_wall_ns': verify_ns,
            'total_benchmark_wall_ns': time.perf_counter_ns() - started,
            'input_sha256': hashlib.sha256(json.dumps(observations).encode()).hexdigest(),
            'all_actions_equal': True, 'action_inventory': sorted(set(expected)),
            'source_sha256': sources, 'warmup_batches_per_backend': warmup,
            'timing_scope': 'warm numeric decision including input validation, marshalling and output creation',
            'per_item_latency_reported': False, 'queue_latency_measured': False,
            'computer_use_e2e_status': 'not_run', 'mcp_status': 'not_run',
            'wasm_status': 'not_run', 'gpu_status': 'not_run', 'production_authorized': False}


def run(output, *, seed=814):
    output.mkdir(parents=True, exist_ok=False)
    rng = random.Random(seed)
    # Fixed workloads, no calibration/selection on measured latency.
    tiny = DecisionIR(4, (Rule((1., -1., 0., 0.), 0., 1),), 0)
    medium = DecisionIR(16, tuple(Rule(tuple(float((i+j) % 3 - 1) for j in range(16)),
                                     float(i-4), i) for i in range(16)), 17)
    # Mostly rejected guards are a separate stress profile, never hidden padding.
    scan = DecisionIR(64, tuple(Rule(tuple(rng.uniform(-1, 1) for _ in range(64)), 8., i)
                               for i in range(32)), 33)
    reports = {}
    for name, policy in (('tiny', tiny), ('medium', medium), ('guard_scan', scan)):
        for count in (1, 8, 32):
            rows = tuple(tuple(rng.uniform(-1, 1) for _ in range(policy.width)) for _ in range(count))
            report = compare_batches(policy, rows)
            key = f'{name}-batch{count}'
            reports[key] = report
            with (output / f'{key}.json').open('x') as stream:
                json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
                stream.write('\n')
    peak_rss = None
    if platform.system() == 'Linux':
        import resource
        peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
    final = {'schema': 'hepta.research.native-prepared-batch.v1', 'seed': seed,
             'platform': platform.platform(), 'timing_unit': 'ns',
             'linux_process_peak_rss_bytes': peak_rss,
             'rss_is_whole_process_not_incremental': True, 'cases': len(reports),
             'independent_host_attestation': False, 'production_authorized': False}
    with (output / 'manifest.json').open('x') as stream:
        json.dump(final, stream, sort_keys=True, indent=2)
    return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', type=int, default=814)
    args = parser.parse_args()
    print(json.dumps(run(args.output, seed=args.seed)))
