"""Independent offline byte/tree audit; does not execute the source gate or tests."""
from pathlib import Path
import ast
import hashlib
import json
import lzma
import tomllib
from datetime import datetime, timezone

ROOT = Path('/workspace/scratch/ed3538174819')
PREP = ROOT / 'mem8-source-v6-preparation'
FINAL = PREP / 'harness/generated-depth6'

def pin(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}

def pairs(items):
    out = {}
    for key, value in items:
        assert key not in out, ('duplicate JSON key', key)
        out[key] = value
    return out

def read_json(data):
    return json.loads(data, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))

def listing(data):
    out = {}
    for record in data.split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, kind, digest = meta.decode().split()
        path = name.decode()
        assert path not in out
        out[path] = {'mode': mode, 'type': kind, 'git_blob': digest}
    return out

def git_tree(entries):
    root = {}
    for path, row in entries.items():
        cursor = root
        components = path.split('/')
        for name in components[:-1]:
            child = cursor.setdefault(name, {})
            assert isinstance(child, dict)
            cursor = child
        assert components[-1] not in cursor
        cursor[components[-1]] = (row['mode'], row['git_blob'])
    def digest(node):
        rows = []
        for name, child in node.items():
            directory = isinstance(child, dict)
            mode, sha = ('40000', digest(child)) if directory else child
            sort_key = (name + ('/' if directory else '')).encode()
            raw = mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
            rows.append((sort_key, raw))
        payload = b''.join(raw for _, raw in sorted(rows))
        return hashlib.sha1(b'tree ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
    return digest(root)

metadata = read_json((FINAL / 'STATIC_VALIDATION.json').read_bytes())
checked = []
for row in metadata['outputs']:
    data = (FINAL / row['path']).read_bytes()
    assert pin(data) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}, row['path']
    checked.append({'path': row['path'], **pin(data)})
driver = (FINAL / '.github/scripts/mem8_source_gates_v6.py').read_bytes()
assert driver == (PREP / 'harness/generated/.github/scripts/mem8_source_gates_v6.py').read_bytes()
workflow = (FINAL / '.github/workflows/hepta-mem8-source-gates-v6.yml').read_bytes()
prior_workflow = (PREP / 'harness/generated/.github/workflows/hepta-mem8-source-gates-v6.yml').read_bytes()
assert prior_workflow.count(b'fetch-depth: 0') == 1
assert workflow == prior_workflow.replace(b'fetch-depth: 0', b'fetch-depth: 6')
constants = {}
for statement in ast.parse(driver).body:
    if isinstance(statement, ast.Assign) and len(statement.targets) == 1 and isinstance(statement.targets[0], ast.Name):
        try:
            constants[statement.targets[0].id] = ast.literal_eval(statement.value)
        except (ValueError, TypeError):
            pass
encoded = (PREP / 'INPUT_SOURCE_GATES.json.xz').read_bytes()
assert pin(encoded) == metadata['input']
assert encoded == (FINAL / 'qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz').read_bytes()
input_bytes = lzma.decompress(encoded)
assert input_bytes == (PREP / 'INPUT_SOURCE_GATES.json').read_bytes()
config = read_json(input_bytes)
assert config['source_gate_run_version'] == 6
assert constants['HEAD'] == metadata['pure_source_head'] == '421d15080b3cb942be8ac51bbe443e268d124a9e'
assert constants['TREE'] == config['expected_initial_tree'] == metadata['pure_source_tree']
assert constants['BASE'] == config['base_sha'] == '2ae5215beaf8d7b7df111a090b82134beae2683d'
assert constants['BASE_TREE'] == config['base_tree'] == '12159640adcf073b51f3837e75575e11f5c20233'
assert (constants['INPUT_SHA'], constants['INPUT_BYTES'], constants['PATH_COUNT']) == (pin(encoded)['sha256'], len(encoded), 109)
records = ROOT / 'mem8-source-ci-v5-original-run/records'
base_bytes = (records / 'BASE_TREE.ls-tree').read_bytes()
parent_bytes = (records / 'CANDIDATE_TREE.ls-tree').read_bytes()
base, parent = listing(base_bytes), listing(parent_bytes)
assert git_tree(base) == config['base_tree']
assert git_tree(parent) == config['source_parent_tree'] == 'c77785ecb368c44ea699769001a47402c9f50591'
expected = dict(base)
sources = {}
assert len(config['files']) == len({row['path'] for row in config['files']}) == 109
for row in config['files']:
    path = row['path']
    data = row['content'].encode()
    assert pin(data) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['input_git_blob']}, path
    assert (base.get(path) or {}).get('git_blob') == row['preimage_git_blob'], path
    assert row['mode'] == '100644'
    sources[path] = data
    expected[path] = {'mode': row['mode'], 'type': 'blob', 'git_blob': row['input_git_blob']}
