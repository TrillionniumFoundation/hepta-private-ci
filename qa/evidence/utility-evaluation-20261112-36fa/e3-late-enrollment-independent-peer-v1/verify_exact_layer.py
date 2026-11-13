#!/usr/bin/env python3
"""Pure byte review of the immutable E3 late enrollment proposal.

Reads JSON and UTF-8 source only. Does not import or run project code,
author review scripts, Rust, formatter, gates, Git, H, or native inputs.
"""
from pathlib import Path
import hashlib
import json
import re

AUTHOR = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1')
LAYER = AUTHOR / 'late-enrollment-layer-v1'
FIRST = AUTHOR / 'root-service-layer-v1'
OUT = Path(__file__).resolve().parent
INVENTORY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
BASE = 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
TREE = '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: '+key)
        result[key] = value
    return result

def read_json(path):
    return json.loads(path.read_bytes(), object_pairs_hook=no_duplicates)

def exact_pin(raw, expected):
    actual = pin(raw)
    assert actual == {k: expected[k] for k in actual}, (actual, expected)
    return actual

def new_json(name, obj):
    raw = (json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)+'\n').encode()
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw, 'immutable output differs: '+str(path)
    else:
        with path.open('xb') as handle:
            handle.write(raw)
    return pin(raw)

inventory_raw = INVENTORY.read_bytes()
assert pin(inventory_raw) == {
    'bytes': 5631947,
    'sha256': 'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e',
    'git_blob': '457adb9bf9ba3a844e9dfa149be49460bb306998'}
inventory = read_json(INVENTORY)
base_rows = {row['path']: row for row in inventory['files']}
assert len(base_rows) == len(inventory['files']) == 15243

def base_body(path, raw):
    row = base_rows[path]
    identity = pin(raw)
    assert row['kind'] == 'file' and row['index_mode'] == '100644'
    assert row['matches_index'] is True
    assert row['index_blob'] == row['working_blob'] == identity['git_blob']
    assert row['bytes'] == identity['bytes'] and row['sha256'] == identity['sha256']
    return identity

first_raw = (FIRST / 'SOURCE_PACKET.json').read_bytes()
assert pin(first_raw)['git_blob'] == '0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b'
first = read_json(FIRST / 'SOURCE_PACKET.json')
assert first['base_commit'] == BASE and first['base_tree'] == TREE
first_entries = {entry['path']: entry for entry in first['entries']}
assert len(first_entries) == len(first['entries']) == 7
first_verified = []
for path, entry in first_entries.items():
    after = entry['after_utf8'].encode()
    exact_pin(after, entry['after'])
    assert (FIRST / 'after' / path).read_bytes() == after
    if entry['before'] is None:
        assert entry['before_utf8'] is None and path not in base_rows
    else:
        before = entry['before_utf8'].encode()
        exact_pin(before, entry['before'])
        assert (FIRST / 'before' / path).read_bytes() == before
        base_body(path, before)
    first_verified.append({'path': path, 'before': entry['before'], 'after': entry['after']})

packet_raw = (LAYER / 'SOURCE_PACKET.json').read_bytes()
assert pin(packet_raw) == {
    'bytes': 426837,
    'sha256': '461a98580f070c8d1a355704732ef0a961249cc019d6c0143d46d04b8cf16933',
    'git_blob': '388bfb3f3ab70e5f39d847c26d2d48daa2c7ead1'}
packet = read_json(LAYER / 'SOURCE_PACKET.json')
assert packet['format'] == 'hepta-local-source-packet-v1'
assert packet['base_commit'] == BASE and packet['base_tree'] == TREE
assert packet['prerequisites'] == ['root-service-layer-v1/0dc5e98ff38ed0c4c4defe277d21a5cb90bae37b']
entries = {entry['path']: entry for entry in packet['entries']}
assert len(entries) == len(packet['entries']) == 20
assert list(entries) == sorted(entries)
manifest = read_json(LAYER / 'MANIFEST.json')
assert manifest['sources'] == [{key: entry[key] for key in ('path','before','after','provenance')}
                               for entry in packet['entries']]
payloads = []
for item in manifest['payloads']:
    actual = exact_pin((LAYER / item['path']).read_bytes(), item)
    payloads.append({'path': item['path'], **actual})
assert len(payloads) == 7 and len({p['path'] for p in payloads}) == 7

