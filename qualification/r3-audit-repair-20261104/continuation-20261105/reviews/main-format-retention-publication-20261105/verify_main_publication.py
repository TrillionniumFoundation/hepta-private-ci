"""Verify exact source edits and bind every intended leaf to an actual Git root.

This is an evidence verifier, not a test, formatter, native run, or qualification.
"""
from pathlib import Path
import hashlib
import importlib.util
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/main-format-retention'
BASE = ROOT / 'hepta-audit-fifth/recovery-2113/trees/eed.json'
FORMAT = ROOT / 'research-audit/eed-supervisor-format-20261105'


def load(path):
    return json.loads(path.read_text())


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def ident(row):
    return {k: row[k] for k in ('path', 'mode', 'type', 'sha')}


def full_tree_from_leaves(leaves):
    nodes = {'': {}}
    for path, row in leaves.items():
        assert row['type'] != 'tree'
        parent, _, name = path.rpartition('/')
        nodes.setdefault(parent, {})[name] = {**ident(row), 'name': name}
        ancestor = parent
        while ancestor:
            nodes.setdefault(ancestor, {})
            ancestor, _, _ = ancestor.rpartition('/')
    directories = {}
    for path in sorted(nodes, key=lambda p: (p.count('/'), len(p)), reverse=True):
        group = sorted(nodes[path].values(), key=lambda e: (e['name'] + ('/' if e['type'] == 'tree' else '')).encode())
        body = b''.join(e['mode'].lstrip('0').encode() + b' ' + e['name'].encode() + b'\0' + bytes.fromhex(e['sha']) for e in group)
        sha = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
        directories[path] = sha
        if path:
            parent, _, name = path.rpartition('/')
            nodes[parent][name] = {'path': path, 'name': name, 'mode': '040000', 'type': 'tree', 'sha': sha}
    entries = list(leaves.values()) + [{'path': p, 'mode': '040000', 'type': 'tree', 'sha': sha} for p, sha in directories.items() if p]
    return {'sha': directories[''], 'tree': sorted(entries, key=lambda r: r['path']), 'truncated': False}


def main():
    spec = importlib.util.spec_from_file_location('treecheck', ROOT / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    base = load(BASE)
    assert base['sha'] == 'ca1c4671ef6b2773280d01b5d76c6166252f5856'
    baseline = mod.verify_merkle(base)
    leaves = {e['path']: ident(e) for e in base['tree'] if e['type'] != 'tree'}
    original = dict(leaves)
    changes = [
        ('codex-rs/core/src/agent/control_tests.rs', '05054632b7cd82e5e7587dbcb7aee293788e00a2', '6c93451a16f833c0241bdbe55806a6af60fa6195',
         FORMAT / 'source-before/codex-rs/core/src/agent/control_tests.rs.source.txt', FORMAT / 'source-after/codex-rs/core/src/agent/control_tests.rs.source.txt'),
        ('codex-rs/core/src/environment_selection.rs', '3c08e1620e800c30c47d98cc775cb20d4650ac88', '18aaa1120cc8449246f363105f16acb459a00dfa',
         FORMAT / 'source-before/codex-rs/core/src/environment_selection.rs.source.txt', FORMAT / 'source-after/codex-rs/core/src/environment_selection.rs.source.txt'),
        ('.github/scripts/collect_bazel_failed_test_logs.py', '2142eeb382664d95f77d83ac7ae3da4459601abf', '18701f51e4df1ef6b0fd390d2990114bf971331d',
         OUT / 'b21/preimage.py.source.txt', OUT / 'b21/postimage.py.source.txt'),
    ]
    source_map = []
    for path, before, after, oldfile, newfile in changes:
        a, b = oldfile.read_bytes(), newfile.read_bytes()
        assert digest(a)['git_blob'] == before == leaves[path]['sha']
        assert digest(b)['git_blob'] == after
        source_map.append({'path': path, 'preimage_file': str(oldfile), 'postimage_file': str(newfile), 'preimage': digest(a), 'postimage': digest(b)})
        leaves[path] = {**leaves[path], 'sha': after}
    old_control, new_control = changes[0][3].read_bytes(), changes[0][4].read_bytes()
    compact = lambda b: b''.join(b.split())
    before_tuple = b'("requires_openai_auth".to_string(),TomlValue::Boolean(false))'
    after_tuple = b'("requires_openai_auth".to_string(),TomlValue::Boolean(false),)'
    assert compact(old_control).count(before_tuple) == 1
    assert compact(old_control).replace(before_tuple, after_tuple, 1) == compact(new_control)
    old_env, new_env = compact(changes[1][3].read_bytes()), compact(changes[1][4].read_bytes())
    assert old_env == new_env
    insertion = b'    "//codex-rs/utils/pty:pty-unit-tests",\n'
    retention_before, retention_after = changes[2][3].read_bytes(), changes[2][4].read_bytes()
    assert insertion not in retention_before and retention_after.count(insertion) == 1
    assert retention_after.replace(insertion, b'', 1) == retention_before
    changed = sorted(p for p in leaves if leaves[p] != original[p])
    assert changed == sorted(c[0] for c in changes)
    tree = full_tree_from_leaves(leaves)
    proof = mod.verify_merkle(tree)
    base5 = load(ROOT / 'hepta-audit-fifth/recovery-2113/trees/5b.json')
    mod.verify_merkle(base5)
    leaves5 = {e['path']: ident(e) for e in base5['tree'] if e['type'] != 'tree'}
    cumulative = sorted(p for p in leaves.keys() | leaves5.keys() if leaves.get(p) != leaves5.get(p))
    result = {'schema': 'hepta-main-format-retention-root-proof-v1', 'baseline': baseline,
              'intended_tree': proof, 'source_map': source_map, 'changed_paths_from_eed': changed,
              'new_paths_from_eed': [], 'removed_paths_from_eed': [], 'cumulative_changed_paths_from_5b': cumulative,
              'semantic_delta': {'environment_selection': 'whitespace only',
                                 'control_tests': 'whitespace plus an optional tuple trailing comma',
                                 'collector': 'one selected successful PTY target appended; all prior bytes and copy/error handling preserved'},
              'original_assertions_calls_time_budgets_unchanged': True,
              'native_test_fix_fmt': 'NOT_RUN: original capacity gate still applies',
              'B21_closure': 'OPEN: retention does not prove the original Intel drain failure fixed',
              'whole_candidate_qualified': False}
    actual_file = OUT / 'actual-tree-root.json'
    if actual_file.exists():
        actual = load(actual_file)['response']
        assert actual['sha'] == tree['sha'] and not actual['truncated']
        expected_roots = {e['path']: ident(e) for e in tree['tree'] if '/' not in e['path']}
        assert expected_roots == {e['path']: ident(e) for e in actual['tree']}
        result['actual_root_sha'] = actual['sha']
        result['actual_root_entries_equal'] = True
        result['complete_intended_leaf_Merkle_equal_to_actual_Git_root'] = True
        result['proof_method'] = 'Every intended leaf is bound through all computed Merkle nodes to the actual GET root; this is not a recursive full-tree GET.'
    (OUT / 'intended-full-tree.json').write_text(json.dumps(tree, separators=(',', ':')) + '\n')
    (OUT / 'source-map.json').write_text(json.dumps(source_map, indent=2) + '\n')
    (OUT / 'root-tree-proof.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'tree': tree['sha'], 'changed': changed, 'cumulative_changed': len(cumulative),
                      'leaves': proof['leaves'], 'directory_nodes': proof['directory_nodes'],
                      'actual_bound': 'actual_root_sha' in result}))


if __name__ == '__main__':
    main()
