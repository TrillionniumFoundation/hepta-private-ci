"""Time the one read-only packaging child, preserving its outputs on failure."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = BASE / 'p1-short-time-toy-packaging-receipt-v1'
SOURCE = BASE / 'assemble_fixed48_handoff_v1.py'


def identity(path):
    raw = path.read_bytes()
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def write(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def main():
    OUT.mkdir()
    before = identity(SOURCE)
    command = [sys.executable, '-B', str(SOURCE)]
    write(OUT / 'INTENT.json', {'command': command, 'source': before,
          'scope': 'Saved JSON/hash/ZIP evidence assembly only; zero toy computation, model, E or oracle.'})
    started = time.monotonic()
    with (OUT / 'stdout').open('xb') as stdout, (OUT / 'stderr').open('xb') as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        _, status, usage = os.wait4(child.pid, 0)
        rc = os.waitstatus_to_exitcode(status)
        child.returncode = rc
    elapsed = time.monotonic() - started
    result = {'schema': 'fixed48-read-only-packaging-whole-child-receipt-v1',
              'returncode': rc, 'child_pid': child.pid, 'whole_child_wall_seconds': elapsed,
              'whole_child_user_CPU_seconds': usage.ru_utime,
              'whole_child_system_CPU_seconds': usage.ru_stime,
              'whole_child_CPU_seconds': usage.ru_utime + usage.ru_stime,
              'whole_child_peak_RSS_bytes': usage.ru_maxrss * 1024,
              'source_before': before, 'source_after': identity(SOURCE),
              'numeric_executions': 0, 'scope': 'Packaging child only; wrapper own cost and earlier interactive preparation unknown.'}
    archive = BASE / 'p1-short-time-toy-handoff-v1.zip'
    if rc == 0:
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise ValueError('handoff CRC failure')
        result['archive'] = {'path': str(archive), **identity(archive)}
        result['manifest'] = identity(BASE / 'p1-short-time-toy-handoff-v1/MANIFEST.json')
        result['status'] = 'completed_read_only_packaging'
    else:
        result['status'] = 'failed_read_only_packaging'
    write(OUT / 'RESULT.json', result)
    print(json.dumps(result, sort_keys=True))
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
