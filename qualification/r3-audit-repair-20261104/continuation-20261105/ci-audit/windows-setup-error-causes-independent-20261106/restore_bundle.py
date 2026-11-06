#!/usr/bin/env python3
"""Restore the immutable review bundle after verifying every chunk and member."""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('manifest', type=Path)
    ap.add_argument('destination', type=Path)
    args = ap.parse_args()
    manifest = json.loads(args.manifest.read_bytes())
    assert manifest['schema'] == 'windows-setup-error-independent-portable-v1'
    parts = []
    for item in manifest['parts']:
        name = item['path']
        assert PurePosixPath(name).name == name
        part = (args.manifest.parent / name).read_bytes()
        assert identity(part) == item['identity']
        parts.append(part)
    archive = base64.b64decode(b''.join(parts), validate=True)
    assert identity(archive) == manifest['archive']
    raw_tar = gzip.decompress(archive)
    assert identity(raw_tar) == manifest['tar']
    destination = args.destination.resolve()
    if destination.exists():
        assert destination.is_dir() and not any(destination.iterdir())
    else:
        destination.mkdir(parents=True)
    expected = {row['path']: row['identity'] for row in manifest['members']}
    assert len(expected) == len(manifest['members'])
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(raw_tar), mode='r:') as tar:
        for member in tar.getmembers():
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute()
            assert all(p not in ('', '.', '..') for p in path.parts)
            assert member.name in expected and member.name not in seen
            data = tar.extractfile(member).read()
            assert identity(data) == expected[member.name]
            target = destination.joinpath(*path.parts)
            assert target.is_relative_to(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            seen.add(member.name)
    assert seen == set(expected)
    print(json.dumps({'verified_members': len(seen), 'all_member_bytes_equal': True,
                      'archive': manifest['archive']}, indent=2))


if __name__ == '__main__':
    main()
