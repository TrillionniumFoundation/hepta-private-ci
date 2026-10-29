#!/usr/bin/env python3
"""Restore exact captured evidence; starts no external operation."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

root = Path(__file__).resolve().parent
descriptor = json.loads((root / 'RAW_ARCHIVE.json').read_bytes())
data = (root / descriptor['archive']).read_bytes()
assert len(data) == descriptor['archive_bytes'] and hashlib.sha256(data).hexdigest() == descriptor['archive_sha256']
out = root / 'raw'
out.mkdir(exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tar:
    for member in tar.getmembers():
        path = PurePosixPath(member.name)
        assert member.isfile() and not path.is_absolute() and '..' not in path.parts
        target = out.joinpath(*path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(tar.extractfile(member).read())
raw_manifest = (out / 'COLLECTION_MANIFEST.json').read_bytes()
assert hashlib.sha256(raw_manifest).hexdigest() == descriptor['manifest_sha256']
manifest = json.loads(raw_manifest)
assert len(manifest['files']) == descriptor['source_files']
assert not manifest['missing']
for row in manifest['files']:
    value = (out / row['archive_path']).read_bytes()
    assert row['stable_stat_during_read']
    assert len(value) == row['bytes'] and hashlib.sha256(value).hexdigest() == row['sha256'], row['archive_path']
print(json.dumps({'verified_files': len(manifest['files']), 'source_bytes': manifest['total_bytes'], 'path': str(out)}))
