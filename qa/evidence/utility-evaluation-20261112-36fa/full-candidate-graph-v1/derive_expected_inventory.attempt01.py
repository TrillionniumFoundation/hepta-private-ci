"""Derive expected metadata only; no source mutation, Git command or native I/O.

The complete inventory shape/serializer is the unchanged original 5118 contract.
The native projection function is taken verbatim from pinned 972ec and invoked
in a restricted pure-data namespace; neither original module/main is executed.
"""
from pathlib import Path
import ast
import base64
import copy
import gzip
import hashlib
import json
import os

ROOT = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
OUT = ROOT / 'expected-inventory-v1'
MATERIALIZER = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/MATERIALIZER_DRIVER.original.py')
BASE_HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
BASE_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
HEAD = '0c59aaca0b4932507f068c723f73da2f96729b3d'
TREE = '4b1ef6a81f8fc49d4c267d9e47bc4b8127fc8d09'
PART_SIZE = 196608


def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def require_pin(data, expected, label):
    assert pin(data) == expected, (label, pin(data), expected)


def exact_write(name, raw):
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw, ('refuse nonidentical overwrite', name)
    else:
        path.write_bytes(raw)


def jbytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def record(name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    exact_write(name, raw)
    return pin(raw)


def package(name, raw):
    exact_write(name, raw)
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == raw
    exact_write(name + '.gz', compressed)
    parts = []
    for i, offset in enumerate(range(0, len(compressed), PART_SIZE), 1):
        chunk = compressed[offset:offset + PART_SIZE]
        part_name = f'{name}.gz.part-{i:03}.b64'
        encoded = base64.b64encode(chunk) + b'\n'
        exact_write(part_name, encoded)
        assert base64.b64decode(encoded[:-1], validate=True) == chunk
        parts.append({'name': part_name, **pin(encoded), 'decoded_offset': offset,
                      'decoded_bytes': len(chunk), 'decoded_sha256': hashlib.sha256(chunk).hexdigest()})
    reassembled = b''.join(base64.b64decode((OUT / p['name']).read_bytes()[:-1], validate=True) for p in parts)
    assert reassembled == compressed and gzip.decompress(reassembled) == raw
    return {'name': name, 'raw': pin(raw), 'gzip_name': name + '.gz', 'gzip': pin(compressed),
            'parts': parts, 'computed_raw_and_gzip_identity_only': True,
            'storage': 'Complete lossless gzip base64 parts; no standalone raw/gzip Git upload claimed'}


OUT.mkdir(exist_ok=True)
base_raw = (ROOT / 'inputs/CC57_INVENTORY.exact.json').read_bytes()
require_pin(base_raw, {'bytes': 5611184,
    'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
    'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}, 'actual canonical inventory')
base = json.loads(base_raw)
assert jbytes(base) == base_raw
assert base['source'] == {'head': BASE_HEAD, 'tree': BASE_TREE, 'status': ''}
assert base['filesystem_entries'] == base['tracked_entries'] == len(base['files']) == 15188
assert base['files'] == sorted(base['files'], key=lambda r: r['path'])
assert all(r['stable'] and r['matches_index'] and r['index_blob'] == r['working_blob'] for r in base['files'])

driver_raw = (ROOT / 'inputs/INVENTORY_DRIVER_5118.original.py').read_bytes()
require_pin(driver_raw, {'bytes': 22946,
    'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
    'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}, 'original complete inventory algorithm')
inventory_node = next(n for n in ast.parse(driver_raw.decode()).body if isinstance(n, ast.FunctionDef) and n.name == 'inventory')
inventory_function = ast.get_source_segment(driver_raw.decode(), inventory_node)
assert 'for relative in sorted(paths | set(index)):' in inventory_function
assert 'return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\\n").encode()' in inventory_function

projection_raw = MATERIALIZER.read_bytes()
require_pin(projection_raw, {'bytes': 57607,
    'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436',
    'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'}, 'original materializer projection')
projection_node = next(n for n in ast.parse(projection_raw.decode()).body if isinstance(n, ast.FunctionDef) and n.name == 'native_projection')
projection_function = ast.get_source_segment(projection_raw.decode(), projection_node)
exact_write('ORIGINAL_NATIVE_PROJECTION_FUNCTION.txt', projection_function.encode() + b'\n')
exact_write('ORIGINAL_5118_INVENTORY_FUNCTION.txt', inventory_function.encode() + b'\n')
known_native = {'bytes': 3530181,
    'sha256': '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9',
    'git_blob': '2def77faf50ba6d74d923732182dcb3cad916e53'}
namespace = {'json': json, 'os': os, 'parse': json.loads, 'pin': require_pin,
             'packet': {'current': {'native_inventory': known_native}}}
exec(compile(projection_function, '<exact pinned native_projection only>', 'exec'), namespace)
base_native = namespace['native_projection'](base_raw)
assert pin(base_native) == known_native and not base_native.endswith(b'\n')

commit_raw = (ROOT / 'CANDIDATE_COMMIT.raw').read_bytes()
require_pin(commit_raw, {'bytes': 731,
    'sha256': '291212c82bd82e80ff598d1261b1041e467e4e7a31fa6fda13ba9db1bec68623',
    'git_blob': '2aa08dc83d297fc37aa7f985afe7af41666d3a98'}, 'actual Root-created commit body')
assert hashlib.sha1(b'commit 731\0' + commit_raw).hexdigest() == HEAD
header = commit_raw.split(b'\n\n', 1)[0].decode().splitlines()
assert header[0] == 'tree ' + TREE
assert [s[7:] for s in header if s.startswith('parent ')] == [BASE_HEAD]
assert not commit_raw.endswith(b'\n')

graph_raw = (ROOT / 'CANDIDATE_FILE_GRAPH.json').read_bytes()
require_pin(graph_raw, {'bytes': 3816885,
    'sha256': '856e2dea53111c6c3e99470743f788188ad964e563e9340ec18237f01894688c',
    'git_blob': 'a37a5f15894e645123ffa32d151c6a8a7940e61c'}, 'complete expected graph')
graph = json.loads(graph_raw)
assert graph['tree'] == TREE and graph['canonical_source_deletions'] == []
original = {r['path']: r for r in base['files']}
rows = []
added = modified = unchanged = 0
for item in sorted(graph['files'], key=lambda r: r['path']):
    old = original.get(item['path'])
    if old is not None:
        row = copy.deepcopy(old)
    else:
        row = {'path': item['path']}
    row.update(index_mode=item['mode'], index_blob=item['git_blob'],
               working_blob=item['git_blob'], bytes=item['bytes'], sha256=item['sha256'],
               kind=item['kind'], permissions=int(item['mode'], 8) & 0o777,
               stable=True, matches_index=True)
    assert set(row) == set(base['files'][0])
    rows.append(row)
    if old is None:
        added += 1
    elif row != old:
        modified += 1
    else:
        unchanged += 1
assert len(rows) == 15237 and (added, modified, unchanged) == (49, 60, 15128)
assert set(original) <= {r['path'] for r in rows}
expected = copy.deepcopy(base)
expected['source'] = {'head': HEAD, 'tree': TREE, 'status': ''}
expected['tracked_entries'] = expected['filesystem_entries'] = len(rows)
expected['files'] = rows
expected_raw = jbytes(expected)
native_rows = [{'path': r['path'], 'mode': r['index_mode'], 'bytes': r['bytes'],
                'sha256': r['sha256'], 'blob': r['working_blob']} for r in rows]
native_candidate = json.dumps(sorted(native_rows, key=lambda r: os.fsencode(r['path'])),
                              sort_keys=True, separators=(',', ':')).encode()
namespace['packet']['current']['native_inventory'] = pin(native_candidate)
assert namespace['native_projection'](expected_raw) == native_candidate
assert not native_candidate.endswith(b'\n')
after = {r['path']: r for r in rows}
special = [r for r in base['files'] if r['index_mode'] != '100644']
assert len(special) == 91 and all(after[r['path']] == r for r in special)

artifacts = [package('EXPECTED_CLEAN_INVENTORY.json', expected_raw),
             package('EXPECTED_NATIVE_FIVE_FIELD.json', native_candidate)]
report = {
    'format': 'hepta-0c59-expected-inventory-projection-review-v1',
    'status': 'Expected projection only; no native materialization or source qualification asserted',
    'qualification': False, 'H_or_Git_source_object_operations': False,
    'actual_canonical_inventory': pin(base_raw),
    'actual_baseline_source': base['source'],
    'original_5118_driver': pin(driver_raw),
    'original_5118_function': pin(inventory_function.encode() + b'\n'),
    'original_5118_serializer_reproduces_complete_baseline_raw': True,
    'original_972ec_driver': pin(projection_raw),
    'original_native_function': pin(projection_function.encode() + b'\n'),
    'original_projection_function_body_unmodified': True,
    'original_972ec_module_or_5118_module_or_main_executed': False,
    'only_original_pure_projection_function_executed': True,
    'baseline_native_projection': pin(base_native),
    'baseline_projection_exactly_matches_independent_original_20008_identity': True,
    'actual_Root_created_candidate_commit': {'typed_oid': HEAD, 'raw': pin(commit_raw),
        'parent': BASE_HEAD, 'tree': TREE, 'raw_final_lf': False,
        'Root_tree_readback_proof_git_blob': '816716719793e212b4f7b7208dfb233054c3cf12'},
    'expected_source': expected['source'], 'expected_complete_graph': pin(graph_raw),
    'expected_files': len(rows), 'expected_rust_all_repository': graph['counts']['rust_all_repository'],
    'expected_rust_under_codex_rs': graph['counts']['rust_under_codex_rs'],
    'actual_graph_additions': added, 'actual_graph_modifications': modified,
    'original_rows_retained_unchanged': unchanged,
    'all_90_executable_and_one_symlink_inventory_rows_unchanged': True,
    'canonical_source_deletions': [],
    'stable_matches_index_and_clean_status_are_expected_requirements_not_observations': True,
    'native_projection_fields': ['path', 'mode', 'bytes', 'sha256', 'blob'],
    'native_projection_path_order': 'os.fsencode(path)',
    'native_projection_serializer': "json.dumps(sort_keys=True,separators=(',',':')), default ensure_ascii=True, encode(), no final LF",
    'full_inventory_serializer': "original5118 compact sorted-key JSON, default ensure_ascii=True, final LF",
    'outputs': [{'name': a['name'], 'raw': a['raw'], 'gzip': a['gzip'], 'parts': len(a['parts'])} for a in artifacts],
    'no_new_source_run_no_ref_change': True,
}
review_pin = record('PROJECTION_REVIEW.json', report)
manifest_pin = record('ENCODING_MANIFEST.json', {'format': 'hepta-expected-0c59-inventory-lossless-parts-v1',
    'qualification': False, 'expected_only': True, 'gzip_mtime': 0,
    'decoded_part_max_bytes': PART_SIZE, 'all_local_reconstructions_equal': True,
    'projection_review': review_pin, 'artifacts': artifacts})
print(json.dumps({'review': review_pin, 'encoding_manifest': manifest_pin, 'outputs': report['outputs']}, indent=2))
