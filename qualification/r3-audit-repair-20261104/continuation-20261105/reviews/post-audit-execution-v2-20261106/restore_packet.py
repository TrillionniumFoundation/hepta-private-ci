#!/usr/bin/env python3
"""Restore an exact root audit snapshot; do not execute restored code."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import hashlib
import json
import tempfile
import zipfile


def identity(raw):
    return {'bytes': len(raw), 'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(),
            'sha256': hashlib.sha256(raw).hexdigest()}


def same(raw, expected):
    assert identity(raw) == {k: expected[k] for k in ('bytes', 'git_blob', 'sha256')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--packet', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    packet, output = args.packet.resolve(), args.output.resolve()
    assert not output.exists(), 'Restore only to a new directory'
    archive = json.loads((packet / 'archive.json').read_bytes())
    raw_manifest = (packet / 'manifest.json').read_bytes()
    same(raw_manifest, archive['payload_manifest'])
    manifest = json.loads(raw_manifest)
    rows = {r['path']: r for r in manifest['files']}
    assert len(rows) == manifest['member_count'] == len(manifest['files'])
    with tempfile.TemporaryDirectory(prefix='hepta-root-v2-restore-') as temporary:
        destination = Path(temporary) / 'snapshot.zip'
        names = set()
        with destination.open('xb') as writer:
            for part in archive['parts']:
                p = PurePosixPath(part['path'])
                assert len(p.parts) == 1 and p.name not in names and p.name not in ('.', '..', '')
                names.add(p.name)
                raw = (packet / p.name).read_bytes()
                same(raw, part)
                writer.write(base64.b64decode(raw, validate=True))
        same(destination.read_bytes(), archive['archive'])
        with zipfile.ZipFile(destination) as z:
            assert len(z.infolist()) == len(rows) and set(z.namelist()) == set(rows) and z.testzip() is None
            for item in z.infolist():
                p = PurePosixPath(item.filename)
                assert not item.is_dir() and not p.is_absolute() and all(x not in ('', '.', '..') for x in p.parts)
                assert item.external_attr >> 16 == 0o100644
                raw = z.read(item)
                same(raw, rows[item.filename])
                target = output.joinpath(*p.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as writer:
                    writer.write(raw)
    print(json.dumps({'archive': archive['archive'], 'parts': len(archive['parts']), 'members': len(rows),
        'all_original_bytes_equal': True, 'restored_code_executed': False, 'product_native_or_CI_executed': False}, indent=2))


if __name__ == '__main__':
    main()
