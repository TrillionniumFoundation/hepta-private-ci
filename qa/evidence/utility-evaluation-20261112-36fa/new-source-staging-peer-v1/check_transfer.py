"""Offline transfer-only audit. Does not import/read the main driver or call H."""
from pathlib import Path, PurePosixPath
from collections import Counter
import base64
import hashlib
import json
import zlib

SOURCE = Path('/tmp/hepta-36fa-new-source-materializer-hold-v1')
OUT = Path('/tmp/hepta-36fa-new-source-staging-peer-v1')
GRAPH = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
OVERLAY = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1')
PARENT = '/home/qian-qi/hepta-utility-36fa-evidence'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def require(raw, expected):
    assert pin(raw) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}


def pairs(items):
    out = {}
    for key, value in items:
        assert key not in out, ('duplicate JSON key', key)
        out[key] = value
    return out


def reject_constant(value):
    raise AssertionError(('nonstandard JSON constant', value))


def parse(raw):
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)


def strict_b64(encoded):
    assert isinstance(encoded, str) and encoded.isascii()
    raw = base64.b64decode(encoded, validate=True)
    assert base64.b64encode(raw).decode() == encoded
    return raw


def typed_sha(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


manifest_raw = (SOURCE / 'STAGING_MANIFEST.HOLD.json').read_bytes()
assert pin(manifest_raw)['git_blob'] == '49e17fcf6f430c90f3048477e3521683903871a3'
manifest = parse(manifest_raw)
packet_raw = (SOURCE / 'MATERIALIZATION_PACKET.HOLD.json').read_bytes()
require(packet_raw, manifest['input_packet'])
assert pin(packet_raw)['git_blob'] == '728a9251a3ee0e5fca4dd4cc43e8629bbfa9185c'
packet = parse(packet_raw)
assert manifest['file_count'] == len(manifest['files']) == 5
assert manifest['status'] == 'HOLD_NO_H_EXECUTION_APPROVAL'
assert manifest['required_parent'] == PARENT and manifest['parent_creation_command'] is None
assert manifest['not_process_requests'] and manifest['separate_materialization_request_approval_still_required']
assert packet['expected_not_native_observed'] and packet['qualification'] is False

exact_paths = [f'{PARENT}/provider-0c59-materialization-v1-base.json.gz.part-{i:03}' for i in (1, 2)]
exact_paths += [f'{PARENT}/provider-0c59-materialization-v1-candidate.json.gz.part-{i:03}' for i in (1, 2, 3)]
decoded = {}
request_report = []
for row, expected_path in zip(manifest['files'], exact_paths, strict=True):
    raw = (SOURCE / row['name']).read_bytes()
    require(raw, row['request'])
    req = parse(raw)
    assert set(req) == {'data_base64', 'expected_version', 'host', 'path'}
    assert req['host'] == row['host'] == 'desktop'
    assert req['expected_version'] == row['expected_version'] == 'absent'
    assert req['path'] == row['path'] == expected_path
    assert str(PurePosixPath(req['path'])) == req['path']
    assert str(PurePosixPath(req['path']).parent) == PARENT
    assert '..' not in PurePosixPath(req['path']).parts
    body = strict_b64(req['data_base64'])
    require(body, row['decoded'])
    assert len(body) == row['decoded_bytes'] <= 524288 < 1048576
    assert len(raw) <= 699244
    assert row['expected_mode'] == 0o600
    assert req['path'] not in decoded
    decoded[req['path']] = body
    request_report.append({'name': row['name'], 'request': pin(raw), 'decoded': pin(body),
        'path': req['path'], 'host': req['host'], 'expected_version': req['expected_version'],
        'exact_four_fields': True, 'strict_canonical_base64': True,
        'mode_is_manifest_expectation_not_native_observation': row['expected_mode']})
assert max(r['request']['bytes'] for r in request_report) == manifest['max_actual_typed_bytes'] == 699244
assert max(r['decoded']['bytes'] for r in request_report) == manifest['max_actual_decoded_bytes'] == 524288

groups = {}
group_report = []
all_objects = {}
for name in ('base', 'candidate'):
    spec = packet['provided_inputs'][name]
    assert spec['maximum_decoded_part'] == 524288
    chunks = []
    offset = 0
    for part in spec['parts']:
        assert part['offset'] == offset and part['mode'] == 0o600
        chunk = decoded[part['path']]
        require(chunk, part)
        chunks.append(chunk)
        offset += len(chunk)
    compressed = b''.join(chunks)
    require(compressed, spec['gzip'])
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    raw = inflater.decompress(compressed, spec['raw']['bytes'] + 1)
    assert inflater.eof and not inflater.unused_data and not inflater.unconsumed_tail
    assert len(raw) == spec['raw']['bytes']
    require(raw, spec['raw'])
    payload = parse(raw)
    assert payload['native_execution'] is False
    objects = {}
    for obj in payload['objects']:
        body = strict_b64(obj['raw_base64'])
        assert obj['type'] in ('blob', 'tree', 'commit')
        assert len(body) == obj['bytes'] and hashlib.sha256(body).hexdigest() == obj['sha256']
        assert typed_sha(obj['type'], body) == obj['sha']
        assert obj['sha'] not in objects
        objects[obj['sha']] = (obj['type'], body)
    groups[name] = payload
    all_objects[name] = objects
    group_report.append({'group': name, 'parts': len(chunks), 'gzip': pin(compressed), 'raw': pin(raw),
        'single_complete_gzip_member_no_trailing_or_unconsumed_bytes': True,
        'objects': len(objects), 'object_types': dict(Counter(t for t, _ in objects.values())),
        'all_object_bytes_SHA256_typed_Git_SHA_and_base64_exact': True})
assert set(decoded) == {p['path'] for g in packet['provided_inputs'].values() for p in g['parts']}
assert set(all_objects['base']).isdisjoint(all_objects['candidate'])
assert len(all_objects['base']) == groups['base']['provided_count'] == packet['format_base']['provided_objects'] == 83
assert groups['base']['required_existing_count'] == packet['format_base']['required_donor_objects'] == 16011
assert groups['base']['base']['commit'] == packet['format_base']['commit']
assert groups['base']['base']['tree'] == packet['format_base']['tree']

base_raw = (GRAPH / 'inputs/CC57_INVENTORY.exact.json').read_bytes()
expected_raw = (GRAPH / 'expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json').read_bytes()
native_raw = (GRAPH / 'expected-inventory-v1/EXPECTED_NATIVE_FIVE_FIELD.json').read_bytes()
graph_raw = (GRAPH / 'CANDIDATE_FILE_GRAPH.json').read_bytes()
overlay_raw = (OVERLAY / 'EXACT_COMPOSED_OVERLAY.json').read_bytes()
require(base_raw, packet['donor']['inventory'])
require(expected_raw, packet['current']['inventory'])
require(native_raw, packet['current']['native_inventory'])
candidate = groups['candidate']
require(graph_raw, candidate['complete_leaf_graph'])
require(overlay_raw, candidate['reviewed_overlay'])
assert pin(overlay_raw)['git_blob'] == '148e9efc242f3ee3ee4e525281ec170feecf3f19'
graph = parse(graph_raw)
overlay = parse(overlay_raw)
base_rows = {r['path']: r for r in parse(base_raw)['files']}
expected_rows = {r['path']: r for r in parse(expected_raw)['files']}
assert candidate['candidate_commit'] == packet['current']['commit'] == '0c59aaca0b4932507f068c723f73da2f96729b3d'
assert candidate['candidate_tree'] == packet['current']['tree'] == graph['tree']
assert candidate['candidate_parents'] == packet['current']['parents'] == [packet['donor']['commit']]
assert candidate['donor_commit'] == packet['donor']['commit']
assert candidate['canonical_source_deletions'] == packet['overlay']['canonical_source_deletions'] == []
assert candidate['qualification'] is False
coverage = overlay['rust_files'] + overlay['non_rust_prepared']
expected_paths = {r['path'] for r in coverage}
assert len(expected_paths) == len(candidate['covered_paths']) == 110
assert {r['path'] for r in candidate['covered_paths']} == expected_paths
classifications = Counter()
objects = all_objects['candidate']
for row in candidate['covered_paths']:
    path = row['path']
    assert row['before'] == base_rows.get(path)
    assert row['after'] == expected_rows[path]
    local = (OVERLAY / 'overlay' / path).read_bytes()
    assert pin(local) == {'bytes': row['after']['bytes'], 'sha256': row['after']['sha256'],
                          'git_blob': row['after']['working_blob']}
    if row['before'] is None:
        classifications['new'] += 1
    elif row['before'] == row['after']:
        classifications['unchanged'] += 1
    else:
        classifications['modified'] += 1
    if row['before'] != row['after']:
        assert objects[row['after']['working_blob']] == ('blob', local)
assert dict(classifications) == {'modified': 60, 'new': 49, 'unchanged': 1}
updates = parse((GRAPH / 'EXACT_UPDATE_ENTRIES.json').read_bytes())
expected_blob_ids = {r['after']['git_blob'] for r in updates['changes']}
assert len(expected_blob_ids) == 109
tree_plan = parse((GRAPH / 'TREE_OBJECT_PLAN.json').read_bytes())
tree_ids = set()
for row in tree_plan['objects']:
    raw = strict_b64(row['raw_base64'])
    assert len(raw) == row['raw_bytes'] and hashlib.sha256(raw).hexdigest() == row['raw_sha256']
    oid = row['expected_git_tree']
    assert typed_sha('tree', raw) == oid and objects[oid] == ('tree', raw)
    tree_ids.add(oid)
assert len(tree_ids) == 10
commit_raw = (GRAPH / 'CANDIDATE_COMMIT.raw').read_bytes()
commit = typed_sha('commit', commit_raw)
assert commit == candidate['candidate_commit'] and objects[commit] == ('commit', commit_raw)
assert set(objects) == expected_blob_ids | tree_ids | {commit}
assert len(objects) == 120

review = {
    'format': 'hepta-fixed-five-staging-transfer-independent-peer-v1',
    'conclusion': 'No concrete transfer-integrity or fixed-request-schema blocker found; still HOLD pending Root engineering approval',
    'scope': 'Five create-only binary staging requests and their exact two payloads; no main-driver review',
    'qualification': False, 'H_calls': 0, 'source_or_ref_changes': False,
    'main_driver_read_or_executed': False,
    'manifest': pin(manifest_raw), 'packet': pin(packet_raw),
    'requests': request_report, 'request_count': 5,
    'max_typed_bytes': max(r['request']['bytes'] for r in request_report),
    'max_decoded_part_bytes': max(r['decoded']['bytes'] for r in request_report),
    'total_typed_bytes': sum(r['request']['bytes'] for r in request_report),
    'total_decoded_bytes': sum(r['decoded']['bytes'] for r in request_report),
    'exact_unique_absolute_paths_under_existing_parent': True,
    'no_mkdir_command_no_environment_no_process_request': True,
    'all_expected_version_values_literal_absent': True,
    'create_only_semantics_source': 'Available h_binary_write tool declaration: expected_version absent is create-only; at most 1 MiB decoded',
    'parent_existence_or_actual_mode_or_path_absence_new_native_observation': False,
    'expected_mode': '0600 is the packet/manifest expectation, not a completed file_info observation',
    'groups': group_report,
    'candidate_graph_crosscheck': {
        'frozen_overlay': pin(overlay_raw), 'complete_graph': pin(graph_raw),
        'covered_paths': 110, 'classifications': dict(classifications),
        'all_110_full_before_and_after_inventory_rows_match': True,
        'all_110_local_after_bytes_match': True,
        'all_109_changed_blob_bodies_match': True,
        'all_10_tree_bodies_match_independent_mode_aware_plan': True,
        'actual_Root_candidate_commit_body_matches': True,
        'candidate_objects': 120, 'extra_or_missing_candidate_objects': [],
        'canonical_deletions': [], 'base_candidate_object_overlap': [],
        'expected_inventory': pin(expected_raw), 'expected_native_projection': pin(native_raw)},
    'unchanged_scope_boundary': 'Base 83 provided objects checked byte-for-byte and by typed identity; donor completeness, native preflight and materializer behavior remain outside this transfer-only review',
    'transport_unknown_rule_preserved': manifest['immutable_error_rule'],
    'permission_boundary': 'No H staging or main execution authorized by this review; Root separately approves exact staging requests and separately approves materialization',
    'readback_evidence': pin((OUT / 'INPUT_READBACK.json').read_bytes()),
}
(OUT / 'REVIEW.json').write_text(json.dumps(review, sort_keys=True, indent=2) + '\n')
print(json.dumps({'review': pin((OUT / 'REVIEW.json').read_bytes()), 'groups': group_report,
                  'candidate_paths': 110, 'candidate_objects': 120, 'conclusion': review['conclusion']}, indent=2))
