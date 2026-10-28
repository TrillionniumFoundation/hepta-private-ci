"""Verify and restore published research evidence without training or evaluation."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_child(root, relative):
    name = PurePosixPath(relative)
    if name.is_absolute() or '..' in name.parts:
        raise ValueError(f'Unsafe archive path: {relative}')
    candidate = root.joinpath(*name.parts)
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Path escapes destination: {relative}')
    return candidate


def verify_file(path, descriptor):
    if path.stat().st_size != descriptor['bytes'] or file_sha(path) != descriptor['sha256']:
        raise ValueError(f'Published bytes differ: {path}')


def materialize(repo, descriptor, temporary):
    """Join byte partitions only after checking each partition's size and hash."""
    parts = descriptor.get('parts')
    if not parts:
        path = safe_child(repo, descriptor['path'])
        verify_file(path, descriptor)
        return path
    result = temporary / (descriptor['name'] + '.tar.gz')
    with result.open('wb') as destination:
        for part in parts:
            source = safe_child(repo, part['path'])
            verify_file(source, part)
            with source.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    destination.write(chunk)
    verify_file(result, descriptor)
    return result


def verify_members(path, manifest_name):
    """Reject duplicate paths, links and special files before any extraction."""
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive paths')
        for member in members:
            pure = PurePosixPath(member.name)
            if pure.is_absolute() or '..' in pure.parts or not (member.isfile() or member.isdir()):
                raise ValueError(f'Unsupported archive member: {member.name}')
        manifest_file = archive.extractfile(manifest_name)
        if manifest_file is None:
            raise ValueError('Missing member manifest')
        expected = json.load(manifest_file)
        actual = {}
        for member in members:
            if member.isfile() and member.name != manifest_name:
                stream = archive.extractfile(member)
                digest = hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
                actual[member.name] = digest.hexdigest()
        if actual != expected:
            raise ValueError('Member hash set does not match archive manifest')
        return actual


def restore(path, destination, manifest_name, expected):
    """Never overwrite a different existing artifact; identical bytes are allowed."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive.getmembers():
            target = safe_child(destination, member.name)
            if member.isfile() and target.exists():
                if member.name == manifest_name:
                    wanted = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                else:
                    wanted = expected[member.name]
                if not target.is_file() or file_sha(target) != wanted:
                    raise FileExistsError(f'Refusing to overwrite different evidence: {target}')
        archive.extractall(destination, filter='data')
    for relative, digest in expected.items():
        if file_sha(safe_child(destination, relative)) != digest:
            raise ValueError(f'Restored file differs: {relative}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path,
                        default=Path(__file__).parent / 'evidence/EVIDENCE_MANIFEST.json')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--destination', type=Path, required=True,
                        help='Creates run/ and evidence/ beneath this directory')
    parser.add_argument('--archive', action='append', default=[],
                        help='Exact logical archive name; repeat to select several, omit for all')
    parser.add_argument('--verify-only', action='store_true')
    arguments = parser.parse_args()
    document = json.loads(arguments.manifest.read_text())
    descriptors = document['archives']
    selected = set(arguments.archive)
    known = {item['name'] for item in descriptors}
    if selected - known:
        raise ValueError(f'Unknown archive selection: {sorted(selected - known)}')
    records = []
    with tempfile.TemporaryDirectory(prefix='hepta-evidence-') as temporary:
        for descriptor in descriptors:
            if selected and descriptor['name'] not in selected:
                continue
            path = materialize(arguments.repo, descriptor, Path(temporary))
            expected = verify_members(path, descriptor['member_manifest'])
            destination = safe_child(arguments.destination, descriptor['restore_root'])
            if not arguments.verify_only:
                restore(path, destination, descriptor['member_manifest'], expected)
            row = {'archive': descriptor['name'], 'sha256': descriptor['sha256'],
                   'data_files': len(expected), 'member_hashes_verified': True,
                   'restored': not arguments.verify_only, 'destination': str(destination)}
            records.append(row)
            print(json.dumps(row), flush=True)
    print(json.dumps({'archives_verified': len(records),
                      'data_files_verified': sum(row['data_files'] for row in records),
                      'scientific_data_regenerated': False}), flush=True)


if __name__ == '__main__':
    main()
