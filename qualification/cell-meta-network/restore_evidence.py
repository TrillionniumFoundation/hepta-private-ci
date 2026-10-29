#!/usr/bin/env python3
"""Restore and verify the original archive; performs no worker actions."""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

root = Path(__file__).resolve().parent
descriptor = json.loads((root / 'evidence/network-final-20261029/ARCHIVE.json').read_bytes())
pieces = []
for part in descriptor['parts']:
    data = (root / part['path']).read_bytes()
    assert len(data) == part['bytes'] and hashlib.sha256(data).hexdigest() == part['sha256']
    pieces.append(data.strip())
archive = base64.b64decode(b''.join(pieces), validate=True)
assert len(archive) == descriptor['archive_bytes']
assert hashlib.sha256(archive).hexdigest() == descriptor['archive_sha256']
dest = Path(sys.argv[1])
dest.mkdir(parents=True, exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
    for item in tar.getmembers():
        path = PurePosixPath(item.name)
        assert item.isfile() and not path.is_absolute() and '..' not in path.parts
        target = dest.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(tar.extractfile(item).read())
raw_manifest = (dest / 'MANIFEST.json').read_bytes()
assert hashlib.sha256(raw_manifest).hexdigest() == descriptor['manifest_sha256']
manifest = json.loads(raw_manifest)
assert len(manifest['files']) == descriptor['source_files']
for item in manifest['files']:
    data = (dest / item['path']).read_bytes()
    assert len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
print(json.dumps({'verified_files': len(manifest['files']), 'archive_sha256': descriptor['archive_sha256'], 'output': str(dest)}))
