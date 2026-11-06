#!/usr/bin/env python3
"""Offline byte/source/tree verification; never compiles or launches native code."""
from pathlib import Path
import hashlib
import json
import re
import sys

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent
SRC = ROOT / 'source'
OUT = ROOT / 'candidate'
PREFIX = 'codex-rs/windows-sandbox-rs/src/'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def ident(path):
    data = path.read_bytes()
    return dict(path=str(path.relative_to(ROOT)), bytes=len(data), sha256=sha(data), git_blob=git_blob(data))


def part(text, begin, end):
    assert text.count(begin) == 1 and text.count(end) == 1, (begin, end)
    return text[text.index(begin):text.index(end)]


def merkle(leaves):
    dirs = {''}
    for path in leaves:
        parent = path.rpartition('/')[0]
        while parent:
            dirs.add(parent)
            parent = parent.rpartition('/')[0]
    children = {path: [] for path in dirs}
    for path, (mode, digest) in leaves.items():
        parent, _, name = path.rpartition('/')
        children[parent].append((name, mode, digest))
    result = {}
    for path in sorted(dirs, key=lambda p: p.count('/') + bool(p), reverse=True):
        entries = sorted(children[path], key=lambda e: e[0].encode() + (b'/' if e[1] == '40000' else b''))
        raw = b''.join(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(digest)
                       for name, mode, digest in entries)
        digest = hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        result[path] = digest
        if path:
            parent, _, name = path.rpartition('/')
            children[parent].append((name, '40000', digest))
    return result


tree = json.loads((ROOT / 'evidence/intended-full-tree.json').read_bytes())
assert tree['sha'] == '9a804c7b6e0dd554cdb435f41e06c5c689fffaaf' and tree['truncated'] is False
leaves = {e['path']: (e['mode'], e['sha']) for e in tree['tree'] if e['type'] == 'blob'}
assert len(leaves) == 10589
original_trees = merkle(leaves)
assert len(original_trees) == 1571 and original_trees[''] == tree['sha']
assert all(original_trees[e['path']] == e['sha'] for e in tree['tree'] if e['type'] == 'tree')
pub = json.loads((ROOT / 'evidence/commit-ref-actual.json').read_bytes())
merge = json.loads((ROOT / 'evidence/actual-merge-commit.json').read_bytes())['response']
assert pub['commit'] == pub['actualCommit']['sha'] == '87b8603f21e52063ed54ce89cba26756a3efaab7'
assert pub['tree'] == pub['actualCommit']['tree']['sha'] == tree['sha']
assert merge['sha'] == '09960fe697c9c181e4a7d624e29b49360877b687' and merge['tree']['sha'] == tree['sha']
assert [p['sha'] for p in merge['parents']] == ['67cc5c28c4adf82f6ef97c34a18b8b13f3ac27ed', pub['commit']]

source_files = []
for file in sorted(SRC.rglob('*')):
    if file.is_file():
        rel = file.relative_to(SRC).as_posix()
        assert git_blob(file.read_bytes()) == leaves[rel][1], rel
        source_files.append(ident(file))
readbacks = json.loads((ROOT / 'source-readbacks.actual.json').read_bytes())
assert len(readbacks) == 4
for receipt in readbacks:
    rel = receipt['path'].split('/source/', 1)[1]
    source = ident(SRC / rel)
    for k in ['bytes', 'sha256', 'git_blob']:
        assert source[k] == receipt[k]

paths = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file())
expected_paths = [PREFIX + p for p in ['acl_control_test_support.rs', 'lib.rs', 'token_tests.rs', 'unified_exec/delete_permission_tests.rs']]
assert paths == expected_paths
updates = {}
for path in paths:
    data = (OUT / path).read_bytes()
    assert not (SRC / path).exists() or (SRC / path).read_bytes() != data
    updates[path] = ('100644', git_blob(data))
