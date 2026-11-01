"""Measure protocol freeze, candidate freeze and aggregation as disjoint jobs."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['freeze', 'candidates', 'summarize'])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    receipts = args.output.parent / (args.output.name + '_admin')
    receipts.mkdir(parents=True, exist_ok=True)
    stem = receipts / args.phase
    module = 'evaluate' if args.phase == 'summarize' else 'study'
    command = [sys.executable, '-B', '-m',
               'experiments.hcsn_validation_r14_20261101.content.' + module,
               args.phase, '--output', str(args.output)]
    begin = time.perf_counter()
    with stem.with_suffix('.stdout').open('xb') as out, \
            stem.with_suffix('.stderr').open('xb') as err:
        child = subprocess.Popen(command, stdout=out, stderr=err)
        _, status, usage = os.wait4(child.pid, 0)
        code = os.waitstatus_to_exitcode(status)
        child.returncode = code
    record = dict(command=command, exit_code=code,
                  cpu_seconds=usage.ru_utime + usage.ru_stime,
                  wall_seconds=time.perf_counter() - begin,
                  max_rss_bytes=int(usage.ru_maxrss * 1024), energy_joules=None,
                  scope='Complete administrative scientific child; disjoint from fit/evaluation workers')
    with stem.with_suffix('.json').open('x') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
    print(json.dumps(record), flush=True)
    print(stem.with_suffix('.stdout').read_text(), end='', flush=True)
    if code:
        raise RuntimeError('Administrative failure retained: ' + args.phase)


if __name__ == '__main__':
    main()
