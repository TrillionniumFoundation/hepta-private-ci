import hashlib
import json
import re
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-checkpoint-after-canonical-20261112')
OLD = Path('/tmp/hepta-36fa-after2138-20261112')
CURRENT = Path('/tmp/hepta-36fa-after2268-20261112')
AGENT = Path('/tmp/hepta-36fa-next-evidence-preparation-v1')
REPO = 'TrillionniumFoundation/hepta-private-ci'


def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def tree_sha(entries):
    entries = sorted(entries, key=lambda e: (e['path'] + ('/' if e['type'] == 'tree' else '')).encode())
    raw = b''.join(('40000' if e['mode'] == '040000' else e['mode']).encode() + b' '
                   + e['path'].encode() + b'\0' + bytes.fromhex(e['sha']) for e in entries)
    return oid('tree', raw)


def merkle(files):
    nested = {}
    for path, sha in files.items():
        parts = path.split('/')
        assert all(part not in ('', '.', '..') for part in parts)
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = sha
    trees = {}

    def walk(node, path=''):
        entries = []
        for name, child in node.items():
            if isinstance(child, dict):
                value = walk(child, (path + '/' if path else '') + name)
                entries.append({'path': name, 'mode': '040000', 'type': 'tree', 'sha': value})
            else:
                entries.append({'path': name, 'mode': '100644', 'type': 'blob', 'sha': child})
        result = tree_sha(entries)
        trees[path] = {'sha': result, 'tree': entries}
        return result
    return walk(nested), trees


def add(files, path, sha):
    assert re.fullmatch('[0-9a-f]{40}', sha), (path, sha)
    assert path not in files or files[path] == sha, (path, files.get(path), sha)
    files[path] = sha


def main():
    anchors = json.loads((OLD / 'PUBLISHED_2268_ANCHORS.json').read_text())
    base = json.loads((OLD / 'NEXT_CHECKPOINT_PUBLISH_PLAN.json').read_text())['files']
    actual = json.loads(json.loads((OLD / 'NEXT_FULL_LEAF_READ.response.json').read_text())['content'])
    assert len(base) == 2268 and actual['truncated'] is False
    assert {e['path']: e['sha'] for e in actual['tree'] if e['type'] == 'blob'} == base
    assert actual['sha'] == merkle(base)[0] == anchors['evidence_leaf']
    files = json.loads((AGENT / 'READY_FILEMAP_WITH_PREPARATION_BEFORE_README.json').read_text())
    assert len(files) == 2768 and all(files.get(path) == sha for path, sha in base.items())
    for row in [json.loads(line) for line in (CURRENT / 'ROOT_UPLOADS.jsonl').read_text().splitlines()]:
        assert row['full_readback_equal'] is True
        add(files, row['path'], row['sha'])
    for row in json.loads((CURRENT / 'SOURCE_LAUNCH_EXISTING_ENTRIES.json').read_text()):
        assert row['full_readback_equal'] is True
        raw = Path(row['local_path']).read_bytes()
        assert len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        assert oid('blob', raw) == row['sha']
        add(files, row['path'], row['sha'])
    extra_path = ROOT / 'EXTRA_VERIFIED_ENTRIES.json'
    if extra_path.exists():
        for row in json.loads(extra_path.read_text()):
            assert row['full_readback_equal'] is True
            add(files, row['path'], row['sha'])
    own = Path(__file__).read_bytes()
    add(files, 'checkpoint-canonical-publication/prepare_checkpoint.py', oid('blob', own))
    assert files['checkpoints/README_2268FILES_BEFORE_FINAL_NONRUST.md'] == base['README.md']
    readme = (ROOT / 'README.TEMPLATE.md').read_text()
    assert readme.count('__FINAL_EVIDENCE_COUNT__') == 1
    readme = readme.replace('__FINAL_EVIDENCE_COUNT__', f'{len(files):,}')
    raw = readme.encode()
    files['README.md'] = oid('blob', raw)
    assert set(base) <= set(files)
    assert [path for path in base if files[path] != base[path]] == ['README.md']
    missing = []
    for link in re.findall(r'\]\(([^)]+)\)', readme):
        if '://' in link or link.startswith('#'):
            continue
        value = link.rstrip('/')
        if value not in files and not any(path.startswith(value + '/') for path in files):
            missing.append(link)
    assert not missing, missing
    (ROOT / 'README.PUBLISH.md').write_bytes(raw)
    leaf, directories = merkle(files)
    changed = {path: sha for path, sha in files.items() if base.get(path) != sha}
    requests = [{'kind': 'leaf', 'expected_sha': leaf, 'request': {
        'repository_full_name': REPO, 'base_tree_sha': anchors['evidence_leaf'],
        'tree_elements': [{'path': path, 'mode': '100644', 'type': 'blob', 'sha': sha}
                          for path, sha in sorted(changed.items())]}}]
    old_child, new_child = anchors['evidence_leaf'], leaf
    for kind, child_name in [('parent-evidence', 'utility-evaluation-20261112-36fa'),
                             ('parent-qa', 'evidence'), ('parent-root', 'qa')]:
        old = json.loads(json.loads((OLD / ('NEXT_READ_' + kind + '.response.json')).read_text())['content'])
        assert tree_sha(old['tree']) == old['sha'] == anchors['evidence_parent_trees'][kind]
        entries = [{key: e[key] for key in ('path', 'mode', 'type', 'sha')} for e in old['tree']]
        selected = [e for e in entries if e['path'] == child_name]
        assert len(selected) == 1 and selected[0]['mode'] == '040000' and selected[0]['sha'] == old_child
        selected[0]['sha'] = new_child
        new_parent = tree_sha(entries)
        requests.append({'kind': kind, 'expected_sha': new_parent, 'request': {
            'repository_full_name': REPO, 'base_tree_sha': old['sha'], 'tree_elements': selected}})
        old_child, new_child = old['sha'], new_parent
    plan = {
        'format': 'hepta-canonical-source-evidence-checkpoint-publication-plan-v1',
        'observation_cutoff_utc': '2026-11-12 22:38:05 UTC',
        'base_head': anchors['evidence_head'], 'base_leaf': anchors['evidence_leaf'],
        'leaf_sha': leaf, 'root_tree': new_child, 'file_count': len(files),
        'original_paths_preserved': 2268, 'unchanged_old_non_readme_paths': 2267,
        'old_readme_exactly_archived': True, 'new_paths': len(files) - len(base),
        'changed_previous_paths': ['README.md'],
        'readme': {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'sha': files['README.md']},
        'preparer': {'bytes': len(own), 'sha256': hashlib.sha256(own).hexdigest(), 'sha': oid('blob', own)},
        'tree_requests': requests, 'files': files, 'tree_count': len(directories),
        'source_branch_head': '246d8cb614770252ee42029a5c014f2a4904176a',
        'source_tree': 'd5646a6ddeb98790b7a86aa5b4fe1bc95fbb3087',
        'source_publication_actual_readback': True,
        'source_gate_job': '1a1d1e83bd4-2564-1c86',
        'source_gate_state_at_last_observation': 'running_source_closure',
        'native_qualification_started': False, 'real_qualified_task_chain_outcomes': 0,
    }
    (ROOT / 'PUBLISH_PLAN.json').write_text(json.dumps(plan, sort_keys=True, indent=2) + '\n')
    print(json.dumps({k: v for k, v in plan.items() if k not in ('files', 'tree_requests')}, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
