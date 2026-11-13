"""Read-only verification of actual created Git trees against frozen maps."""
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
BASE = Path('/tmp/hepta-36fa-after2793-20261112')
spec = importlib.util.spec_from_file_location('merkle_helpers', '/tmp/hepta-36fa-checkpoint-after-canonical-20261112/prepare_checkpoint.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def read(name, root=ROOT):
    return json.loads((root / name).read_bytes())


def actual_tree(kind, root=ROOT):
    return json.loads(read(kind + '.READ.response.json', root)['content'])


def clean(rows):
    return {r['path']: {k: r[k] for k in ('mode', 'type', 'sha')} for r in rows}


plan = read('PUBLISH_PLAN.json')
files = plan['files']
old = read('PUBLISH_PLAN.json', BASE)['files']
leaf = actual_tree('leaf')
assert leaf['truncated'] is False
assert len(files) == plan['file_count'] == 3328
assert len(leaf['tree']) == 3727
assert all(r['type'] in ('blob', 'tree') for r in leaf['tree'])
assert {r['path']: r['sha'] for r in leaf['tree'] if r['type'] == 'blob'} == files
assert all(r['mode'] == ('100644' if r['type'] == 'blob' else '040000') for r in leaf['tree'])
computed, dirs = m.merkle(files)
assert computed == leaf['sha'] == plan['leaf_sha']
assert len(dirs) == plan['tree_count'] == 400
assert {path: value['sha'] for path, value in dirs.items() if path} == {
    r['path']: r['sha'] for r in leaf['tree'] if r['type'] == 'tree'
}
assert all(m.tree_sha(v['tree']) == v['sha'] for v in dirs.values())
assert len(old) == 2841 and set(old) <= set(files)
assert [p for p in old if files[p] != old[p]] == ['README.md']
assert files[plan['old_readme_archive']] == old['README.md']
assert len(set(files) - set(old)) == plan['new_paths'] == 487
package = read('FROZEN_INPUT_FILEMAP.json')
assert len(package) == 3251 and all(files[p] == v for p, v in package.items() if p != 'README.md')
for row in read('ROOT_VERIFIED_INCREMENTAL_ENTRIES.json'):
    raw = Path(row['local']).read_bytes()
    assert row['full_readback_equal'] is True and len(raw) == row['bytes']
    assert hashlib.sha256(raw).hexdigest() == row['sha256']
    assert m.oid('blob', raw) == row['sha'] == files[row['path']]
parent_reviews = []
old_child, new_child = plan['base_leaf'], computed
for kind, child in [('parent-evidence', 'utility-evaluation-20261112-36fa'), ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
    before, after = actual_tree(kind, BASE), actual_tree(kind)
    assert before.get('truncated') is False and after.get('truncated') is False
    assert m.tree_sha(before['tree']) == before['sha']
    assert m.tree_sha(after['tree']) == after['sha']
    prior, actual = clean(before['tree']), clean(after['tree'])
    assert prior[child] == {'mode': '040000', 'type': 'tree', 'sha': old_child}
    prior[child]['sha'] = new_child
    assert prior == actual
    request = next(r for r in plan['tree_requests'] if r['kind'] == kind)
    assert after['sha'] == request['expected_sha'] and before['sha'] == request['request']['base_tree_sha']
    parent_reviews.append({'kind': kind, 'sha': after['sha'], 'entries': len(actual), 'only_changed_child': child, 'other_entries_unchanged': True})
    old_child, new_child = before['sha'], after['sha']
assert new_child == plan['root_tree']
raw = (ROOT / 'README.PUBLISH.md').read_bytes()
assert m.oid('blob', raw) == files['README.md'] == plan['readme']['sha']
assert len(raw) == plan['readme']['bytes']
assert hashlib.sha256(raw).hexdigest() == plan['readme']['sha256']
proof = read('README_FULL_READBACK.json')
assert proof['full_content_equal'] is True and proof['sha'] == files['README.md']
assert '__FINAL_EVIDENCE_COUNT__' not in raw.decode()
result = {
    'format': 'hepta-root-actual-complete-tree-readback-review-v1',
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'status': 'passed', 'base_head': plan['base_head'], 'leaf_sha': computed,
    'root_tree': new_child, 'actual_recursive_tree_entries': len(leaf['tree']),
    'complete_file_map_equal': True, 'file_count': len(files),
    'every_blob_mode_100644': True, 'tree_count': len(dirs),
    'every_directory_sha_recomputed_and_equal': True,
    'unchanged_old_non_readme_files': 2840, 'old_readme_exactly_archived': True,
    'new_paths': 487, 'frozen_3251_paths_preserved_except_readme': True,
    'root_verified_incremental_rows': len(read('ROOT_VERIFIED_INCREMENTAL_ENTRIES.json')),
    'parent_trees': parent_reviews, 'readme_actual_full_readback': proof,
    'snapshot': plan['observed_state'], 'commit_created_by_this_verifier': False,
    'ref_updated_by_this_verifier': False,
    'prior_local_schema_observation': 'An earlier root helper used directory values as strings. Actual helper values are dictionaries with sha and tree. The exact assertion was corrected to select value[sha]; no source gate, inventory, map, tree or publication range changed.'
}
(ROOT / 'ROOT_COMPLETE_TREE_READBACK_REVIEW.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ('snapshot', 'prior_local_schema_observation')}, sort_keys=True))
