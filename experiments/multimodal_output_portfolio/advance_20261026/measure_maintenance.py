"""Measure evidence sealing or verified duplicate reclamation, never model work."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())


def resources():
    root = Path('/sys/fs/cgroup')
    disk = os.statvfs(Path.cwd())
    return {'actual_free_bytes': disk.f_bfree * disk.f_frsize,
            'cgroup_memory_events': (root / 'memory.events').read_text(),
            'cgroup_memory_current': int((root / 'memory.current').read_text())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--operation', choices=('seal_evidence', 'reclaim_verified_members'), required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    registration, log = args.receipt.with_suffix('.registration.json'), args.receipt.with_suffix('.log')
    if any(path.exists() for path in (args.receipt, registration, log)):
        raise FileExistsError('Prior process attempts must be retained')
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    extra = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    entrypoint = Path(__file__).with_name(args.operation + '.py')
    command = [sys.executable, '-B', '-u', '-m', __package__ + '.' + args.operation, *extra]
    write(registration, {'schema': 'hepta.advance.maintenance-launch.v1', 'command': command,
        'cwd': str(Path.cwd()), 'python': sys.version, 'entrypoint_sha256': sha(entrypoint),
        'wrapper_sha256': sha(__file__), 'started_unix_ns': time.time_ns(), 'resources_before': resources()})
    started = time.monotonic_ns()
    with log.open('xb') as stream:
        child = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
        waited, status, usage = os.wait4(child.pid, 0)
        child.returncode = os.waitstatus_to_exitcode(status)
        stream.flush(); os.fsync(stream.fileno())
    result = {'schema': 'hepta.advance.maintenance-process.v1', 'child_pid': child.pid,
        'waited_pid': waited, 'returncode': child.returncode, 'wall_ns': time.monotonic_ns() - started,
        'child_cpu_ns': round(1e9 * (usage.ru_utime + usage.ru_stime)),
        'child_peak_rss_bytes_linux': usage.ru_maxrss * 1024,
        'registration_sha256': sha(registration), 'log_sha256': sha(log), 'resources_after': resources(),
        'cost_scope': 'Whole maintenance child, imports, hashing, archive operations, log fsync and exit; separate from inference and training.'}
    write(args.receipt, result)
    print(json.dumps(result), flush=True)
    raise SystemExit(child.returncode)


if __name__ == '__main__':
    main()
