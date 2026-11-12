import ast
import base64
import gzip
import hashlib
import json
import pathlib
import subprocess
import tempfile
import tomllib

ROOT = pathlib.Path('/tmp')
PREFIX = 'qa/evidence/utility-evaluation-20261112-36fa/next-profile/nonrust-structural-v1/'

def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob_sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def merkle(entries):
    root = {}
    for entry in entries:
        node = root
        parts = entry['path'].split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = entry
    def walk(node):
        rows = []
        for name, entry in node.items():
            if all(k in entry for k in ('sha', 'mode', 'path')):
                rows.append((name.encode(), entry['mode'], entry['sha']))
            else:
                rows.append((name.encode() + b'/', '40000', walk(entry)))
        raw = b''.join(mode.encode() + b' ' + name.rstrip(b'/') + b'\0' + bytes.fromhex(sha) for name, mode, sha in sorted(rows))
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    return walk(root)

artifacts = {}
for bundle in sorted(ROOT.glob('hepta-36fa-nonrust-structural-root-bundle-*.json')):
    for item in json.loads(bundle.read_text()):
        assert item['path'].startswith(PREFIX)
        name = item['path'][len(PREFIX):]
        assert name not in artifacts
        raw = item['content'].encode()
        assert identity(raw) == {key: item[key] for key in ('bytes', 'sha256', 'git_blob_sha')}
        artifacts[name] = raw
assert len(artifacts) == 20
manifest = json.loads(artifacts['MANIFEST.json'])
parts = json.loads(artifacts['PACKET_PARTS.json'])
joined = b''
for part in sorted(parts['parts'], key=lambda p: p['index']):
    raw = artifacts[part['path']]
    assert identity(raw) == {key: part[key] for key in ('bytes', 'sha256', 'git_blob_sha')}
    joined += raw
assert identity(joined) == parts['original_identity'] == manifest['packet_gzip_base64_utf8_with_one_final_lf']
assert joined.endswith(b'\n') and b'\n' not in joined[:-1]
packet_raw = gzip.decompress(base64.b64decode(joined[:-1], validate=True))
assert identity(packet_raw) == manifest['packet_json']
packet = json.loads(packet_raw)
assert len(packet['files']) == len(manifest['files']) == 13
assert identity(artifacts['delta.patch']) == manifest['delta_patch']
for name, info in manifest['references'].items():
    assert identity(artifacts[name]) == info
assert identity(artifacts['PROTECTION_PLAN.json']) == manifest['protection_plan']

leaf_path = ROOT / 'hepta-36fa-post-profile-increments-preformat-leaf-map.json'
leaf_raw = leaf_path.read_bytes()
assert identity(leaf_raw) == manifest['source_leaf_map']
leaf = json.loads(leaf_raw)
assert merkle(leaf['entries']) == leaf['tree'] == packet['source_base_tree_unformatted'] == manifest['source_base_tree_unformatted'] == '02103ded93173dd17aef645ddfcaa5fc6f674042'
assert len(leaf['entries']) == manifest['source_leaf_count'] == 15188
entries = {entry['path']: dict(entry) for entry in leaf['entries']}
images = {}
for item, info in zip(packet['files'], manifest['files']):
    assert {key: item[key] for key in ('path', 'mode', 'before', 'after')} == info
    before = base64.b64decode(item['before_base64'], validate=True)
    after = base64.b64decode(item['postimage_base64'], validate=True)
    assert identity(before) == item['before'] and identity(after) == item['after']
    path = item['path']
    assert entries[path]['sha'] == item['before']['git_blob_sha']
    assert entries[path]['mode'] == item['mode'] == '100644'
    assert path not in images
    images[path] = (before, after)
    entries[path]['sha'] = item['after']['git_blob_sha']
with tempfile.TemporaryDirectory(prefix='hepta-36fa-nonrust-patch-') as directory:
    checkout = pathlib.Path(directory)
    for path, (before, _) in images.items():
        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(before)
    patch = checkout / 'structural.patch'
    patch.write_bytes(artifacts['delta.patch'])
    for args in (['git', 'apply', '--check', str(patch)], ['git', 'apply', str(patch)]):
        subprocess.run(args, cwd=checkout, check=True, capture_output=True)
    assert {str(p.relative_to(checkout)) for p in checkout.rglob('*') if p.is_file()} == set(images) | {'structural.patch'}
    for path, (_, after) in images.items():
        assert (checkout / path).read_bytes() == after

old, new = (tomllib.loads(raw.decode()) for raw in images['CALLERS.toml'])
assert old.keys() == new.keys()
assert {k: v for k, v in old.items() if k not in ('boundary', 'privileged_inventory')} == {k: v for k, v in new.items() if k not in ('boundary', 'privileged_inventory')}
assert len(old['boundary']) == 541 and len(new['boundary']) == 569
assert len(old['protected_file']) == len(new['protected_file']) == 412
assert not any(new['authority'].values())
plan = json.loads(artifacts['STRUCTURAL_REGISTRATION_PLAN.json'])
old_ids = [row['id'] for row in old['boundary']]
new_ids = [row['id'] for row in new['boundary']]
assert len(set(new_ids)) == 569 and new_ids[:541] == old_ids
assert new['boundary'][541:] == plan['new_boundaries']
assert old['privileged_inventory'].keys() == new['privileged_inventory'].keys() == {'required_boundary_ids'}
assert new['privileged_inventory']['required_boundary_ids'] == old['privileged_inventory']['required_boundary_ids'] + new_ids[541:]
assert len(new['privileged_inventory']['required_boundary_ids']) == 569
assert set(new['privileged_inventory']['required_boundary_ids']) == set(new_ids)
changed = []
for position, (before, after) in enumerate(zip(old['boundary'], new['boundary'])):
    assert {k: v for k, v in before.items() if k != 'product_callers'} == {k: v for k, v in after.items() if k != 'product_callers'}
    if before != after:
        add = [p for p in after['product_callers'] if p not in before['product_callers']]
        remove = [p for p in before['product_callers'] if p not in after['product_callers']]
        changed.append({'position': position, 'id': before['id'], 'add': add, 'remove': remove, 'before': before['product_callers'], 'after': after['product_callers']})
