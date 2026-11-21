"""Record process success/failure costs without timeout or kill controllers."""
import json
from pathlib import Path
import resource
import subprocess
import sys
import time


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2:
        raise SystemExit('usage: measure.py RECORD COMMAND [ARG ...]')
    start = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    try:
        result = subprocess.run(args[1:], check=False)
    except OSError as exc:
        # No child completed: child CPU/RSS are unknown, never zero-filled.
        record = {
            'command': args[1:], 'status': 'launch_failed', 'exit_code': None,
            'error': {'type': type(exc).__name__, 'errno': exc.errno, 'message': str(exc)},
            'user_cpu_seconds': None, 'system_cpu_seconds': None, 'peak_rss_KiB': None,
            'resource_note': 'Child did not launch; child resource measurements unavailable.',
        }
        return_code = 127
    else:
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        record = {
            'command': args[1:],
            'status': 'succeeded' if result.returncode == 0 else 'child_failed',
            'exit_code': result.returncode,
            'user_cpu_seconds': after.ru_utime - before.ru_utime,
            'system_cpu_seconds': after.ru_stime - before.ru_stime,
            'peak_rss_KiB': after.ru_maxrss,
        }
        return_code = result.returncode
    record['wall_seconds'] = time.perf_counter() - start
    record['wall_scope'] = 'wrapper elapsed time including launch attempt'
    Path(args[0]).write_text(json.dumps(record, indent=2) + '\n')
    return return_code


if __name__ == '__main__':
    sys.exit(main())
