"""Read-only verification of actual immutable evidence trees and wording correction."""
from pathlib import Path
import datetime
import hashlib
import importlib.util
import json

ROOT = Path('/tmp/hepta-36fa-complete-source-native-refusal-publication-v2')
INITIAL = Path('/tmp/hepta-36fa-complete-source-native-refusal-publication-v1')
BASE = Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
spec = importlib.util.spec_from_file_location('merkle', '/tmp/hepta-36fa-checkpoint-after-canonical-20261112/prepare_checkpoint.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def read(root, name):
    return json.loads((root / name).read_bytes())


def tree(root, kind):
    return json.loads(read(root, kind + '.READ.response.json')['content'])


def clean(rows):
    return {r['path']: {k: r[k] for k in ('mode', 'type', 'sha')} for r in rows}


plan = read(ROOT, 'PUBLISH_PLAN.json')
initial = read(INITIAL, 'PUBLISH_PLAN.json')
prior = read(BASE, 'PUBLISH_PLAN.json')
files = plan['files']
assert len(files) == plan['file_count'] == 3638
assert set(files) == set(initial['files'])
assert [p for p in files if files[p] != initial['files'][p]] == ['README.md', 'checkpoint-source-complete-native-refusal/prepare_checkpoint.py']
assert (ROOT / 'prepare_checkpoint.py').read_bytes().replace(str(ROOT).encode(), str(INITIAL).encode()) == (INITIAL / 'prepare_checkpoint.py').read_bytes()
assert (ROOT / 'README.PUBLISH.md').read_bytes().replace(b'422 protected-file inventory entries (351 distinct paths)', b'422 protected files') == (INITIAL / 'README.PUBLISH.md').read_bytes()
raw_verify = json.loads(Path('/tmp/hepta-36fa-source-qualification-cc57-launch-v2/stage-originals/verify/verify.original.log').read_bytes())
assert len(raw_verify['protectedFiles']) == 422 and len(set(raw_verify['protectedFiles'])) == 351
leaf = tree(ROOT, 'leaf')
assert leaf['truncated'] is False and len(leaf['tree']) == 4071
assert {r['path']: r['sha'] for r in leaf['tree'] if r['type'] == 'blob'} == files
assert all(r['mode'] == ('100644' if r['type'] == 'blob' else '040000') for r in leaf['tree'])
computed, dirs = m.merkle(files)
assert computed == leaf['sha'] == plan['leaf_sha'] and len(dirs) == 434
assert {p: v['sha'] for p, v in dirs.items() if p} == {r['path']: r['sha'] for r in leaf['tree'] if r['type'] == 'tree'}
assert all(m.tree_sha(v['tree']) == v['sha'] for v in dirs.values())
assert len(prior['files']) == 3328
assert [p for p in prior['files'] if files[p] != prior['files'][p]] == ['README.md']
assert files[plan['old_readme_archive']] == prior['files']['README.md']
assert len(set(files) - set(prior['files'])) == 310
window = read(Path('/tmp/hepta-36fa-post3454-evidence-preparation-v1'), 'FULL_FILEMAP.json')
assert len(window) == 3623 and all(files[p] == v for p, v in window.items() if p != 'README.md')
old_child, new_child = plan['base_leaf'], computed
parents = []
for kind, child in [('parent-evidence', 'utility-evaluation-20261112-36fa'), ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
    before, after = tree(BASE, kind), tree(ROOT, kind)
    assert before['truncated'] is False and after['truncated'] is False
    assert m.tree_sha(before['tree']) == before['sha'] and m.tree_sha(after['tree']) == after['sha']
    old_entries, new_entries = clean(before['tree']), clean(after['tree'])
    assert old_entries[child] == {'mode': '040000', 'type': 'tree', 'sha': old_child}
    old_entries[child]['sha'] = new_child
    assert old_entries == new_entries
    request = next(r for r in plan['tree_requests'] if r['kind'] == kind)
    assert after['sha'] == request['expected_sha'] and before['sha'] == request['request']['base_tree_sha']
    parents.append({'kind': kind, 'sha': after['sha'], 'entries': len(new_entries), 'only_changed_child': child, 'other_entries_unchanged': True})
    old_child, new_child = before['sha'], after['sha']
assert new_child == plan['root_tree']
for name in ('README', 'PREPARE'):
    proof = read(ROOT, name + '.FULL_READBACK.original.json')
    raw = Path(proof['identity']['frozen_local']).read_bytes()
    assert proof['full_readback_equal'] is True
    assert proof['fetch']['structuredContent']['content'].encode() == raw
    assert m.oid('blob', raw) == proof['create']['structuredContent']['sha'] == proof['identity']['git_blob']
    assert hashlib.sha256(raw).hexdigest() == proof['identity']['sha256']
result = {'format': 'hepta-root-corrected-3638-complete-tree-review-v1',
          'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'status': 'COMPLETE_ACTUAL_TREE_READBACK_MATCHES_REVIEWED_CONTENT',
          'leaf': computed, 'root': new_child, 'files': 3638, 'child_trees': 433, 'all_merkle_trees': 434,
          'old_non_readme_paths_unchanged': 3327, 'old_readme_archived': True, 'new_paths': 310,
          'only_initial_preparation_changes': ['README precise 422 entries / 351 distinct paths wording', 'Preparation helper local OUT path'],
          'qualification_evidence_or_window_changed': False,
          'complete_source_original_protectedFiles_count': 422, 'complete_source_original_distinct_protected_paths': 351,
          'all_3623_window_paths_preserved_except_readme': True,
          'all_modes_and_directory_hashes_verified': True, 'parents': parents,
          'real_qualified_task_chains': 0, 'evidence_ref_modified_by_verifier': False}
(ROOT / 'ROOT_COMPLETE_TREE_READBACK_REVIEW.json').open('x').write(json.dumps(result, sort_keys=True, indent=2) + '\n')
print(json.dumps(result, sort_keys=True))
