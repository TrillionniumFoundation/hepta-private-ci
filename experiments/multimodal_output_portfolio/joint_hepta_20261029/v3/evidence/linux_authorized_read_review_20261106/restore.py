"""Read-only restoration of the pinned Core evidence bundle; report to stdout."""

from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import os
import stat
import tarfile

INDEX_SHA256 = '1e9706099c84caa274dfea234cc9243180f9e0a77dcbd4e4ad8ea0e3425d5fbf'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_regular(path):
    mode = path.lstat().st_mode
    require(stat.S_ISREG(mode), f'Input must be a regular file: {path}')
    return path.read_bytes()


def safe_relative(name):
    require(isinstance(name, str) and name, 'Empty or non-string member name')
    require('\\' not in name and '\0' not in name, f'Unsafe member name: {name!r}')
    path = PurePosixPath(name)
    require(not path.is_absolute(), f'Absolute member: {name}')
    require(all(part not in ('', '.', '..') for part in name.split('/')), f'Unsafe member: {name}')
    require(path.as_posix() == name, f'Noncanonical member: {name}')
    require(path.parts[0] == 'round3_core_ci', f'Unexpected member root: {name}')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    bundle = args.bundle.resolve(strict=True)
    require(bundle.is_dir(), 'Bundle must be a directory')
    raw_destination = Path(os.path.abspath(args.destination))
    require(not os.path.lexists(raw_destination), 'Destination already exists')
    parent = raw_destination.parent.resolve(strict=True)
    require(parent.is_dir(), 'Destination parent must be an existing directory')
    destination = parent / raw_destination.name
    require(not os.path.lexists(destination), 'Resolved destination already exists')
    require(destination != bundle and bundle not in destination.parents,
            'Destination must be outside the input bundle')

    index_bytes = read_regular(bundle / 'INDEX.json')
    require(sha(index_bytes) == INDEX_SHA256, 'INDEX SHA-256 differs from the pinned value')
    index = json.loads(index_bytes)
    expected = {}
    for entry in index['files']:
        name = entry['path']
        safe_relative(name)
        require(name not in expected, f'Duplicate index member: {name}')
        mode = int(entry['mode'], 8)
        require(stat.S_ISREG(mode) and (mode & 0o7000) == 0,
                f'Unsafe or nonregular indexed mode: {name}')
        expected[name] = entry
    require(len(expected) == index['source_files'], 'Indexed source count differs')

    chunks = []
    seen_parts = set()
    for part in index['parts']:
        name = part['path']
        require(Path(name).name == name and name not in seen_parts, 'Unsafe or duplicate shard name')
        seen_parts.add(name)
        data = read_regular(bundle / name)
        require(len(data) == part['bytes'] and len(data) <= 450000, f'Shard size differs: {name}')
        require(sha(data) == part['sha256'], f'Shard hash differs: {name}')
        chunks.append(data)
    archive_bytes = b''.join(chunks)
    require(len(archive_bytes) == index['archive']['bytes'], 'Archive size differs')
    require(sha(archive_bytes) == index['archive']['sha256'], 'Archive hash differs')

    verified = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode='r:xz') as archive:
        for member in archive:
            name = member.name
            safe_relative(name)
            require(member.type in (tarfile.REGTYPE, tarfile.AREGTYPE), f'Nonregular archive member: {name}')
            require(name in expected and name not in verified, f'Unexpected or duplicate archive member: {name}')
            entry = expected[name]
            require(member.size == entry['bytes'], f'Archive member size differs: {name}')
            require((member.mode & ~0o777) == 0, f'Unsafe archive permission bits: {name}')
            require((stat.S_IFREG | member.mode) == int(entry['mode'], 8), f'Archive mode differs: {name}')
            stream = archive.extractfile(member)
            require(stream is not None, f'Archive member has no data: {name}')
            data = stream.read(entry['bytes'] + 1)
            require(len(data) == entry['bytes'] and sha(data) == entry['sha256'],
                    f'Archive member bytes differ: {name}')
            verified[name] = (data, member.mode & 0o777)
    require(set(verified) == set(expected), 'Archive member set differs from the exact index')

    destination.mkdir()
    for name, (data, permission_bits) in verified.items():
        path = destination.joinpath(*PurePosixPath(name).parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as output:
            output.write(data)
        path.chmod(permission_bits)
        require(read_regular(path) == data, f'Restored bytes differ: {name}')
        require(path.lstat().st_mode == int(expected[name]['mode'], 8), f'Restored mode differs: {name}')

    print(json.dumps({
        'kind': 'actual_read_only_raw_shard_restoration',
        'index_sha256': INDEX_SHA256,
        'archive_sha256': sha(archive_bytes),
        'restored_files': len(verified),
        'restored_bytes': sum(len(data) for data, _ in verified.values()),
        'exact_unique_regular_member_set': True,
        'all_file_bytes_and_safe_regular_modes_match': True,
        'bundle_files_written': 0,
        'native_tests_executed': False,
    }, indent=2))


if __name__ == '__main__':
    main()
