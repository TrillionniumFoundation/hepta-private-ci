#!/usr/bin/env python3
"""Recover only when all native artifact identities match; no native/source actions."""
from pathlib import Path
import base64
import gzip
import hashlib
import json

ROOT = Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/actual-finalfmt-exact-recovery')
ACTUAL = Path('/tmp/hepta-36fa-source-repair-finalfmt-launch-v1/ARTIFACTS.original.json')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def save(name, raw):
    path = ROOT / name
    if path.exists():
        assert path.read_bytes() == raw
    else:
        path.write_bytes(raw)
    return {'name': name, **pin(raw)}


def main():
    manifest_raw = ACTUAL.read_bytes()
    manifest = json.loads(manifest_raw)
    raw = (ROOT / 'final.inventory.exact-recovered.json').read_bytes()
    observed = next(row for row in manifest['files'] if row['name'] == 'final.inventory.json.gz')
    assert pin(raw) == {'bytes': observed['raw_bytes'], 'sha256': observed['raw_sha256'],
                        'git_blob': observed['raw_git_blob']}
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    assert pin(compressed) == {key: observed[key] for key in ('bytes', 'sha256', 'git_blob')}
    gzip_record = save('final.inventory.json.gz', compressed)
    parts = []
    for expected in observed['parts']:
        start = expected['decoded_offset']
        piece = compressed[start:start + expected['decoded_bytes']]
        assert len(piece) == expected['decoded_bytes']
        assert hashlib.sha256(piece).hexdigest() == expected['decoded_sha256']
        encoded = base64.b64encode(piece) + b'\n'
        assert pin(encoded) == {key: expected[key] for key in ('bytes', 'sha256', 'git_blob')}
        parts.append(save(expected['name'], encoded))
    assembled = b''.join(base64.b64decode((ROOT / row['name']).read_bytes()) for row in parts)
    assert assembled == compressed and gzip.decompress(assembled) == raw
    same_bytes_paths = []
    for row in manifest['files']:
        if row.get('raw_sha256') == observed['raw_sha256']:
            assert row['raw_bytes'] == observed['raw_bytes'] and row['raw_git_blob'] == observed['raw_git_blob']
            assert {key: row[key] for key in ('bytes', 'sha256', 'git_blob')} == pin(compressed)
            assert [{key: part[key] for key in ('bytes', 'sha256', 'git_blob', 'decoded_offset', 'decoded_bytes', 'decoded_sha256')} for part in row['parts']] == [{key: part[key] for key in ('bytes', 'sha256', 'git_blob', 'decoded_offset', 'decoded_bytes', 'decoded_sha256')} for part in observed['parts']]
            same_bytes_paths.append(row['name'])
    report = {
        'format': 'hepta-246d-actual-inventory-gzip-parts-exact-recovery-v1',
        'status': 'EXACT_ORIGINAL_RAW_GZIP_AND_ALL_FIVE_ENCODED_PARTS_MATCH',
        'actual_artifact_manifest': pin(manifest_raw), 'raw': pin(raw),
        'gzip': gzip_record, 'parts': parts,
        'same_original_inventory_bytes_at_paths': same_bytes_paths,
        'provenance': 'The raw inventory had already matched native original bytes/SHA256/Git identity. One standard gzip level-9 mtime-zero encoding and its original 262144-byte parts independently match every observed original ARTIFACTS identity, including each decoded offset and SHA256. This is exact-byte recovery, not another native full read.',
        'reconstruction': 'Base64-decode the five listed text parts separately, concatenate in order, verify gzip identity, gunzip once, verify raw identity. The same bytes are mapped to all listed original inventory paths; no synthetic new observation is claimed.',
        'native_commands_executed': False, 'source_mutation': False, 'qualification': False,
    }
    record = save('ORIGINAL_GZIP_PARTS_RECOVERY.json', (json.dumps(report, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'report': record, 'gzip': gzip_record, 'parts': parts,
                      'same_original_inventory_paths': same_bytes_paths}, indent=2))


if __name__ == '__main__':
    main()
