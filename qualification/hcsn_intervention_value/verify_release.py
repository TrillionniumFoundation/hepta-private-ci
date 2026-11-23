"""Recompute archived confirmation results from an already unpacked evidence directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

PACKAGE = 'qualification.hcsn_intervention_value'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def link_prefix_inputs(archive, destination):
    """Expose the original prefix-audit layout using only the specified archive."""
    links = {
        'discovery': 'primary/discovery',
        'policies': 'primary/policies',
        'semantic': 'semantic',
        'commons/roster': 'media/recording_roster',
        'commons/features': 'media/features',
        'commons/receipts': 'media/receipts',
        'observed/validity_seal.json': 'media/validity_seal.json',
    }
    for alias, source in links.items():
        original = archive / source
        if not original.exists():
            raise FileNotFoundError(original)
        target = destination / alias
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(original, target_is_directory=original.is_dir())


def check(archive, scratch):
    discovery = archive / 'primary/discovery'
    policies = archive / 'primary/policies'
    roster = archive / 'media/recording_roster/test.json'
    validation = archive / 'validation'
    outcomes = archive / 'outcomes'
    certificate = validation / 'early_known.json'
    partial = outcomes / 'partial_bounds.released.json'
    inputs = scratch / 'prefix_inputs'
    link_prefix_inputs(archive, inputs)
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')

    cases = [
        ('verify_policy', [discovery, policies, '--output'], validation / 'confirm_verified.json'),
        ('partial_prefix', [inputs], certificate),
        ('opportunity_bounds', [discovery, roster, certificate], outcomes / 'opportunity_bounds.released.json'),
        ('partial_bounds', [roster, discovery, policies, '--known', certificate, '--output'], partial),
        ('verify_partial_bounds', [discovery, policies, roster, certificate, partial, '--output'],
         validation / 'partial_bounds_independent.json'),
        ('families', [discovery, policies], outcomes / 'families.released.json'),
        ('attribution', [discovery, policies], outcomes / 'attribution.released.json'),
    ]
    verified = {}
    for name, arguments, reference in cases:
        result = scratch / (name + '.json')
        command = [sys.executable, '-m', f'{PACKAGE}.{name}', *map(str, arguments), str(result)]
        process = subprocess.run(command, env=environment, capture_output=True, text=True)
        if process.returncode:
            raise RuntimeError(f'{name} failed with exit {process.returncode}\n{process.stderr}')
        expected, actual = read(reference), read(result)
        if name == 'partial_prefix':
            # A fresh process has a new runtime. Everything used for scientific
            # certification, including input hashes and control scores, must match.
            expected['provenance'].pop('wall_seconds')
            actual['provenance'].pop('wall_seconds')
        if expected != actual:
            raise ValueError(f'{name} differs from archived {reference.relative_to(archive)}')
        if name in ('verify_policy', 'verify_partial_bounds') and actual.get('passed') is not True:
            raise ValueError(f'{name} did not return a passing verification')
        verified[name] = {'passed': True, 'archived_sha256': digest(reference)}
        if name == 'partial_prefix':
            verified[name]['ignored_fields'] = ['provenance.wall_seconds']
        if name in ('verify_policy', 'verify_partial_bounds'):
            verified[name]['counts'] = actual['counts']
    return {'passed': True, 'checks': verified,
            'comparison': 'JSON value equality; only the independent prefix rerun wall clock is excluded.'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('archive', type=Path, help='verified, unpacked release root')
    cli.add_argument('--output', type=Path)
    args = cli.parse_args()
    with tempfile.TemporaryDirectory(prefix='hepta-release-verify-') as work:
        report = check(args.archive.resolve(), Path(work))
    rendered = json.dumps(report, indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x') as out:
            out.write(rendered)
    print(rendered, end='')


if __name__ == '__main__':
    main()
