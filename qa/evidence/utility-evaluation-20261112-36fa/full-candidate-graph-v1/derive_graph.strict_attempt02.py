"""Pure mode-aware source graph projection; never writes a Git source object."""
from pathlib import Path
from collections import Counter
import base64
import gzip
import hashlib
import json
import subprocess

OUT = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
RECOVERED = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1')
COMPOSED = Path('/tmp/hepta-36fa-at-b-composed-candidate-v1')
COMMIT = 'cc57c7198db6293ccca562253c42fffbe2a04633'
BASE_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
PARTS = [
    '3d7016ec9824f833325aefe36517e150b51bbefc',
    '37139c2012d11d52b053c23e576d1babd9873285',
    '73dd2bebeb79ab5d4f18cc78e3bfafb2e64e3376',
    '2b3f0fb42a5c8c5a555f57aa9f6fbdd378e933d6',
    '1126a55286a4124acf5f634fe1ef1adc700d62f9',
]
RAW_PIN = {'bytes': 5611184,
           'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
           'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}
OVERLAY_PIN = '148e9efc242f3ee3ee4e525281ec170feecf3f19'


def oid(kind, body):
    return hashlib.sha1(kind.encode() + b' ' + str(len(body)).encode() + b'\0' + body).hexdigest()


def pin(body):
    return {'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            'git_blob': oid('blob', body)}


def encoded_json(value, compact=False):
    if compact:
        return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def write(name, value, compact=False):
    path = OUT / name
    assert not path.exists(), f'create-only output: {path}'
    path.parent.mkdir(parents=True, exist_ok=True)
    body = value if isinstance(value, bytes) else encoded_json(value, compact)
    path.write_bytes(body)
    return pin(body)


def safe_parts(path):
    parts = path.split('/')
    assert path and not path.startswith('/') and all(part not in ('', '.', '..') for part in parts)
    assert '\0' not in path
    path.encode('utf-8')
    return parts


def merkle(files):
    """Git's raw tree modes and basename ordering, including directory '/'."""
    directories = {'': {}}
    for path, row in files.items():
        parts = safe_parts(path)
        parent = ''
        for component in parts[:-1]:
            child = parent + '/' + component if parent else component
            entry = {'path': component, 'mode': '040000', 'type': 'tree', 'directory': child}
            prior = directories[parent].get(component)
            assert prior in (None, entry), (path, component, 'file/directory collision')
            directories[parent][component] = entry
            directories.setdefault(child, {})
            parent = child
        assert parts[-1] not in directories[parent], path
        directories[parent][parts[-1]] = {'path': parts[-1], 'mode': row['mode'],
                                         'type': 'blob', 'sha': row['git_blob']}
    trees = {}
    # Descendants must be constructed before their parent. Root is last.
    for path in sorted(directories, key=lambda item: (item.count('/') + bool(item), item.encode()), reverse=True):
        entries = []
        for stored in directories[path].values():
            entry = dict(stored)
            if entry['type'] == 'tree':
                entry['sha'] = trees[entry.pop('directory')]['sha']
            entries.append(entry)
        entries.sort(key=lambda entry: entry['path'].encode() + (b'/' if entry['type'] == 'tree' else b'\0'))
        raw = b''.join(entry['mode'].lstrip('0').encode() + b' ' + entry['path'].encode() + b'\0'
                       + bytes.fromhex(entry['sha']) for entry in entries)
        trees[path] = {'sha': oid('tree', raw), 'raw': raw, 'entries': entries}
    return trees


def tree_identity(path, tree):
    return {'path': path, 'git_tree': tree['sha'], 'raw_bytes': len(tree['raw']),
            'raw_sha256': hashlib.sha256(tree['raw']).hexdigest(), 'immediate_entries': len(tree['entries'])}


def counts(files):
    rows = list(files.values())
    return {'files': len(rows),
            'rust_all_repository': sum(row['path'].endswith('.rs') for row in rows),
            'rust_under_codex_rs': sum(row['path'].startswith('codex-rs/') and row['path'].endswith('.rs') for row in rows),
            'rust_outside_codex_rs': sum(not row['path'].startswith('codex-rs/') and row['path'].endswith('.rs') for row in rows),
            'modes': dict(sorted(Counter(row['mode'] for row in rows).items())),
            'kinds': dict(sorted(Counter(row['kind'] for row in rows).items())),
            'unique_blob_objects': len({row['git_blob'] for row in rows})}


assert not (OUT / 'GRAPH_REVIEW.json').exists(), 'Keep any frozen prior result intact'
OUT.mkdir(parents=True, exist_ok=True)
manifest_bytes = (RECOVERED / 'CC57_INVENTORY_MANIFEST.json').read_bytes()
manifest = json.loads(manifest_bytes)
assert [part['git_blob'] for part in manifest['parts']] == PARTS
compressed_parts, part_proof = [], []
offset = 0
for index, expected in enumerate(manifest['parts']):
    path = RECOVERED / f'c0f_compare_cc57_part_{index}.b64'
    sdk_path = RECOVERED / f'c0f_compare_cc57_part_{index}.GITHUB_GET.original.json'
    encoded = path.read_bytes()
    assert pin(encoded) == {key: expected[key] for key in ('bytes', 'sha256', 'git_blob')}
    assert encoded.endswith(b'\n')
    decoded = base64.b64decode(encoded[:-1], validate=True)
    assert base64.b64encode(decoded) + b'\n' == encoded
    assert expected['decoded_offset'] == offset
    assert expected['decoded_bytes'] == len(decoded)
    assert expected['decoded_sha256'] == hashlib.sha256(decoded).hexdigest()
    sdk_bytes = sdk_path.read_bytes()
    sdk = json.loads(sdk_bytes)
    assert sdk.get('isError') is not True
    assert sdk['structuredContent']['content'].encode() == encoded
    compressed_parts.append(decoded)
    part_proof.append({'local_part': str(path), **pin(encoded),
                       'decoded_offset': offset, 'decoded_bytes': len(decoded),
                       'decoded_sha256': hashlib.sha256(decoded).hexdigest(),
                       'prior_full_GET_SDK': {'path': str(sdk_path), **pin(sdk_bytes)},
                       'prior_GET_content_exactly_equals_local_part': True})
    offset += len(decoded)
compressed = b''.join(compressed_parts)
assert pin(compressed) == {key: manifest[key] for key in ('bytes', 'sha256', 'git_blob')}
assert compressed == (RECOVERED / 'CC57_INVENTORY.json.gz').read_bytes()
raw = gzip.decompress(compressed)
assert pin(raw) == RAW_PIN
assert raw == (RECOVERED / 'CC57_INVENTORY.json').read_bytes()
inventory = json.loads(raw)
assert inventory['source'] == {'head': COMMIT, 'status': '', 'tree': BASE_TREE}
assert inventory['tracked_entries'] == inventory['filesystem_entries'] == len(inventory['files'])

before = {}
for row in inventory['files']:
    path = row['path']
    safe_parts(path)
    assert path not in before
    assert row['stable'] is True and row['matches_index'] is True
    assert row['index_blob'] == row['working_blob']
    mode = row['index_mode']
    assert mode in ('100644', '100755', '120000')
    inferred = '120000' if row['kind'] == 'symlink' else ('100755' if row['permissions'] & 0o111 else '100644')
    assert inferred == mode
    assert (mode == '120000') == (row['kind'] == 'symlink')
    before[path] = {'path': path, 'mode': mode, 'git_blob': row['working_blob'],
                    'bytes': row['bytes'], 'sha256': row['sha256'], 'kind': row['kind']}

base_trees = merkle(before)
assert base_trees['']['sha'] == BASE_TREE, base_trees['']['sha']
overlay_bytes = (COMPOSED / 'EXACT_COMPOSED_OVERLAY.json').read_bytes()
assert pin(overlay_bytes)['git_blob'] == OVERLAY_PIN
overlay = json.loads(overlay_bytes)
assert overlay['source_commit'] == COMMIT and overlay['source_tree'] == BASE_TREE
assert overlay['canonical_source_deletions'] == [] and overlay['materializer_delete_operations'] == []
covered = overlay['rust_files'] + overlay['non_rust_prepared']
assert len({row['path'] for row in covered}) == len(covered)
after = {path: dict(row) for path, row in before.items()}
update_rows, unchanged_rows = [], []
for row in covered:
    path = row['path']
    safe_parts(path)
    source = Path(overlay['local_overlay_directory']) / path
    assert not source.is_symlink() and source.is_file()
    body = source.read_bytes()
    assert pin(body) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
    old = before.get(path)
    assert row['original_git_blob'] == (old['git_blob'] if old else None)
    if old:
        assert row['mode'] == old['mode'], 'Refuse an unapproved executable/symlink mode change'
    else:
        assert row['mode'] == '100644'
    new = {'path': path, 'mode': row['mode'], 'git_blob': row['git_blob'],
           'bytes': row['bytes'], 'sha256': row['sha256'], 'kind': 'file'}
    after[path] = new
    if old == new:
        unchanged_rows.append({'path': path, 'identity': new, 'reason': 'Covered exact original; no tree update required'})
    else:
        update_rows.append({'path': path, 'change': 'modified' if old else 'added', 'before': old, 'after': new})
for removed in overlay['historical_candidate_removals']:
    assert removed not in before and removed not in after
assert all(after[path] == row for path, row in before.items() if path not in {item['path'] for item in update_rows})
candidate_trees = merkle(after)
changed_directories = [path for path in candidate_trees if path not in base_trees or candidate_trees[path]['sha'] != base_trees[path]['sha']]
changed_directories.sort(key=lambda item: (item.count('/') + bool(item), item.encode()), reverse=True)
unchanged_directories = [path for path in candidate_trees if path in base_trees and candidate_trees[path]['sha'] == base_trees[path]['sha']]

# Independent Git hashing only. No -w, mktree, update-index, commit or refs.
hash_checks = []
to_check = [('base', '', base_trees[''])] + [('candidate', path, candidate_trees[path]) for path in changed_directories]
for label, path, tree in to_check:
    argv = ['git', '--no-optional-locks', 'hash-object', '-t', 'tree', '--stdin']
    result = subprocess.run(argv, input=tree['raw'], capture_output=True, cwd=OUT)
    if result.returncode != 0:
        diagnostic = {'graph': label, 'path': path, 'argv': argv,
                      'returncode': result.returncode, 'stdout': result.stdout.decode(errors='replace'),
                      'stderr': result.stderr.decode(errors='replace'),
                      'tree': tree['sha'], 'raw_bytes': len(tree['raw']),
                      'candidate_root_computed': candidate_trees['']['sha'],
                      'base_counts': counts(before), 'candidate_counts': counts(after),
                      'source_objects_or_refs_written': False}
        (OUT / 'STRICT_GIT_HASH_DIAGNOSTIC.json').write_bytes(encoded_json(diagnostic))
        print(json.dumps(diagnostic, indent=2))
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    observed = result.stdout.decode().strip()
    assert observed == tree['sha']
    hash_checks.append({'graph': label, 'path': path, 'argv': argv, 'returncode': 0,
                        'stdout': observed, 'expected': tree['sha'], 'writes_git_object': False})

before_count, after_count = counts(before), counts(after)
source_recovery = {
    'format': 'hepta-exact-canonical-inventory-reuse-v1',
    'source': 'Reused already-recovered canonical bytes and prior full Git GET SDKs; reconstructed the same five compressed parts locally. No new native read and no repeat part download.',
    'reused_raw_path': str(RECOVERED / 'CC57_INVENTORY.json'),
    'raw': pin(raw), 'gzip': pin(compressed), 'manifest': pin(manifest_bytes),
    'parts': part_proof, 'source_identity': inventory['source'],
    'raw_exactly_equal_reused_original': True, 'gzip_exactly_equal_reused_original': True,
    'base_graph_root_recomputed': base_trees['']['sha'], 'qualification': False,
}
write('INPUT_RECOVERY_PROOF.json', source_recovery)
write('inputs/CC57_INVENTORY.exact.json', raw)
write('inputs/COMPOSED_110_MAP.exact.json', overlay_bytes)
write('BASE_FILE_GRAPH.json', {'format': 'hepta-complete-mode-aware-file-graph-v1',
    'source_commit': COMMIT, 'tree': BASE_TREE, 'counts': before_count,
    'files': [before[path] for path in sorted(before, key=lambda item: item.encode())]}, compact=True)
write('CANDIDATE_FILE_GRAPH.json', {'format': 'hepta-complete-mode-aware-file-graph-v1',
    'status': 'Expected source graph only; not materialized, formatted, compiled, executed or qualified',
    'base_commit': COMMIT, 'base_tree': BASE_TREE, 'overlay_map': OVERLAY_PIN,
    'tree': candidate_trees['']['sha'], 'counts': after_count, 'canonical_source_deletions': [],
    'files': [after[path] for path in sorted(after, key=lambda item: item.encode())]}, compact=True)
write('TREE_IDENTITIES.json', {
    'format': 'hepta-complete-mode-aware-tree-identities-v1',
    'base': [tree_identity(path, base_trees[path]) for path in sorted(base_trees)],
    'candidate': [tree_identity(path, candidate_trees[path]) for path in sorted(candidate_trees)],
    'changed_directory_paths': changed_directories,
    'unchanged_directory_paths': unchanged_directories,
}, compact=True)
api_updates = [{'path': item['path'], 'mode': item['after']['mode'], 'type': 'blob', 'sha': item['after']['git_blob']}
               for item in sorted(update_rows, key=lambda item: item['path'].encode())]
write('EXACT_UPDATE_ENTRIES.json', {
    'format': 'hepta-exact-source-update-entries-plan-v1', 'status': 'PLAN_ONLY_DO_NOT_EXECUTE',
    'base_tree': BASE_TREE, 'expected_after_tree': candidate_trees['']['sha'],
    'tree': api_updates, 'deletions': [], 'changes': update_rows, 'covered_unchanged': unchanged_rows,
})
tree_plan = []
for path in changed_directories:
    tree = candidate_trees[path]
    before_tree = base_trees.get(path)
    tree_plan.append({'path': path, 'expected_git_tree': tree['sha'],
        'base_git_tree': before_tree['sha'] if before_tree else None,
        'raw_bytes': len(tree['raw']), 'raw_sha256': hashlib.sha256(tree['raw']).hexdigest(),
        'raw_base64': base64.b64encode(tree['raw']).decode(), 'full_immediate_entries': tree['entries']})
write('TREE_OBJECT_PLAN.json', {
    'format': 'hepta-mode-aware-tree-object-plan-v1', 'status': 'PLAN_ONLY_NO_SOURCE_OBJECT_CREATED',
    'base_root': BASE_TREE, 'expected_root': candidate_trees['']['sha'],
    'creation_order': 'Bottom-up; every row has the full immediate tree entries and exact raw body',
    'objects': tree_plan, 'source_tree_create_calls': 0, 'source_commit_create_calls': 0, 'ref_updates': 0,
}, compact=True)
all_base_blobs = {row['git_blob'] for row in before.values()}
changed_blob_rows = {item['after']['git_blob']: item['after'] for item in update_rows}
write('BLOB_REUSE_PLAN.json', {
    'format': 'hepta-existing-source-blob-reuse-plan-v1',
    'actual_prior_full_readback': '106e4ed2e978b7eb2fb39696678c675a74a0f62e',
    'meaning': 'All final overlay blobs already had complete Git GETs. This plan does not create source blobs or infer native qualification.',
    'changed_or_new_path_count': len(update_rows), 'unique_after_blob_count': len(changed_blob_rows),
    'after_blobs_already_in_base_graph': sum(sha in all_base_blobs for sha in changed_blob_rows),
    'after_blobs_not_in_base_graph': sum(sha not in all_base_blobs for sha in changed_blob_rows),
    'objects': [changed_blob_rows[sha] for sha in sorted(changed_blob_rows)],
})
write('GIT_HASH_CROSSCHECK.json', {'scope': 'Pure git hash-object without -w; no objects or repository metadata written',
                                'checks': hash_checks})
mode_sensitive = [row for row in before.values() if row['mode'] != '100644']
assert all(after[row['path']] == row for row in mode_sensitive)
review = {
    'format': 'hepta-complete-candidate-source-graph-review-v1',
    'qualification': False, 'real_qualified_task_chains': 0,
    'base_commit': COMMIT, 'base_root_expected': BASE_TREE, 'base_root_recomputed': base_trees['']['sha'],
    'candidate_root_expected': candidate_trees['']['sha'], 'overlay_map': OVERLAY_PIN,
    'base': before_count, 'candidate': after_count,
    'overlay_coverage': len(covered), 'actual_modified_paths': sum(item['change'] == 'modified' for item in update_rows),
    'actual_added_paths': sum(item['change'] == 'added' for item in update_rows),
    'actual_removed_paths': 0, 'covered_unchanged_original_paths': len(unchanged_rows),
    'unchanged_canonical_paths': sum(path in before and row == before[path] for path, row in after.items()),
    'base_directory_paths': len(base_trees), 'candidate_directory_paths': len(candidate_trees),
    'base_unique_tree_objects': len({tree['sha'] for tree in base_trees.values()}),
    'candidate_unique_tree_objects': len({tree['sha'] for tree in candidate_trees.values()}),
    'changed_directory_paths': changed_directories, 'changed_tree_objects': len({candidate_trees[path]['sha'] for path in changed_directories}),
    'unchanged_directory_paths': len(unchanged_directories),
    'all_executable_and_symlink_rows_exactly_preserved': True,
    'mode_sensitive_rows': mode_sensitive,
    'old_prepared_helper_absent_from_both_graphs': True,
    'canonical_source_deletions': [], 'materializer_delete_operations': [],
    'full_graph_counts_are_expected_not_physical_native_observation': True,
    'whole_repository_rust_count_is_distinct_from_codex_rs_collector_scope': True,
    'source_trees_or_commits_created': False, 'refs_changed': False,
    'H_format_compile_or_QA_executed': False,
    'input_recovery_proof': pin((OUT / 'INPUT_RECOVERY_PROOF.json').read_bytes()),
    'candidate_graph': pin((OUT / 'CANDIDATE_FILE_GRAPH.json').read_bytes()),
    'exact_updates': pin((OUT / 'EXACT_UPDATE_ENTRIES.json').read_bytes()),
    'tree_object_plan': pin((OUT / 'TREE_OBJECT_PLAN.json').read_bytes()),
}
write('GRAPH_REVIEW.json', review)
print(json.dumps({key: review[key] for key in (
    'base_root_recomputed', 'candidate_root_expected', 'base', 'candidate', 'overlay_coverage',
    'actual_modified_paths', 'actual_added_paths', 'actual_removed_paths',
    'covered_unchanged_original_paths', 'base_directory_paths', 'candidate_directory_paths',
    'changed_directory_paths', 'changed_tree_objects', 'candidate_graph', 'tree_object_plan')}, indent=2))
