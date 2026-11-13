"""Read-only verification of the already frozen 3328-entry publication scope."""
import ast
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
BASE = Path('/tmp/hepta-36fa-after2793-20261112')
OUT = Path(__file__).parent


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def identity(path):
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}


def read(path):
    return json.loads(path.read_bytes())


def api(path):
    outer = read(path)
    if isinstance(outer.get('content'), str):
        return json.loads(outer['content'])
    return outer.get('structuredContent', outer)


def raw_tree(entries):
    ordered = sorted(entries, key=lambda r: (r['path'] + ('/' if r['type'] == 'tree' else '')).encode())
    assert len({r['path'] for r in ordered}) == len(ordered)
    return b''.join(('40000' if r['type'] == 'tree' else r['mode']).encode() + b' ' + r['path'].encode() + b'\0' + bytes.fromhex(r['sha']) for r in ordered)


def own_merkle(files):
    directories = {''}
    for name, sha in files.items():
        assert re.fullmatch('[0-9a-f]{40}', sha)
        parts = name.split('/')
        assert all(part not in ('', '.', '..') for part in parts)
        directories.update('/'.join(parts[:n]) for n in range(1, len(parts)))
    trees = {}
    for directory in sorted(directories, key=lambda x: (-len(x.split('/')), x), reverse=False):
        # The root's empty name has the same split length as top-level folders;
        # explicitly defer it until all child trees are available.
        if directory == '':
            continue
        rows = []
        prefix = directory + '/'
        for name, sha in files.items():
            if name.startswith(prefix) and '/' not in name[len(prefix):]:
                rows.append({'path': name[len(prefix):], 'mode': '100644', 'type': 'blob', 'sha': sha})
        for child in directories:
            if child.startswith(prefix) and '/' not in child[len(prefix):] and child != directory:
                rows.append({'path': child[len(prefix):], 'mode': '040000', 'type': 'tree', 'sha': trees[child]['sha']})
        body = raw_tree(rows)
        trees[directory] = {'sha': oid('tree', body), 'tree': rows, 'raw_bytes': len(body), 'raw_sha256': hashlib.sha256(body).hexdigest()}
    rows = [{'path': name, 'mode': '100644', 'type': 'blob', 'sha': sha} for name, sha in files.items() if '/' not in name]
    rows += [{'path': name, 'mode': '040000', 'type': 'tree', 'sha': trees[name]['sha']} for name in directories if name and '/' not in name]
    body = raw_tree(rows)
    trees[''] = {'sha': oid('tree', body), 'tree': rows, 'raw_bytes': len(body), 'raw_sha256': hashlib.sha256(body).hexdigest()}
    return trees['']['sha'], trees


plan, base_plan = read(ROOT / 'PUBLISH_PLAN.json'), read(BASE / 'PUBLISH_PLAN.json')
files, original = plan['files'], base_plan['files']
assert len(files) == plan['file_count'] == 3328
assert len(original) == 2841 and set(original) <= set(files)
assert [p for p in original if files[p] != original[p]] == ['README.md']
assert sum(files[p] == original[p] for p in original) == plan['unchanged_old_non_readme_paths'] == 2840
assert len(set(files) - set(original)) == plan['new_paths'] == 487
archive = plan['old_readme_archive']
assert archive == 'checkpoints/README_2841FILES_BEFORE_CC57_SOURCE_REQUALIFICATION.md'
assert files[archive] == original['README.md'] == '8a26a971b80ca5124061b85c496c9744c3eac8ab'
old_readme = (BASE / 'README.PUBLISH.md').read_bytes()
assert oid('blob', old_readme) == original['README.md']
new_readme = (ROOT / 'README.PUBLISH.md').read_bytes()
assert oid('blob', new_readme) == files['README.md'] == plan['readme']['sha']
assert len(new_readme) == plan['readme']['bytes'] and hashlib.sha256(new_readme).hexdigest() == plan['readme']['sha256']
assert (ROOT / 'README.TEMPLATE.md').read_text().replace('__FINAL_EVIDENCE_COUNT__', '3,328').encode() == new_readme

frozen = read(ROOT / 'FROZEN_INPUT_FILEMAP.json')
assert all(frozen.get(p) == sha for p, sha in original.items())
reconstructed = dict(frozen)
increment = read(ROOT / 'ROOT_VERIFIED_INCREMENTAL_ENTRIES.json')
increment_pins = []
for row in increment:
    raw = Path(row['local']).read_bytes()
    assert row['full_readback_equal'] is True and oid('blob', raw) == row['sha']
    assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    assert len(raw) < 500000
    assert row['path'] not in reconstructed or reconstructed[row['path']] == row['sha']
    reconstructed[row['path']] = row['sha']
    increment_pins.append({'path': row['path'], 'sha': row['sha'], 'bytes': row['bytes'], 'sha256': row['sha256']})
