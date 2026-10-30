"""Measure an authorized root helper using reviewed owned-child machinery.

Stdin values and environment values are never copied into receipts. Original
helper stdout/stderr are private operational files; returned descriptors alone
do not establish a successful remote service write.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import sys
import time

from durable_archive import descriptor, require, write_json
from supervisor import OwnedChild, require_matching_proc_namespace


def forward_stdin():
    """The exact owned child becomes the helper without another process/group."""
    require(len(sys.argv) > 4 and sys.argv[3] == '--', 'Invalid stdin-forwarding boundary')
    path, argv = sys.argv[2], sys.argv[4:]
    with Path(path).open('rb') as stream:
        os.dup2(stream.fileno(), 0)
    os.execvpe(argv[0], argv, os.environ)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--cwd', required=True)
    parser.add_argument('--stdin-file')
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    require(args.argv and args.argv[0] == '--' and len(args.argv) > 1, 'Explicit command boundary required')
    require_matching_proc_namespace()
    directory = Path(args.directory).absolute()
    require(directory.is_relative_to(Path(__file__).resolve().parents[3]), 'Engineering receipt must stay in this workspace')
    directory.mkdir(parents=True, exist_ok=False)
    started, cpu, child = time.monotonic(), time.process_time(), None
    intent = {'schema': 'hepta.execution04.root-engineering-intent.1',
        'at_utc': datetime.now(timezone.utc).isoformat(), 'argv': args.argv[1:], 'cwd': args.cwd,
        'stdin': descriptor(args.stdin_file) if args.stdin_file else None,
        'stdin_values_disclosed': False, 'automatic_retry': False}
    write_json(directory / 'INTENT.json', intent)
    argv = args.argv[1:]
    if args.stdin_file:
        argv = [sys.executable, '-B', str(Path(__file__).resolve()), '--stdin-child', intent['stdin']['path'], '--', *argv]
    previous = {}
    def interrupted(signum, frame):
        raise InterruptedError('Root engineering command interrupted by signal ' + str(signum))
    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, interrupted)
        child = OwnedChild(directory, 'helper', argv, args.cwd,
            {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        while child.poll() is None:
            time.sleep(.1)
        result = {'schema': 'hepta.execution04.root-engineering-wait4.1', 'complete': True,
            'at_utc': datetime.now(timezone.utc).isoformat(), 'intent': descriptor(directory / 'INTENT.json'),
            'child': child.result, 'wall_seconds': time.monotonic() - started,
            'measuring_parent_cpu_seconds': time.process_time() - cpu,
            'stdout': descriptor(child.output), 'stderr': descriptor(child.error),
            'command_success': child.result['exit_code'] == 0,
            'service_outcome_requires_reading_actual_tool_result': True,
            'unknown_write_outcome_must_be_reconciled_before_retry': True,
            'scope': 'Local helper and waited descendants; excludes remote service compute and other root commands'}
        write_json(directory / 'WAIT4.json', result)
        print(json.dumps(result), flush=True)
        code = child.result['exit_code']
        return code if code >= 0 else 128 - code
    except BaseException as error:
        stopped = child.stop() if child is not None else {'constructor_cleanup_owned_by_OwnedChild': True}
        write_json(directory / 'FAILED.json', {'schema': 'hepta.execution04.root-engineering-failure.1',
            'error_type': type(error).__name__, 'message': str(error), 'cleanup': stopped,
            'known_child_cost': child.result if child is not None else None,
            'remote_write_outcome_unknown': True, 'automatic_retry': False})
        raise
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--stdin-child':
        forward_stdin()
    else:
        raise SystemExit(main())
