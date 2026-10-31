"""Execute the fresh actor study against an exact, independently published dataset."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
import traceback

from experiments.hcsn_conservative_acceleration_v1.hosted.runner import RunBook, write_new


BASE = Path(__file__).resolve().parent
MODULE = 'experiments.hcsn_blocker_closure_v1'
OUTPUT = BASE / 'av/results/hosted001'
RECEIPTS = BASE / 'av/results/hosted_driver001'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'train', 'finalize'))
    args = parser.parse_args()
    plan = json.loads((BASE / 'AV_LAUNCH.json').read_text())
    book = RunBook(RECEIPTS / args.command, args.command)
    result = {'complete': False}
    try:
        if args.command == 'prepare':
            book.run('source_head', ['git', 'rev-parse', 'HEAD'])
            head = (book.folder / 'source_head.log').read_text().strip()
            if head != os.environ.get('GITHUB_SHA'):
                raise ValueError('Execution source differs from public seal')
            expected = {'torch': '2.8.0+cpu', 'numpy': '2.3.5', 'scipy': '1.17.0'}
            actual = {name: importlib.metadata.version(name) for name in expected}
            if sys.version_info[:3] != (3, 12, 14) or actual != expected:
                raise ValueError('Pinned numerical runtime changed')
            cgroup = {name: (Path('/sys/fs/cgroup') / name).read_text()
                      for name in ('cpu.max', 'memory.max', 'memory.swap.max', 'memory.events')}
            quota, period = map(int, cgroup['cpu.max'].split())
            if quota != 4 * period or int(cgroup['memory.max']) != 8 * 1024**3 or int(cgroup['memory.swap.max']) != 0:
                raise ValueError('Declared resource isolation is absent')
            write_new(RECEIPTS / 'EXECUTION_IDENTITY.json', dict(
                seal=head, run_id=os.environ.get('GITHUB_RUN_ID'), packages=actual, python=sys.version,
                cgroup=cgroup, workers=4, energy_joules=None, gpu_executed=False))
            proof = BASE / 'av/results/hosted_preflight001.json'
            book.run('synthetic_preflight', [sys.executable, '-m', MODULE + '.av.study', 'preflight',
                                             '--output', str(proof)])
            data = plan['data']
            commit, prefix = data['commit'], data['transport_prefix']
            if (len(commit) != 40 or any(c not in '0123456789abcdef' for c in commit)
                    or prefix != 'experiments/hcsn_blocker_closure_v1/av/transport_41156412198'):
                raise ValueError('Unexpected immutable data binding')
            book.run('fetch_data_commit', ['git', '-c', 'protocol.version=2', 'fetch', '--depth=1',
                                          '--filter=blob:none', 'origin', commit])
            manifest_path = prefix + '/TRANSPORT.json'
            book.run('data_manifest_git_blob', ['git', 'rev-parse', commit + ':' + manifest_path])
            if (book.folder / 'data_manifest_git_blob.log').read_text().strip() != data['transport_git_blob']:
                raise ValueError('Exact data commit does not contain the pinned transport')
            temporary = Path(os.environ['RUNNER_TEMP'])
            archive_path = temporary / 'hcsn-fresh-av-input.tar'
            book.run('materialize_data_objects', ['git', 'archive', '--format=tar', '--output=' + str(archive_path),
                                                 commit, prefix])
            transport = temporary / 'hcsn-fresh-av-input'
            transport.mkdir(exist_ok=False)
            with tarfile.open(archive_path) as tar:
                for member in tar:
                    if member.isdir():
                        continue
                    if not member.isfile() or not member.name.startswith(prefix + '/'):
                        raise ValueError('Unexpected archive member')
                    name = PurePosixPath(member.name).relative_to(PurePosixPath(prefix))
                    if len(name.parts) != 1 or name.name in ('.', '..'):
                        raise ValueError('Data transport must contain regular flat filenames')
                    target = transport / name.name
                    with target.open('xb') as stream:
                        stream.write(tar.extractfile(member).read())
            transport_bytes = (transport / 'TRANSPORT.json').read_bytes()
            if hashlib.sha256(transport_bytes).hexdigest() != data['transport_sha256']:
                raise ValueError('Materialized transport differs from sealed manifest')
            manifest = json.loads(transport_bytes)
            if manifest['execution_seal'] != data['acquisition_seal'] or manifest['run_id'] != str(data['acquisition_run_id']):
                raise ValueError('Acquisition provenance mismatch')
            restored = temporary / 'hcsn-fresh-av-data'
            book.run('restore_data', [sys.executable, '-m', MODULE + '.av.bootstrap', 'restore',
                                     '--transport', str(transport), '--output', str(restored)])
            if hashlib.sha256((restored / 'DATASET.json').read_bytes()).hexdigest() != data['dataset_sha256']:
                raise ValueError('Restored dataset identity changed')
            write_new(RECEIPTS / 'DATA_BINDING.json', dict(
                execution_seal=head, data_commit=commit, transport_path=manifest_path,
                transport_git_blob=data['transport_git_blob'], transport_sha256=data['transport_sha256'],
                dataset_sha256=data['dataset_sha256'], copied_files=manifest['files'],
                acquisition_run_id=data['acquisition_run_id'], model_outcomes_read=False))
            book.run('register', [sys.executable, '-m', MODULE + '.av.study', 'register', '--output', str(OUTPUT),
                                 '--dataset', str(restored / 'DATASET.json'), '--data-commit', commit,
                                 '--data-transport-path', manifest_path, '--preflight', str(proof)])
            result = {'complete': True, 'test_predictions_read': False}
        elif args.command == 'train':
            for stage in ('development', 'fixed', 'equal_cpu'):
                book.run(stage, [sys.executable, '-m', MODULE + '.av.study', 'run', '--output', str(OUTPUT),
                                 '--stage', stage, '--workers', '4'])
                if stage == 'development':
                    book.run('selection_lock', [sys.executable, '-m', MODULE + '.av.study', 'lock',
                                                '--output', str(OUTPUT)])
            result = {'complete': True}
        else:
            analyzed = book.run('analysis', [sys.executable, '-m', MODULE + '.av.study', 'analyze',
                                            '--output', str(OUTPUT)], required=False)
            path = OUTPUT / 'ANALYSIS.json'
            scientific = json.loads(path.read_text()) if path.exists() else {}
            integrity = (analyzed['exit_code'] == 0 and scientific.get('complete') is True
                         and scientific.get('errors') == [] and scientific.get('valid_jobs') == 90)
            result = {'complete': integrity, 'positive_scientific_outcomes_not_required': True}
            if not integrity:
                raise RuntimeError('AV integrity failed; all original evidence remains preserved')
    except BaseException:
        write_new(book.folder / 'FATAL.json', dict(exception=traceback.format_exc(), complete=False))
        raise
    finally:
        print(json.dumps(book.finish(result), sort_keys=True))


if __name__ == '__main__':
    main()