splices = read_json(LAYER / 'EXACT_SOURCE_SPLICES.json')
splice_map = {row['path']: row for row in splices}
assert len(splice_map) == len(splices) == len(entries)
assert set(splice_map) == set(entries)
checks = []
new_paths = []
from_first = []
from_base = []
for path, entry in entries.items():
    before = b'' if entry['before'] is None else entry['before_utf8'].encode()
    after = entry['after_utf8'].encode()
    exact_pin(after, entry['after'])
    assert (LAYER / 'after' / path).read_bytes() == after
    if entry['before'] is None:
        assert entry['before_utf8'] is None
        assert path not in base_rows and path not in first_entries
        assert not (LAYER / 'before' / path).exists()
        new_paths.append(path)
        preimage_basis = 'absent from full b608 inventory and first layer'
    else:
        exact_pin(before, entry['before'])
        assert (LAYER / 'before' / path).read_bytes() == before
        if path in first_entries:
            assert entry['before'] == first_entries[path]['after']
            assert before == first_entries[path]['after_utf8'].encode()
            from_first.append(path)
            preimage_basis = 'complete exact first-layer postimage'
        else:
            base_body(path, before)
            assert (AUTHOR / 'references' / path).read_bytes() == before
            from_base.append(path)
            preimage_basis = 'complete exact b608 body and canonical inventory row'
    old_lines = before.decode().splitlines(keepends=True)
    new_lines = after.decode().splitlines(keepends=True)
    operations = splice_map[path]['operations']
    previous_old_end = 0
    previous_new_end = 0
    forward = []
    inverse = []
    for op in operations:
        old_start, old_end = op['before_lines']
        new_start, new_end = op['after_lines']
        assert 0 <= previous_old_end <= old_start <= old_end <= len(old_lines)
        assert 0 <= previous_new_end <= new_start <= new_end <= len(new_lines)
        assert ''.join(old_lines[old_start:old_end]) == op['old_utf8']
        assert ''.join(new_lines[new_start:new_end]) == op['new_utf8']
        assert old_lines[previous_old_end:old_start] == new_lines[previous_new_end:new_start]
        forward.extend(old_lines[previous_old_end:old_start])
        forward.append(op['new_utf8'])
        inverse.extend(new_lines[previous_new_end:new_start])
        inverse.append(op['old_utf8'])
        previous_old_end = old_end
        previous_new_end = new_end
    assert old_lines[previous_old_end:] == new_lines[previous_new_end:]
    forward.extend(old_lines[previous_old_end:])
    inverse.extend(new_lines[previous_new_end:])
    assert ''.join(forward).encode() == after
    assert ''.join(inverse).encode() == before
    checks.append({'path': path, 'basis': preimage_basis, 'before': entry['before'],
                   'after': entry['after'], 'splice_count': len(operations),
                   'complete_forward_equal': True, 'complete_inverse_equal': True,
                   'all_unlisted_line_ranges_equal': True})
assert (len(new_paths), len(from_first), len(from_base)) == (10, 6, 4)

refs = read_json(LAYER / 'SOURCE_REFERENCES.json')
assert len({row['path'] for row in refs}) == len(refs)
reference_checks = []
for row in refs:
    raw = (AUTHOR / 'references' / row['path']).read_bytes()
    exact_pin(raw, row)
    base_body(row['path'], raw)
    reference_checks.append({'path': row['path'], **pin(raw),
                             'full_local_body_and_canonical_inventory_equal': True,
                             'original_sdk_available_author_claim': row['original_sdk_available']})

protected = ['config_resident_learning.rs','resident_learning_delivery.rs',
             'authority_host_learning_resident_transport.rs','learning_owner_command_channel.rs',
             'authority_host_learning_candidate_service.rs']
assert all('codex-rs/hepta-agentd/src/'+name not in entries for name in protected)
assert all('codex-rs/hepta-agentd/src/'+name not in first_entries for name in protected)

test_files = [p for p in new_paths if p.endswith('_tests.rs')]
assert len(test_files) == 2
test_methods = []
ignored_count = 0
for path in test_files:
    body = entries[path]['after_utf8']
    assert len(body.splitlines()) < 500
    methods = re.findall(r'^fn ([A-Za-z0-9_]+)\(', body, re.M)
    test_count = len(re.findall(r'^#\[test\]', body, re.M))
    ignore_count = len(re.findall(r'^#\[ignore', body, re.M))
    assert test_count == len(methods)
    ignored_count += ignore_count
    test_methods.extend({'path': path, 'name': method} for method in methods)
assert len(test_methods) == 5 and ignored_count == 3
new_production = [p for p in new_paths if not p.endswith('_tests.rs')]
assert len(new_production) == 8
assert all(len(entries[p]['after_utf8'].splitlines()) < 500 for p in new_paths)

report = {
    'format': 'hepta-e3-late-enrollment-independent-byte-review-v1',
    'status': 'PURE_BYTE_AND_PREIMAGE_VERIFICATION_COMPLETED',
    'packet': pin(packet_raw), 'prerequisite_packet': pin(first_raw),
    'canonical_inventory': {'path': str(INVENTORY), **pin(inventory_raw)},
    'counts': {'source_paths': len(entries), 'modified': 10, 'new': 10,
               'new_production': 8, 'new_test_files': 2, 'new_test_methods': 5,
               'ignored_root_test_methods': 3, 'first_layer_preimages': 6,
               'b608_preimages': 4, 'reference_bodies': len(refs)},
    'metadata_payloads': payloads,
    'first_layer_dependencies': first_verified,
    'source_checks': checks, 'reference_checks': reference_checks,
    'unmodified_original_cores': protected, 'test_methods': test_methods,
    'all_exact_forward_and_inverse_equal': True,
    'reference_sdk_claims_not_independently_replayed_by_this_script': True,
    'not_a_compile_or_qualification_result': True,
    'executed_project_code': False, 'executed_author_script': False,
    'rust_or_formatter_or_tests_or_h': False,
    'source_or_refs_written': False,
}
result_pin = new_json('BYTE_AND_PREIMAGE_REVIEW.json', report)
print(json.dumps({'status': report['status'], 'output': str(OUT/'BYTE_AND_PREIMAGE_REVIEW.json'),
                  'identity': result_pin, 'counts': report['counts']}, sort_keys=True))
