"""Recover exact prior history and salvage the surviving V4 prefix, without training."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


CONTROL = Path(__file__).resolve().parent
REPO = CONTROL.parents[1]
BASELINE = 'f8c9419df6ddeb36ff8b522a50219981fb8d9345'
V2 = '57d2b9658839f11aa4685049f90cb7142d59026d'
V3 = 'ddd2ec4f9167c5ccf22adb63f4ce7402ebd7ae19'


def identity(path):
    checksum = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1048576):
            size += len(block)
            checksum.update(block)
    return {'bytes': size, 'sha256': checksum.hexdigest()}


def command(*args, capture=False):
    result = subprocess.run(args, cwd=REPO, check=True, capture_output=capture, text=True)
    return result.stdout.strip() if capture else None


def main():
    head = command('git', 'rev-parse', 'HEAD', capture=True)
    expected = os.environ['EXPECTED_SOURCE_SHA']
    if head != expected:
        raise ValueError('Hosted checkout differs from the workflow source')
    output = CONTROL / 'recovered'
    output.mkdir(exist_ok=False)
    bundle_dir = output / 'bundles'
    bundle_dir.mkdir()
    records = [
        {
            'version': 'v1-v2',
            'directory': 'qualification/memory-cell-delivery/bundle-parts',
            'filename': 'hepta-memory-v1-v2-history-20261026.bundle',
            'parts': 5,
            'bytes': 36526176,
            'sha256': '283ed9c9c966417c9ac72388e8f22f1f03b46620130e3f193cb31024586fce7d',
            'required': BASELINE,
            'commit': V2,
            'advertised_ref': 'refs/heads/research/memory-cell-six-stage-20261025',
        },
        {
            'version': 'v3',
            'directory': 'qualification/memory-cell-v3-delivery/bundle-parts',
            'filename': 'hepta-memory-v3-history-20261026.bundle',
            'parts': 7,
            'bytes': 54731928,
            'sha256': 'ed9dc2f129051210b729e01281f16c6b863f17c71d5a474a7e3885509cd4cf3e',
            'required': V2,
            'commit': V3,
            'advertised_ref': 'refs/heads/research/memory-cell-v3-20261026',
        },
    ]
    command('git', 'cat-file', '-e', BASELINE + '^{commit}')
    refs_before = command('git', 'for-each-ref', '--format=%(refname) %(objectname)', capture=True)
    for record in records:
        bundle = bundle_dir / record['filename']
        paths = sorted((REPO / record['directory']).glob(record['filename'] + '.part*'))
        if len(paths) != record['parts']:
            raise ValueError('Unexpected original bundle part count')
        with bundle.open('xb') as destination:
            for path in paths:
                with path.open('rb') as source:
                    shutil.copyfileobj(source, destination, length=1048576)
        if identity(bundle) != {'bytes': record['bytes'], 'sha256': record['sha256']}:
            raise ValueError('Original bundle bytes differ from the sealed identity')
        heads = command('git', 'bundle', 'list-heads', str(bundle), capture=True)
        expected_head = record['commit'] + ' ' + record['advertised_ref']
        if expected_head not in heads.splitlines():
            raise ValueError('Original bundle advertised head differs')
        command('git', 'cat-file', '-e', record['required'] + '^{commit}')
        command('git', 'bundle', 'verify', str(bundle))
        command('git', 'bundle', 'unbundle', str(bundle))
        command('git', 'cat-file', '-e', record['commit'] + '^{commit}')
    names = command('git', 'ls-tree', '--name-only', V3 + ':qualification', capture=True).splitlines()
    paths = ['qualification/' + name for name in names if name.startswith('memory-cell')]
    if not paths:
        raise ValueError('No original memory-cell qualification trees found')
    command('git', 'archive', '--format=tar.gz', '--prefix=original-v3/',
            '--output=' + str(output / 'v3-qualification.tar.gz'), V3, '--', *paths)
    prefix_out = output / 'v4-prefix'
    command(sys.executable, '-B', str(CONTROL / 'salvage_prefix.py'),
            '--part', str(CONTROL / 'bundle-parts/hepta-memory-v4-history-20261026.bundle.part001'),
            '--part', str(CONTROL / 'bundle-parts/hepta-memory-v4-history-20261026.bundle.part002'),
            '--expected-part-blob', '655b681c8a05f06d666386b74acdf9fb44dcb554',
            '--expected-part-blob', 'b52cd381c56366e46834b47d9a1987552a738835',
            '--expected-part-sha256', '0bcc3ffd312ce256dce8cb6c40ba694004e475f1891823861987ccaf5a011626',
            '--expected-part-sha256', '127c4989b832059e92bb88a4587454ee1dd0b12b4b69c6ebfde132840bcc0a1a',
            '--base-repo', str(REPO), '--output', str(prefix_out))
    recovery = json.loads((prefix_out / 'RECOVERY.json').read_text())
    if recovery['full_bundle_identity_verified'] or recovery['formal_evidence_verified']:
        raise ValueError('A known incomplete prefix cannot establish full V4 evidence')
    for filename in ('salvage_prefix.py', 'run_hosted_recovery.py'):
        shutil.copyfile(CONTROL / filename, output / filename)
    if command('git', 'rev-parse', 'HEAD', capture=True) != head:
        raise ValueError('Hosted checkout changed during recovery')
    if command('git', 'for-each-ref', '--format=%(refname) %(objectname)', capture=True) != refs_before:
        raise ValueError('Recovery unexpectedly changed repository refs')
    summary = {
        'schema': 'hepta.memory.hosted-recovery.v1',
        'workflow_source_commit': head,
        'repository_head_and_refs_unchanged': True,
        'complete_prior_bundles_verified': records,
        'v3_qualification_archive': identity(output / 'v3-qualification.tar.gz'),
        'v3_exported_prefixes': paths,
        'v4_partial_recovery': recovery,
        'old_experiments_rerun': False,
        'new_qualification_claimed': False,
    }
    (output / 'RECOVERY_SUMMARY.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
