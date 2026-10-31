"""Exact child-PID receipt including launch, imports, work, failure and exit."""

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from ...abc_recovery.base_recovery import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--module', required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.module.startswith('experiments.multimodal_output_portfolio.closure_20261025.control.'):
        raise ValueError('Only this registered control study is permitted')
    spec = importlib.util.find_spec(args.module)
    if spec is None or spec.origin is None:
        raise ValueError('Unavailable child entrypoint')
    log, registration = args.receipt.with_suffix('.log'), args.receipt.with_suffix('.registration.json')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    if any(p.exists() for p in (args.receipt, log, registration)):
        raise FileExistsError('Actual process observations cannot be overwritten')
    extra = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    command = [sys.executable, '-B', '-u', '-m', args.module, *extra]
    write_json(registration, {'schema': 'hepta.closure.exact-child-registration.v1', 'unix_ns': time.time_ns(),
               'command': command, 'cwd': str(Path.cwd()), 'wrapper_pid': os.getpid(), 'wrapper_parent_pid': os.getppid(),
               'python': sys.version, 'torch': importlib.metadata.version('torch'), 'numpy': importlib.metadata.version('numpy'),
               'platform': platform.platform(), 'entrypoint_sha256': hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest(),
               'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    with log.open('xb') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        stream.flush(); os.fsync(stream.fileno())
    result = {'schema': 'hepta.closure.exact-child-receipt.v1', 'exit_code': child.returncode,
              'child_pid': child.pid, 'parent_pid': os.getpid(), 'wall_ns': time.perf_counter_ns() - wall,
              'wrapper_cpu_ns': time.process_time_ns() - cpu, 'child_cpu_ns': round(1e9 * (usage.ru_utime + usage.ru_stime)),
              'child_peak_rss_bytes_linux': usage.ru_maxrss * 1024,
              'registration_sha256': hashlib.sha256(registration.read_bytes()).hexdigest(),
              'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest(),
              'scope': 'Entire child launch/imports/work/output/exit and log fsync; shared Linux host, excludes this receipt write'}
    write_json(args.receipt, result)
    print(json.dumps(result), flush=True)
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
