#!/usr/bin/env python3
"""Verify archived bytes only; never import or execute the recovered sources."""
import hashlib
import json
from pathlib import Path, PurePosixPath

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'SOURCE_MANIFEST.json').read_bytes())
for item in manifest['sources'] + manifest['licenses']:
    relative = PurePosixPath(item['stored_path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise SystemExit('unsafe stored path')
    path = root.joinpath(*relative.parts)
    if path.is_symlink():
        raise SystemExit('unexpected symlink')
    data = path.read_bytes()
    actual_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
    if len(data) != item['bytes'] or hashlib.sha256(data).hexdigest() != item['sha256'] or actual_blob != item['git_blob_sha']:
        raise SystemExit('byte mismatch: ' + item['stored_path'])
print('Verified', len(manifest['sources']), 'source objects and', len(manifest['licenses']), 'license objects; archived source execution: false')