candidate_leaves = dict(leaves)
candidate_leaves.update(updates)
candidate_trees = merkle(candidate_leaves)
assert len(candidate_leaves) == 10590 and len(candidate_trees) == 1571
changed = sorted(p for p in candidate_leaves if candidate_leaves[p] != leaves.get(p))
assert changed == paths
assert leaves[PREFIX + 'token_neither_privilege_observation.rs'] == candidate_leaves[PREFIX + 'token_neither_privilege_observation.rs']
assert leaves[PREFIX + 'token_integrity_probe_tests.rs'] == candidate_leaves[PREFIX + 'token_integrity_probe_tests.rs']

proofs = []
def same(name, a, b):
    assert a == b, name
    proofs.append(dict(name=name, bytes=len(a.encode()), sha256=sha(a.encode()), equal=True))

pre_token = (SRC / (PREFIX + 'token_tests.rs')).read_bytes().decode()
post_token = (OUT / (PREFIX + 'token_tests.rs')).read_bytes().decode()
case = 'fn workspace_capability_delete_routes_require_the_capability_in_all_four_cells()'
same('token test complete prefix before modified case', pre_token[:pre_token.index(case)], post_token[:post_token.index(case)])
pre_case = pre_token[pre_token.index(case):]
post_case = post_token[post_token.index(case):]
strict_begin = '    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });'
same('token complete original strict half', pre_case[pre_case.index(strict_begin):], post_case[post_case.index(strict_begin):])
assert_begin = '    eprintln!("delete_matrix host_native_errors={host_errors:?}");'
same('token all original host error and physical assertions', part(pre_case, assert_begin, strict_begin), part(post_case, assert_begin, strict_begin))
expression = part(pre_case, '    let host_errors: Vec<_> = host\n', '    let host_outcomes = host.finish(')
expression = expression.replace('    let host_errors: Vec<_> = host\n', '    host\n').removesuffix(';\n') + '\n'
inner = part(post_case, '        host\n', '    };\n    acl_control.ensure_restored()?;')
same('Rust original host four operation expression (indent adaptation only)',
     ''.join('    ' + line for line in expression.splitlines(keepends=True)), inner)
assert post_case.index('acl_control.impersonate()?') < post_case.index('        host\n')
assert post_case.index('acl_control.ensure_restored()?') < post_case.index('host.finish(')

pre_cmd = (SRC / (PREFIX + 'unified_exec/delete_permission_tests.rs')).read_bytes().decode()
post_cmd = (OUT / (PREFIX + 'unified_exec/delete_permission_tests.rs')).read_bytes().decode()
same('complete original matrix_script and imports', pre_cmd[:pre_cmd.index('#[test]')], post_cmd[:post_cmd.index('#[test]')])
strict_begin_cmd = '        let allowed_file = workspace.join("allowed-file");'
same('CMD complete original strict half', pre_cmd[pre_cmd.index(strict_begin_cmd):], post_cmd[post_cmd.index(strict_begin_cmd):])
cmd_assert = '        eprintln!("delete_matrix host_cmd_status={status} output={host_log:?}");'
same('CMD all original host status, roster, physical assertions', part(pre_cmd, cmd_assert, strict_begin_cmd), part(post_cmd, cmd_assert, strict_begin_cmd))
same('CMD original fixture/guard/script setup', pre_cmd[:pre_cmd.index('        let host_log = fs::File::create(')],
     post_cmd[:post_cmd.index('        // This host comparison is an ordinary ACL control,')])
assert pre_cmd.count('/*dwmilliseconds*/ 5_000') == 1
assert 'child.kill()' in pre_cmd and 'child.wait()' in pre_cmd
assert 'std::process::Command::new' not in post_cmd
for pre, post in [(pre_token, post_token), (pre_cmd, post_cmd)]:
    assert re.findall(r'#\[(?:test|ignore)[^\]]*\]', pre) == re.findall(r'#\[(?:test|ignore)[^\]]*\]', post)
    assert re.findall(r'fn ([A-Za-z0-9_]+)\(', pre) == re.findall(r'fn ([A-Za-z0-9_]+)\(', post)