reconstructed[archive] = original['README.md']
reconstructed['checkpoint-cc57/prepare_checkpoint.HOLD.py'] = oid('blob', (ROOT / 'prepare_checkpoint.HOLD.py').read_bytes())
reconstructed['README.md'] = oid('blob', new_readme)
assert reconstructed == files

leaf, trees = own_merkle(files)
assert leaf == plan['leaf_sha'] == 'cbc9999071443c4e969830ca2fc198f3dad7ca96'
assert len(trees) == plan['tree_count'] == 400
helper_path = Path('/tmp/hepta-36fa-checkpoint-after-canonical-20261112/prepare_checkpoint.py')
helper_ast = ast.parse(helper_path.read_bytes())
only_pure_functions = ast.Module(body=[node for node in helper_ast.body if isinstance(node, ast.FunctionDef) and node.name in ('oid', 'tree_sha', 'merkle')], type_ignores=[])
namespace = {'hashlib': hashlib}
exec(compile(only_pure_functions, str(helper_path) + ':pure-functions-only', 'exec'), namespace)
helper_leaf, helper_trees = namespace['merkle'](files)
assert helper_leaf == leaf and set(helper_trees) == set(trees)
assert all(isinstance(row, dict) and set(row) == {'sha', 'tree'} for row in helper_trees.values())
for name, row in trees.items():
    assert helper_trees[name]['sha'] == row['sha']
    assert raw_tree(helper_trees[name]['tree']) == raw_tree(row['tree'])

actual = api(ROOT / 'leaf.READ.response.json')
old_actual = api(BASE / 'leaf.READ.response.json')
assert actual['truncated'] is False and old_actual['truncated'] is False
assert len({r['path'] for r in actual['tree']}) == len(actual['tree'])
actual_blobs = {r['path']: r['sha'] for r in actual['tree'] if r['type'] == 'blob'}
assert actual_blobs == files
assert {r['path']: r['sha'] for r in old_actual['tree'] if r['type'] == 'blob'} == original
assert all(r['mode'] == ('100644' if r['type'] == 'blob' else '040000') for r in actual['tree'])
actual_trees = {r['path']: r['sha'] for r in actual['tree'] if r['type'] == 'tree'}
assert actual_trees == {name: row['sha'] for name, row in trees.items() if name}
assert actual['sha'] == leaf == api(ROOT / 'leaf.CREATE.original.json')['sha']
assert len(actual['tree']) == 3328 + 399
assert old_actual['sha'] == plan['base_leaf'] == own_merkle(original)[0]
anchors = read(BASE / 'PUBLISHED_2841_ANCHORS.json')
assert plan['base_head'] == anchors['evidence_head'] and plan['base_leaf'] == anchors['evidence_leaf']
assert plan['tree_requests'][0]['request']['base_tree_sha'] == plan['base_leaf']
changed = {p: sha for p, sha in files.items() if original.get(p) != sha}
request_rows = plan['tree_requests'][0]['request']['tree_elements']
assert len(request_rows) == len(changed) == 488
assert {r['path']: r['sha'] for r in request_rows} == changed

