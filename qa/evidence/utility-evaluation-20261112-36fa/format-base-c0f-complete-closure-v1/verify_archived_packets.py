#!/usr/bin/env python3
"""Verify saved complete Git GET payloads and all lossless reconstruction pins."""
import base64
import gzip
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(), 'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def require(b, expected):
    observed = pin(b)
    assert all(observed[key] == expected[key] for key in observed), (observed, expected)
    return observed

def main():
    ledger = json.loads((ROOT / 'ARCHIVE_READBACK_LEDGER.json').read_bytes())
    saved = {}
    for row in ledger['entries']:
        name = row['path'].split('/', 1)[1]
        sdk = json.loads((ROOT / 'archive' / (name + '.GET.original.json')).read_bytes())
        assert not sdk.get('isError')
        body = sdk['structuredContent']['content'].encode('utf-8')
        require(body, row)
        assert body == (ROOT / name).read_bytes()
        saved[name] = body
    assert len(saved) == 59
    compact = json.loads(saved['TRANSPORT_INPUT_MANIFEST.json'])
    encodings = json.loads(saved['ENCODING_MANIFEST.json'])
    bundles = [compact] + encodings['bundles']
    reports = []
    for spec in bundles:
        decoded_parts = []
        for item in spec['parts']:
            encoded = saved[item['path']]
            assert encoded.endswith(b'\n') and b'\n' not in encoded[:-1]
            decoded = base64.b64decode(encoded[:-1], validate=True)
            assert base64.b64encode(decoded) + b'\n' == encoded
            assert len(decoded) == item['decoded_bytes']
            assert sum(map(len, decoded_parts)) == item['decoded_offset']
            assert hashlib.sha256(decoded).hexdigest() == item['decoded_sha256']
            decoded_parts.append(decoded)
        compressed = b''.join(decoded_parts)
        require(compressed, spec['gzip'])
        raw = gzip.decompress(compressed)
        require(raw, spec['raw'])
        assert raw == (ROOT / spec['raw']['path']).read_bytes()
        reports.append({'name': spec['raw']['path'], 'raw': pin(raw), 'gzip': pin(compressed), 'actual_full_GET_parts': len(spec['parts']), 'all_encoded_decoded_raw_original_bytes_equal': True})
    small = json.loads((ROOT / 'BASE_OBJECT_INPUT.json').read_bytes())
    full = json.loads((ROOT / 'BASE_OBJECT_PACKET.json').read_bytes())
    assert small['objects'] == full['provided_objects'] and len(small['objects']) == 83
    assert small['complete_closure_identity_manifest'] == full['complete_base_closure']['identity_manifest']
    old = json.loads((ROOT / 'ORIGINAL_GIT_GETS.json').read_bytes())
    assert len(old['entries']) == 90
    for row in old['entries']:
        raw = base64.b64decode(row['raw_base64'], validate=True)
        require(raw, row)
        assert raw == (ROOT / row['path']).read_bytes()
    result = {'schema': 'hepta-c0f-actual-full-git-readback-and-reconstruction-v1', 'status': 'ALL_FIXED_ARTIFACT_BYTES_VERIFIED', 'actual_Git_create_and_full_GET_files': 59, 'lossless_bundle_results': reports, 'original_source_GET_SDKs_preserved': 90, 'provided_object_bodies': 83, 'required_shared_objects': 16011, 'native_execution': False, 'source_mutation': False, 'qualification': False}
    raw = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
    with (ROOT / 'FULL_READBACK_VERIFICATION.json').open('xb') as out:
        out.write(raw)
    print(json.dumps({'review': pin(raw), 'bundles': reports}, sort_keys=True))

if __name__ == '__main__':
    main()
