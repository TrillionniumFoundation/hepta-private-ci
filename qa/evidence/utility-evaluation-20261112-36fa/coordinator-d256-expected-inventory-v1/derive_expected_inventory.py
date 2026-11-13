#!/usr/bin/env python3
"""Expected inventory projection, usable only with Root's actual commit body.

No source files, Git objects, refs, native programs, QA or driver main functions
are executed or mutated. Only an archived pure projection function is invoked.
"""
import argparse
import ast
import base64
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import re

R = Path(__file__).resolve().parent
OUT = R / 'expected-inventory-v1'
OLD = Path('/tmp/hepta-36fa-full-candidate-graph-v1')
MATERIALIZER = Path('/tmp/hepta-36fa-c0f-format-base-recovery-v1/MATERIALIZER_DRIVER.original.py')
BASE_HEAD = 'cc57c7198db6293ccca562253c42fffbe2a04633'
BASE_TREE = 'b7b357c07b5539769a068c6b9b009629f5612d1e'
TREE = 'a489b394666b8141840275128a780605b024cde0'
PART_SIZE = 196608


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def require_pin(raw, expected, label):
    assert pin(raw) == expected, (label, pin(raw), expected)


def jbytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def save(name, value):
    raw = value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, ('refuse nonidentical overwrite', str(path))
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'name': name, 'path': str(path), **pin(raw)}


def package(name, raw):
    raw_info = save(name, raw)
    compressed = gzip.compress(raw, compresslevel=9, mtime=0)
    gzip_info = save(name + '.gz', compressed)
    parts = []
    for number, offset in enumerate(range(0, len(compressed), PART_SIZE), 1):
        chunk = compressed[offset:offset + PART_SIZE]
        body = base64.b64encode(chunk) + b'\n'
        info = save(f'{name}.gz.part-{number:03d}.b64', body)
        assert info['bytes'] <= 512000
        parts.append({**info, 'decoded_offset': offset, 'decoded_bytes': len(chunk),
                      'decoded_sha256': hashlib.sha256(chunk).hexdigest()})
    decoded = b''.join(base64.b64decode(Path(part['path']).read_bytes()[:-1], validate=True) for part in parts)
    assert decoded == compressed and gzip.decompress(decoded) == raw
    return {'name': name, 'raw': raw_info, 'gzip': gzip_info, 'parts': parts,
            'expected_only': True, 'storage': 'Complete lossless gzip/base64 parts; no standalone large raw/gzip blob claim'}


parser = argparse.ArgumentParser()
parser.add_argument('--commit-raw', type=Path, required=True)
parser.add_argument('--commit-oid', required=True)
parser.add_argument('--root-readback-proof', required=True)
args = parser.parse_args()
assert re.fullmatch('[0-9a-f]{40}', args.commit_oid)
assert re.fullmatch('[0-9a-f]{40}', args.root_readback_proof)
commit_raw = args.commit_raw.read_bytes()
typed = hashlib.sha1(b'commit ' + str(len(commit_raw)).encode() + b'\0' + commit_raw).hexdigest()
assert typed == args.commit_oid
headers = commit_raw.split(b'\n\n', 1)[0].decode().splitlines()
assert headers[0] == 'tree ' + TREE
assert [line[7:] for line in headers if line.startswith('parent ')] == [BASE_HEAD]

base_raw = (OLD / 'inputs/CC57_INVENTORY.exact.json').read_bytes()
require_pin(base_raw, {'bytes': 5611184, 'sha256': '13d3efc000a6f1ae9e15d18e5d3cab27722062c27f3524f4ddd7e32f418fceb9',
                       'git_blob': '7f94788b70546a8b8030dfd2b9182a7d9287c537'}, 'original complete cc57 inventory')
