#!/usr/bin/env python3
"""Pure cloud preparation. No native calls, Git commands, or source mutation."""
from __future__ import annotations
import ast, base64, gzip, hashlib, json, os, pathlib

HERE = pathlib.Path(__file__).resolve().parent
OLD = pathlib.Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1')
GRAPH = pathlib.Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1')
OVERLAY = GRAPH
DONOR = '/home/qian-qi/hepta-utility-36fa-native-cc57-isolated-v1'
TARGET = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-isolated-materialization-v1'
STAGING_PREFIX = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-materialization-v1'
COMMIT_BINDING = json.loads((HERE / 'CANDIDATE_COMMIT_BINDING.json').read_bytes())
DEST_HEAD = COMMIT_BINDING['commit']
assert isinstance(DEST_HEAD, str) and len(DEST_HEAD) == 40 and DEST_HEAD != 'cc57c7198db6293ccca562253c42fffbe2a04633'
DEST_TREE = 'a489b394666b8141840275128a780605b024cde0'
MAX_PART = 524288

def check(value, label):
    if not value:
        raise ValueError(label)

def sha256(raw):
    return hashlib.sha256(raw).hexdigest()

def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def pin(raw):
    return {'bytes': len(raw), 'sha256': sha256(raw), 'git_blob': oid('blob', raw)}

def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()

def write(name, raw):
    with (HERE / name).open('xb') as stream:
        stream.write(raw)
    return pin(raw)

def obj(kind, raw):
    return {'type': kind, 'sha': oid(kind, raw), 'bytes': len(raw), 'sha256': sha256(raw), 'raw_base64': base64.b64encode(raw).decode()}

def project(row):
    return {'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'], 'sha256': row['sha256'], 'blob': row['working_blob']}

def native(rows):
    return json.dumps(sorted([project(row) for row in rows], key=lambda row: os.fsencode(row['path'])), sort_keys=True, separators=(',', ':')).encode()

original_source = (OLD / 'MATERIALIZER_DRIVER.original.py').read_text()
tree_node = next(node for node in ast.parse(original_source).body if isinstance(node, ast.FunctionDef) and node.name == 'tree_objects')
ns = {'check': check, 'oid': oid, 'pathlib': pathlib}
exec(compile(ast.Module(body=[tree_node], type_ignores=[]), 'original-pure-tree-function', 'exec'), ns)
tree_objects = ns['tree_objects']

seed = json.loads((OLD / 'MATERIALIZER_PACKET.original.json').read_bytes())
donor_raw = (OLD / 'CC57_INVENTORY.json').read_bytes()
donor = json.loads(donor_raw)
check(pin(donor_raw) == seed['current']['inventory'], 'actual canonical donor inventory')
check(pin(native(donor['files'])) == seed['current']['native_inventory'], 'actual original native serializer')
donor_by_path = {row['path']: row for row in donor['files']}
leaf_graph_raw = (GRAPH / 'CANDIDATE_FILE_GRAPH.json').read_bytes()
leaf_graph = json.loads(leaf_graph_raw)
check(leaf_graph['tree'] == DEST_TREE and leaf_graph['base_commit'] == seed['current']['commit'], 'Root accepted complete graph')
overlay_raw = (OVERLAY / 'EXACT_COMPOSED_OVERLAY.json').read_bytes()
overlay = json.loads(overlay_raw)
coverage = sorted(overlay['rust_files'] + overlay['non_rust_prepared'], key=lambda row: os.fsencode(row['path']))
check(len(coverage) == 119 and len({row['path'] for row in coverage}) == 119, 'exact frozen overlay coverage')
check(overlay['canonical_source_deletions'] == overlay['materializer_delete_operations'] == [], 'no canonical deletion')

rows = []
for row in leaf_graph['files']:
    check(row['mode'] in ('100644', '100755', '120000'), 'canonical modes only')
    rows.append({'bytes': row['bytes'], 'index_blob': row['git_blob'], 'index_mode': row['mode'], 'kind': row['kind'],
                 'matches_index': True, 'path': row['path'], 'permissions': {'100644': 0o644, '100755': 0o755, '120000': 0o777}[row['mode']],
                 'sha256': row['sha256'], 'stable': True, 'working_blob': row['git_blob']})
