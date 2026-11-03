#!/usr/bin/env python3
"""Verify original Library bytes; no runtime experiments are claimed."""
from pathlib import Path
import hashlib, json, sys
root=Path(__file__).resolve().parent
manifest=json.loads((root/'MANIFEST.json').read_text(encoding='utf-8'))
errors=[]
for row in manifest['files']:
    p=root/'files'/row['name']
    try: buf=p.read_bytes()
    except OSError as exc: errors.append(f"{row['name']}: {exc}");continue
    sha=hashlib.sha256(buf).hexdigest()
    git_sha=hashlib.sha1(b'blob '+str(len(buf)).encode('ascii')+b'\x00'+buf).hexdigest()
    if (len(buf),sha,git_sha)!=(row['bytes'],row['sha256'],row['git_blob_sha']):
        errors.append(row['name']+': hash or size mismatch')
if errors:
    print('\n'.join('FAIL: '+e for e in errors));sys.exit(1)
print('PASS: %d source files retained with SHA-256 and Git blob identity' % len(manifest['files']))