base = json.loads(base_raw)
assert jbytes(base) == base_raw
assert base['source'] == {'head': BASE_HEAD, 'tree': BASE_TREE, 'status': ''}
assert base['filesystem_entries'] == base['tracked_entries'] == len(base['files']) == 15188
assert all(row['matches_index'] and row['stable'] and row['index_blob'] == row['working_blob'] for row in base['files'])

driver_raw = (OLD / 'inputs/INVENTORY_DRIVER_5118.original.py').read_bytes()
require_pin(driver_raw, {'bytes': 22946, 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2',
                         'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31'}, 'original complete inventory driver')
node = next(node for node in ast.parse(driver_raw.decode()).body if isinstance(node, ast.FunctionDef) and node.name == 'inventory')
inventory_function = ast.get_source_segment(driver_raw.decode(), node)
assert 'for relative in sorted(paths | set(index)):' in inventory_function
assert 'return (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\\n").encode()' in inventory_function

projection_raw = MATERIALIZER.read_bytes()
require_pin(projection_raw, {'bytes': 57607, 'sha256': '5717afe87597089462b685014d0687f0d45a3416f5a1d65580f69f26c9650436',
                             'git_blob': '972ec74449b113a95b4ec098e562a565f23aa82f'}, 'original projection driver')
node = next(node for node in ast.parse(projection_raw.decode()).body if isinstance(node, ast.FunctionDef) and node.name == 'native_projection')
projection_function = ast.get_source_segment(projection_raw.decode(), node)
known_native = {'bytes': 3530181, 'sha256': '20008a0cb7bbfd5ed67396a301e2bfdbbd30f336d0f962cac23e5d1601f660d9',
                'git_blob': '2def77faf50ba6d74d923732182dcb3cad916e53'}
namespace = {'json': json, 'os': os, 'parse': json.loads, 'pin': require_pin,
             'packet': {'current': {'native_inventory': known_native}}}
exec(compile(projection_function, 'archived_pure_native_projection_only', 'exec'), namespace)
base_native = namespace['native_projection'](base_raw)
assert pin(base_native) == known_native and not base_native.endswith(b'\n')

graph_raw = (R / 'CANDIDATE_FILE_GRAPH.json').read_bytes()
require_pin(graph_raw, {'bytes': 3818494, 'sha256': '41e1924454c39e21d46f4dddde2cc61a654f462cd82e8a6b659f46fa8e3eae4a',
                        'git_blob': '097282896b5881614498faf2231e4c8c0da393c3'}, 'frozen complete final source graph')
graph = json.loads(graph_raw)
assert graph['tree'] == TREE and graph['canonical_source_deletions'] == []
original = {row['path']: row for row in base['files']}
rows = []
added = modified = unchanged = 0
for item in sorted(graph['files'], key=lambda row: row['path']):
    old = original.get(item['path'])
    row = copy.deepcopy(old) if old is not None else {'path': item['path']}
    if old is not None:
        assert old['index_mode'] == item['mode']
    else:
        assert item['mode'] == '100644' and item['kind'] == 'file'
    row.update(index_mode=item['mode'], index_blob=item['git_blob'], working_blob=item['git_blob'],
               bytes=item['bytes'], sha256=item['sha256'], kind=item['kind'],
               permissions=old['permissions'] if old is not None else 0o644, stable=True, matches_index=True)
    assert set(row) == set(base['files'][0])
    rows.append(row)
    if old is None:
        added += 1
    elif old != row:
        modified += 1
    else:
        unchanged += 1
assert (len(rows), added, modified, unchanged) == (15243, 55, 63, 15125)
assert set(original) <= {row['path'] for row in rows}
expected = copy.deepcopy(base)
expected['source'] = {'head': args.commit_oid, 'tree': TREE, 'status': ''}
expected['tracked_entries'] = expected['filesystem_entries'] = len(rows)
expected['files'] = rows
expected_raw = jbytes(expected)
native_rows = [{'path': row['path'], 'mode': row['index_mode'], 'bytes': row['bytes'],
                'sha256': row['sha256'], 'blob': row['working_blob']} for row in rows]
