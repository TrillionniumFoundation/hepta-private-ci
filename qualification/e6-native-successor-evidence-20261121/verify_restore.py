"""Verify every published evidence byte, optionally restore files into a new directory.

This reads data only. It never imports or executes scripts inside the evidence.
"""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def relative(name):
    path = PurePosixPath(name)
    require(isinstance(name, str) and name and not path.is_absolute() and '..' not in path.parts,
            'unsafe published path')
    return Path(*path.parts)


def file_bytes(root, name, expected=None):
    path = root / relative(name)
    require(path.is_file() and not path.is_symlink() and path.stat().st_size <= 512000,
            'published file is missing, not regular, or above the unchanged blob ceiling')
    raw = path.read_bytes()
    require(expected is None or sha(raw) == expected, 'published file hash differs: ' + name)
    return raw


def verify(root, destination=None):
    manifest = json.loads(file_bytes(root, 'MANIFEST.json'))
    require(manifest['schema'] == 'hepta.e6-content-addressed-evidence.v1'
            and manifest['blob_limit_bytes'] == 512000 and manifest['part_blob_limit_bytes'] == 360000
            and manifest['part_storage'] == 'binary',
            'unknown evidence schema or altered policy ceiling')
    file_bytes(root, manifest['verifier_file'], manifest['verifier_sha256'])
    members = [json.loads(line) for line in file_bytes(root, manifest['members_file'], manifest['members_sha256']).splitlines()]
    chunks = [json.loads(line) for line in file_bytes(root, manifest['chunks_file'], manifest['chunks_sha256']).splitlines()]
    containers = [json.loads(line) for line in file_bytes(root, manifest['original_containers_file'], manifest['original_containers_sha256']).splitlines()]
    require(len(members) == manifest['logical_files'] <= 10000 and len(chunks) == manifest['parts'] <= 400,
            'published file or chunk count differs')
    require(len({row['path'] for row in members}) == len(members), 'duplicate logical path')
    objects, packed, offset = {}, bytearray(), 0
    for row in members:
        relative(row['path'])
        require(type(row['bytes']) is int and 0 <= row['bytes'] <= 64 * 1024**2,
                'invalid individual original size')
        require(row['sha256'] not in objects or objects[row['sha256']] == row['bytes'], 'inconsistent object sizes')
        objects[row['sha256']] = row['bytes']
    require(len(objects) == manifest['unique_objects'] and sum(objects.values()) == manifest['unique_object_bytes']
            and sum(row['bytes'] for row in members) == manifest['logical_file_bytes'] <= 256 * 1024**2,
            'original object/alias inventory differs')
    for index, row in enumerate(chunks):
        require(row['index'] == index and row['offset'] == offset, 'chunk order/offset differs')
        raw = file_bytes(root, row['path'], row['sha256'])
        require(len(raw) == row['bytes'] <= 360000, 'binary chunk length differs')
        packed.extend(raw)
        offset += len(raw)
    require(offset == manifest['new_gzip_bytes'] and sha(packed) == manifest['new_gzip_sha256'], 'new gzip differs')
    with gzip.GzipFile(fileobj=io.BytesIO(packed), mode='rb') as stream:
        uncompressed = stream.read(256 * 1024**2 + 1)
    require(len(uncompressed) == manifest['new_tar_bytes'] <= 256 * 1024**2
            and sha(uncompressed) == manifest['new_tar_sha256'], 'new tar differs or exceeds verifier bound')
    content = {}
    with tarfile.open(fileobj=io.BytesIO(uncompressed), mode='r:') as archive:
        for member in archive:
            value = member.name.removeprefix('objects/')
            require(member.isfile() and member.name == 'objects/' + value and value in objects
                    and value not in content and member.size == objects[value], 'unexpected object member')
            raw = archive.extractfile(member).read()
            require(len(raw) == objects[value] and sha(raw) == value, 'original object bytes differ')
            content[value] = raw
    require(set(content) == set(objects), 'missing original objects')
    for container in containers:
        if 'regular_members' not in container:
            row = next(item for item in members if item['path'] == container['decoded_path'])
            require(row['sha256'] == container['decoded_sha256'] and row['bytes'] == container['decoded_bytes'],
                    'original gzip-copy decoded content differs')
            continue
        original_members = []
        for row in members:
            for origin in row.get('container_memberships', []):
                if origin['id'] == container['id']:
                    original_members.append((origin['ordinal'], {'path': row['path'], 'sha256': row['sha256'], 'bytes': row['bytes']}))
        ordered = [row for _, row in sorted(original_members)]
        encoded = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        require(len(ordered) == container['regular_members'] and sum(row['bytes'] for row in ordered) == container['member_bytes']
                and sha(encoded) == container['member_index_sha256'], 'original container member inventory differs')
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=False)
        for row in members:
            path = destination / relative(row['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(content[row['sha256']])
    return {'verified_logical_files': len(members), 'verified_unique_objects': len(objects),
            'new_container_sha256': manifest['new_gzip_sha256'], 'restored': destination is not None,
            'original_outer_gzip_bitstream_reconstructed': False, 'archived_programs_executed': 0,
            'native_tests_started': 0, 'model_calls_started': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', type=Path, help='new directory; an existing destination is refused')
    args = parser.parse_args()
    print(json.dumps(verify(Path(__file__).resolve().parent, args.restore), indent=2))
