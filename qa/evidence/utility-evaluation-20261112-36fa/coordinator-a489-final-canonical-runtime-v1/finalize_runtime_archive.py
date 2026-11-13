import collections
import hashlib
import json
from pathlib import Path

D = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
INDEX = D / 'CLOSED_RUNTIME_ARCHIVE_INPUTS.json'
CAP = 512000

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def exact_pin(raw, expected):
    actual = identity(raw)
    assert actual == {k: expected[k] for k in actual}, (actual, expected)
    return actual

def create(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    assert len(raw) <= CAP
    p = D / name
    if p.exists():
        assert p.read_bytes() == raw, p
    else:
        with p.open('xb') as f:
            f.write(raw)
    return {'path': str(p), **identity(raw)}

idxraw = INDEX.read_bytes()
exact_pin(idxraw, {'bytes': 110230, 'sha256': 'c6fa5ca58ae8c5c7e4602c3f577c4b4a7f3d21ad9bcebb1aa613078f4b1ade99',
                   'git_blob': '5d8fbb094e98cbc2a6a803ff47da6ad84d94a850'})
idx = json.loads(idxraw)
assert len(idx['entries']) == idx['count'] == 161
assert len({e['evidence_path'] for e in idx['entries']}) == 161
rows = []
for entry in idx['entries']:
    p = Path(entry['path'])
    raw = p.read_bytes()
    exact_pin(raw, entry)
    assert len(raw) <= CAP
    raw.decode('utf-8')
    ledger_path = Path(str(p) + '.PUBLISH_LEDGER_ENTRY.json')
    create_path = Path(str(p) + '.PUBLISH_CREATE.original.json')
    get_path = Path(str(p) + '.PUBLISH_GET.original.json')
    ledger_raw, create_raw, get_raw = [x.read_bytes() for x in (ledger_path, create_path, get_path)]
    ledger, made, fetched = [json.loads(x) for x in (ledger_raw, create_raw, get_raw)]
    exact_pin(raw, ledger)
    assert ledger['actual_git_create'] is True and ledger['actual_full_get_equal'] is True
    assert made.get('isError') is not True
    assert made['structuredContent']['sha'] == entry['git_blob']
    assert fetched.get('isError') is not True
    content = fetched['structuredContent']['content']
    assert isinstance(content, str) and content.encode('utf-8') == raw, p
    previous = entry.get('prior_actual_git_full_get')
    if previous:
        assert previous['ledger_path'] == str(ledger_path)
        assert previous['original_get_sdk_path'] == str(get_path)
        exact_pin(get_raw, previous['original_get_sdk_identity'])
    rows.append({'evidence_path': entry['evidence_path'], 'local_path': str(p),
                 **identity(raw), 'provenance': entry['provenance'],
                 'actual_git_create_and_full_get_equal': True,
                 'reused_already_verified_get': bool(previous),
                 'original_create_sdk': {'local_path': str(create_path), **identity(create_raw)},
                 'original_full_get_sdk': {'local_path': str(get_path), **identity(get_raw)}})

assert sum(x['reused_already_verified_get'] for x in rows) == 57
assert sum(x['provenance'] == 'original-native-binary-read-sdk' for x in rows) == 58
ledger = create('FULL_GIT_READBACK_LEDGER.json', {
    'format': 'hepta-fixed-runtime-actual-git-full-readback-ledger-v1',
    'job_id': idx['job_id'], 'fixed_cut_at_utc': idx['cut_at_utc'],
    'closed_index': identity(idxraw), 'count': len(rows),
    'prior_full_get_claims_verified': 57, 'new_full_get_equal': 104,
    'verification_method': 'Original saved create and complete GET responses, complete UTF-8 content byte comparison, and Git blob/length/SHA256 for every fixed member. No new H read or operation.',
    'entries': rows})

review = create('ARCHIVE_CLOSURE_REVIEW.json', {
    'format': 'hepta-fixed-canonical-runtime-archive-closure-v1',
    'status': 'FIXED_CLOSED_SET_ALL_ACTUAL_GIT_FULL_GET_EQUAL',
    'job_id': idx['job_id'], 'fixed_cut_at_utc': idx['cut_at_utc'],
    'closed_index': identity(idxraw), 'full_get_ledger': ledger,
    'fixed_members': len(rows), 'prior_claims_revalidated': 57, 'new_members_saved': 104,
    'unique_blob_count': len({x['git_blob'] for x in rows}),
    'maximum_payload_leaf_bytes': max(x['bytes'] for x in rows), 'leaf_cap_bytes': CAP,
    'provenance_counts': dict(collections.Counter(x['provenance'] for x in rows)),
    'native_binary_read_sdk_wrappers_preserved': 58,
    'native_read_calls_are_historical_completed_observations': True,
    'native_read_failures': 0, 'new_native_operations_for_archive': 0,
    'archive_publication_failures_in_104_member_batch': 0,
    'local_reviewer_errors_preserved': [
        'Initial reviewer incorrectly expected timed_out on the original OBJECT_BATCH special schema; original error and corrected reviewer are retained.',
        'Initial cloud archive collector attempted to read the helper transport-save-parts directory as a file; original error and exact exclusion correction are retained.'
    ],
    'representation_boundaries': [
        'Both raw indices were fully read through original compressed files and stable-version chunks; the original-format bounded parts preserve their exact bytes.',
        'The complete original index audit was reconstructed from the actual raw indices and accepted only after all original raw/gzip/part identities matched. No new lstat or second H audit download occurred.',
        'The full source inventory recovery is separately preserved by placement 29bff7138b54ec375b8cd96779edfa090f271e2d, using preheld bytes matched to actual producer identities.',
        'The two large staging bodies were not externally downloaded again; exact preheld dispatched bytes are bound by the actual bootstrap full-readback and terminal input audit.',
        'The 505 original catalogue entries are references, not a claim of 505 external file downloads.',
        'Generated Git publication SDK files are supporting records for the ledger, not an unbounded recursive expansion of the fixed native evidence set.'
    ],
    'qualification': False, 'tests_started': 0,
    'no_source_or_remote_ref_mutation_by_archive': True,
    'next_source_or_native_dispatch_authorized_by_this_record': False})
print(json.dumps({'ledger': ledger, 'review': review}, sort_keys=True))
