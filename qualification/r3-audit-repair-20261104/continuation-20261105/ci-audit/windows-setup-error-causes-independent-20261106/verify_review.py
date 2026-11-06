#!/usr/bin/env python3
"""Independently verify frozen source identities and exact patch scope, without Rust execution."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

SOURCE_HEAD = '67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed'
SOURCE_TREE = '3982ba56dc5a3f1da0c1de7ea57992f88125c359'
EXPECTED_TREE = '78b817fec87e593e0a0f6357d84f895b8574bde5'
PINS = {
    'codex-rs/windows-sandbox-rs/src/setup_error.rs': (
        'd9104602bc19af88101fbb5b44f839a1d799c174',
        '37aa38dde9e83ee5f3ce8f267f11afd76fee3400'),
    'codex-rs/windows-sandbox-rs/src/bin/setup_main/win.rs': (
        '1d9340c6db26d6d10c1b3edecb1c9fecc908ef1d',
        '505be9299f9580877449740fd235e988f8c93b7b'),
}
DEP_PINS = {
    'codex-rs/Cargo.lock': '71fc8fa78b5afa076835b29790a5e6b0bd772558',
    'codex-rs/windows-sandbox-rs/Cargo.toml': 'aa41ed5f08608c0275785b2f5e27ec5db08f50dd',
    'codex-rs/windows-sandbox-rs/BUILD.bazel': '8531cb4d664c25de6fbf200c71cb8042d1d8d865',
    'codex-rs/windows-sandbox-rs/src/lib.rs': '11778af7beb645b36401807cf3e31a0dd4deddc0',
    'codex-rs/windows-sandbox-rs/src/setup.rs': '890755d01ca24f5ede1960582eacb9714633a0db',
    'codex-rs/windows-sandbox-rs/src/deny_read_acl.rs': 'dd3bc350e48299fe5a99e8d45eba61a239e5a186',
    'codex-rs/windows-sandbox-rs/src/deny_read_state.rs': 'fd073a4d45c781f0441839708f92e32d0831556c',
    'codex-rs/windows-sandbox-rs/src/acl_deny.rs': '8f73a1a58176a1a15b3476c008cb3682b24f6579',
    'codex-rs/windows-sandbox-rs/src/bin/setup_main/win/read_acl_mutex.rs': 'a96b6a502474a8bab3baa7842f36dfa814c9cc37',
    'codex-rs/core/tests/suite/workspace_roots.rs': '0af48c703785999365e8c538e91840c66aae4c28',
    'codex-rs/core/tests/suite/windows_sandbox.rs': 'cd22ea91c61afdf49b669bfd5e664841036551f4',
}
CONSTRUCTOR = '''impl SetupErrorReport {
    pub fn from_error(error: &anyhow::Error) -> Self {
        match extract_failure(error) {
            Some(failure) => Self {
                code: failure.code,
                message: failure.message.clone(),
            },
            None => Self {
                code: SetupErrorCode::HelperUnknownError,
                message: format!("{error:#}"),
            },
        }
    }
}

'''
OLD_REPORT = '''        let failure = extract_setup_failure(err)
            .map(|f| SetupFailure::new(f.code, f.message.clone()))
            .unwrap_or_else(|| {
                SetupFailure::new(SetupErrorCode::HelperUnknownError, err.to_string())
            });
        let report = SetupErrorReport {
            code: failure.code,
            message: failure.message,
        };
'''
NEW_REPORT = '        let report = SetupErrorReport::from_error(err);\n'
NEW_TESTS = [
    'untyped_setup_report_preserves_context_chain_and_os_error',
    'typed_setup_report_preserves_code_and_message_through_context',
]


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(
        b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(),
        'sha256': hashlib.sha256(data).hexdigest()}


def merkle(leaves):
    nodes = {'': {}}
    for path, leaf in leaves.items():
        parts = path.split('/')
        assert all(p and p not in ('.', '..') for p in parts)
        for i in range(len(parts) - 1):
            parent, child = '/'.join(parts[:i]), '/'.join(parts[:i + 1])
            nodes.setdefault(parent, {})[parts[i]] = ('40000', child, True)
            nodes.setdefault(child, {})
        parent = '/'.join(parts[:-1])
        assert parts[-1] not in nodes[parent]
        nodes[parent][parts[-1]] = (leaf['mode'], leaf['sha'], False)
    hashes = {}
    for path in sorted(nodes, key=lambda p: (p.count('/'), bool(p)), reverse=True):
        body = b''
        for name, (mode, ref, is_tree) in sorted(nodes[path].items(),
                key=lambda kv: (kv[0] + ('/' if kv[1][2] else '')).encode()):
            sha = hashes[ref] if is_tree else ref
            body += mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
        hashes[path] = hashlib.sha1(b'tree ' + str(len(body)).encode() + b'\0' + body).hexdigest()
    return hashes[''], hashes


def validate_tree(data, expected):
    assert data['sha'] == expected and data.get('truncated') is False
    entries = {x['path']: x for x in data['tree']}
    assert len(entries) == len(data['tree'])
    leaves = {p: x for p, x in entries.items() if x['type'] != 'tree'}
    root, dirs = merkle(leaves)
    assert root == expected
    listed_dirs = {p: x['sha'] for p, x in entries.items() if x['type'] == 'tree'}
    assert listed_dirs == {p: sha for p, sha in dirs.items() if p}
    return leaves, dirs


def get_body(envelope):
    if envelope.get('structuredContent') is not None:
        return envelope['structuredContent']['content']
    return json.loads(next(x['text'] for x in envelope['content'] if x['type'] == 'text'))['content']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    root = args.root.resolve()
    inputs = root / 'inputs'
    before, dirs = validate_tree(json.loads((inputs / 'main67-full-tree.json').read_bytes()), SOURCE_TREE)
    assert len(before) == 10582 and len(dirs) == 1571
    after = dict(before)
    sources = []
    texts = {}
    for path, (old_sha, new_sha) in PINS.items():
        old = (inputs / 'preimage' / path).read_bytes()
        new = (inputs / 'candidate' / path).read_bytes()
        assert identity(old)['git_blob'] == old_sha == before[path]['sha']
        assert identity(new)['git_blob'] == new_sha
        assert new.endswith(b'\n') and b'\r' not in new
        after[path] = {**before[path], 'sha': new_sha}
        sources.append({'path': path, 'preimage': identity(old), 'postimage': identity(new)})
        texts[path] = (old.decode(), new.decode())
    candidate_tree, candidate_dirs = merkle(after)
    assert candidate_tree == EXPECTED_TREE and len(candidate_dirs) == 1571
    supplied_after, _ = validate_tree(json.loads((inputs / 'intended-full-tree.json').read_bytes()), EXPECTED_TREE)
    assert supplied_after == after
    changed = sorted(p for p in after if before[p] != after[p])
    assert changed == sorted(PINS)

    setup_path, win_path = list(PINS)
    old_setup, new_setup = texts[setup_path]
    old_win, new_win = texts[win_path]
    assert new_setup.count(CONSTRUCTOR) == 1
    assert new_setup.split('#[cfg(test)]\nmod tests {')[0].replace(CONSTRUCTOR, '', 1) == old_setup.split('#[cfg(test)]\nmod tests {')[0]
    old_test_tail = old_setup[old_setup.index('    #[test]\n'):]
    assert new_setup.endswith(old_test_tail)
    old_tests = re.findall(r'    fn (\w+)\(', old_setup.split('#[cfg(test)]\nmod tests {')[1])
    new_tests = re.findall(r'    fn (\w+)\(', new_setup.split('#[cfg(test)]\nmod tests {')[1])
    assert new_tests == NEW_TESTS + old_tests
    assert old_win.count(OLD_REPORT) == 1 and new_win.count(NEW_REPORT) == 1
    assert old_win.replace(OLD_REPORT, NEW_REPORT, 1) == new_win
    assert new_win.replace(NEW_REPORT, OLD_REPORT, 1) == old_win
    assert new_win.count('extract_setup_failure(&err)') == old_win.count('extract_setup_failure(&err)') == 3
    assert old_win.split('#[cfg(test)]\n#[path = "win_acl_tests.rs"]')[1] == new_win.split('#[cfg(test)]\n#[path = "win_acl_tests.rs"]')[1]
    for name in NEW_TESTS:
        test_body = new_setup.split('fn ' + name + '()', 1)[1].split('\n    #[test]', 1)[0]
        assert 'write_setup_error_report(codex_home.path(), &report)?;' in test_body
        assert 'read_setup_error_report(codex_home.path())?' in test_body
        assert 'SetupFailure::from_report(restored)' in test_body
    assert 'let cause_message = cause.to_string();' in new_setup
    assert 'format!("apply deny-read ACLs: read security descriptor: {cause_message}")' in new_setup
    assert '.context("outer setup context")' in new_setup

    deps, dep_text = [], {}
    for path, sha in DEP_PINS.items():
        data = (inputs / 'dependencies' / path).read_bytes()
        assert identity(data)['git_blob'] == sha == before[path]['sha']
        deps.append({'path': path, **identity(data)})
        dep_text[path] = data.decode()
    cargo = dep_text['codex-rs/windows-sandbox-rs/Cargo.toml']
    lock = dep_text['codex-rs/Cargo.lock']
    lib = dep_text['codex-rs/windows-sandbox-rs/src/lib.rs']
    assert 'anyhow = "1.0"' in cargo and 'tempfile = "3"' in cargo
    assert '[dev-dependencies]\npretty_assertions = { workspace = true }' in cargo
    assert 'name = "anyhow"\nversion = "1.0.104"' in lock
    assert '#[cfg(target_os = "windows")]\nmod setup_error;' in lib
    assert '#[cfg(target_os = "windows")]\npub use setup_error::SetupErrorReport;' in lib
    assert new_win.index('sync_persistent_deny_read_acls(') < new_win.index('match read_acl_mutex_exists()')
    workspace = dep_text['codex-rs/core/tests/suite/workspace_roots.rs']
    metadata_test = workspace.split('async fn workspace_roots_allow_patches_but_protect_metadata_directories()', 1)[1]
    checked = metadata_test.split('assert_ne!(patch_success, Some(false));', 1)[1]
    assert checked.index('read_file(&test, &allowed_path).await?') < checked.index('for directory in PROTECTED_METADATA_DIRECTORIES')

    fresh_gets = []
    for filename, source_path, dep in [
        ('setup_error.postimage.json', setup_path, False),
        ('win.postimage.json', win_path, False),
        ('cargo.dependency.json', 'codex-rs/windows-sandbox-rs/Cargo.toml', True),
        ('build.dependency.json', 'codex-rs/windows-sandbox-rs/BUILD.bazel', True),
        ('lock.dependency.json', 'codex-rs/Cargo.lock', True),
        ('lib.dependency.json', 'codex-rs/windows-sandbox-rs/src/lib.rs', True),
    ]:
        raw = (inputs / 'actual-GET' / filename).read_bytes()
        body = get_body(json.loads(raw)).encode()
        expected = (inputs / ('dependencies' if dep else 'candidate') / source_path).read_bytes()
        assert body == expected
        fresh_gets.append({'record': filename, 'envelope': identity(raw), 'decoded': identity(body), 'full_bytes_equal': True})

    patch = inputs / 'candidate.patch'
    command_results = []
    with tempfile.TemporaryDirectory(prefix='hepta-independent-setup-review-') as td:
        scratch = Path(td)
        for path in PINS:
            dest = scratch / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((inputs / 'preimage' / path).read_bytes())
        for flags, expected_kind in [(['--check'], None), ([], 'candidate'), (['--reverse', '--check'], None), (['--reverse'], 'preimage')]:
            proc = subprocess.run(['git', 'apply', *flags, str(patch)], cwd=scratch, capture_output=True, timeout=30)
            command_results.append({'argv': ['git', 'apply', *flags, '<frozen candidate.patch>'], 'exit': proc.returncode, 'stdout': proc.stdout.decode(), 'stderr': proc.stderr.decode()})
            assert proc.returncode == 0
            if expected_kind:
                assert all((scratch / path).read_bytes() == (inputs / expected_kind / path).read_bytes() for path in PINS)
    result = {
        'schema': 'windows-setup-error-causes-independent-static-v1',
        'source_head': SOURCE_HEAD, 'source_tree': SOURCE_TREE,
        'computed_candidate_tree': candidate_tree, 'source_files': sources,
        'full_tree_verified': {'leaves': len(before), 'directories_including_root': len(dirs), 'changed_paths': changed, 'unchanged_leaves': len(before) - len(changed)},
        'dependencies': deps, 'fresh_full_GETs': fresh_gets,
        'patch_identity': identity(patch.read_bytes()), 'patch_operations': command_results,
        'exact_runtime_delta': 'One constructor addition; one report-construction substitution. All remaining production bytes and original test bodies unchanged.',
        'original_setup_error_tests': old_tests, 'added_setup_error_tests': NEW_TESTS,
        'new_tests_include_real_file_JSON_roundtrip_in_source': True,
        'new_tests_target_os': 'windows', 'tests_executed': False, 'Rust_compiled': False, 'rustfmt_executed': False,
        'new_native_started': False, 'refs_written': False,
        'ACL_cause_status': 'UNKNOWN: preserved originals expose only apply deny-read ACLs; state read/parse/write and ACE operation remain distinguishable possibilities.',
        'read_acl_mutex_position': 'The failing synchronous deny-read operation precedes the background read-grant mutex check.',
        'protected_metadata_scope': 'The original test fails on allowed-file readback before its three protected-directory refusal/physical assertions; no protected-metadata escape established.',
    }
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')


if __name__ == '__main__':
    main()
