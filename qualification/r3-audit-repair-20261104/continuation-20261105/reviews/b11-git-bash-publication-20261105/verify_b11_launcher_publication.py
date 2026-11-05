"""Bind a three-path launcher change to actual Git root/subtree responses."""
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/b11-launcher-publication'


def load(path):
    return json.loads(path.read_text())


def verify_merkle(tree):
    assert tree.get('truncated') is False
    expected = {'': tree['sha']}
    children = {'': []}
    seen = set()
    for e in tree['tree']:
        assert e['path'] not in seen
        seen.add(e['path'])
        parent, _, name = e['path'].rpartition('/')
        children.setdefault(parent, []).append({**e, 'name': name})
        if e['type'] == 'tree':
            expected[e['path']] = e['sha']
            children.setdefault(e['path'], [])
    assert set(expected) == set(children)
    for path, group in children.items():
        group.sort(key=lambda e: (e['name'] + ('/' if e['type'] == 'tree' else '')).encode())
        body = b''.join(e['mode'].lstrip('0').encode() + b' ' + e['name'].encode() + b'\0' + bytes.fromhex(e['sha']) for e in group)
        actual = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        assert actual == expected[path], (path, actual, expected[path])
    return {'tree': tree['sha'], 'entries': len(seen), 'leaves': sum(e['type'] != 'tree' for e in tree['tree']),
            'directory_nodes': len(children), 'all_Merkle_nodes_match': True}


def identity(e):
    return {k: e[k] for k in ('path', 'mode', 'type', 'sha')}


def run(which):
    assert which in ('head', 'merge')
    base_label = {'head': 'diag233', 'merge': 'merge8fd'}[which]
    base = load(ROOT / f'hepta-audit-fifth/recovery-2113/trees/{base_label}.json')
    base_proof = verify_merkle(base)
    inputs = load(OUT / f'actual-{which}-trees.json')
    actual_root, actual_subtree = inputs['root'], inputs['subtree']
    assert not actual_root.get('truncated') and not actual_subtree.get('truncated')
    old_root = {e['path']: identity(e) for e in base['tree'] if '/' not in e['path']}
    new_root = {e['path']: identity(e) for e in actual_root['tree']}
    assert set(old_root) == set(new_root)
    assert {k: v for k, v in old_root.items() if k != '.github'} == {k: v for k, v in new_root.items() if k != '.github'}
    assert new_root['.github']['sha'] == actual_subtree['sha']
    actual = {e['path']: identity(e) for e in base['tree'] if e['path'] != '.github' and not e['path'].startswith('.github/')}
    actual['.github'] = new_root['.github']
    for e in actual_subtree['tree']:
        row = identity(e)
        row['path'] = '.github/' + row['path']
        actual[row['path']] = row
    complete = {'sha': actual_root['sha'], 'tree': list(actual.values()), 'truncated': False}
    proof = verify_merkle(complete)
    old_leaves = {e['path']: identity(e) for e in base['tree'] if e['type'] != 'tree'}
    intended = dict(old_leaves)
    source_map = load(ROOT / 'architecture-audit/b11-git-bash-launcher-20261105/source-map.json')
    for row in source_map:
        assert intended[row['path']]['sha'] == row['preimage']['git_blob']
        for name in ('preimage', 'postimage'):
            body = Path(row[name + '_file']).read_bytes()
            assert len(body) == row[name]['bytes']
            assert hashlib.sha256(body).hexdigest() == row[name]['sha256']
            assert hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == row[name]['git_blob']
        intended[row['path']] = {**intended[row['path']], 'sha': row['postimage']['git_blob']}
    actual_leaves = {e['path']: identity(e) for e in complete['tree'] if e['type'] != 'tree'}
    assert actual_leaves == intended
    changed = sorted(p for p in intended if intended[p] != old_leaves[p])
    assert changed == sorted(row['path'] for row in source_map)
    proof.update({'observed_api_utc': inputs['observed_utc'], 'base': base_proof,
                  'all_root_siblings_except_dot_github_unchanged': True,
                  'complete_actual_dot_github_subtree_untruncated': True,
                  'every_intended_leaf_equal_to_actual_tree': True,
                  'changed_paths': changed, 'new_paths': [], 'removed_paths': [],
                  'composition': 'actual root + actual .github subtree + unchanged base siblings bound by SHA'})
    (OUT / f'{which}-composed-full-tree.json').write_text(json.dumps(complete, separators=(',', ':')) + '\n')
    (OUT / f'{which}-tree-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    run(sys.argv[1])
