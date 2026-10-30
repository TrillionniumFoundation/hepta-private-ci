"""Measure the entire training/execution coordinator, including its startup."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--raw-root', type=Path, required=True)
    parser.add_argument('--prior-attempt', action='append', type=Path, default=[])
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Campaign requires a new output directory')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_log = args.output.with_suffix('.campaign.log')
    command = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.task_value_run',
               '--output', str(args.output), '--raw-root', str(args.raw_root)]
    for prior in args.prior_attempt:
        command.extend(['--prior-attempt', str(prior)])
    started = time.perf_counter()
    with temporary_log.open('x') as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
    if not args.output.exists():
        args.output.mkdir()
    final_log = args.output / 'CAMPAIGN.log'
    temporary_log.rename(final_log)
    receipt = {'command': command, 'exit_code': process.returncode,
               'complete_child_cpu_seconds': usage.ru_utime + usage.ru_stime,
               'child_user_cpu_seconds': usage.ru_utime, 'child_system_cpu_seconds': usage.ru_stime,
               'wall_seconds': time.perf_counter() - started,
               'peak_rss_kib_linux': usage.ru_maxrss,
               'log_sha256': hashlib.sha256(final_log.read_bytes()).hexdigest(),
               'measurement': 'Outer wait4 covers coordinator startup/imports, all waited study workers and their waited native descendants; phase totals are nested, not additive.',
               'analysis_parent_self_cpu_seconds_before_report_import': time.process_time()}
    with (args.output / 'CAMPAIGN_EXECUTION.json').open('x') as handle:
        json.dump(receipt, handle, indent=2)
        handle.write('\n')
    if process.returncode:
        raise RuntimeError('Failed campaign retained: ' + str(final_log))
    from .task_value_report import report
    report(args.output)
    with (args.output / 'ANALYSIS_PARENT_EXECUTION.json').open('x') as handle:
        json.dump({'whole_parent_self_cpu_seconds_through_report': time.process_time(),
                   'scope': 'Outer supervisor and final audit/report, including analysis imports; child campaign is separate.',
                   'campaign_wait4_cpu_seconds': receipt['complete_child_cpu_seconds']}, handle, indent=2)
        handle.write('\n')
    print(json.dumps({'status': 'completed', 'output': str(args.output),
                      'complete_campaign_child_cpu_seconds': receipt['complete_child_cpu_seconds']}), flush=True)


if __name__ == '__main__':
    main()
