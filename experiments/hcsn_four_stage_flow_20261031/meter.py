"""POSIX whole-child meter. Usage: --out PREFIX [--artifact FILE] -- COMMAND ...

The command inherits the current environment unchanged. There is no timeout.
Files PREFIX.stdout.log, PREFIX.stderr.log and PREFIX.receipt.json are unique;
an existing prefix or any existing output refuses execution. wait4 accounting
is reported separately from wrapper overhead and inner application timers.
"""

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


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def file_record(path):
    path = Path(path)
    if not path.is_file():
        return dict(path=str(path), is_file=False)
    return dict(path=str(path), is_file=True, bytes=path.stat().st_size, sha256=sha256(path))


def execute(prefix, command, artifacts):
    if not hasattr(os, 'wait4'):
        raise RuntimeError('This meter requires POSIX os.wait4')
    prefix = Path(prefix)
    paths = {key: Path(str(prefix) + suffix) for key, suffix in
             [('stdout', '.stdout.log'), ('stderr', '.stderr.log'), ('receipt', '.receipt.json')]}
    if prefix.exists() or any(path.exists() for path in paths.values()):
        raise FileExistsError('Meter refuses an existing prefix or output: ' + str(prefix))
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive receipt creation also reserves the name against another wrapper.
    with paths['receipt'].open('x') as receipt_stream:
        receipt = dict(schema='hcsn.complete-child-meter.v1', status='starting',
            command=command, cwd=os.getcwd(), environment='inherited unchanged',
            started_utc=datetime.now(timezone.utc).isoformat(),
            meter_source_sha256=sha256(__file__),
            stdout_path=str(paths['stdout']), stderr_path=str(paths['stderr']))

        def save():
            receipt_stream.seek(0)
            json.dump(receipt, receipt_stream, indent=2, allow_nan=False)
            receipt_stream.write('\n'); receipt_stream.truncate(); receipt_stream.flush()

        save()
        start, wrapper_start = time.perf_counter(), time.process_time()
        usage = None; child = None; returncode = 127; launch_error = None
        forwarded = []
        prior_handlers = {}

        def forward(signum, frame):
            forwarded.append(signum)
            if child is not None:
                try:
                    os.kill(child.pid, signum)
                except ProcessLookupError:
                    pass

        try:
            with paths['stdout'].open('xb') as stdout, paths['stderr'].open('xb') as stderr:
                child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
                receipt.update(status='running', pid=child.pid)
                save()
                print(json.dumps(dict(status='running', pid=child.pid, receipt=str(paths['receipt']))), flush=True)
                for signum in (signal.SIGINT, signal.SIGTERM):
                    prior_handlers[signum] = signal.signal(signum, forward)
                while True:
                    try:
                        _, wait_status, usage = os.wait4(child.pid, 0)
                        break
                    except InterruptedError:
                        continue
                returncode = os.waitstatus_to_exitcode(wait_status)
                child.returncode = returncode  # Popen must not reap a second time.
        except OSError as error:
            launch_error = str(error)
        finally:
            for signum, handler in prior_handlers.items():
                signal.signal(signum, handler)
        elapsed = time.perf_counter() - start
        receipt.update(status='completed' if usage is not None else 'launch_failed',
            finished_utc=datetime.now(timezone.utc).isoformat(), returncode=returncode,
            wrapper_exit_code=returncode if returncode >= 0 else 128 - returncode,
            wall_seconds=elapsed, launch_error=launch_error, forwarded_signals=forwarded,
            user_cpu_seconds=None if usage is None else usage.ru_utime,
            system_cpu_seconds=None if usage is None else usage.ru_stime,
            total_cpu_seconds=None if usage is None else usage.ru_utime + usage.ru_stime,
            peak_rss_bytes=None if usage is None else usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024),
            peak_rss_native_units=None if usage is None else usage.ru_maxrss,
            accounting='os.wait4 on direct child, including interpreter startup, imports and writes; no separate live descendant enumeration',
            rss_scope='wait4 peak RSS, not aggregate simultaneous process-tree memory',
            wall_scope='wrapper before Popen through child wait and log close; artifact hashing follows',
            cpu_additivity='Inner process timers are contained in this measurement; do not add them again')
        receipt['logs'] = [file_record(paths[key]) for key in ('stdout', 'stderr')]
        receipt['artifacts'] = [file_record(path) for path in artifacts]
        receipt['meter_source_unchanged'] = receipt['meter_source_sha256'] == sha256(__file__)
        receipt['wrapper_cpu_seconds'] = time.process_time() - wrapper_start
        receipt['wrapper_cpu_scope'] = 'After initial receipt, through optional hashing; final receipt write excluded'
        save()
        print(json.dumps(dict(status=receipt['status'], returncode=returncode,
                              receipt=str(paths['receipt']), wall_seconds=elapsed,
                              total_cpu_seconds=receipt['total_cpu_seconds'])), flush=True)
        return receipt['wrapper_exit_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--artifact', action='append', default=[])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command:
        parser.error('Pass a command after --')
    try:
        return execute(args.out, command, args.artifact)
    except FileExistsError as error:
        parser.error(str(error))


if __name__ == '__main__':
    raise SystemExit(main())
