"""Verify already-retrieved exact source files; no network or repository writes.

Usage: python verify_sources.py /path/containing/codex-rs
The evidence package intentionally omits source copies. Retrieve each immutable
SOURCE_MANIFEST.json URL/blob into the supplied directory before running this.
"""
import hashlib
import json
import sys
from pathlib import Path

manifest = json.loads((Path(__file__).parent / 'SOURCE_MANIFEST.json').read_bytes())
root = Path(sys.argv[1]).resolve()
for item in manifest['files']:
    path = root / item['path']
    data = path.read_bytes()
    assert len(data) == item['bytes'], item['path']
    assert hashlib.sha256(data).hexdigest() == item['sha256'], item['path']
    assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == item['git_blob'], item['path']
print(json.dumps({'verified_exact_source_files': len(manifest['files']),
                  'source_commit': manifest['source_commit'],
                  'source_qa_run': False, 'native_run': False, 'ordinary_qualification': 0}))
