"""Prepare an append-only evidence tree from the actual 2793-file checkpoint."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

OUT = Path('/tmp/hepta-36fa-after2793-20261112')
BASE = Path('/tmp/hepta-36fa-checkpoint-after-canonical-20261112')
REPO = 'TrillionniumFoundation/hepta-private-ci'
SPEC = importlib.util.spec_from_file_location('prior_evidence_tree_helpers', BASE / 'prepare_checkpoint.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main():
    anchors = json.loads((BASE / 'PUBLISHED_2793_ANCHORS.json').read_text())
    base = json.loads((BASE / 'PUBLISH_PLAN.json').read_text())['files']
    remote = json.loads(json.loads((BASE / 'leaf.READ.response.json').read_text())['content'])
    assert len(base) == 2793 and remote['truncated'] is False
    assert {row['path']: row['sha'] for row in remote['tree'] if row['type'] == 'blob'} == base
    assert MODULE.merkle(base)[0] == anchors['evidence_leaf'] == remote['sha']
    files = dict(base)
    for row in json.loads((OUT / 'VERIFIED_INCREMENTAL_ENTRIES.json').read_text()):
        raw = Path(row['local']).read_bytes()
        assert row['full_readback_equal'] is True
        assert MODULE.oid('blob', raw) == row['sha']
        if 'bytes' in row:
            assert row['bytes'] == len(raw) and row['sha256'] == hashlib.sha256(raw).hexdigest()
        MODULE.add(files, row['path'], row['sha'])
    archive = 'checkpoints/README_2793FILES_BEFORE_COMPLETE_SOURCE_RESULT.md'
    MODULE.add(files, archive, base['README.md'])
    for name in ['collect_verified_entries.py', 'prepare_checkpoint.py']:
        MODULE.add(files, 'checkpoint-complete-source-result/' + name,
                   MODULE.oid('blob', (OUT / name).read_bytes()))
    text = (OUT / 'README.TEMPLATE.md').read_text()
    assert text.count('__FINAL_EVIDENCE_COUNT__') == 1
    text = text.replace('__FINAL_EVIDENCE_COUNT__', f'{len(files):,}')
    raw = text.encode()
    files['README.md'] = MODULE.oid('blob', raw)
    assert set(base) <= set(files)
    assert [path for path in base if files[path] != base[path]] == ['README.md']
    for link in re.findall(r'\]\(([^)]+)\)', text):
        if '://' in link or link.startswith('#'):
            continue
        target = link.split('#')[0].rstrip('/')
        assert target in files or any(path.startswith(target + '/') for path in files), link
    (OUT / 'README.PUBLISH.md').write_bytes(raw)
    leaf, directories = MODULE.merkle(files)
    changed = {path: sha for path, sha in files.items() if base.get(path) != sha}
    requests = [{'kind': 'leaf', 'expected_sha': leaf, 'request': {
        'repository_full_name': REPO, 'base_tree_sha': anchors['evidence_leaf'],
        'tree_elements': [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha}
                          for path, sha in sorted(changed.items())]}}]
    old_child, new_child = anchors['evidence_leaf'], leaf
    for kind, name in [('parent-evidence', 'utility-evaluation-20261112-36fa'),
                       ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
        old = json.loads(json.loads((BASE / (kind + '.READ.response.json')).read_text())['content'])
        assert MODULE.tree_sha(old['tree']) == old['sha'] == anchors['evidence_parent_trees'][kind]
        entries = [{key: row[key] for key in ('path', 'mode', 'type', 'sha')} for row in old['tree']]
        selected = [row for row in entries if row['path'] == name]
        assert len(selected) == 1 and selected[0]['mode'] == '040000' and selected[0]['sha'] == old_child
        selected[0]['sha'] = new_child
        parent = MODULE.tree_sha(entries)
        requests.append({'kind': kind, 'expected_sha': parent, 'request': {
            'repository_full_name': REPO, 'base_tree_sha': old['sha'], 'tree_elements': selected}})
        old_child, new_child = old['sha'], parent
    plan = {'format': 'hepta-completed-source-result-evidence-checkpoint-v1',
            'base_head': anchors['evidence_head'], 'base_leaf': anchors['evidence_leaf'],
            'leaf_sha': leaf, 'root_tree': new_child, 'file_count': len(files),
            'unchanged_old_non_readme_paths': 2792, 'old_readme_archive': archive,
            'new_paths': len(files) - len(base), 'tree_count': len(directories),
            'changed_old_paths': ['README.md'], 'tree_requests': requests, 'files': files,
            'readme': {'bytes': len(raw), 'sha': files['README.md'], 'sha256': hashlib.sha256(raw).hexdigest()},
            'source': '246d8cb614770252ee42029a5c014f2a4904176a',
            'source_tree': 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
            'source_gate_job': '1a1d1e83bd4-2564-1c86', 'source_gate_status': 'failed',
            'native_qualification_started': False, 'actual_qualified_task_chain_outcomes': 0}
    (OUT / 'PUBLISH_PLAN.json').write_text(json.dumps(plan, sort_keys=True, indent=2) + '\n')
    print(json.dumps({key: value for key, value in plan.items() if key not in ('files', 'tree_requests')}, indent=2))


if __name__ == '__main__':
    main()
