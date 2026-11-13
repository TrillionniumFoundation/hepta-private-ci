#!/usr/bin/env python3
"""Losslessly bound the two already observed Git originals for 512000-byte leaves."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

BASE = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-hold-v1')
OUT = BASE / 'original-9101-readback-encoded-v1'


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def put(name, raw):
    assert len(raw) <= 512000
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(path), **identity(raw)}


def main():
    OUT.mkdir(exist_ok=True)
    rows = []
    for name in ('ORIGINAL_9101_PROCESS_INPUT.json', 'ORIGINAL_9101_PROCESS_INPUT.GITHUB_GET.original.json'):
        raw = (BASE / name).read_bytes()
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        encoded = base64.b64encode(compressed)
        parts = [put(name + '.gz.b64.part%03d' % (i // 348000 + 1), encoded[i:i + 348000] + b'\n')
                 for i in range(0, len(encoded), 348000)]
        reconstructed_gzip = base64.b64decode(b''.join((OUT / p['name']).read_bytes().rstrip(b'\n') for p in parts), validate=True)
        assert reconstructed_gzip == compressed and gzip.decompress(reconstructed_gzip) == raw
        rows.append({'original_name': name, 'original_identity': identity(raw),
                     'gzip_identity': identity(compressed), 'parts': parts,
                     'full_local_decode_equal': True})
    actual_sdk = json.loads((BASE / 'ORIGINAL_9101_PROCESS_INPUT.GITHUB_GET.original.json').read_bytes())
    request = (BASE / 'ORIGINAL_9101_PROCESS_INPUT.json').read_bytes()
    assert actual_sdk['isError'] is False and actual_sdk['structuredContent']['content'].encode() == request
    manifest = {'format': 'hepta-lossless-original-git-readback-bounded-encoding-v1',
                'source_request_git_blob': '60e6b8d8b12523318410b8f60d7626a7fdc1643e',
                'original_sdk_full_content_equals_request': True,
                'no_native_execution_or_native_observation': True,
                'encoding': 'gzip level9 mtime0 then strict base64 in 348000-character parts with one LF',
                'maximum_leaf_bytes': 512000, 'records': rows}
    final = put('ENCODING_MANIFEST.json', (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'manifest': final, 'parts': [p for row in rows for p in row['parts']]}))


if __name__ == '__main__':
    main()
