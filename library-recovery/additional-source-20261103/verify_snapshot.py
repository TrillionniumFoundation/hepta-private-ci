#!/usr/bin/env python3
"""Verify original Library snapshot bytes; no training or runtime inference."""
import hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parent
manifest=json.loads((root/'MANIFEST.json').read_text())
errors=[]
for entry in manifest['files']:
    try: b=(root/'files'/entry['name']).read_bytes()
    except OSError as exc: errors.append(str(exc));continue
    if (len(b),hashlib.sha256(b).hexdigest(),hashlib.sha1(b'blob '+str(len(b)).encode()+b'\x00'+b).hexdigest())!=(entry['bytes'],entry['sha256'],entry['git_blob_sha']):
        errors.append(entry['name'])
if errors:
    print('FAIL:',*errors);sys.exit(1)
print('PASS: %d preserved source-file identities' % len(manifest['files']))