actual_tree = git_tree(expected)
assert actual_tree == constants['TREE']
assert len(expected) == 14050
actual_changed = {path for path in set(parent) | set(expected) if parent.get(path) != expected.get(path)}
assembly = read_json((PREP / 'ASSEMBLY.json').read_bytes())
assert pin((PREP / 'ASSEMBLY.json').read_bytes()) == metadata['assembly']
assert actual_changed == {row['path'] for row in assembly['files']} == {row['path'] for row in config['new_reviewed_edits_vs_parent']}
assert len(actual_changed) == 10
for row in assembly['files']:
    assert (parent.get(row['path']) or {}).get('git_blob') == row['preimage_git_blob']
    assert pin(sources[row['path']]) == {key: row[key] for key in ('bytes', 'sha256', 'git_blob')}
manifest_bytes = (PREP / 'harness/reference/CALLERS.toml').read_bytes()
assert pin(manifest_bytes) == metadata['caller_manifest']
assert pin(manifest_bytes)['git_blob'] == constants['CALLERS_BLOB'] == expected['CALLERS.toml']['git_blob']
roots = tomllib.loads(manifest_bytes.decode())['source_roots']
rust_paths = [path for root in roots for path, row in sorted(expected.items()) if path.startswith(root.rstrip('/') + '/') and path.endswith('.rs')]
assert len(rust_paths) == 6201 == constants['EXPECTED_RUST_FILES']
assert all(expected[path]['mode'] in ('100644', '100755') and expected[path]['type'] == 'blob' for path in rust_paths)
golden_bytes = (PREP / 'GOLDEN_CALLER_RECEIPT.json').read_bytes()
golden = read_json(golden_bytes)
assert pin(golden_bytes) == metadata['golden']
assert golden_bytes == (FINAL / 'qualification/memory-cell-mem8-source-gates-v6/GOLDEN_CALLER_RECEIPT.json').read_bytes()
assert (len(golden_bytes), pin(golden_bytes)['sha256']) == (constants['GOLDEN_BYTES'], constants['GOLDEN_SHA'])
assert golden['rustFilesScanned'] == 6200 and golden['authorityGranted'] is False and golden['status'] == 'PASS_HEPTA_CALLER_CLOSED_SET'
case_inventory = {}
for path, names in constants['REGRESSION_CASES'].items():
    module = ast.parse(sources[path])
    actual_names = []
    for statement in module.body:
        if isinstance(statement, ast.ClassDef):
            actual_names.extend(statement.name + '.' + member.name for member in statement.body if isinstance(member, ast.FunctionDef) and member.name.startswith('test_'))
    assert sorted(actual_names) == sorted(names), path
    case_inventory[path] = actual_names