rows.sort(key=lambda row: os.fsencode(row['path']))
target_by_path = {row['path']: row for row in rows}
check(len(rows) == len(target_by_path) == 15243 and set(donor_by_path) <= set(target_by_path), 'complete expected candidate membership')
changes, provided = [], {}
for covered in coverage:
    row = target_by_path[covered['path']]
    before = donor_by_path.get(row['path'])
    body = (OVERLAY / 'overlay' / row['path']).read_bytes()
    check(pin(body) == {'bytes': covered['bytes'], 'sha256': covered['sha256'], 'git_blob': covered['git_blob']}, 'full actual prepared overlay body')
    check(project(row) == {'path': covered['path'], 'mode': covered['mode'], 'bytes': covered['bytes'], 'sha256': covered['sha256'], 'blob': covered['git_blob']}, 'graph and reviewed overlay agree')
    check((before['working_blob'] if before else None) == covered['original_git_blob'], 'exact cc57 original preimage')
    changes.append({'path': row['path'], 'before': before, 'after': row})
    if before != row:
        item = obj('blob', body)
        check(item['sha'] not in provided, 'independent changed blob identity')
        provided[item['sha']] = item
for path in set(donor_by_path) - {row['path'] for row in changes}:
    check(target_by_path[path] == donor_by_path[path], 'every uncovered canonical leaf unchanged')
check(len(provided) == 118, '118 actual changed-or-new distinct blob bodies')
target_root, target_trees = tree_objects(rows)
donor_root, donor_trees = tree_objects(donor['files'])
check(target_root == DEST_TREE and donor_root == seed['current']['tree'], 'independent exact Merkle roots')
tree_plan = json.loads((GRAPH / 'TREE_OBJECT_PLAN.json').read_bytes())
changed_trees = {key: raw for key, raw in target_trees.items() if key not in donor_trees}
check(len(changed_trees) == len(tree_plan['trees']) == 10, 'exact candidate new tree scope')
for item in tree_plan['trees']:
    raw = base64.b64decode(item['raw_base64'], validate=True)
    check(raw == changed_trees[item['sha']] and pin(raw) == item['raw'], 'complete original candidate tree body')
    given = obj('tree', raw)
    provided[given['sha']] = given
commit_raw = (HERE / 'CANDIDATE_COMMIT.raw.txt').read_bytes()
commit = obj('commit', commit_raw)
check(commit['sha'] == DEST_HEAD and pin(commit_raw) == COMMIT_BINDING['raw'], 'actual typed candidate commit bytes')
check(commit_raw.split(b'\n', 1)[0] == ('tree ' + DEST_TREE).encode() and [line[7:].decode() for line in commit_raw.split(b'\n\n', 1)[0].split(b'\n') if line.startswith(b'parent ')] == [seed['current']['commit']], 'actual tree and sole clean-donor parent')
provided[DEST_HEAD] = commit
check(len(provided) == 129, 'exact 118 blobs 10 trees one commit')
candidate_input = {'format': 'hepta-reviewed-candidate-source-object-input-v1', 'qualification': False, 'native_execution': False,
    'donor_commit': seed['current']['commit'], 'candidate_commit': DEST_HEAD, 'candidate_tree': DEST_TREE, 'candidate_parents': [seed['current']['commit']],
    'reviewed_overlay': pin(overlay_raw), 'complete_leaf_graph': pin(leaf_graph_raw), 'canonical_source_deletions': [],
    'covered_paths': changes, 'objects': [provided[key] for key in sorted(provided)]}
candidate_raw = encoded(candidate_input)
candidate_gzip = gzip.compress(candidate_raw, mtime=0)
write('CANDIDATE_OBJECT_INPUT.json', candidate_raw)
write('CANDIDATE_OBJECT_INPUT.json.gz', candidate_gzip)

parent_rows = {path: dict(row) for path, row in donor_by_path.items()}
for change in seed['parent_snapshot']['changes_from_current']:
    row = parent_rows[change['path']]
    check(row['working_blob'] == change['current']['git_blob'], 'original parent delta preimage')
    row.update(index_blob=change['parent']['git_blob'], working_blob=change['parent']['git_blob'], bytes=change['parent']['bytes'], sha256=change['parent']['sha256'])
