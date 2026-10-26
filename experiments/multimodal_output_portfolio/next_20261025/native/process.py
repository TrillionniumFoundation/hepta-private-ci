"""Measure one explicitly selected native study process and its descendants."""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .common import sha


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--module', choices=tuple(__package__ + '.' + name for name in ('run', 'boundaries', 'collect_qualification')), required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    entry = Path(importlib.util.find_spec(args.module).origin)
    extra = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    command = [sys.executable, '-B', '-m', args.module, *extra]
    registration = args.receipt.with_suffix('.registration.json')
    log = args.receipt.with_suffix('.log')
    if any(p.exists() for p in (args.receipt, registration, log)):
        raise FileExistsError('Process evidence must use new paths')
    write(registration, {'schema': 'hepta.next.native-process-registration.v1',
                         'command': command, 'cwd': os.getcwd(), 'entrypoint_sha256': sha(entry),
                         'wrapper_sha256': sha(__file__), 'registered_ns': time.time_ns()})
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    with log.open('xb') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        waited, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        stream.flush()
        os.fsync(stream.fileno())
    write(args.receipt, {'schema': 'hepta.next.native-process-cost.v1', 'command': command,
                        'child_pid': child.pid, 'waited_pid': waited, 'exit_code': child.returncode,
                        'wall_ns': time.monotonic_ns() - began, 'wrapper_cpu_ns': time.process_time_ns() - cpu,
                        'child_user_seconds': usage.ru_utime, 'child_system_seconds': usage.ru_stime,
                        'peak_rss_bytes': usage.ru_maxrss * 1024,
                        'registration_sha256': sha(registration), 'log_sha256': sha(log),
                        'cost_scope': 'Python child including waited native subprocesses; Linux wait4 ru_maxrss is peak, not sum'})
    print(json.dumps({'receipt': str(args.receipt), 'exit_code': child.returncode}), flush=True)
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
