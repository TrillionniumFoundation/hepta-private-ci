#!/usr/bin/env python3
"""Verify the previously fixed 58 preparation SDK copies; no native access."""
import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-git-sdk-archive-v1')


def identity(raw):
    return {
        'bytes': len(raw),
        'sha256': hashlib.sha256(raw).hexdigest(),
        'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest(),
    }


def write_new(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()
    assert len(raw) <= 512000
    with (ROOT / name).open('xb') as stream:
        stream.write(raw)
    return {'name': name, 'path': str(ROOT / name), **identity(raw)}


index_raw = (ROOT / 'COPY_INDEX.json').read_bytes()
assert hashlib.sha256(index_raw).hexdigest() == '88dcc2329f2d90782a0f52b99e4dd2c222cae1a8a1c685854a59ceaaf704ce66'
index = json.loads(index_raw)
assert index['source_index_git_blob'] == '00623d7cc550daf08131575896d974ccf02432ef'
entries = index['entries']
assert index['count'] == len(entries) == 58
assert len({entry['name'] for entry in entries}) == 58
proofs = []
for entry in entries:
    path = ROOT / entry['name']
    assert str(path) == entry['path']
    raw = path.read_bytes()
    expected = {key: entry[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert identity(raw) == expected
    assert len(raw) <= 512000
    assert Path(entry['original_path']).read_bytes() == raw
    create_path = ROOT / (entry['name'] + '.PUBLISH_CREATE.original.json')
    get_path = ROOT / (entry['name'] + '.PUBLISH_GET.original.json')
    ledger_path = ROOT / (entry['name'] + '.PUBLISH_LEDGER_ENTRY.json')
    create_raw, get_raw = create_path.read_bytes(), get_path.read_bytes()
    create, fetched = json.loads(create_raw), json.loads(get_raw)
    row = json.loads(ledger_path.read_bytes())
    assert not create.get('isError')
    assert not fetched.get('isError')
    assert create['structuredContent']['sha'] == expected['git_blob']
    assert fetched['structuredContent']['content'].encode('utf-8') == raw
    assert {key: row[key] for key in expected} == expected
    assert row['path'] == str(path)
    assert row['name'] == entry['name']
    assert row['actual_git_create'] is True and row['actual_full_get_equal'] is True
    proofs.append({
        'name': entry['name'],
        'original_path': entry['original_path'],
        'copy_path': str(path),
        **expected,
        'original_and_copy_bytes_equal': True,
        'actual_git_create_sha_equal': True,
        'actual_full_get_content_bytes_equal': True,
        'publication_create_sdk': {'path': str(create_path), **identity(create_raw)},
        'publication_full_get_sdk': {'path': str(get_path), **identity(get_raw)},
    })
report = {
    'format': 'hepta-fixed-preparation-git-sdk-archive-full-readback-v1',
    'scope': 'The fixed 58 prior preparation create/full-GET SDK originals only.',
    'source_index_git_blob': index['source_index_git_blob'],
    'copy_index': identity(index_raw),
    'copied_original_count': len(proofs),
    'total_original_bytes': sum(row['bytes'] for row in proofs),
    'maximum_original_leaf_bytes': max(row['bytes'] for row in proofs),
    'all_original_copies_equal': True,
    'all_git_create_and_full_get_equal': True,
    'native_calls_performed': 0,
    'source_or_git_worktree_mutations_performed': 0,
    'includes_runtime_job_records': False,
    'recursive_publication_sdk_capture': False,
    'publication_sdk_retention': 'The new archive publication SDKs are retained locally with their identities below; they are not recursively added as archive leaves.',
    'qualification_claim': False,
    'entries': proofs,
}
result = write_new('ACTUAL_GIT_FULL_READBACK_LEDGER.json', report)
print(json.dumps({'status': 'VERIFIED_FIXED_58_ORIGINAL_COPIES', 'report': result,
                  'count': len(proofs), 'native_calls_performed': 0}, sort_keys=True))