parent_root, parent_trees = tree_objects(list(parent_rows.values()))
check(parent_root == seed['parent_snapshot']['tree'], 'original independent parent snapshot')
existing = {}
def add_object(key, meta, label):
    check(key not in existing or existing[key] == meta, 'object collision: ' + label)
    existing[key] = meta
for collection in (donor['files'], list(parent_rows.values())):
    for row in collection:
        add_object(row['working_blob'], {'type': 'blob', 'bytes': row['bytes'], 'sha256': row['sha256']}, 'seed blob')
for tree_map in (donor_trees, parent_trees):
    for key, raw in tree_map.items():
        add_object(key, {'type': 'tree', 'bytes': len(raw), 'sha256': sha256(raw)}, 'seed tree')
for item in seed['raw_commits']:
    raw = base64.b64decode(item['raw_base64'], validate=True)
    check(oid('commit', raw) == item['sha'] and len(raw) == item['bytes'] and sha256(raw) == item['sha256'], 'authentic seed commit')
    add_object(item['sha'], {k: item[k] for k in ('type', 'bytes', 'sha256')}, 'seed commit')
check(len(existing) == 16449, 'actual declared donor object set')
base_raw = (OLD / 'BASE_OBJECT_INPUT.json').read_bytes()
base_gzip = (OLD / 'BASE_OBJECT_INPUT.json.gz').read_bytes()
base_input = json.loads(base_raw)
closure = json.loads((OLD / 'C0F_CLOSURE_IDENTITIES.json').read_bytes())
base_set = {row['sha'] for row in closure['objects']}
check(len(base_set) == 16094 and len(base_set & set(existing)) == 16011 and len(base_set - set(existing)) == 83, 'complete formatting-base difference')
reuse = dict(existing)
for item in base_input['objects']:
    raw = base64.b64decode(item['raw_base64'], validate=True)
    check(oid(item['type'], raw) == item['sha'] and len(raw) == item['bytes'] and sha256(raw) == item['sha256'], 'all original provided base bytes')
    check(item['sha'] not in reuse, 'base-only provided object')
    add_object(item['sha'], {k: item[k] for k in ('type', 'bytes', 'sha256')}, 'base object')
base_candidate_overlap = sorted(set(provided) & set(existing))
for key, item in provided.items():
    add_object(key, {k: item[k] for k in ('type', 'bytes', 'sha256')}, 'candidate object')
counts = {kind: sum(row['type'] == kind for row in existing.values()) for kind in ('blob', 'tree', 'commit')}
expected_inventory = {'files': rows, 'filesystem_entries': len(rows), 'schema': donor['schema'],
                      'source': {'head': DEST_HEAD, 'status': '', 'tree': DEST_TREE}, 'tracked_entries': len(rows)}
expected_inventory_raw = encoded(expected_inventory)
expected_native_raw = native(rows)
write('EXPECTED_CANDIDATE.complete.inventory.json', expected_inventory_raw)
write('EXPECTED_CANDIDATE.native-five-field.inventory.json', expected_native_raw)

stage = {}
for label, raw, packed in [('base', base_raw, base_gzip), ('candidate', candidate_raw, candidate_gzip)]:
    check(gzip.decompress(packed) == raw, 'complete bounded staging gzip')
    parts = []
    for number, offset in enumerate(range(0, len(packed), MAX_PART), 1):
        body = packed[offset:offset + MAX_PART]
        name = label.upper() + '.json.gz.part-%03d' % number
        write(name, body)
        parts.append({'path': STAGING_PREFIX + '-' + label + '.json.gz.part-%03d' % number,
                      'offset': offset, **pin(body), 'mode': 0o600})
    stage[label] = {'raw': pin(raw), 'gzip': pin(packed), 'parts': parts, 'maximum_decoded_part': MAX_PART}

