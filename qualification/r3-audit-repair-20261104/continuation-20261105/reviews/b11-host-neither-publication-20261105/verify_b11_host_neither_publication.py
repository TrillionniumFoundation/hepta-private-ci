"""Bind the two-path B11 observation candidate to its unchanged native10 tree.

Static source and Git object verification only; no compiler or native execution.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json

ROOT = Path('/workspace/scratch/07dd58cc9630')
CANDIDATE = ROOT / 'architecture-audit/b11-host-neither-observation-candidate-20261105'
OUT = ROOT / 'hepta-audit-fifth/b11-host-neither-publication'


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


def main():
    OUT.mkdir(exist_ok=True)
    builder = imported('b11_builder', ROOT / 'hepta-audit-fifth/verify_main_format_retention_publication.py')
    checker = imported('b11_checker', ROOT / 'hepta-audit-fifth/verify_b11_launcher_publication.py')
    before = load(ROOT / 'hepta-audit-fifth/b11-env-publication/intended-full-tree.json')
    assert before['sha'] == '36ca349de7f4c7c5a2914cf1960a81d8621350fa'
    base_proof = checker.verify_merkle(before)
    leaves = {r['path']: builder.ident(r) for r in before['tree'] if r['type'] != 'tree'}
    original_leaves = dict(leaves)
    probe_path = 'codex-rs/windows-sandbox-rs/src/token_integrity_probe_tests.rs'
    module_path = 'codex-rs/windows-sandbox-rs/src/token_neither_privilege_observation.rs'
    old_probe = (CANDIDATE / 'source' / probe_path).read_bytes()
    probe = (CANDIDATE / 'v2/candidate' / probe_path).read_bytes()
    v1_module = (CANDIDATE / 'candidate' / module_path).read_bytes()
    module = (CANDIDATE / 'v2/candidate' / module_path).read_bytes()
    assert digest(old_probe)['git_blob'] == leaves[probe_path]['sha'] == '2a384792e8ba88518c26943716e8c3a39a523f9b'
    assert digest(probe)['git_blob'] == 'fc9faa6d47ac5fdefa216affceb51a586f8e6b81'
    assert digest(v1_module)['git_blob'] == '1f08099d13cc0e282c1fa95cf0261990ff28b88b'
    assert digest(module)['git_blob'] == 'b40b49ce772c402c51ddb16bb98ff73dc78cdb41'
    assert probe == (CANDIDATE / 'candidate' / probe_path).read_bytes()
    inserts = [b'\n#[path = "token_neither_privilege_observation.rs"]\nmod neither_privileges;\n',
               b'    // The preceding receipt belongs only to the original eight-row phase.\n    // The separate privilege observation below owns two gated cmd processes.\n    neither_privileges::run()?;\n']
    reverted = probe
    for insert in inserts:
        assert reverted.count(insert) == 1 and insert not in old_probe
        reverted = reverted.replace(insert, b'', 1)
    assert reverted == old_probe
    old_env = b'    env.remove("B11_RELEASE");\n'
    new_env = b'''    env.retain(|name, _| {
        !name.eq_ignore_ascii_case("ERRORLEVEL")
            && !name.eq_ignore_ascii_case("B11_RELEASE")
            && !(0..4).any(|index| {
                name.eq_ignore_ascii_case(&format!("MATRIX_FILE_{index}"))
                    || name.eq_ignore_ascii_case(&format!("MATRIX_DIR_{index}"))
            })
    });
'''
    old_flags = b'        "/c".to_owned(), script_path.to_string_lossy().into_owned()];'
    new_flags = b'        "/e:on".to_owned(), "/v:off".to_owned(), "/c".to_owned(), script_path.to_string_lossy().into_owned()];'
    assert v1_module.count(old_env) == v1_module.count(old_flags) == 1
    assert module == v1_module.replace(old_env, new_env, 1).replace(old_flags, new_flags, 1)
    assert b'#[test]' not in module and b'#[ignore]' not in module
    assert module_path not in leaves
    sources = []
    for path, raw in [(probe_path, probe), (module_path, module)]:
        record = {'path': path, 'mode': '100644', 'type': 'blob', 'sha': digest(raw)['git_blob']}
        sources.append({'path': path, 'before': original_leaves.get(path), 'after': digest(raw),
                        'local_file': str(CANDIDATE / 'v2/candidate' / path)})
        leaves[path] = record
    changed = sorted(p for p in leaves.keys() | original_leaves.keys() if leaves.get(p) != original_leaves.get(p))
    assert changed == sorted([probe_path, module_path])
    after = builder.full_tree_from_leaves(leaves)
    proof = checker.verify_merkle(after)
    result = {'schema': 'hepta-b11-host-neither-root-source-proof-v1',
              'parent_commit': '021a59ff05ccd963bc087918db823aa86af31bb8',
              'parent_tree': before['sha'], 'base_proof': base_proof,
              'intended_tree': proof, 'changed_paths': changed,
              'new_paths': [module_path], 'removed_paths': [],
              'all_other_leaves_unchanged': True, 'sources': sources,
              'original_complete_probe_recovered_by_removing_only_two_insertions': True,
              'v2_exactly_two_new_observation_environment_and_cmd_flag_replacements': True,
              'original_assertions_and_workflow_scripts_and_11_helper_pins_unchanged': True,
              'new_test_or_ignore_attributes': 0,
              'compiled_roster_156_and_exact_filtered_155': 'Static preservation expectation only; candidate not compiled or run.',
              'root_source_review': 'Complete new module and both original probe insertions, paired effective thread-token scopes, actual child token gate, fixture physical readback and original process/Job backend reviewed.',
              'native_compilation_or_fmt_or_execution': False,
              'cause_claim': None, 'B11': 'OPEN', 'whole_candidate_qualified': False}
    review_path = ROOT / 'ci-audit/b11-host-neither-independent-20261105/review.json'
    if review_path.exists():
        review_raw = review_path.read_bytes()
        review = json.loads(review_raw)
        assert digest(review_raw)['git_blob'] == 'a53e8141b1a62532a483f91cc2b7a6d84486f5fb'
        assert review['decision'] == 'ACCEPT_V2_AS_OBSERVATION_CANDIDATE_ONLY'
        assert review['candidate_probe']['git_blob'] == digest(probe)['git_blob']
        assert review['accepted_module_v2']['git_blob'] == digest(module)['git_blob']
        assert review['blocking_source_findings_remaining'] == []
        result['independent_review'] = {'identity': digest(review_raw), 'decision': review['decision']}
    actual_file = OUT / 'actual-tree-root.json'
    if actual_file.exists():
        actual = load(actual_file)['response']
        assert actual['sha'] == after['sha'] and actual['truncated'] is False
        assert {r['path']: builder.ident(r) for r in actual['tree']} == {
            r['path']: builder.ident(r) for r in after['tree'] if '/' not in r['path']}
        result['actual_root_entries_equal'] = True
        result['actual_root_sha'] = actual['sha']
        result['proof_method'] = 'Complete intended Merkle tree bound to actual root GET, not recursive full-tree GET.'
    for name, data in [('intended-full-tree.json', after), ('root-tree-proof.json', result), ('source-map.json', sources)]:
        (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'expected_tree': after['sha'], 'changed_paths': changed, 'leaves': proof['leaves'],
                      'actual_bound': 'actual_root_sha' in result, 'B11': 'OPEN'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    CANDIDATE = ROOT / 'architecture-audit/b11-host-neither-observation-candidate-20261105'
    OUT = ROOT / 'hepta-audit-fifth/b11-host-neither-publication'
    main()
