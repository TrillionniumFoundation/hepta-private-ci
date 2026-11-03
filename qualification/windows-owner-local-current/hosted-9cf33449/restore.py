#!/usr/bin/env python3
"""Restore original hosted ZIP bytes from verified binary parts without running them."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'artifact-parts.json').read_text())
args.output.mkdir(parents=True, exist_ok=False)
for row in manifest['artifacts']:
    parts = []
    for part in row['parts']:
        relative = Path(part['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('unsafe part path')
        data = (root / relative).read_bytes()
        if len(data) != part['bytes'] or hashlib.sha256(data).hexdigest() != part['sha256']:
            raise ValueError('part differs from original evidence')
        parts.append(data)
    raw = b''.join(parts)
    if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
        raise ValueError('complete original ZIP differs')
    archive = zipfile.ZipFile(io.BytesIO(raw))
    if sum(item.file_size for item in archive.infolist()) > 128000000:
        raise ValueError('unexpected expanded evidence size')
    if len(archive.namelist()) != len(set(archive.namelist())) or archive.testzip() is not None:
        raise ValueError('invalid original ZIP members')
    destination = args.output / str(row['artifact_id'])
    destination.mkdir()
    (destination / 'artifact.zip').write_bytes(raw)
    for item in archive.infolist():
        path = PurePosixPath(item.filename)
        if path.is_absolute() or '..' in path.parts or item.external_attr >> 16 & 0o170000 == 0o120000:
            raise ValueError('unsafe archive member')
        target = destination / item.filename
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(item))
for name in ['artifact-metadata.json', '9cf-artifacts.json']:
    if (root / name).is_file():
        (args.output / name).write_bytes((root / name).read_bytes())
print(json.dumps({'source_commit': manifest['source_commit'], 'restored_original_archives': len(manifest['artifacts']), 'executed_archive_content': False}))
