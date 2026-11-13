#!/usr/bin/env python3
"""Compose exact source content and a mode-aware graph; no source Git writes."""
import ast
import base64
from collections import Counter
import copy
import gzip
import hashlib
import json
from pathlib import Path

R = Path(__file__).resolve().parent
OLD = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
CANONICAL = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/CC57_INVENTORY.json')
ACTUAL = Path('/tmp/hepta-36fa-provider-0c59-finalfmt-inventory-recovery-v1')
ORIGINAL_OVERLAY = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1')
FMT = Path('/tmp/hepta-36fa-provider-0c59-fix101-apply-fmt-runtime-v1/fmt.after.postimages.json')
WITNESS = Path('/tmp/hepta-36fa-provider-0c59-maintenance-runtime-v1/final.postimages.json')
PACKETS = [
    ('coordinator-actual-format-rebase', Path('/tmp/hepta-36fa-coordinator-f905-preparation-v1/SOURCE_PACKET.json'), '773d67128190fd2e1c3271c372f72e2a5537d1e8'),
    ('coordinator-original-metadata-getters', Path('/tmp/hepta-36fa-coordinator-original-metadata-getters-v1/SOURCE_PACKET.json'), '5279a43b99aa7031343578a21dba895f5eac3188'),
    ('actual-format-coordinator-registration', Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1/SOURCE_PACKET.json'), 'e01b6c1689e1d834701a0d4565c5da662936ea80'),
]
CC57 = 'cc57c7198db6293ccca562253c42fffbe2a04633'
BASE_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
F905 = 'f905b18e6b05de1582024548179725a05d932536'


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def dump(value, compact=False):
    if compact:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def save(name, value, compact=False):
    raw = value if isinstance(value, bytes) else dump(value, compact)
    path = R / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), **pin(raw)}


def file_rows(inventory):
    result = {}
    for row in inventory['files']:
        path = row['path']
        assert path not in result
        mode = row['index_mode']
        assert mode in ('100644', '100755', '120000')
        assert mode == ('120000' if row['kind'] == 'symlink' else '100755' if row['permissions'] & 0o111 else '100644')
        assert row['stable'] is True
        result[path] = {'path': path, 'mode': mode, 'kind': row['kind'],
                        'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']}
    return result


def row_pin(row):
    return {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}


# Preserve the already archived mode-aware Git algorithm verbatim by extracting
# its pure functions, not importing its executable preparation module.
old_algorithm = (OLD / 'derive_graph.py').read_text()
names = {'oid', 'safe_parts', 'merkle', 'tree_identity', 'counts'}
nodes = [node for node in ast.parse(old_algorithm).body if isinstance(node, ast.FunctionDef) and node.name in names]
assert {node.name for node in nodes} == names
environment = {'hashlib': hashlib, 'Counter': Counter}
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'original_archived_mode_aware_functions_only', 'exec'), environment)
merkle, counts = environment['merkle'], environment['counts']

