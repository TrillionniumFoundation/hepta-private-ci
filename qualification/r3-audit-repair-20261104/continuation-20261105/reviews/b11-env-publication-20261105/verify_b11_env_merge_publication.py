"""Bind the B11 environment repair and exact main merge to all source leaves."""
from pathlib import Path
import ast
import hashlib
import importlib.util
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
OUT = ROOT / 'hepta-audit-fifth/b11-env-publication'
CANDIDATE = ROOT / 'architecture-audit/b11-windows-env-casing-20261105'


def load(path):
    return json.loads(path.read_text())


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def ident(row):
    return {k: row[k] for k in ('path', 'mode', 'type', 'sha')}


def leafmap(tree):
    return {e['path']: ident(e) for e in tree['tree'] if e['type'] != 'tree'}


def constants(body):
    result = {}
    def evaluate(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return result[node.id]
        if isinstance(node, ast.Dict):
            return {evaluate(k): evaluate(v) for k, v in zip(node.keys, node.values)}
        raise ValueError(type(node).__name__)
    for node in ast.parse(body).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                value = evaluate(node.value)
            except (KeyError, ValueError):
                continue
            result[node.targets[0].id] = value
    return result


def main():
    OUT.mkdir(exist_ok=True)
    merkle = module('b11root', ROOT / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    mainverify = module('mainroot', ROOT / 'hepta-audit-fifth/verify_main_format_retention_publication.py')
    trees = {
        'common_5b': load(ROOT / 'hepta-audit-fifth/recovery-2113/trees/5b.json'),
        'diag_855': load(ROOT / 'hepta-audit-fifth/b11-launcher-publication/head-composed-full-tree.json'),
        'main_67': load(ROOT / 'hepta-audit-fifth/main-format-retention/intended-full-tree.json'),
        'old_actual_merge_cb5': load(ROOT / 'hepta-audit-fifth/b11-launcher-publication/merge-composed-full-tree.json'),
    }
    proofs = {k: merkle.verify_merkle(v) for k, v in trees.items()}
    base, ours, theirs, oldmerge = (leafmap(trees[k]) for k in trees)
    merged = {}
    conflicts = []
    for path in sorted(base.keys() | ours.keys() | theirs.keys()):
        a, b, c = base.get(path), ours.get(path), theirs.get(path)
        if b == c:
            row = b
        elif b == a:
            row = c
        elif c == a:
            row = b
        else:
            conflicts.append(path)
            continue
        if row:
            merged[path] = row
    collector = '.github/scripts/collect_bazel_failed_test_logs.py'
    assert conflicts == [collector]
    union = ROOT / 'hepta-audit-fifth/main-format-retention/diagnostic-collector.merged.py.source.txt'
    union_bytes = union.read_bytes()
    union_blob = mainverify.digest(union_bytes)['git_blob']
    assert union_blob == '76a183d6a45e4a6c1493de194f8a1f6c422f0892'
    merged[collector] = {**ours[collector], 'sha': union_blob}
    union_proof = load(ROOT / 'hepta-audit-fifth/main-format-retention/collector-union-proof.json')
    assert union_proof['all_other_bytes_equal'] is True
    source_map = load(CANDIDATE / 'source-map.json')
    for row in source_map:
        path = row['path']
        for side in ('preimage', 'postimage'):
            raw = Path(row[side + '_file']).read_bytes()
            assert mainverify.digest(raw) == row[side]
        assert merged[path]['sha'] == row['preimage']['git_blob']
        merged[path] = {**merged[path], 'sha': row['postimage']['git_blob']}
    control = constants((CANDIDATE / 'candidate/.github/scripts/run_b11_acl_identity_counterfactual.py').read_bytes())
    readiness = constants((CANDIDATE / 'candidate/.github/scripts/run_b11_read_acl_readiness.py').read_bytes())
    pins = readiness['PINS']
    assert pins[collector] == union_blob
    assert pins[readiness['CONTROL_SCRIPT']] == readiness['CONTROL_BLOB']
    for path, sha in pins.items():
        assert merged[path]['sha'] == sha, (path, merged[path]['sha'], sha)
    assert merged[control['SOURCE']]['sha'] == control['POSITIVE']
    assert merged[control['TEST_SOURCE']]['sha'] == control['TEST_BLOB']
    full = mainverify.full_tree_from_leaves(merged)
    proof = merkle.verify_merkle(full)
    changed_oldmerge = sorted(p for p in merged.keys() | oldmerge.keys() if merged.get(p) != oldmerge.get(p))
    expected_changes = sorted([collector, 'codex-rs/core/src/agent/control_tests.rs', 'codex-rs/core/src/environment_selection.rs'] + [r['path'] for r in source_map])
    assert changed_oldmerge == expected_changes
    diff = lambda other: sorted(p for p in merged.keys() | other.keys() if merged.get(p) != other.get(p))
    result = {'schema': 'b11-env-main-merge-root-proof-v1', 'input_complete_tree_proofs': proofs,
              'intended_tree': proof, 'merge_parents': ['855733b0f88c82c68135b1879682358a818daa84', '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'],
              'three_way_common_base': '5b6331250ff459033bd44d1a95daec70131277cc',
              'three_way_conflicts': conflicts, 'collector_union_proof': union_proof,
              'changed_paths_from_old_actual_merge_cb5': changed_oldmerge,
              'changed_paths_from_diag_parent_855': diff(ours), 'changed_paths_from_main_parent_67': diff(theirs),
              'every_helper_pin_equal_to_intended_HEAD_leaf': pins,
              'control_positive_and_test_blob_equal_to_intended_HEAD': True,
              'source_map': source_map, 'new_native_evidence_required': True, 'B11': 'OPEN',
              'native9_preserved': {'checkout': 'cb5aba57802272d7f535cd6ee2ac3e26334dbff6', 'tree': 'bf1c52a3ed14ca2bd0276ffc693dccf6c1dbbb83', 'not_relabelled_as_new_source': True}}
    actual_path = OUT / 'actual-tree-root.json'
    if actual_path.exists():
        actual = load(actual_path)['response']
        assert actual['sha'] == full['sha'] and not actual['truncated']
        expected_root = {e['path']: ident(e) for e in full['tree'] if '/' not in e['path']}
        assert expected_root == {e['path']: ident(e) for e in actual['tree']}
        result['actual_root_SHA_and_entries_equal'] = True
        result['every_intended_leaf_Merkle_bound_to_actual_root'] = True
        result['method'] = 'Full intended leaf/Merkle recomputation bound to actual root GET, not a recursive full-tree GET.'
    (OUT / 'intended-full-tree.json').write_text(json.dumps(full, separators=(',', ':')) + '\n')
    (OUT / 'root-tree-proof.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'tree': full['sha'], 'leaves': proof['leaves'], 'directories': proof['directory_nodes'],
                      'changed_from_cb5': changed_oldmerge, 'changed_from_855': len(diff(ours)), 'changed_from_67': len(diff(theirs)),
                      'pins_checked': len(pins), 'actual_bound': 'actual_root_SHA_and_entries_equal' in result}))


if __name__ == '__main__':
    main()