helper = (OUT / (PREFIX + 'acl_control_test_support.rs')).read_bytes().decode()
obs = (SRC / (PREFIX + 'token_neither_privilege_observation.rs')).read_bytes().decode()
probe = (SRC / (PREFIX + 'token_integrity_probe_tests.rs')).read_bytes().decode()
support = (SRC / (PREFIX + 'token_integrity_probe_support.rs')).read_bytes().decode()
same('8c exact TokenBuffer/token_record/effective_record block',
     part(obs, '// A bounded, aligned native result.', 'fn physical('),
     part(helper, '// A bounded, aligned native result.', 'struct OwnedChild {'))
same('8c exact OwnedChild/Drop/atomic launcher block',
     part(obs, 'struct OwnedChild {', 'fn cmd_observation('),
     part(helper, 'struct OwnedChild {', '/// Only the enabled privilege set differs'))
same('fc9 exact TokenState/token_state block',
     part(probe, '#[derive(Debug, PartialEq, Eq, Serialize)]', 'fn full_restricting_read_token('),
     part(helper, '#[derive(Debug, PartialEq, Eq, Serialize)]', '// A bounded, aligned native result.'))
same('handle ownership Drop body after visibility-only adaptation',
     part(support, 'pub(super) struct Handle(', 'struct Local(').replace('pub(super) struct Handle(pub(super) win::HANDLE);', 'struct Handle(win::HANDLE);'),
     part(helper, 'struct Handle(win::HANDLE);', '#[derive(Debug, PartialEq, Eq, Serialize)]'))
pre_lib = (SRC / (PREFIX + 'lib.rs')).read_bytes().decode()
post_lib = (OUT / (PREFIX + 'lib.rs')).read_bytes().decode()
registration = '\n\n#[cfg(all(test, target_os = "windows"))]\n#[path = "acl_control_test_support.rs"]\nmod acl_control_test_support;'
assert post_lib.count(registration) == 1
same('lib only private test/Windows module registration', pre_lib, post_lib.replace(registration, ''))
assert '#[test]' not in helper and '#[ignore]' not in helper
assert helper.count('CreateRestrictedToken(') == 1
assert 'CreateRestrictedToken(base.0, security::DISABLE_MAX_PRIVILEGE,' in helper
assert '/*restrictedsidcount*/ 0, std::ptr::null(), &mut stripped)' in helper
assert 'AdjustTokenPrivileges(' not in helper and 'SetTokenInformation(' not in helper
assert helper.count('/*dwmilliseconds*/ 5_000') == 3
assert 'script.extend(fs::read(script_path)?);' in helper
assert '"/d".to_owned(),\n            "/c".to_owned(), gated_path' in helper
assert 'let cwd = std::env::current_dir()?;' in helper
assert 'env.retain(|existing, _| !existing.eq_ignore_ascii_case(name));' in helper
assert 'release_flags & win::HANDLE_FLAG_INHERIT == 0' in helper
assert helper.index('"actual ACL child token differs before release"') < helper.index('let bytes = b"release-owned-fixture\\r\\n";')
assert helper.index('drop(release);') < helper.index('let terminated = child.job.terminate();')
assert helper.index('accounting.ActiveProcesses == 0') < helper.index('child.cleaned = true;')
assert helper.index('child.cleaned = true;') < helper.index('let exit = work?;')
donor_gate = part(obs, '    let mut script = concat!(', '    let mut env: HashMap<String, String>')
new_gate = part(helper, '        let mut script = concat!(', '        script.extend(fs::read(script_path)?);')
def concatenated_strings(code):
    return ''.join(json.loads(token) for token in re.findall(r'"(?:\\.|[^"\\])*"', code))
expected_gate = concatenated_strings(donor_gate).replace('NEITHER_INPUT_RELEASED', 'ACL_CONTROL_INPUT_RELEASED')
expected_gate = expected_gate.replace('@echo off\r\n', '@echo off\r\nsetlocal EnableExtensions DisableDelayedExpansion\r\n', 1) + 'endlocal\r\n'
same('native12 gate runtime bytes plus local mode scope restored before original script',
     expected_gate, concatenated_strings(new_gate))
