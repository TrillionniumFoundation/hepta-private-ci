"""New CPU cost measurement of the recovered same-template three-mode kernel.

This does not reconstruct the lost original clock readings. Ordinary FP32 is
timed only as an explicitly unqualified diagnostic baseline. Failed batches
are retained and never included in comparable completed-evaluation ratios.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np
from threadpoolctl import threadpool_limits

from compiled import Kernel
from recovery_eval import dump, seal

ROOT = Path(__file__).resolve().parent
MODES = ('float64', 'float32', 'compensated32')
INPUT_SHA = '07e4abe9e19da7b1617484a0697dbe7fb9767f3b5a33136976327e6b61711836'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(protocol_path, expected, output):
    if output.exists():
        raise ValueError('Output file is create-only')
    p = json.loads(protocol_path.read_text())
    seal(p, protocol_path, expected)
    input_path = ROOT/'regression_input/frozen_PROTOCOL_V3.json'
    if sha(input_path) != INPUT_SHA:
        raise ValueError('Wrong original parameter-case manifest')
    script_hash = sha(Path(__file__))
    cases = json.loads(input_path.read_text())['cases']
    if len(cases) != 18:
        raise ValueError('Expected original eighteen cases')
    theta54 = np.repeat(np.asarray([c['theta'] for c in cases], dtype=np.float32), 3, axis=0)
    state54 = np.tile(np.asarray([.001, .1, 100.], dtype=np.float32), 18)
    coordinates54 = ['log_distance', 'log_distance', 'asset']*18
    theta = np.tile(theta54, (50, 1))
    state = np.tile(state54, 50)
    coordinates = coordinates54*50
    kernel = Kernel(ROOT/'recovered.so')
    conditions = [(reuse, mode) for reuse in (False, True) for mode in MODES]
    warmup = {}
    records = []

    def inspect(values, jacobian, status):
        good = (status == 0) & np.all(np.isfinite(values), axis=1) & np.all(np.isfinite(jacobian), axis=(1, 2))
        failed = [{'index': int(i), 'case': cases[(int(i)%54)//3]['name'],
                   'state': float(state[i]), 'coordinate': coordinates[i], 'status': int(status[i])} for i in np.flatnonzero(~good)]
        checksum = float(values[good].sum()+jacobian[good].sum())
        return failed, checksum

    # One full 2,700-state warmup for each of all six conditions is excluded.
    for reuse, mode in conditions:
        result = kernel.batch(theta, state, coordinates, mode, 3 if reuse else 0)
        failures, checksum = inspect(*result)
        warmup[(reuse, mode)] = (result, failures, checksum)

    for round_index in range(6):
        order = conditions[round_index:]+conditions[:round_index]
        for order_index, (reuse, mode) in enumerate(order):
            wall_start = time.perf_counter_ns()
            cpu_start = time.process_time_ns()
            values, jacobian, status = kernel.batch(theta, state, coordinates, mode, 3 if reuse else 0)
            cpu_ns = time.process_time_ns()-cpu_start
            wall_ns = time.perf_counter_ns()-wall_start
            failures, checksum = inspect(values, jacobian, status)
            original = warmup[(reuse, mode)][0]
            deterministic = all(np.array_equal(a, b, equal_nan=True) for a, b in zip((values, jacobian, status), original))
            comparable = not failures and deterministic
            records.append({'round': round_index, 'order_in_round': order_index, 'mode': mode,
                            'boundary_reuse': reuse, 'evaluations': 2700,
                            'boundary_evaluations': 900 if reuse else 2700,
                            'wall_ns': wall_ns, 'process_cpu_ns': cpu_ns,
                            'complete_batch_comparable': comparable, 'deterministic_vs_warmup': deterministic,
                            'finite_completed_evaluations': 2700-len(failures), 'failures': failures,
                            'diagnostic_checksum': checksum,
                            'wall_seconds_per_complete_state': wall_ns*1e-9/2700 if comparable else None})
        print(json.dumps({'completed_cost_rounds': round_index+1}), flush=True)
    seal(p, protocol_path, expected)
    if sha(Path(__file__)) != script_hash or sha(input_path) != INPUT_SHA:
        raise ValueError('Timing script/input changed')
    summaries = []
    for reuse, mode in conditions:
        sample = [r['wall_seconds_per_complete_state'] for r in records if r['boundary_reuse'] == reuse and r['mode'] == mode and r['complete_batch_comparable']]
        summaries.append({'mode': mode, 'boundary_reuse': reuse, 'comparable_batches': len(sample),
                          'median_seconds_per_state': statistics.median(sample) if len(sample) == 6 else None,
                          'min_seconds_per_state': min(sample) if len(sample) == 6 else None,
                          'max_seconds_per_state': max(sample) if len(sample) == 6 else None})
    reuse_identity = {}
    for mode in MODES:
        a, b = warmup[(False, mode)][0], warmup[(True, mode)][0]
        reuse_identity[mode] = all(np.array_equal(x, y, equal_nan=True) for x, y in zip(a, b))
    result = {
        'schema': 'hcsn.recovered-cpu-cost.v1', 'measurement': 'New clock measurements after executor reset; lost historical clock samples are not reconstructed.',
        'precision': 'Same C++ formulas and ten-column forward AD instantiated for native double, native float, and explicit two-float-word compensated arithmetic.',
        'scope': 'Descriptive single-host CPU cost; includes batch C-API/Python allocation and complete boundary plus five values and fifty partial derivatives. No GPU, energy or model-quality claim.',
        'ordinary_fp32_admitted': False, 'protocol_sha256': expected, 'binary_sha256': p['binary_sha256'],
        'source_sha256': p['source_sha256'], 'script_sha256': script_hash, 'parameter_manifest_sha256': INPUT_SHA,
        'warmup_evaluations': 16200, 'timed_evaluations': 97200,
        'input_words': {'theta54': theta54.tolist(), 'state54': state54.tolist(), 'coordinates54': coordinates54},
        'environment': {'python': platform.python_version(), 'numpy': np.__version__, 'system': platform.platform(), 'threadpool_limit': 1, 'compiler': p['compiler_version']},
        'records': records, 'summaries': summaries, 'boundary_reuse_bit_identity': reuse_identity,
        'warmup_failures': [{'mode': mode, 'boundary_reuse': reuse, 'failures': warmup[(reuse, mode)][1]} for reuse, mode in conditions],
    }
    dump(output, result)
    print(json.dumps({'summaries': summaries, 'reuse_bit_identity': reuse_identity}, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--protocol-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        run(args.protocol, args.protocol_sha256, args.output)
