#!/usr/bin/env python3
import base64
import gzip
import hashlib
import json
from pathlib import Path

BASE = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1')


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def put(name, raw):
    p = BASE / name
    if p.exists():
        assert p.read_bytes() == raw
    else:
        with p.open('xb') as stream:
            stream.write(raw)
    return {'name': name, **identity(raw)}


def main():
    artifacts = {r['name']: r for r in json.loads((BASE / 'ARTIFACTS.json').read_bytes())['files']}
    expected = artifacts['fmt.after.postimages.json.gz']
    version = None
    offset = 0
    chunks = []
    reads = []
    for i in range(1, 7):
        name = 'FMT_POSTIMAGES_GZIP_READ_%02d.original.json' % i
        original = (BASE / name).read_bytes()
        sdk = json.loads(original)
        assert sdk['isError'] is False
        observation = sdk.get('structuredContent') or json.loads(sdk['content'][0]['text'])
        if version is None:
            version = observation['version']
        data = base64.b64decode(observation['data_base64'], validate=True)
        assert observation['version'] == version
        assert observation['path'] == '/home/qian-qi/hepta-utility-36fa-evidence/provider-0c59-fix101-apply-fmt-v1/run/fmt.after.postimages.json.gz'
        assert observation['size'] == expected['bytes'] == 390123
        assert observation['offset'] == offset
        assert observation['next_offset'] == offset + len(data)
        assert hashlib.sha256(data).hexdigest() == observation['chunk_sha256']
        assert observation['eof'] is (i == 6)
        reads.append({'sdk': {'name': name, **identity(original)}, 'offset': offset,
                      'next_offset': observation['next_offset'], 'chunk_sha256': observation['chunk_sha256'],
                      'version': version, 'eof': observation['eof']})
        offset += len(data)
        chunks.append(data)
    compressed = b''.join(chunks)
    assert offset == expected['bytes']
    assert identity(compressed) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}
    raw = gzip.decompress(compressed)
    assert identity(raw) == {'bytes': expected['raw_bytes'], 'sha256': expected['raw_sha256'], 'git_blob': expected['raw_git_blob']}
    packet = json.loads(raw)
    assert packet['stage'] == 'fmt.after' and len(packet['changes']) == 62
    assert len({r['path'] for r in packet['changes']}) == 62
    saved = [put('fmt.after.postimages.json.gz', compressed), put('fmt.after.postimages.json', raw)]
    parts = []
    for original_part in expected['parts']:
        start = original_part['decoded_offset']
        part = compressed[start:start + original_part['decoded_bytes']]
        assert hashlib.sha256(part).hexdigest() == original_part['decoded_sha256']
        encoded = base64.b64encode(part) + b'\n'
        assert identity(encoded) == {k: original_part[k] for k in ('bytes', 'sha256', 'git_blob')}
        parts.append(put(original_part['name'], encoded))
    review = {'format': 'hepta-native-complete-fmt-postimages-binary-readback-v1',
              'job_id': '1a1d41eb3ef-392-2b2', 'actual_native_file_read': 'fmt.after.postimages.json.gz',
              'version': version, 'reads': reads, 'coverage_start': 0, 'coverage_end': offset,
              'coverage_complete_without_overlap_or_gap': True, 'observed_eof': True,
              'gzip_identity_matches_actual_artifacts': True,
              'raw_identity_matches_actual_artifacts': True, 'saved_decoded_originals': saved,
              'ascii_parts': parts,
              'ascii_part_provenance': 'Derived deterministically from the six actual pinned-version gzip reads; all bytes/SHA/Git equal the native ARTIFACTS part identities. Individual native .b64 paths were not separately read.',
              'actual_transition_count': len(packet['changes']), 'semantic_review_completed': False,
              'qualification': False}
    report = put('FMT_POSTIMAGES_FULL_READBACK_REVIEW.json', (json.dumps(review, sort_keys=True, indent=2) + '\n').encode())
    print(json.dumps({'review': report, 'saved': saved, 'parts': parts,
                      'packet_fields': sorted(packet),
                      'first_change_fields': sorted(packet['changes'][0]),
                      'first_after_row': packet['changes'][0]['after']}))


if __name__ == '__main__':
    main()
