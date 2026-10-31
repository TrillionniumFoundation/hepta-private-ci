"""Bounded hosted continuation; source seals, failures and costs are durable."""

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

from experiments.hcsn_conservative_acceleration_v1.hosted.runner import RunBook, write_new


BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
MODULE = 'experiments.hcsn_blocker_closure_v1'
CONTENT = BASE / 'content/results/hosted001'
RECEIPTS = BASE / 'results/hosted001'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'finalize'))
    args = parser.parse_args()
    book = RunBook(RECEIPTS / args.command, args.command)
    result = {'complete': False}
    try:
        if args.command == 'prepare':
            head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
            if head != os.environ.get('GITHUB_SHA'):
                raise ValueError('Checkout differs from public execution seal')
            if os.environ.get('GITHUB_REPOSITORY', '').lower() != 'trillionniumfoundation/hepta-private-ci':
                raise ValueError('Unexpected repository execution identity')
            expected = {'torch': '2.8.0+cpu', 'numpy': '2.3.5', 'scipy': '1.17.0'}
            actual = {name: importlib.metadata.version(name) for name in expected}
            if actual != expected or sys.version_info[:3] != (3, 12, 14):
                raise ValueError('Pinned numerical runtime changed')
            cgroup = {name: (Path('/sys/fs/cgroup') / name).read_text()
                      for name in ('cpu.max', 'memory.max', 'memory.swap.max', 'memory.events', 'memory.stat')}
            quota, period = map(int, cgroup['cpu.max'].split())
            if quota != 4 * period or int(cgroup['memory.max']) != 8 * 1024**3 or int(cgroup['memory.swap.max']) != 0:
                raise ValueError('Declared resource isolation was not applied')
            write_new(RECEIPTS / 'EXECUTION_IDENTITY.json', dict(
                seal=head, run_id=os.environ.get('GITHUB_RUN_ID'), run_attempt=os.environ.get('GITHUB_RUN_ATTEMPT'),
                python=sys.version, packages=actual, cgroup=cgroup, concurrent_workers=4,
                image='python:3.12.14@sha256:6dc02694c53fde08b0e39de9273a708d2f2a612f77dc173a64835c3f7a40ee35',
                image_digest_independently_attested=False, energy_joules=None, gpu_executed=False))
            book.run('finite_qvi', [sys.executable, '-m', MODULE + '.oracle.audit', '--output',
                                    str(BASE / 'oracle/results/hosted001')])
            book.run('torch_bridge', [sys.executable, '-m', MODULE + '.oracle.torch_bridge_tests', '--output',
                                     str(BASE / 'oracle/results/torch_hosted001')])
            preflight = BASE / 'content/results/hosted_preflight001.json'
            book.run('content_preflight', [sys.executable, '-m', MODULE + '.content.preflight', '--output', str(preflight)])
            book.run('registration', [sys.executable, '-m', MODULE + '.content.study', 'register',
                                      '--output', str(CONTENT), '--preflight', str(preflight)])
            result = {'complete': True, 'formal_outcomes_read': False}
        elif args.command == 'train':
            for stage in ('development', 'fixed', 'equal_cpu'):
                book.run(stage, [sys.executable, '-m', MODULE + '.content.study', 'run',
                                 '--output', str(CONTENT), '--stage', stage, '--workers', '4'])
                if stage == 'development':
                    book.run('selection_lock', [sys.executable, '-m', MODULE + '.content.study', 'lock',
                                                '--output', str(CONTENT)])
            result = {'complete': True}
        else:
            analysis = book.run('content_analysis', [sys.executable, '-m', MODULE + '.content.study', 'analyze',
                                                     '--output', str(CONTENT)], required=False)
            analysis_path = CONTENT / 'ANALYSIS.json'
            scientific = json.loads(analysis_path.read_text()) if analysis_path.exists() else {}
            expected_jobs = json.loads((BASE / 'HOSTED_LAUNCH.json').read_text())['expected_jobs']['total']
            integrity = (analysis['exit_code'] == 0 and scientific.get('complete') is True
                         and scientific.get('errors') == [] and scientific.get('valid_results') == expected_jobs)
            binary = Path(os.environ['RUNNER_TEMP']) / 'hcsn-native-owner'
            restore = book.run('native_restore', [sys.executable, '-m', 'experiments.hcsn_free_boundary_v1.restore_native',
                                                   str(binary)], required=False)
            native = None
            if restore['exit_code'] == 0:
                native = book.run('native_task', [sys.executable, '-m', MODULE + '.runtime.measure',
                                                  '--output', str(BASE / 'runtime/results/hosted001'),
                                                  '--binary', str(binary)], required=False)
            result = {'complete': integrity and native is not None and native['exit_code'] == 0,
                      'content_integrity': integrity,
                      'scientific_advantage_not_required_for_integrity': True,
                      'native_scope': 'Exact-task analytic policy engineering replay; not a trained content neural kernel.'}
            if not result['complete']:
                raise RuntimeError('One or more integrity/execution stages failed; evidence retained')
    except BaseException:
        write_new(RECEIPTS / args.command / 'FATAL.json', dict(
            exception=traceback.format_exc(), stage=args.command, complete=False))
        raise
    finally:
        print(json.dumps(book.finish(result), sort_keys=True))


if __name__ == '__main__':
    main()