materialization = json.loads((HERE / 'DONOR_RESULT.original.json').read_bytes())
metadata_raw = (HERE / 'DONOR_GIT_METADATA.recovered.json').read_bytes()
donor_metadata = json.loads(metadata_raw)
base_complete = json.loads((OLD / 'C0F_INVENTORY.json').read_bytes())
base_projection = native(base_complete['files'])
packet = {'format': 'hepta-complete-candidate-isolated-materialization-packet-v1', 'qualification': False,
    'source_repo': DONOR, 'destination_repo': TARGET,
    'donor': {**seed['current'], 'leaves': 15188, 'allowed_missing_paths': []},
    'current': {'commit': DEST_HEAD, 'tree': DEST_TREE, 'parents': [seed['current']['commit']], 'leaves': len(rows),
                'inventory': pin(expected_inventory_raw), 'native_inventory': pin(expected_native_raw)},
    'parent_snapshot': seed['parent_snapshot'], 'seed_raw_commits': seed['raw_commits'], 'original_inventory': seed['original_inventory'],
    'donor_proof': {'job_id': '1a1d2d20686-392-36', 'result': pin((HERE / 'DONOR_RESULT.original.json').read_bytes()),
                    'supervisor': pin((HERE / 'DONOR_NORMAL_SUPERVISOR.original.json').read_bytes()),
                    'current_git_state': materialization['current_git_state_after'], 'current_git_metadata': pin(metadata_raw)},
    'donor_git': {'files': donor_metadata, 'refs_base64': '',
                  'absent_lookup_paths': ['.git/packed-refs', '.git/objects/info/alternates', '.git/shallow', '.git/info/grafts', '.git/index.lock', '.git/HEAD.lock']},
    'git_tool': seed['git_tool'], 'provided_inputs': stage,
    'format_base': {**base_input['base'], 'objects': 16094, 'counts': {'blob': 14315, 'tree': 1778, 'commit': 1},
                   'provided_objects': 83, 'required_donor_objects': 16011, 'leaf_projection': pin(base_projection)},
    'object_scope': {'format': 'four-complete-snapshots-not-full-ancestry',
                    'complete_snapshot_commits': [DEST_HEAD, seed['current']['commit'], seed['parent_snapshot']['commit'], base_input['base']['commit']],
                    'reused_donor_objects': 16449, 'provided_base_objects': 83, 'provided_candidate_objects': 129,
                    'provided_base_candidate_overlap': base_candidate_overlap,
                    'union_objects': len(existing), 'counts': counts,
                    'unmaterialized_parent_boundaries': ['9c4a11f61d30e9cc352bf44d56c98909d202a55d', *base_input['base']['parents']],
                    'no_network': True, 'no_fsck': True, 'no_recursive_ancestor_walk': True},
    'overlay': {'identity': pin(overlay_raw), 'covered_paths': 119, 'new_paths': 55, 'modified_paths': 63, 'unchanged_covered_paths': 1,
                'canonical_source_deletions': [], 'rust_under_codex_rs': 6672, 'rust_all_repository': 6794},
    'expected_not_native_observed': True}
packet_identity = write('MATERIALIZATION_PACKET.HOLD.json', encoded(packet))
write('EXPECTED_OBJECT_IDENTITIES.json', encoded([{'sha': key, **existing[key]} for key in sorted(existing)]))
write('EXPECTED_DONOR_OBJECT_IDENTITIES.json', encoded([{'sha': key, **reuse[key]} for key in sorted(reuse)]))
summary = {'status': 'HOLD_NOT_EXECUTED', 'packet': packet_identity, 'provided_inputs': stage,
    'expected_candidate_inventory': pin(expected_inventory_raw), 'expected_candidate_native_projection': pin(expected_native_raw),
    'candidate_objects': len(provided), 'base_candidate_overlap': base_candidate_overlap,
    'union_objects': len(existing), 'counts': counts, 'donor_objects_full_body_read_required': 16449,
    'original_action_seconds': 600, 'original_record_seconds': 180, 'original_outer_seconds': 900,
    'typed_main_not_yet_sealed': True, 'expected_source_is_not_actual_materialization': True,
    'all_staged_parts_decoded_le_524288': all(part['bytes'] <= MAX_PART for row in stage.values() for part in row['parts']),
    'complete_inputs_cannot_be_inlined_in_one_original_stdin': sum(len(base64.b64encode(body)) for body in (base_gzip, candidate_gzip)) > 1048576}
write('INPUT_PREPARATION_REVIEW.json', encoded(summary))
print(json.dumps(summary, sort_keys=True))