parents = []
old_child, new_child = plan['base_leaf'], leaf
for kind, child_name in [('parent-evidence', 'utility-evaluation-20261112-36fa'), ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
    old, current = api(BASE / (kind + '.READ.response.json')), api(ROOT / (kind + '.READ.response.json'))
    assert old['truncated'] is False and current['truncated'] is False
    old_rows = [{k: r[k] for k in ('path', 'mode', 'type', 'sha')} for r in old['tree']]
    current_rows = [{k: r[k] for k in ('path', 'mode', 'type', 'sha')} for r in current['tree']]
    assert oid('tree', raw_tree(old_rows)) == old['sha'] == anchors['evidence_parent_trees'][kind]
    assert oid('tree', raw_tree(current_rows)) == current['sha'] == api(ROOT / (kind + '.CREATE.original.json'))['sha']
    assert [r for r in old_rows if r['path'] == child_name] == [{'path': child_name, 'mode': '040000', 'type': 'tree', 'sha': old_child}]
    expected = [dict(row, sha=new_child) if row['path'] == child_name else row for row in old_rows]
    assert expected == current_rows
    request = next(r for r in plan['tree_requests'] if r['kind'] == kind)
    assert request['expected_sha'] == current['sha']
    assert request['request']['base_tree_sha'] == old['sha']
    assert request['request']['tree_elements'] == [{'path': child_name, 'mode': '040000', 'type': 'tree', 'sha': new_child}]
    parents.append({'kind': kind, 'old_sha': old['sha'], 'new_sha': current['sha'], 'only_changed_child': child_name, 'other_children_unchanged': len(old_rows) - 1})
    old_child, new_child = old['sha'], current['sha']
assert new_child == plan['root_tree'] == '783ed420aa3e8c8d8205769050c31637faf99434'

broken = []
for link in re.findall(r'\]\(([^)]+)\)', new_readme.decode()):
    if '://' in link or link.startswith('#'):
        continue
    path = link.split('#')[0].rstrip('/')
    if path not in files and not any(p.startswith(path + '/') for p in files):
        broken.append(link)
assert not broken
scope_before = {str(p): identity(p) for p in [ROOT / 'PUBLISH_PLAN.json', ROOT / 'FROZEN_INPUT_FILEMAP.json', ROOT / 'README.TEMPLATE.md', ROOT / 'README.PUBLISH.md']}
tree_index = [{'path': name, 'sha': row['sha'], 'raw_bytes': row['raw_bytes'], 'raw_sha256': row['raw_sha256']} for name, row in sorted(trees.items())]
OUT.mkdir(exist_ok=True)
tree_bytes = (json.dumps(tree_index, sort_keys=True, indent=2) + '\n').encode()
with (OUT / 'ALL_400_TREE_IDENTITIES.json').open('xb') as stream:
    stream.write(tree_bytes)
result = {'format': 'hepta-cc57-3328-evidence-independent-tree-review-v1', 'at_utc': datetime.now(timezone.utc).isoformat(),
    'status': 'FROZEN_3328_MAPPING_AND_CREATED_TREE_READBACKS_MATCH', 'qualification': False,
    'scope': 'Existing frozen file map and recorded Git API tree responses only; no new publication selection, source/gate execution, commit or ref update.',
    'base_head': plan['base_head'], 'base_leaf': plan['base_leaf'], 'leaf': leaf, 'root_tree': new_child,
    'file_count': len(files), 'old_file_count': len(original), 'unchanged_old_non_readme_paths': 2840,
    'changed_old_paths': ['README.md'], 'new_paths': 487, 'request_change_rows': 488,
    'old_readme_archive': {'path': archive, 'git_blob': files[archive], 'original_raw': identity(BASE / 'README.PUBLISH.md')},
    'new_readme': identity(ROOT / 'README.PUBLISH.md'), 'broken_readme_local_links': broken,
    'full_map_matches_recorded_recursive_Git_readback': True, 'recorded_recursive_response_truncated': False,
    'all_400_trees_recomputed_from_raw_Git_encoding': True, 'tree_count_includes_evidence_leaf_itself': True,
    'all_399_descendant_tree_SHA_match_recorded_recursive_readback': True,
    'helper_merkle_return_value_checked_as_dict_sha_and_tree': True,
    'helper_main_executed': False, 'pure_helper_crosscheck': identity(helper_path),
    'all_76_incremental_local_bytes_and_claimed_full_readback_pins_match': len(increment) == 76,
    'frozen_input_reconstruction_matches_plan_without_scope_additions': True,
    'parent_tree_changes': parents,
    'tree_index': {'bytes': len(tree_bytes), 'sha256': hashlib.sha256(tree_bytes).hexdigest(), 'git_blob': oid('blob', tree_bytes)},
    'frozen_inputs': list(scope_before.values()),
    'recorded_API_inputs': [identity(ROOT / (name + suffix)) for name in ('leaf', 'parent-evidence', 'parent-qa', 'parent-root') for suffix in ('.CREATE.original.json', '.READ.response.json')],
    'observed_state_kept_as_frozen': plan['observed_state'],
    'real_qualified_task_chain_outcomes': 0, 'H_calls': 0, 'new_Git_tree_or_commit_or_ref_calls': 0,
    'limitation': 'Verifies saved full API responses and current local immutable inputs; does not claim a new remote ref publication or reacquisition of all 3328 blob bodies.'}
assert all(identity(Path(path)) == value for path, value in scope_before.items())
raw = (json.dumps(result, sort_keys=True, indent=2) + '\n').encode()
with (OUT / 'TREE_REVIEW.json').open('xb') as stream:
    stream.write(raw)
print(json.dumps({'review': identity(OUT / 'TREE_REVIEW.json'), 'tree_index': result['tree_index']}))