native_raw = json.dumps(sorted(native_rows, key=lambda row: os.fsencode(row['path'])),
                        sort_keys=True, separators=(',', ':')).encode()
namespace['packet']['current']['native_inventory'] = pin(native_raw)
assert namespace['native_projection'](expected_raw) == native_raw and not native_raw.endswith(b'\n')
by_path = {row['path']: row for row in rows}
special = [row for row in base['files'] if row['index_mode'] != '100644']
assert len(special) == 91 and all(by_path[row['path']] == row for row in special)

save('ACTUAL_CANDIDATE_COMMIT.raw', commit_raw)
save('ORIGINAL_NATIVE_PROJECTION_FUNCTION.txt', projection_function.encode() + b'\n')
save('ORIGINAL_5118_INVENTORY_FUNCTION.txt', inventory_function.encode() + b'\n')
outputs = [package('EXPECTED_CLEAN_INVENTORY.json', expected_raw),
           package('EXPECTED_NATIVE_FIVE_FIELD.json', native_raw)]
report = {'format': 'hepta-coordinator-expected-inventory-projection-v1',
    'status': 'EXPECTED_ONLY_NOT_NATIVE_OBSERVATION_OR_QUALIFICATION', 'qualification': False,
    'actual_root_created_commit': {'typed_oid': args.commit_oid, 'raw': pin(commit_raw), 'tree': TREE,
        'sole_parent': BASE_HEAD, 'Root_readback_proof_git_blob': args.root_readback_proof,
        'final_lf': commit_raw.endswith(b'\n')},
    'original_cc57_inventory': pin(base_raw), 'complete_baseline_serialization_reproduced': True,
    'original_5118_driver': pin(driver_raw), 'original_5118_function': pin(inventory_function.encode() + b'\n'),
    'original_projection_driver': pin(projection_raw), 'original_projection_function': pin(projection_function.encode() + b'\n'),
    'original_5118_or_projection_module_main_executed': False, 'only_original_pure_projection_function_invoked': True,
    'baseline_native_projection_exact': pin(base_native), 'frozen_graph': pin(graph_raw),
    'expected_source': expected['source'], 'expected_files': len(rows), 'additions_vs_cc57': added,
    'modified_vs_cc57': modified, 'unchanged_cc57_rows': unchanged,
    'expected_rust_under_codex_rs': graph['counts']['rust_under_codex_rs'],
    'expected_rust_all_repository': graph['counts']['rust_all_repository'],
    'all_90_executables_and_one_symlink_rows_preserved': True, 'canonical_source_deletions': [],
    'native_projection_fields': ['path', 'mode', 'bytes', 'sha256', 'blob'],
    'native_serializer': "os.fsencode(path) order; json.dumps(sort_keys=True,separators=(',',':')); default ensure_ascii=True; no final LF",
    'complete_serializer': "original5118 json.dumps(sort_keys=True,separators=(',',':')); default ensure_ascii=True; final LF",
    'stable_matches_index_clean_status_are_future_requirements_not_observed': True,
    'H_or_source_or_ref_mutation': False, 'new_test_or_gate_qualification': False,
    'outputs': [{'name': output['name'], 'raw': output['raw'], 'gzip': output['gzip'], 'parts': len(output['parts'])} for output in outputs]}
review = save('PROJECTION_REVIEW.json', report)
manifest = save('ENCODING_MANIFEST.json', {'format': 'hepta-complete-expected-inventory-lossless-parts-v1',
    'expected_only': True, 'qualification': False, 'gzip_mtime': 0, 'decoded_part_max_bytes': PART_SIZE,
    'all_complete_local_reconstructions_equal': True, 'projection_review': review, 'artifacts': outputs})
print(json.dumps({'review': review, 'manifest': manifest, 'expected_source': expected['source'],
                  'outputs': report['outputs']}, indent=2))
