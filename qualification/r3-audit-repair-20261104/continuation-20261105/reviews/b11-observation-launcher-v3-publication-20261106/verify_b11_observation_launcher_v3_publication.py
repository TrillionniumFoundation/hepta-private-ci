"""Bind the diagnostic-only v3 launcher to the complete actual v2 tree.

Offline Git/source verification; never compile or execute native product code.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys


DEFAULT_ROOT = Path('/workspace/scratch/07dd58cc9630')
SOURCE_PATH = 'codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs'
PARENT = '2980fa274c599bd07437a2f5915b86d858f89bcc'
BASE_TREE = '9cb7302777ce018dd022086041c2225d1dd5c8dd'
POSTIMAGE = '8c16416c185f17871c25139bc16c6fd112b5fd41'
EXPECTED_TREE = '9a804c7b6e0dd554cdb435f41e06c5c689fffaaf'


def load(path):
    return json.loads(path.read_bytes())


def digest(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def imported(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(root):
    out = root / 'hepta-audit-fifth/b11-observation-launcher-v3-publication'
    out.mkdir(exist_ok=True)
    candidate = root / 'architecture-audit/b11-host-neither-observation-candidate-20261105/v3'
    builder = imported('v3_builder', root / 'hepta-audit-fifth/verify_main_format_retention_publication.py')
    checker = imported('v3_checker', root / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    before = load(root / 'hepta-audit-fifth/b11-host-neither-publication/intended-full-tree.json')
    assert before['sha'] == BASE_TREE
    original_proof = checker.verify_merkle(before)
    leaves = {row['path']: builder.ident(row) for row in before['tree'] if row['type'] != 'tree'}
    original_leaves = dict(leaves)
    assert len(leaves) == 10589
    previous = (candidate / 'source' / SOURCE_PATH).read_bytes()
    revised = (candidate / 'candidate' / SOURCE_PATH).read_bytes()
    assert digest(previous)['git_blob'] == leaves[SOURCE_PATH]['sha'] == 'b40b49ce772c402c51ddb16bb98ff73dc78cdb41'
    assert digest(revised)['git_blob'] == POSTIMAGE
    actual_postimage = load(out / 'candidate-full-get.actual.json')['content'].encode('utf-8')
    assert actual_postimage == revised
    source_map = load(candidate / 'source-map.json')
    dependencies = []
    for row in source_map['original_sources']:
        actual = digest((candidate / 'source' / row['repository_path']).read_bytes())
        assert all(actual[k] == row[k] for k in actual)
        assert actual['git_blob'] == leaves[row['repository_path']]['sha']
        dependencies.append({'path': row['repository_path'], **actual})
    assert len(dependencies) == 14
    # Re-execute the complete independent preparation verifier, including full
    # patch forward/reverse byte checks and all protected unchanged source regions.
    replay = subprocess.run([sys.executable, str(candidate / 'verify_v3_candidate.py')],
                            cwd=root, capture_output=True, check=False)
    assert replay.returncode == 0, replay.stderr.decode()
    replay_data = json.loads(replay.stdout)
    assert replay_data['expected_candidate_tree'] == EXPECTED_TREE
    assert replay_data['all_three_existing_wait_values_ms'] == [5000, 5000, 5000]
    assert replay_data['same_full_run_function_bytes']
    assert replay_data['same_full_token_record_and_effective_token_bytes']
    assert replay_data['same_cmd_gate_work_cleanup_oracle_bytes_except_launcher_and_job_field']
    assert replay_data['new_test_or_ignore_attributes'] == 0
    assert replay_data['native_execution_performed'] is False
    (out / 'candidate-static-root-replay.json').write_bytes(replay.stdout)
    # Use a separate tree implementation from the preparation verifier.
    leaves[SOURCE_PATH] = {**leaves[SOURCE_PATH], 'sha': POSTIMAGE}
    changed = sorted(path for path in leaves.keys() | original_leaves.keys()
                     if leaves.get(path) != original_leaves.get(path))
    assert changed == [SOURCE_PATH]
    after = builder.full_tree_from_leaves(leaves)
    assert after['sha'] == EXPECTED_TREE
    after_proof = checker.verify_merkle(after)
    pre = load(out / 'prepublication-actual.json')
    assert pre['ref']['object']['sha'] == PARENT
    assert pre['pr']['head']['sha'] == PARENT
    assert pre['pr']['base']['sha'] == '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
    assert pre['pr']['draft'] is True and pre['pr']['state'] == 'open'
    parent = load(out / 'actual-parent-commit.json')['response']
    assert parent['sha'] == PARENT and parent['tree']['sha'] == BASE_TREE
    result = {
        'schema': 'hepta-b11-observation-launcher-v3-root-proof-v1',
        'parent_commit': PARENT, 'parent_tree': BASE_TREE,
        'before_tree_proof': original_proof, 'candidate_tree_proof': after_proof,
        'changed_paths': changed, 'new_paths': [], 'removed_paths': [],
        'unchanged_leaves': len(leaves) - 1,
        'source_before': digest(previous), 'source_after': digest(revised),
        'candidate_full_actual_get_byte_equal': True,
        'full_source_dependencies_bound_to_original_tree': dependencies,
        'complete_original_orchestration_and_oracles_preserved': True,
        'production_desktop_zero_restricted_sid_guard_unchanged': True,
        'original_assertions_timeouts_workflows_and_helper_pins_unchanged': True,
        'root_review': 'Complete 26205-byte module, five-hunk patch, production desktop/process/attribute/Job sources and Windows-sys 0.52 CreateProcessAsUserW signature read. Both subjects use the identical test-only launcher, atomic Job and explicit stdio handle attributes; returned process and thread handles become owned immediately. Actual primary-token gate, physical fixture oracles and original three 5000 ms waits remain unchanged.',
        'prior_diagnostic_failure': {'run': 42130823627, 'job': 127606676952,
            'whole': {'passed': 146, 'failed': 8, 'ignored': 2},
            'error': 'GetTokenInformation(TokenRestrictedSids) size query failed: 122',
            'cmd_children_qualified': 0,
            'scope': 'Prior review missed the production launcher restriction; retain this failure. Three Rust matrices support a privilege-intervention observation only.'},
        'compilation_or_native_or_formatting_performed_by_this_verifier': False,
        'qualification': 'STATIC_SOURCE_CANDIDATE_ONLY', 'B11': 'OPEN',
    }
    actual_tree_path = out / 'actual-tree-root.json'
    if actual_tree_path.exists():
        actual = load(actual_tree_path)['response']
        assert actual['sha'] == EXPECTED_TREE and actual['truncated'] is False
        assert {row['path']: builder.ident(row) for row in actual['tree']} == {
            row['path']: builder.ident(row) for row in after['tree'] if '/' not in row['path']}
        result['actual_tree_root_bound'] = True
        result['tree_binding_method'] = 'Complete intended Merkle tree against actual non-recursive root GET.'
    independent_raw = (out / 'independent-review.md').read_bytes()
    assert digest(independent_raw)['git_blob'] == '7d707c4315cb29c7d765e5bcf4027d12e52a2f07'
    assert b'STATIC_ACCEPT_EXACT_CANDIDATE_NOT_COMPILE_OR_NATIVE_QUALIFICATION' in independent_raw
    assert POSTIMAGE.encode() in independent_raw and EXPECTED_TREE.encode() in independent_raw
    result['independent_review'] = digest(independent_raw)
    published_path = out / 'commit-ref-actual.json'
    if published_path.exists():
        published = load(published_path)
        assert published['parent'] == PARENT and published['tree'] == EXPECTED_TREE
        commit = published['actualCommit']
        assert commit['sha'] == published['commit'] == published['after']['object']['sha']
        assert commit['tree']['sha'] == EXPECTED_TREE
        assert [p['sha'] for p in commit['parents']] == [PARENT]
        assert published['before']['object']['sha'] == PARENT
        merge = load(out / 'actual-merge-commit.json')['response']
        assert merge['tree']['sha'] == EXPECTED_TREE
        assert [p['sha'] for p in merge['parents']] == [pre['pr']['base']['sha'], commit['sha']]
        pr_update = load(out / 'pr4884-update.actual.json')
        pr = pr_update['actual']
        assert pr['head']['sha'] == commit['sha'] and pr['draft'] is True and pr['state'] == 'open'
        assert pr['body'] == pr_update['request_body'] and pr['body'].endswith(pre['pr']['body'])
        result['actual_publication'] = {'source_commit': commit['sha'],
            'tree': EXPECTED_TREE, 'parent': PARENT, 'actual_PR_merge': merge['sha'],
            'actual_PR_merge_parents': [p['sha'] for p in merge['parents']],
            'leased_ref_readback_equal': True, 'full_PR_body_readback_equal': True,
            'previous_PR_body_preserved_as_dated_history': True,
            'qualification': 'PUBLISHED_SOURCE_ONLY_NATIVE_CI_PENDING'}
    for name, value in [('intended-full-tree.json', after), ('root-tree-proof.json', result)]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'expected_tree': EXPECTED_TREE, 'changed_paths': changed,
                      'leaves': len(leaves), 'actual_bound': result.get('actual_tree_root_bound', False),
                      'B11': 'OPEN'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args()
    main(args.root.resolve())
