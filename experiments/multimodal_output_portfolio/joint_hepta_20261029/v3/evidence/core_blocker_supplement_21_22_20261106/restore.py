"""Read-only restoration of the pinned Core supplement evidence bundle; report to stdout."""

from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import os
import stat
import tarfile
import zlib

INDEX_SHA256 = '2ec0e16919c4d82a7ea4c8becee736db08ff32e0872da5cf5c35fd70a034b0a7'
TRANSPORT_SHA256 = '60d9d146e9206bfd80418d74c8975d0829ffbd777042aec13a48a7bfad6fa5cf'


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

    transport_bytes = read_regular(bundle / 'TRANSPORT.json')
    require(sha(transport_bytes) == TRANSPORT_SHA256, 'TRANSPORT differs from its fixed review seal')
    transport = json.loads(transport_bytes)
    require(transport['schema'] == 'core.evidence.gzip-transport.v1', 'Unknown transport schema')
    require(transport['representation'] == 'one-bounded-gzip-member-per-transport-segment',
            'Unknown transport representation')
    require(transport['index_sha256'] == INDEX_SHA256
            and transport['original_archive_sha256'] == index['archive']['sha256']
            and transport['original_archive_bytes'] == index['archive']['bytes']
            and transport['original_part_count'] == len(index['parts']),
            'Transport changed the original evidence binding')
    require(transport['segment_limit'] == 440000 and transport['container_limit'] == 450000,
            'Transport size limits changed')
    require(len(transport['parts']) == (index['archive']['bytes'] + 439999) // 440000,
            'Unexpected transport segment count')
    chunks = []
    for ordinal, part in enumerate(transport['parts']):
        name = part['path']
        require(name == f'core-supplement-06-14.tar.xz.transport-{ordinal:03d}.gz',
                'Unsafe, duplicate or out-of-order transport segment')
        data = read_regular(bundle / name)
        require(len(data) == part['bytes'] and len(data) <= 450000,
                f'Transport container size differs: {name}')
        require(sha(data) == part['sha256'], f'Transport container hash differs: {name}')
        segment_bytes = min(440000, index['archive']['bytes'] - ordinal * 440000)
        require(part['segment_bytes'] == segment_bytes, f'Transport segment size differs: {name}')
        inflater = zlib.decompressobj(wbits=31)
        segment = inflater.decompress(data, segment_bytes + 1)
        require(inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail,
                f'Transport is not exactly one bounded gzip member: {name}')
        require(len(segment) == segment_bytes and sha(segment) == part['segment_sha256'],
                f'Transport segment bytes differ: {name}')
        chunks.append(segment)
    archive_bytes = b''.join(chunks)
    require(len(archive_bytes) == index['archive']['bytes'], 'Archive size differs')
    require(sha(archive_bytes) == index['archive']['sha256'], 'Archive hash differs')

    # Keep the original raw-segment identities as an independent integrity layer.
    seen_parts = set()
    offset = 0
    for part in index['parts']:
        name = part['path']
        require(Path(name).name == name and name not in seen_parts, 'Unsafe or duplicate shard name')
        seen_parts.add(name)
        require(type(part['bytes']) is int and 0 < part['bytes'] <= 450000,
                f'Original shard size is invalid: {name}')
        segment = archive_bytes[offset:offset + part['bytes']]
        require(len(segment) == part['bytes'] and sha(segment) == part['sha256'],
                f'Original raw shard bytes differ: {name}')
        offset += part['bytes']
    require(offset == len(archive_bytes), 'Original raw shard boundaries differ')

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
