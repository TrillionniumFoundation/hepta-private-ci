"""One-shot process envelope for the frozen research phases; never retries."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


LIMITS = {
    'main': (145, 150, 240, 'run_main.py'),
    'confirmation': (55, 60, 120, 'run_confirmation.py'),
    'reader': (55, 60, 120, 'verify_records.py'),
}
THREAD_KEYS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS')


def utc():
    return datetime.now(timezone.utc).isoformat()


def pin(path):
    path = Path(path).resolve()
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def save(path, value):
    # Exclusive creation makes failure and launch receipts immutable within a run.
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def command_for(kind, protocol, output, main=None, confirmation=None):
    if kind not in LIMITS:
        raise ValueError('unknown phase')
    command = [sys.executable, str(Path(__file__).resolve().with_name(LIMITS[kind][3])),
               '--protocol', str(Path(protocol).resolve()), '--output', str(Path(output).resolve())]
    if kind in ('confirmation', 'reader'):
        if main is None:
            raise ValueError('main artifacts required')
        command += ['--main', str(Path(main).resolve())]
    elif main is not None:
        raise ValueError('main phase cannot consume a prior main')
    if kind == 'reader':
        if confirmation is None:
            raise ValueError('confirmation artifacts required')
        command += ['--confirmation', str(Path(confirmation).resolve())]
    elif confirmation is not None:
        raise ValueError('only the reader consumes confirmation')
    return command


def main(args):
    wall_start, self_start = time.monotonic(), time.process_time()
    soft, hard, wall, script = LIMITS[args.kind]
    root = args.run_dir.resolve()
    command = command_for(args.kind, args.protocol, root / 'output', args.main, args.confirmation)
    environment = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONHASHSEED='0')
    environment.update({key: '1' for key in THREAD_KEYS})
    # Explicit frozen dependency prefix; caller-provided Python paths are not inherited.
    environment['PYTHONPATH'] = str(args.python_packages.resolve())
    source = pin(Path(__file__))
    protocol_before = pin(args.protocol)
    entry_before = pin(Path(__file__).with_name(script))
    root.mkdir(parents=True, exist_ok=False)
    launch = {'schema': 'hepta-value-process-launch-v1', 'phase': args.kind,
              'created_utc': utc(), 'command': command, 'protocol_pin': protocol_before,
              'entry_pin': entry_before, 'supervisor_pin': source,
              'CPU_soft_seconds': soft, 'CPU_hard_seconds': hard,
              'wall_seconds': wall, 'address_space_bytes': 512 * 1024 * 1024,
              'affinity': [7], 'threads': 1, 'python_packages': environment['PYTHONPATH'],
              'retry_permitted': False}
    save(root / 'LAUNCH.json', launch)

    def constrain():
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (soft, hard))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    process, timeout, error = None, False, None
    launched_at = time.monotonic()
    try:
        with (root / 'stdout.txt').open('xb') as stdout, (root / 'stderr.txt').open('xb') as stderr:
            process = subprocess.Popen(command, env=environment, stdout=stdout, stderr=stderr,
                                       start_new_session=True, preexec_fn=constrain)
            try:
                process.wait(timeout=wall)
            except subprocess.TimeoutExpired:
                timeout = True
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    except BaseException as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    child_wall = time.monotonic() - launched_at
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_user = after.ru_utime - before.ru_utime
    cpu_system = after.ru_stime - before.ru_stime
    unchanged = (pin(args.protocol) == protocol_before and
                 pin(Path(__file__).with_name(script)) == entry_before and pin(__file__) == source)
    result_name = 'READER_RESULTS.json' if args.kind == 'reader' else 'RESULTS.json'
    expected_status = 'PASS' if args.kind == 'reader' else 'COMPLETED'
    result_path = root / 'output' / result_name
    result_pin, result_status = None, None
    if result_path.is_file():
        result_pin = pin(result_path)
        try:
            result_status = json.loads(result_path.read_text())['status']
        except (ValueError, KeyError, TypeError) as exc:
            error = error or {'type': type(exc).__name__, 'message': 'invalid RESULTS.json: ' + str(exc)}
    returncode = process.returncode if process is not None else None
    completed = (returncode == 0 and not timeout and error is None and unchanged
                 and cpu_user + cpu_system <= hard and child_wall <= wall
                 and result_status == expected_status)
    receipt = dict(launch, schema='hepta-value-process-receipt-v1', completed_utc=utc(),
        status='COMPLETED' if completed else 'FAILED_OR_UNKNOWN', returncode=returncode,
        wall_timeout=timeout, error=error, protocol_and_entry_unchanged=unchanged,
        child_user_CPU_seconds=cpu_user, child_system_CPU_seconds=cpu_system,
        child_CPU_seconds=cpu_user + cpu_system, child_wall_seconds=child_wall,
        supervisor_CPU_seconds=time.process_time() - self_start,
        supervisor_wall_seconds=time.monotonic() - wall_start,
        child_maxrss_KiB=after.ru_maxrss, result_status=result_status, result_pin=result_pin,
        expected_result_status=expected_status)
    save(root / 'PROCESS.json', receipt)
    print(json.dumps({'status': receipt['status'], 'receipt': str(root / 'PROCESS.json'),
                      'child_CPU_seconds': receipt['child_CPU_seconds'],
                      'supervisor_CPU_seconds': receipt['supervisor_CPU_seconds'],
                      'child_wall_seconds': receipt['child_wall_seconds']}, sort_keys=True), flush=True)
    return 0 if completed else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', required=True, choices=tuple(LIMITS))
    parser.add_argument('--protocol', required=True, type=Path)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--main', type=Path)
    parser.add_argument('--confirmation', type=Path)
    parser.add_argument('--python-packages', required=True, type=Path)
    sys.exit(main(parser.parse_args()))
