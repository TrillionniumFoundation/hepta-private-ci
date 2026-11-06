"""Offline verification of the published V9 audit tree and PR metadata receipts.

This verifies retained bytes and Git identities; it does not run product tests.
"""
from pathlib import Path
import argparse
import hashlib
import json

PREFIX = 'qualification/r3-audit-repair-20261104/continuation-20261105/'
COMMIT = '089c13ab39cedb9fea0f9e9bd03d95317936cd65'
TREE = 'cd5ad6773d53055ae79cf3a5b79703406161eb69'
PARENT = '0fc276d03e7d90f2e4fc53d67a0de8b942d51559'


def read(root, name):
    return json.loads((root / name).read_bytes())


def identity(row):
    return {k: row[k] for k in ('path', 'mode', 'type', 'sha')}


def merkle(tree):
    nodes = {'': {}}
    leaves = {}
    declared = {}
    for row in tree['tree']:
        path = row['path']
        assert path not in leaves and path not in declared
        if row['type'] == 'tree':
            declared[path] = row['sha']
            continue
        leaves[path] = identity(row)
        parent, _, name = path.rpartition('/')
        nodes.setdefault(parent, {})[name] = {**identity(row), 'name': name}
        while parent:
            nodes.setdefault(parent, {})
            parent, _, _ = parent.rpartition('/')
    directories = {}
    for path in sorted(nodes, key=lambda p: (p.count('/'), len(p)), reverse=True):
        rows = sorted(nodes[path].values(), key=lambda r: (r['name'] + ('/' if r['type'] == 'tree' else '')).encode())
        body = b''.join(r['mode'].lstrip('0').encode() + b' ' + r['name'].encode() + b'\0' + bytes.fromhex(r['sha']) for r in rows)
        sha = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        directories[path] = sha
        if path:
            parent, _, name = path.rpartition('/')
            nodes[parent][name] = {'name': name, 'mode': '040000', 'type': 'tree', 'sha': sha}
    assert tree['sha'] == directories['']
    assert declared == {p: sha for p, sha in directories.items() if p}
    return leaves, directories


def verify(root):
    base, base_dirs = merkle(read(root, 'auditV8-full-tree.json'))
    intended = read(root, 'intended-full-audit-tree.json')
    leaves, directories = merkle(intended)
    assert intended['sha'] == TREE
    plan = read(root, 'tree-publication-plan.json')
    assert plan['parent_commit'] == PARENT and plan['final_expected_tree'] == TREE
    assert not (base.keys() - leaves.keys())
    assert all(leaves[p] == row for p, row in base.items())
    added = set(leaves) - set(base)
    assert len(added) == 565 and all(p.startswith(PREFIX) for p in added)
    planned = {e['path']: identity(e) for s in plan['stages'] for e in s['entries']}
    assert planned == {p: leaves[p] for p in added}
    root_actual = read(root, 'final-tree-root.actual.json')['response']
    assert root_actual['sha'] == TREE and root_actual['truncated'] is False
    assert {e['path']: identity(e) for e in root_actual['tree']} == {
        e['path']: identity(e) for e in intended['tree'] if '/' not in e['path']}
    stages = read(root, 'tree-stages.actual.json')
    assert len(stages) == len(plan['stages']) == 4
    for actual, expected in zip(stages, plan['stages']):
        assert actual['base'] == expected['base_tree']
        assert actual['actual']['sha'] == expected['expected_tree']
        assert actual['entries'] == len(expected['entries'])
    publication = read(root, 'commit-ref-actual.json')
    assert publication['commit'] == COMMIT and publication['parent'] == PARENT
    assert publication['before']['object']['sha'] == PARENT
    assert publication['after']['object']['sha'] == COMMIT
    commit = publication['actualCommit']
    assert commit['sha'] == COMMIT and commit['tree']['sha'] == TREE
    assert [p['sha'] for p in commit['parents']] == [PARENT]
    index_file = root / 'evidence-index-v9-registered.json'
    raw = index_file.read_bytes()
    index_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert leaves[PREFIX + index_file.name]['sha'] == index_blob
    index = read(root, index_file.name)
    assert len(index['items']) == index['actual_registered_objects'] == 564
    assert {PREFIX + index_file.name} | {r['path'] for r in index['items']} == added
    assert all(leaves[r['path']]['sha'] == r['git_blob'] for r in index['items'])
    assert index['counts'] == {'CLOSED_SCOPED': 15, 'OPEN': 7, 'SCIENTIFIC_HOLD': 1}
    prs = []
    for number, head in [(4797, '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'),
                         (4884, '021a59ff05ccd963bc087918db823aa86af31bb8')]:
        previous = read(root, f'recovery-pr{number}.json')['decoded']
        receipt = read(root, f'pr{number}-update.actual.json')
        after = receipt['after']
        desired = (root / f'pr{number}-desired-body.md').read_text()
        assert after['head']['sha'] == head == previous['head']['sha']
        assert after['body'] == desired and desired.endswith(previous['body'])
        assert after['draft'] is True and after['state'] == 'open'
        assert COMMIT in desired
        prs.append({'number': number, 'head': head, 'draft': True,
                    'full_body_readback_equal': True, 'prior_body_preserved': True,
                    'observed_utc': receipt['observed_utc']})
    return {'schema': 'hepta-v9-core-publication-root-verification-v1',
            'commit': COMMIT, 'tree': TREE, 'parent': PARENT,
            'added_paths': len(added), 'overwritten_paths': [], 'removed_paths': [],
            'all_prior_source_and_evidence_leaves_unchanged': True,
            'leaves': len(leaves), 'directory_nodes_including_root': len(directories),
            'base_leaves': len(base), 'base_directory_nodes_including_root': len(base_dirs),
            'all_Merkle_nodes_recomputed': True, 'actual_root_entries_match': True,
            'proof_method': 'Complete intended leaves and directory hashes bound to actual Git root; not a recursive full-tree GET.',
            'actual_commit_parent_and_ref_readback_match': True,
            'registered_evidence_objects': 564, 'index_blob': index_blob,
            'counts': index['counts'], 'PR_metadata': prs,
            'whole_candidate_qualified': False, 'all_blockers_closed': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('originals', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = verify(args.originals)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    print(text)