assert helper.count('env.retain(|name, _| !name.eq_ignore_ascii_case("B11_RELEASE"));') == 1
assert helper.index('env.insert(name.clone(), value.clone());') < helper.index('env.retain(|name, _| !name.eq_ignore_ascii_case("B11_RELEASE"));') < helper.index('let mut child = spawn_observation_child(')
for name, digest in [('lib.rs', '208e17fcedc894663b5eaa6dc2d2c5d1991967d7'),
                     ('token_tests.rs', 'ba51c9e5e30f0e614451c02c54b40a6ea40f9ada'),
                     ('unified_exec/delete_permission_tests.rs', '14a9cae9a7913ebc53a34ac3e1d3e038bc88d004')]:
    assert git_blob((OUT / (PREFIX + name)).read_bytes()) == digest

native_log = ROOT / 'evidence/native12-whole.original.log'
assert ident(native_log)['sha256'] == '36c31fd6f11301673685d00f5e6c63d0a797650148d215cd01b4db5f168f397d'
observed = {}
for line_no, line in enumerate(native_log.read_bytes().decode().splitlines(), 1):
    marker = 'PROBE_OBSERVATION_ONLY neither_privileges '
    if marker not in line:
        continue
    kind, _, payload = line.split(marker, 1)[1].partition(' ')
    if kind == 'complete':
        observed[kind] = payload
    else:
        observed.setdefault(kind, []).append(dict(line=line_no, value=json.loads(payload)))
assert observed['complete'] == 'subjects=2 matrices=5 routes=4 rust_contexts=3 cmd_contexts=2 owned_child_processes=2 observation_only=true isolation_qualified=false'
assert len(observed['child_before_release']) == len(observed['child_finished']) == len(observed['cmd_physical']) == 2
for i, subject in enumerate(['ordinary', 'disabled']):
    before = observed['child_before_release'][i]['value']
    finished = observed['child_finished'][i]['value']
    physical = observed['cmd_physical'][i]['value']
    assert before['subject'] == finished['subject'] == physical['subject'] == subject
    expected = observed['subjects'][0]['value']['ordinary' if i == 0 else 'disable_max_privilege']
    actual = before['token']
    assert actual['identity'] == expected['identity'] and actual['privileges'] == expected['privileges'] and actual['token_type'] == 1
    assert finished['work_error'] is None and finished['exit'] == 0 and finished['cleanup_wait'] == 0
    assert finished['terminate_error'] is None and finished['accounted'] != 0 and finished['active_processes'] == 0
    assert physical['command_exit_codes'] == [[0, 0]] * 4
    for j, outcome in enumerate(physical['outcomes']):
        assert outcome['file_deleted'] is outcome['directory_deleted'] is (i == 0 or j > 0)

result = dict(
    revision='v2_private_gate_local_modes_and_alias_removal',
    status='STATIC_CANDIDATE_ONLY_NOT_COMPILED_OR_NATIVE_QUALIFIED',
    source_commit=pub['commit'], source_merge=merge['sha'], source_tree=tree['sha'],
    expected_candidate_tree=candidate_trees[''], leaf_count=10590, directory_count=1571,
    changed_paths=changed, source_files=source_files,
    candidate_files=[ident(OUT / path) for path in paths],
    original_byte_preservation=proofs, original_test_roster_unchanged=True,
    original_v3_and_probe_unchanged=True, production_token_desktop_unchanged=True,
    native12_donor_evidence=dict(log=ident(native_log), xml=ident(ROOT / 'evidence/native12-whole.original.xml'),
                               completed_observation=observed, applies_to_candidate=False),
    budget_note='d851 already has a 5000 ms host wait; candidate preserves it and adds v3 owned-Job bounded cleanup. It does not widen original strict 5000 ms / collect 10 s budgets.',
    limits=['No causal attribution to any single privilege.',
            'New host premise can expose deeper unchanged strict failures; no prediction that fail count decreases.',
            'Native12 qualifies the donor observation, not this uncompiled four-path candidate.',
            'No ref, CI, native, Cargo, rustfmt, just test/fix/fmt operation was performed.'],
)
print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