assert sum(map(len, case_inventory.values())) == 18
report = {
    'schema': 'hepta.mem8.source-v6.independent-static-peer.v1',
    'reviewed_at': datetime.now(timezone.utc).isoformat(),
    'status': 'STATIC_NO_REMAINING_MUST_FIX',
    'reviewer': 'mem_experiment_review',
    'final_variant': 'generated-depth6',
    'source_head': constants['HEAD'], 'source_tree': actual_tree,
    'artifacts': checked,
    'metadata': {'path': 'harness/generated-depth6/STATIC_VALIDATION.json', **pin((FINAL / 'STATIC_VALIDATION.json').read_bytes())},
    'offline_independent_checks': {
        'all_four_final_output_bytes_sha256_git_blob': 'PASS',
        'depth6_only_one_line_change_driver_input_golden_unchanged': 'PASS',
        'ancestor_chain_depth6': ['421d15080b3cb942be8ac51bbe443e268d124a9e', '9bd2f589debdba4a93baa363817c3669cb103721', 'c842e995b047eb2ee7d81c073f14fb2fcaa6bff2', '6ce78781977d1ca77d004845b933ec9a99f54a83', '189711e3563ea13a5328d52e99a286f082045b98', '2ae5215beaf8d7b7df111a090b82134beae2683d'],
        'ancestor_chain_source': 'Parent root independently read actual raw Git ancestry; this peer verified final workflow depth is 6 and literal base remains 2ae.',
        'base_tree_rehashed_from_full_listing': config['base_tree'],
        'parent_tree_rehashed_from_full_listing': config['source_parent_tree'],
        'full_base_plus_109_postimages_rehashed': actual_tree,
        'complete_leaf_entries': len(expected), 'changed_paths_vs_parent': sorted(actual_changed),
        'each_109_base_preimage_and_postimage_bytes_sha256_git_blob': 'PASS',
        'full_rust_inventory': {'roots': roots, 'files': len(rust_paths), 'ignored_path_fragments_applied': False},
        'golden_receipt_full_bytes_unchanged': pin(golden_bytes),
        'golden_expected_count_delta_only': {'field': 'rustFilesScanned', 'before': 6200, 'after': 6201},
        'python_regression_source_ast_exact_case_ids': case_inventory,
    },
    'reviewed_runtime_contract': [
        'Pure source and frozen harness occupy separate checkouts; source HEAD/tree/clean and all reviewed source bytes are checked before commands.',
        'Input/golden/CALLERS identities are exact. Full caller output is parsed without duplicate keys or non-JSON constants, then compared as complete type-preserving and array-order-preserving JSON; only independently derived rustFilesScanned changes.',
        'Two direct Python scripts require exactly 16 and 2 unique expected case IDs, matching method suffixes, actual exit zero, one exact Ran summary, all ok and terminal OK. Empty, skipped, unexpected, duplicate and failed selections cannot satisfy this predicate.',
        'The existing 600-second command deadline is shared by formatting, Python cases, caller self-test, full proof, and final source/tree checks. Commands have no automatic retries; timeout cleanup addresses only the process group created for that command.',
        'Post-format source bytes, both locks, HEAD/tree, staged path inventory and the complete tree are revalidated after verification. No commit or ref is changed.',
        'Workflow preserves strict pipefail, fixed tool identities, contents-read permission, branch-specific trigger, and always retaining complete records even on failure.'
    ],
    'limits_and_nonclaims': [
        'This is static review plus offline byte/tree reconstruction. The driver, regression scripts, formatter, full caller scan, native tests and model were not executed by this peer.',
        'The 13-name scan retains historical hits with review_required; inherited final status explicitly leaves review remaining, so a successful process exit is not a claim of zero old-name hits.',
        'Failure capture and artifact sealing preserve evidence after command deadline. They do not extend the source command budget and are still subject to the original 20-minute job limit.',
        'Depth 6 reaches the independently verified six-commit chain. No fetch or host operation was performed by this peer.',
        'No original unknown remote operation or provider turn is reconciled or replayed by this source-only harness.'
    ],
    'native_executions_by_peer': 0, 'model_requests_by_peer': 0, 'remote_process_starts_by_peer': 0, 'ref_mutations_by_peer': 0,
}
out = FINAL / 'MEM_EXPERIMENT_HARNESS_PEER.json'
with out.open('xb') as f:
    f.write((json.dumps(report, indent=2, ensure_ascii=False) + '\n').encode())
print(json.dumps({'path': str(out), **pin(out.read_bytes()), 'status': report['status']}, indent=2))
