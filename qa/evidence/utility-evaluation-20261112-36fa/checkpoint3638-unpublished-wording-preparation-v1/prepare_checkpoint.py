"""Prepare immutable evidence trees; no H, ref, source, or PR operations."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re

OUT = Path('/tmp/hepta-36fa-complete-source-native-refusal-publication-v1')
BASE = Path('/tmp/hepta-36fa-cc57-evidence-publication-v1')
WINDOW = Path('/tmp/hepta-36fa-post3454-evidence-preparation-v1')
REPO = 'TrillionniumFoundation/hepta-private-ci'
spec = importlib.util.spec_from_file_location('original_merkle_helpers', '/tmp/hepta-36fa-checkpoint-after-canonical-20261112/prepare_checkpoint.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def read_json(path):
    return json.loads(path.read_bytes())


def blob_pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': m.oid('blob', raw)}


def main():
    old = read_json(BASE / 'PUBLISH_PLAN.json')
    anchors = read_json(BASE / 'PUBLISHED_3328_ANCHORS.json')
    assert anchors['actual_tree_commit_and_ref_readback'] is True
    assert anchors['evidence_head'] == '15673f01e5248efdecd00fcb06a58ae3dd45d2c0'
    assert len(old['files']) == 3328 and m.merkle(old['files'])[0] == anchors['evidence_leaf']
    window_raw = (WINDOW / 'FULL_FILEMAP.json').read_bytes()
    assert blob_pin(window_raw)['git_blob'] == 'a18e6489707efdabe4539bcb16bb3b3c1e1dc5c5'
    files = json.loads(window_raw)
    assert len(files) == 3623 and all(files.get(k) == v for k, v in old['files'].items())
    metadata = read_json(OUT / 'METADATA_ROWS.complete.json')
    assert len(metadata) == 13
    for r in metadata:
        raw = Path(r['frozen_local']).read_bytes()
        assert blob_pin(raw) == {k: r[k] for k in ('bytes', 'sha256', 'git_blob')}
        readback = read_json(WINDOW / 'git-readbacks' / (r['git_blob'] + '.json'))
        assert readback['fetch']['isError'] is False
        assert readback['fetch']['structuredContent']['content'].encode() == raw
        assert r['path'] not in files
        m.add(files, r['path'], r['git_blob'])
    archive = 'checkpoints/README_3328FILES_BEFORE_COMPLETE_SOURCE_AND_NATIVE_REFUSAL.md'
    m.add(files, archive, old['files']['README.md'])
    script_path = 'checkpoint-source-complete-native-refusal/prepare_checkpoint.py'
    m.add(files, script_path, m.oid('blob', Path(__file__).read_bytes()))
    template = (OUT / 'README.TEMPLATE.md').read_text()
    assert template.count('__FINAL_EVIDENCE_COUNT__') == 1
    readme = template.replace('__FINAL_EVIDENCE_COUNT__', f'{len(files):,}').encode()
    files['README.md'] = m.oid('blob', readme)
    assert len(files) == 3638
    assert [p for p in old['files'] if files[p] != old['files'][p]] == ['README.md']
    for link in re.findall(r'\]\(([^)]+)\)', readme.decode()):
        if '://' in link or link.startswith('#'):
            continue
        target = link.split('#')[0].rstrip('/')
        assert target in files or any(p.startswith(target + '/') for p in files), ('missing README link', link)
    (OUT / 'README.PUBLISH.md').open('xb').write(readme)
    leaf, directories = m.merkle(files)
    changed = {p: sha for p, sha in files.items() if old['files'].get(p) != sha}
    requests = [{'kind': 'leaf', 'expected_sha': leaf, 'request': {
        'repository_full_name': REPO, 'base_tree_sha': anchors['evidence_leaf'],
        'tree_elements': [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': sha} for p, sha in sorted(changed.items())]}}]
    old_child, new_child = anchors['evidence_leaf'], leaf
    for kind, name in [('parent-evidence', 'utility-evaluation-20261112-36fa'), ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
        outer = read_json(BASE / (kind + '.READ.response.json'))
        value = json.loads(outer['content'])
        assert m.tree_sha(value['tree']) == value['sha'] == anchors['evidence_parent_trees'][kind]
        entries = [{k: r[k] for k in ('path', 'mode', 'type', 'sha')} for r in value['tree']]
        selected = [r for r in entries if r['path'] == name]
        assert len(selected) == 1 and selected[0]['mode'] == '040000' and selected[0]['sha'] == old_child
        selected[0]['sha'] = new_child
        parent = m.tree_sha(entries)
        requests.append({'kind': kind, 'expected_sha': parent, 'request': {
            'repository_full_name': REPO, 'base_tree_sha': value['sha'], 'tree_elements': selected}})
        old_child, new_child = value['sha'], parent
    plan = {'format': 'hepta-complete-source-native-refusal-evidence-checkpoint-v1',
            'base_head': anchors['evidence_head'], 'base_leaf': anchors['evidence_leaf'],
            'leaf_sha': leaf, 'root_tree': new_child, 'file_count': len(files),
            'tree_count': len(directories), 'unchanged_old_non_readme_paths': 3327,
            'old_readme_archive': archive, 'changed_old_paths': ['README.md'],
            'new_paths': len(files) - len(old['files']), 'files': files,
            'tree_requests': requests, 'readme': blob_pin(readme),
            'preparation_script': {'path': script_path, **blob_pin(Path(__file__).read_bytes())},
            'source_head': 'cc57c7198db6293ccca562253c42fffbe2a04633',
            'source_tree': 'b7b357c07b5539769a068c6b9b009629f5612d1e',
            'scope': 'Completed source 1cb4 and full original review; first native 1cd4 precondition refusal, zero behavioral stages; readonly 1ce4 seven-row difference; bounded provider v1 source review. Subsequent object availability/materialization and provider v2 work are excluded.',
            'real_qualified_task_chain_outcomes': 0,
            'later_frozen_window': read_json(WINDOW / 'MANIFEST.json'),
            'metadata_path_normalization': [{'original': r['original_handoff_path'], 'final_relative_path': r['path'], 'same_blob': r['git_blob']} for r in metadata if 'original_handoff_path' in r]}
    (OUT / 'PUBLISH_PLAN.json').open('x').write(json.dumps(plan, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in plan.items() if k not in ('files', 'tree_requests', 'later_frozen_window')}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
