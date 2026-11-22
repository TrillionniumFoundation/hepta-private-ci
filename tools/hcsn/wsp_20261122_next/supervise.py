"""Bounded, create-only scientific phases with complete child CPU receipts."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import resource
import signal
import subprocess
import sys
import time


def pin(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('generation', 'selection', 'confirmation', 'verification'))
    parser.add_argument('--protocol', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--run-root', type=Path, required=True)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    args = parser.parse_args()
    expected_protocol = pin(args.protocol)
    protocol = json.loads(args.protocol.read_bytes())
    limits = protocol['limits'][args.phase]
    args.attempt.mkdir(parents=True, exist_ok=False)
    entry = Path(__file__).with_name('verify_run.py' if args.phase == 'verification' else 'run_value_study.py')
    command = [sys.executable, '-B', str(entry)]
    if args.phase != 'verification':
        command.append(args.phase)
    command.extend(['--protocol', str(args.protocol.resolve()), '--inputs', str(args.inputs.resolve()),
                    '--run-root', str(args.run_root.resolve()), '--output', str(args.attempt.resolve() / 'output')])
    if args.previous:
        command.extend(['--previous', str(args.previous.resolve())])
    environment = dict(os.environ, PYTHONHASHSEED='0', PYTHONDONTWRITEBYTECODE='1',
                       OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    def restrict():
        os.setsid()
        os.sched_setaffinity(0, {7})
        resource.setrlimit(resource.RLIMIT_CPU, (limits['cpu_hard_seconds']-1, limits['cpu_hard_seconds']))
        resource.setrlimit(resource.RLIMIT_AS, (protocol['address_space_bytes'],) * 2)
    started, cpu = time.monotonic(), time.process_time()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    with (args.attempt / 'stdout.txt').open('xb') as out, (args.attempt / 'stderr.txt').open('xb') as err:
        process = subprocess.Popen(command, stdout=out, stderr=err, env=environment, preexec_fn=restrict)
        wall_timeout = False
        while process.poll() is None:
            if time.monotonic()-started > limits['wall_seconds']:
                wall_timeout = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
            time.sleep(.05)
        process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = args.attempt / 'output/RESULTS.json'
    record = dict(schema='hepta-value-sensitive-process-v1', phase=args.phase,
        status='COMPLETED' if process.returncode == 0 and result.is_file() else 'FAILED',
        returncode=process.returncode, wall_timeout=wall_timeout, command=command,
        protocol_pin=expected_protocol, protocol_unchanged=pin(args.protocol)==expected_protocol,
        entry_pin=pin(entry), result_pin=pin(result) if result.is_file() else None,
        child_CPU_seconds=after.ru_utime+after.ru_stime-before.ru_utime-before.ru_stime,
        supervisor_CPU_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started,
        peak_child_RSS_KiB=after.ru_maxrss, limits=limits)
    with (args.attempt / 'PROCESS.json').open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(json.dumps(record), flush=True)
    sys.exit(0 if record['status']=='COMPLETED' else 1)


if __name__=='__main__':
    main()
