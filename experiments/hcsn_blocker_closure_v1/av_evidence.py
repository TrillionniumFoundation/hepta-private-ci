"""Bounded fresh-audiovisual evidence, isolated from the content archive."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from experiments.hcsn_free_boundary_v1 import archive


BASE = Path(__file__).resolve().parent / 'av'
PREFIX = 'experiments/hcsn_blocker_closure_v1/av'
LIMIT = 512000


def sha(path):
    return archive.sha256(path)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def bounded(root, name):
    path = archive.safe_name(name)
    target = root.joinpath(*path.parts)
    if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Unsafe publication path')
    return target


def package(output):
    start_cpu, start_wall = time.process_time(), time.perf_counter()
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    art = output / PREFIX / 'artifacts/closure001'
    manifest = archive.pack(BASE, art, 'closure_attempt', part_bytes=327680)
    original = art / 'closure_attempt.json'
    member_shards = []
    for index, offset in enumerate(range(0, len(manifest['members']), 600)):
        target = art / f'members_{index:04d}.json'
        rows = manifest['members'][offset:offset + 600]
        write(target, rows)
        if target.stat().st_size > LIMIT:
            raise ValueError('Member shard exceeds the existing repository blob limit')
        member_shards.append(dict(path=target.name, sha256=sha(target),
                                  bytes=target.stat().st_size, members=len(rows)))
    descriptor = {key: value for key, value in manifest.items() if key != 'members'}
    descriptor['member_shards'] = member_shards
    descriptor['original_manifest_sha256'] = sha(original)
    descriptor['original_member_count'] = len(manifest['members'])
    descriptor['schema'] = 'hcsn-bounded-member-index.v1'
    write(art / 'INDEX.json', descriptor)
    # The exact canonical JSON is reconstructible from INDEX + all member shards.
    rebuilt = {key: value for key, value in descriptor.items()
               if key not in ('member_shards', 'original_manifest_sha256', 'original_member_count')}
    rebuilt['schema'] = 'hcsn-evidence-bundle.v1'
    rebuilt['members'] = manifest['members']
    canonical = (json.dumps(rebuilt, indent=2, sort_keys=True) + '\n').encode()
    if hashlib.sha256(canonical).hexdigest() != descriptor['original_manifest_sha256']:
        raise ValueError('Manifest sharding was not lossless')
    original.unlink()
    for pattern in ('results/hosted001/ANALYSIS.json',
                    'results/hosted001/REPORT.md',
                    'results/hosted001/SELECTION_LOCK.json',
                    'results/hosted001/RUN_*.json',
                    'results/hosted_driver001/*.json',
                    'results/hosted_driver001/*/*.json',
                    'results/hosted_preflight001.json'):
        for source in BASE.glob(pattern):
            if source.stat().st_size <= LIMIT:
                destination = output / PREFIX / source.relative_to(BASE)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
    analysis_path = BASE / 'results/hosted001/ANALYSIS.json'
    if analysis_path.exists():
        full = json.loads(analysis_path.read_text())
        summary = {key: value for key, value in full.items() if key not in ('checks', 'costs', 'stages')}
        summary.update(full_analysis_sha256=sha(analysis_path),
                       total_checks=len(full.get('checks', [])),
                       passed_checks=sum(row.get('passed') is True for row in full.get('checks', [])),
                       derivation='Lossless headline extraction only; all raw checks and ledgers remain in the archive.')
        target = output / PREFIX / 'results/hosted001/SUMMARY.json'
        write(target, summary)
    files = []
    for path in sorted(output.rglob('*')):
        if path.is_file():
            if path.stat().st_size > LIMIT:
                raise ValueError('Publication file exceeds existing blob limit')
            files.append(dict(path=path.relative_to(output).as_posix(), bytes=path.stat().st_size,
                              sha256=sha(path)))
    receipt = dict(schema='hcsn-blocker-publication.v1', execution_seal=os.environ.get('GITHUB_SHA'),
                   github_run_id=os.environ.get('GITHUB_RUN_ID'), files=files,
                   raw_member_count=len(manifest['members']), raw_bytes=manifest['uncompressed_file_bytes'],
                   archive_sha256=manifest['archive_sha256'], archive_bytes=manifest['compressed_bytes'],
                   source_root=PREFIX, failed_attempts_preserved=True,
                   packaging_cpu_seconds=time.process_time() - start_cpu,
                   packaging_wall_seconds=time.perf_counter() - start_wall)
    write(art / 'PUBLICATION.json', receipt)
    if (art / 'PUBLICATION.json').stat().st_size > LIMIT:
        raise ValueError('Publication receipt exceeds existing blob limit')
    return receipt


def verify(output, seal):
    root = output.resolve()
    receipt_path = root / PREFIX / 'artifacts/closure001/PUBLICATION.json'
    receipt = json.loads(receipt_path.read_text())
    if receipt['execution_seal'] != seal:
        raise ValueError('Execution seal mismatch')
    expected = {receipt_path.relative_to(root).as_posix()}
    for row in receipt['files']:
        if row['path'] in expected or not row['path'].startswith(PREFIX + '/'):
            raise ValueError('Duplicate or unexpected publication prefix')
        expected.add(row['path'])
        path = bounded(root, row['path'])
        if path.stat().st_size != row['bytes'] or row['bytes'] > LIMIT or sha(path) != row['sha256']:
            raise ValueError('Publication byte integrity failed')
    if {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} != expected:
        raise ValueError('Unlisted or missing publication bytes')
    return dict(passed=True, files=len(expected), raw_members=receipt['raw_member_count'])


def restore(index, destination):
    descriptor = json.loads(index.read_text())
    if descriptor['schema'] != 'hcsn-bounded-member-index.v1':
        raise ValueError('Unknown member index contract')
    manifest = {key: value for key, value in descriptor.items()
                if key not in ('member_shards', 'original_manifest_sha256', 'original_member_count')}
    manifest['schema'] = 'hcsn-evidence-bundle.v1'
    manifest['members'] = []
    for row in descriptor['member_shards']:
        path = bounded(index.parent, row['path'])
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise ValueError('Member shard integrity failed')
        members = json.loads(path.read_text())
        if len(members) != row['members']:
            raise ValueError('Member count mismatch')
        manifest['members'].extend(members)
    if len(manifest['members']) != descriptor['original_member_count']:
        raise ValueError('Original member count mismatch')
    encoded = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    if hashlib.sha256(encoded).hexdigest() != descriptor['original_manifest_sha256']:
        raise ValueError('Canonical reconstructed manifest changed')
    with tempfile.TemporaryDirectory(prefix='hcsn-index-') as temp:
        folder = Path(temp)
        manifest_path = folder / 'original.json'
        manifest_path.write_bytes(encoded)
        for part in manifest['parts']:
            source = bounded(index.parent, part['path'])
            target = bounded(folder, part['path'])
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
        return archive.restore(manifest_path, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('package', 'verify', 'restore'))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seal')
    parser.add_argument('--index', type=Path)
    args = parser.parse_args()
    if args.command == 'package':
        result = package(args.output)
    elif args.command == 'verify':
        result = verify(args.output, args.seal)
    else:
        result = restore(args.index, args.output)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
