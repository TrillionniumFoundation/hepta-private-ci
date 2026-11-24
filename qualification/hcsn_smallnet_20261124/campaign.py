"""Fresh-process workers with bounded concurrency and explicit parent costs.

The run directory is create-only per attempt. A failed child is evidence, not a
reason to rerun it under the same identity. This driver never constructs data.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def process_rss():
    try:
        import resource
        amount = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(amount if platform.system() == 'Darwin' else amount * 1024)
    except (ImportError, AttributeError):
        return None


def record(path, value):
    with Path(path).open('x') as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def worker(args):
    # Timing starts before importing Torch or the model. process_time() at exit
    # includes all CPU consumed by this process up to the reporting point.
    begin = time.perf_counter()
    result, status, error = None, 'failed', None
    try:
        from .train import fit, load_protocol
        p = load_protocol(args.manifest)
        arm = next(a for a in p['arms'] if a['id'] == args.arm)
        result = fit(p, args.output, arm=arm, neurons=args.neurons, seed=args.seed)
        status = result['status']
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        output = Path(args.output)
        output.mkdir(parents=True, exist_ok=True)
        record(output / 'worker_cost.json', {
            'status': status, 'wrapper_error': error,
            'wall_including_import_seconds': time.perf_counter() - begin,
            'process_cpu_through_report_seconds': time.process_time(),
            'process_peak_rss_bytes': process_rss(),
            'energy_joules': None,
            'energy_reason': 'No process-attributable energy counter.',
            'scope': 'Fresh process; CPU includes interpreter/import up to report; shutdown excluded. Parent separately measures launch-through-exit wall.',
        })
    return 0 if result and result['status'] == 'completed' else 1


def launch_one(command, directory):
    begin = time.perf_counter()
    directory.parent.mkdir(parents=True, exist_ok=True)
    log = directory.parent / (directory.name + '.worker.log')
    env = dict(os.environ, OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
    with log.open('x') as stream:
        child = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                               env=env, check=False)
    row = {'attempt': directory.name, 'returncode': child.returncode,
           'launch_through_exit_wall_seconds': time.perf_counter() - begin,
           'log': log.name}
    print(json.dumps(row), flush=True)
    return row


def launch(args):
    p = json.loads(Path(args.manifest).read_text())
    if args.neurons not in p['independent_neurons'] or not 1 <= args.workers <= 4:
        raise ValueError('declared size and 1..4 concurrent workers required')
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    claim = root / f'SHARD_n{args.neurons}.claim'
    with claim.open('x') as handle:
        handle.write(f'{time.time()}\n')
    begin = time.perf_counter()
    commands = []
    for arm in p['arms']:
        for seed in p['seeds']:
            directory = root / f'n{args.neurons}-{arm["id"]}-s{seed}'
            if directory.exists():
                raise FileExistsError('attempt already exists; duplicate execution refused')
            command = [sys.executable, '-m', __package__ + '.campaign', 'worker',
                       '--manifest', args.manifest, '--output', str(directory),
                       '--neurons', str(args.neurons), '--arm', arm['id'], '--seed', str(seed)]
            commands.append((command, directory))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(launch_one, command, directory) for command, directory in commands]
        rows = [future.result() for future in as_completed(futures)]
    try:
        import resource
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu = usage.ru_utime + usage.ru_stime
    except (ImportError, AttributeError):
        child_cpu = None
    record(root / f'SHARD_n{args.neurons}.json', {
        'neurons': args.neurons, 'workers': args.workers, 'attempts': rows,
        'shard_wall_seconds': time.perf_counter() - begin,
        'all_child_cpu_seconds_including_shutdown': child_cpu,
        'driver_cpu_seconds': time.process_time(),
        'energy_joules': None, 'energy_reason': 'No process-attributable energy counter.',
    })
    return 0 if all(row['returncode'] == 0 for row in rows) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['launch', 'worker'])
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--neurons', required=True, type=int)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--arm')
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    sys.exit(launch(args) if args.action == 'launch' else worker(args))


if __name__ == '__main__':
    main()
