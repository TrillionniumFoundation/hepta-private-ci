"""Small pre-formal pipeline check; keep complete child receipts and failures."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', type=int, required=True)
    args = parser.parse_args()
    if args.attempt < 2:
        raise ValueError('Attempt 1 is retained unchanged; use a new attempt number')
    base = Path(__file__).resolve().parents[1]
    repo = base.parents[2]
    output = base / f'results/development_{args.attempt:02d}'
    receipts = base / f'results/development_{args.attempt:02d}_process'
    receipts.mkdir(parents=True, exist_ok=False)
    common = [sys.executable, '-B', '-m',
              'experiments.hcsn_validation_r14_20261101.content.study']
    jobs = [
        ('freeze', ['freeze', '--output', str(output), '--updates', '2']),
        ('frozen_backend', ['train', '--output', str(output), '--task', 'recall',
                            '--seed', '12031', '--mode', 'frozen_backend']),
        ('joint_backend', ['train', '--output', str(output), '--task', 'recall',
                           '--seed', '12031', '--mode', 'joint_backend']),
    ]
    records = []
    start = time.perf_counter()
    own_cpu = time.process_time()
    for name, arguments in jobs:
        command = common + arguments
        begin = time.perf_counter()
        with (receipts / (name + '.stdout')).open('xb') as out, \
                (receipts / (name + '.stderr')).open('xb') as err:
            child = subprocess.Popen(command, cwd=repo, stdout=out, stderr=err)
            _, status, usage = os.wait4(child.pid, 0)
            code = os.waitstatus_to_exitcode(status)
            child.returncode = code
        record = dict(command=command, exit_code=code,
                      cpu_seconds=usage.ru_utime + usage.ru_stime,
                      wall_seconds=time.perf_counter() - begin,
                      max_rss_bytes=int(usage.ru_maxrss * 1024),
                      energy_joules=None, heldout_opened=False)
        (receipts / (name + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        records.append(record)
        print(json.dumps(dict(job=name, exit_code=code,
                              cpu_seconds=record['cpu_seconds'])), flush=True)
        if code:
            (receipts / 'TOTAL.json').write_text(json.dumps(dict(
                records=records, child_cpu_seconds=sum(r['cpu_seconds'] for r in records),
                coordinator_cpu_seconds=time.process_time() - own_cpu,
                wall_seconds=time.perf_counter() - start, heldout_opened=False,
                complete=False), indent=2) + '\n')
            raise RuntimeError('Development failure retained: ' + name)
    (receipts / 'TOTAL.json').write_text(json.dumps(dict(
        records=records, child_cpu_seconds=sum(r['cpu_seconds'] for r in records),
        coordinator_cpu_seconds=time.process_time() - own_cpu,
        wall_seconds=time.perf_counter() - start, heldout_opened=False), indent=2) + '\n')


if __name__ == '__main__':
    main()