assert len(changed) == len(plan['changed_existing_boundaries'])
for actual, stated in zip(changed, plan['changed_existing_boundaries']):
    assert {k: v for k, v in actual.items() if k not in ('add', 'remove')} == {k: v for k, v in stated.items() if k not in ('add', 'remove')}
    for key in ('add', 'remove'):
        assert len(actual[key]) == len(stated[key]) and set(actual[key]) == set(stated[key])
assert len(changed) == 30 and sum(len(x['add']) for x in changed) == 38 and sum(len(x['remove']) for x in changed) == 8

qa = []
for path, (before, after) in images.items():
    if path == 'CALLERS.toml':
        continue
    before_text, after_text = before.decode(), after.decode()
    before_ast, after_ast = ast.parse(before_text), ast.parse(after_text)
    def expected(node):
        return isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'EXPECTED'
    before_expected = [n for n in before_ast.body if expected(n)]
    after_expected = [n for n in after_ast.body if expected(n)]
    assert len(before_expected) == len(after_expected) == 1
    assert isinstance(before_expected[0].value, ast.Dict) and isinstance(after_expected[0].value, ast.Dict)
    before_values = {ast.literal_eval(key): ast.dump(value, include_attributes=False) for key, value in zip(before_expected[0].value.keys, before_expected[0].value.values)}
    after_values = {ast.literal_eval(key): ast.dump(value, include_attributes=False) for key, value in zip(after_expected[0].value.keys, after_expected[0].value.values)}
    assert before_values.keys() == after_values.keys()
    changed_keys = [key for key in before_values if before_values[key] != after_values[key]]
    before_ast.body = [n for n in before_ast.body if not expected(n)]
    after_ast.body = [n for n in after_ast.body if not expected(n)]
    assert ast.dump(before_ast, include_attributes=False) == ast.dump(after_ast, include_attributes=False)
    functions_before = [n for n in ast.walk(before_ast) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    functions_after = [n for n in ast.walk(after_ast) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(functions_before) == len(functions_after)
    for a, b in zip(functions_before, functions_after):
        assert ast.dump(a, include_attributes=False) == ast.dump(b, include_attributes=False)
        assert ast.get_source_segment(before_text, a) == ast.get_source_segment(after_text, b)
    qa.append({'path': path, 'changed_expected_keys': changed_keys, 'unchanged_function_count': len(functions_before)})
assert len(qa) == 12 and sum(len(x['changed_expected_keys']) for x in qa) == 44
assert sum(x['unchanged_function_count'] for x in qa) == 140
out = ROOT / 'hepta-36fa-root-nonrust-structural-v1'
for path, (_, after) in images.items():
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(after)
final = sorted(entries.values(), key=lambda x: x['path'])
tree = merkle(final)
assert len(final) == 15188
proof = {'schema': 'hepta.nonrust-structural-root-review.v1', 'manifest_blob': identity(artifacts['MANIFEST.json'])['git_blob_sha'], 'base_tree_unformatted': leaf['tree'], 'result_tree_unformatted': tree, 'files': len(final), 'artifacts_fully_hashed': 20, 'exact_five_part_packet_reconstruction': True, 'packet_json_identity': identity(packet_raw), 'all_13_before_images_match_full_leaf_map': True, 'all_13_postimages_and_actual_patch_application_equal': True, 'old_boundaries_retained_in_order': 541, 'new_boundary_count': 28, 'all_569_boundary_ids_required': True, 'existing_boundary_only_product_callers_changed': True, 'changed_old_boundary_rows': 30, 'member_additions': 38, 'member_migrations_removed': 8, 'unchanged_original_protected_rows': 412, 'unchanged_authority_flags_all_false': True, 'qa': qa, 'pending': {'ten_new_protected_paths': plan['pending_new_protected_paths'], 'existing_protected_literal_rows': 39, 'new_qa_mutations': 'not_added', 'exact_markers_and_allowlist': 'pending_actual_native_fmt', 'source_closure_and_full_caller': 'not_run', 'rust_compile_and_runtime_gates': 'not_run'}, 'scope': 'Independent complete byte, patch, TOML and existing QA AST/body verification of an incomplete structural preparation only. This does not establish full-source caller membership, new guard coverage, formatted source, compilation, native qualification, actual authorized A/B/C or adoption.'}
(ROOT / 'hepta-36fa-nonrust-structural-preformat-leaf-map.json').write_text(json.dumps({'tree': tree, 'entries': final}, separators=(',', ':')) + '\n')
(ROOT / 'hepta-36fa-nonrust-structural-ROOT_REVIEW.json').write_text(json.dumps(proof, indent=2) + '\n')
print(json.dumps({k: v for k, v in proof.items() if k not in ('qa', 'pending')}, indent=2))