canonical_raw = CANONICAL.read_bytes()
assert pin(canonical_raw) == {'bytes': 5611184, 'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
                              'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}
canonical = json.loads(canonical_raw)
assert canonical['source'] == {'head': CC57, 'tree': BASE_TREE, 'status': ''}
assert all(row['matches_index'] is True and row['index_blob'] == row['working_blob'] for row in canonical['files'])
base = file_rows(canonical)
base_trees = merkle(base)
assert base_trees['']['sha'] == BASE_TREE and len(base) == 15188

actual_raw = (ACTUAL / 'final.inventory.exact_recovered.json').read_bytes()
assert pin(actual_raw) == {'bytes': 5634549, 'sha256': 'bc6b9d59143004236665bb9446e2c45d1ac77cd7aaba14ba7cee8f4ea76d003f',
                           'git_blob': 'e1e48f35bb6cf5a3dd86c59472da77df87154b6a'}
actual = json.loads(actual_raw)
assert actual['source']['head'] == '0c59aaca0b4932507f068c723f73da2f96729b3d'
assert actual['source']['tree'] == '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
current = file_rows(actual)
actual_trees = merkle(current)
assert actual_trees['']['sha'] == F905 and len(current) == 15237
zero = json.loads((OLD / 'CANDIDATE_FILE_GRAPH.json').read_bytes())
zero_rows = {row['path']: row for row in zero['files']}
assert merkle(zero_rows)['']['sha'] == actual['source']['tree']
assert set(current) == set(zero_rows)
actual_changes = {path for path in current if current[path] != zero_rows[path]}
assert len(actual_changes) == 63
assert all(row['index_mode'] == zero_rows[row['path']]['mode'] and row['index_blob'] == zero_rows[row['path']]['git_blob'] for row in actual['files'])

overlay_raw = (ORIGINAL_OVERLAY / 'EXACT_COMPOSED_OVERLAY.json').read_bytes()
assert pin(overlay_raw)['git_blob'] == '148e9efc242f3ee3ee4e525281ec170feecf3f19'
old_overlay = json.loads(overlay_raw)
assert old_overlay['canonical_source_deletions'] == []
pool = {}
provenance = {}
for item in old_overlay['rust_files'] + old_overlay['non_rust_prepared']:
    path = item['path']
    raw = (ORIGINAL_OVERLAY / 'overlay' / path).read_bytes()
    assert pin(raw) == row_pin(item) == row_pin(zero_rows[path])
    pool[path] = raw
    provenance[path] = ['exact original 0c59 source overlay 148e9efc242f3ee3ee4e525281ec170feecf3f19']
assert len(pool) == 110

assert pin(FMT.read_bytes())['git_blob'] == '43f7dd7eaa1578a4d6d570252939084f80181685'
formatter = json.loads(FMT.read_bytes())
assert len(formatter['changes']) == 62
assert len(json.loads(WITNESS.read_bytes())['changes']) == 1
observed_raw_paths = set()
for name, packet in (('actual fix101 retained witness', json.loads(WITNESS.read_bytes())),
                     ('actual normal0 fmt900 afterimage', formatter)):
    for change in packet['changes']:
        path = change['path']
        raw = base64.b64decode(change['after_raw_base64'], validate=True)
        assert pin(raw) == row_pin(current[path])
        assert path not in observed_raw_paths
        observed_raw_paths.add(path)
        pool[path] = raw
        provenance.setdefault(path, []).append(name)
assert observed_raw_paths == actual_changes
for path, raw in pool.items():
    assert pin(raw) == row_pin(current[path])

prepared = copy.deepcopy(current)
layer_records = []
for name, packet_path, expected in PACKETS:
    raw = packet_path.read_bytes()
    assert pin(raw)['git_blob'] == expected
    packet = json.loads(raw)
    touched = []
    for change in packet['source_changes']:
        path = change['path']
        before = base64.b64decode(change['before_base64'], validate=True) if change['before'] else None
        after = base64.b64decode(change['after_base64'], validate=True)
        assert before is None or pin(before) == change['before']
        assert pin(after) == change['after']
        if before is None:
            assert path not in prepared
        else:
            assert path in prepared and row_pin(prepared[path]) == pin(before)
            if path in pool:
                assert pool[path] == before
        assert change['mode'] == '100644'
        prepared[path] = {'path': path, 'mode': change['mode'], 'kind': 'file', **pin(after)}
        pool[path] = after
        provenance.setdefault(path, []).append(name + ' / ' + expected)
        touched.append(path)
    computed = merkle(prepared)['']['sha']
    if 'expected_after_physical_tree' in packet:
        assert packet['expected_after_physical_tree'] == computed
    layer_records.append({'name': name, 'packet': pin(raw), 'path': str(packet_path), 'changed_paths': touched,
                           'resulting_expected_tree': computed, 'resulting_expected_leaf_count': len(prepared)})
assert len(prepared) == 15243
final_trees = merkle(prepared)
tree = final_trees['']['sha']
assert tree == 'a489b394666b8141840275128a780605b024cde0'
assert set(base) <= set(prepared) and set(current) <= set(prepared)
obsolete = 'codex-rs/hepta-agentd/src/cell_q24_training_shared_readback_test_support.rs'
assert obsolete not in base and obsolete not in current and obsolete not in prepared

updates_cc57, updates_f905 = [], []
for label, old, destination in (('cc57 canonical', base, updates_cc57), ('actual f905', current, updates_f905)):
    for path, after in sorted(prepared.items(), key=lambda item: item[0].encode()):
        before = old.get(path)
        if before == after:
            continue
        if before is not None:
            assert before['mode'] == after['mode']
        else:
            assert after['mode'] == '100644'
        assert path in pool and pin(pool[path]) == row_pin(after)
        destination.append({'path': path, 'change': 'modified' if before else 'added',
                            'before': before, 'after': after, 'local_source': str(R / 'overlay' / path)})
assert len(updates_f905) == 16
assert all(prepared[path] == before for path, before in base.items() if path not in {row['path'] for row in updates_cc57})
assert {row['path'] for row in updates_cc57} <= set(pool)

coverage = []
for path, raw in sorted(pool.items(), key=lambda item: item[0].encode()):
    row = prepared[path]
    assert row_pin(row) == pin(raw)
    assert row['mode'] == '100644'
    target_info = save('overlay/' + path, raw)
    before = base.get(path)
    coverage.append({**row, 'original_git_blob': before['git_blob'] if before else None,
                     'classification_from_cc57': 'added' if before is None else 'unchanged_original' if before == row else 'modified',
                     'last_layer': provenance[path][-1], 'ordered_provenance': provenance[path],
                     'local_source': target_info['path']})
final_counts = counts(prepared)
overlay = {'format': 'hepta-exact-complete-coordinator-registered-overlay-v1',
    'status': 'PREPARED_NOT_QUALIFIED_REGISTRATION_INDEPENDENT_REVIEW_PENDING',
    'source_commit': CC57, 'source_tree': BASE_TREE, 'source_commit_or_ref_created': False,
    'expected_tree': tree, 'full_repository_expected_counts': final_counts,
    'base_actual_working_source': actual['source'], 'base_actual_working_tree': F905,
    'actual_final_inventory': pin(actual_raw), 'original_complete_cc57_inventory': pin(canonical_raw),
    'root_required_new_commit_sole_parent': CC57, 'new_commit_identity': None,
    'canonical_source_deletions': [], 'materializer_delete_operations': [],
    'historical_candidate_only_exclusion': {'path': obsolete, 'present_in_cc57': False, 'canonical_deletion': False},
    'base_overlay': pin(overlay_raw), 'actual_retained_witness_packet': pin(WITNESS.read_bytes()),
    'actual_fmt62_packet': pin(FMT.read_bytes()), 'appended_layers': layer_records,
    'rust_files': [row for row in coverage if row['path'].endswith('.rs')],
    'non_rust_prepared': [row for row in coverage if not row['path'].endswith('.rs')],
    'total_covered_paths': len(coverage), 'actual_updates_from_cc57': len(updates_cc57),
    'actual_updates_from_f905': len(updates_f905), 'local_overlay_directory': str(R / 'overlay'),
    'prepared_source_bytes_all_locally_verified': True, 'all_other_source_graph_rows_unchanged': True,
    'runtime_materialized': False, 'formatter_compiler_qa_full_collector_native_executions': 0,
    'prior_fix101_remains_failed': True, 'real_task_chain_results': 0,
    'production_root_startup_wiring_completed': False,
    'limits': ['Complete file counts and mode-aware hashes are expected projections, not observations from a new materialization.',
        'Registration peer approval and Root exact source commit/materializer/maintenance/gates remain separate.',
        'Twelve new coordinator APIs still have no non-test caller; the new local custody mechanism is not a complete deployed Root path.',
        'RootSession timeout or outer cancellation does not prove worker join; cold cases are same-process existing-state reopen mechanisms.',
        'The prior fix101 failure and actual f905 bytes remain intact; no previous test result qualifies this candidate.']}
overlay_info = save('EXACT_COMPOSED_OVERLAY.json', overlay)
graph = {'format': 'hepta-complete-mode-aware-file-graph-v1', 'status': 'Expected source graph only; no new materialization or qualification',
    'base_commit': CC57, 'base_tree': BASE_TREE, 'tree': tree, 'candidate_commit': None,
    'actual_starting_working_tree': F905, 'overlay_map': overlay_info['git_blob'],
    'canonical_source_deletions': [], 'counts': final_counts,
    'files': [row for _, row in sorted(prepared.items(), key=lambda item: item[0].encode())]}
graph_info = save('CANDIDATE_FILE_GRAPH.json', graph, compact=True)
updates_base_info = save('EXACT_UPDATE_ENTRIES_CC57.json', updates_cc57)
updates_actual_info = save('EXACT_UPDATE_ENTRIES_F905.json', updates_f905)

changed_dirs = [path for path in final_trees if path not in base_trees or final_trees[path]['sha'] != base_trees[path]['sha']]
changed_dirs.sort(key=lambda value: (value.count('/') + bool(value), value.encode()), reverse=True)
plan = {'format': 'hepta-mode-aware-content-tree-plan-v1', 'status': 'PURE_EXPECTED_PLAN_NO_SOURCE_TREE_CREATED',
    'base_commit': CC57, 'base_tree': BASE_TREE, 'expected_tree': tree, 'expected_file_count': len(prepared),
    'blob_updates': [{'path': row['path'], 'mode': row['after']['mode'], 'type': 'blob', 'sha': row['after']['git_blob']} for row in updates_cc57],
    'trees': [{'directory': path, 'base_tree': base_trees[path]['sha'] if path in base_trees else None,
               'sha': final_trees[path]['sha'], 'raw': pin(final_trees[path]['raw']),
               'raw_base64': base64.b64encode(final_trees[path]['raw']).decode(),
               'entries': final_trees[path]['entries']} for path in changed_dirs],
    'canonical_source_deletions': [], 'git_tree_commit_or_ref_created': False}
plan_info = save('TREE_OBJECT_PLAN.json', plan)
summary = {'format': 'hepta-final-coordinator-source-graph-review-v1', 'status': 'PURE_COMPOSITION_NOT_QUALIFIED',
    'cc57_inventory': pin(canonical_raw), 'cc57_exact_merkle': base_trees['']['sha'],
    'actual_f905_inventory': pin(actual_raw), 'actual_f905_exact_merkle': actual_trees['']['sha'],
    'original_0c59_tree': merkle(zero_rows)['']['sha'], 'actual_dirty_paths_vs_0c59': len(actual_changes),
    'layers': layer_records, 'final_expected_tree': tree, 'final_expected_counts': final_counts,
    'overlay_paths': len(coverage), 'overlay_rust_paths': len(overlay['rust_files']),
    'overlay_non_rust_paths': len(overlay['non_rust_prepared']),
    'changes_vs_cc57': dict(Counter(row['change'] for row in updates_cc57)),
    'changes_vs_f905': dict(Counter(row['change'] for row in updates_f905)),
    'covered_unchanged_original_paths': [row['path'] for row in coverage if row['classification_from_cc57'] == 'unchanged_original'],
    'changed_directory_trees_vs_cc57': len(changed_dirs), 'unchanged_directory_trees': len(final_trees) - len(changed_dirs),
    'mode_changes': [], 'canonical_source_deletions': [], 'historical_only_exclusion_is_not_deletion': True,
    'all_overlay_bytes_match_complete_graph_pins': True, 'all_other_full_source_rows_preserved': True,
    'complete_file_graph': graph_info, 'overlay': overlay_info,
    'exact_updates_cc57': updates_base_info, 'exact_updates_actual_f905': updates_actual_info,
    'tree_object_plan': plan_info, 'source_commit_or_ref_writes': 0, 'native_or_test_calls': 0,
    'algorithm': {'original_archived_source': pin((OLD / 'derive_graph.py').read_bytes()),
                  'pure_functions_verbatim': sorted(names), 'no_import_of_executable_original_module': True},
    'registration_peer': 'pending; any correction must be a separate immutable successor',
    'real_authorized_task_chain_results': 0}
review_info = save('REVIEW.json', summary)

bundles = []
for name in ('CANDIDATE_FILE_GRAPH.json', 'TREE_OBJECT_PLAN.json'):
    raw = (R / name).read_bytes()
    zipped = gzip.compress(raw, compresslevel=9, mtime=0)
    zip_info = save(name + '.gz', zipped)
    parts = []
    for number, offset in enumerate(range(0, len(zipped), 307200), 1):
        body = zipped[offset:offset + 307200]
        encoded = base64.b64encode(body)
        assert len(encoded) <= 512000
        part_info = save(name + f'.gz.part-{number:03d}.b64', encoded)
        parts.append({**part_info, 'decoded_offset': offset, 'decoded': pin(body)})
    assert gzip.decompress(b''.join(base64.b64decode(Path(p['path']).read_bytes(), validate=True) for p in parts)) == raw
    bundles.append({'name': name, 'raw': pin(raw), 'gzip': zip_info, 'parts': parts})
manifest = {'format': 'hepta-final-coordinator-composition-manifest-v1', 'status': 'HOLD_NOT_QUALIFIED',
    'review': review_info, 'overlay': overlay_info, 'graph': graph_info, 'tree_plan': plan_info,
    'updates_cc57': updates_base_info, 'updates_f905': updates_actual_info, 'bundles': bundles,
    'source_commit_or_ref_created': False, 'parent_required_for_future_commit': CC57,
    'source_commit': None, 'expected_tree': tree, 'expected_counts': final_counts}
manifest_info = save('MANIFEST.json', manifest)
print(json.dumps({'manifest': manifest_info, 'overlay': overlay_info, 'review': review_info,
                  'graph': graph_info, 'expected_tree': tree, 'counts': final_counts,
                  'coverage': {'total': len(coverage), 'rust': len(overlay['rust_files']), 'non_rust': len(overlay['non_rust_prepared'])},
                  'updates_cc57': len(updates_cc57), 'updates_f905': len(updates_f905),
                  'changed_directory_trees': len(changed_dirs)}, indent=2))
