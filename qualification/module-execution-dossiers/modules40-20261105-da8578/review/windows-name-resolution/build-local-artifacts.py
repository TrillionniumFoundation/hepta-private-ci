#!/usr/bin/env python3
"""Build only the two reviewed Windows test name-resolution postimages."""
from pathlib import Path
import difflib
import hashlib
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parent.parent
INPUT = json.loads((ROOT / 'source-inputs.json').read_text())


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def write_source(kind, path, content):
    destination = ROOT / kind / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content.encode())


for record in INPUT['files'] + INPUT['reviewedParents'] + INPUT['executedPreimages']:
    assert blob(record['content'].encode()) == record['sha'], record['path']
for source, executed in zip(INPUT['files'], INPUT['executedPreimages']):
    assert source['path'] == executed['path']
    assert source['content'] == executed['content']
    assert source['sha'] == executed['sha']

pty = INPUT['files'][0]
old_pty = pty['content']
old_call = 'self.child.as_raw_handle()'
new_call = 'AsRawHandle::as_raw_handle(&self.child)'
assert old_pty.count(old_call) == 3
assert 'use std::os::windows::io::AsRawHandle;\n' in old_pty
assert 'use portable_pty::Child as _;\n' in old_pty
new_pty = old_pty.replace(old_call, new_call)
long_wait = '        match unsafe { WaitForSingleObject(AsRawHandle::as_raw_handle(&self.child).cast(), wait_ms) } {\n'
wrapped_wait = '        match unsafe {\n            WaitForSingleObject(AsRawHandle::as_raw_handle(&self.child).cast(), wait_ms)\n        } {\n'
assert new_pty.count(long_wait) == 1
new_pty = new_pty.replace(long_wait, wrapped_wait, 1)
assert new_pty.replace(wrapped_wait, long_wait, 1).replace(new_call, old_call) == old_pty

sandbox = INPUT['files'][1]
old_sandbox = sandbox['content']
anchor = 'use crate::delete_permission_matrix::DeleteRoute;\n'
explicit_macro = 'use pretty_assertions::assert_eq;\n'
assert old_sandbox.count(anchor) == 1
assert explicit_macro not in old_sandbox
new_sandbox = old_sandbox.replace(anchor, anchor + explicit_macro, 1)
assert new_sandbox.replace(explicit_macro, '', 1) == old_sandbox
assert old_sandbox.count('assert_eq!') == new_sandbox.count('assert_eq!') == 8

reviewed = {record['path']: record for record in INPUT['reviewedParents']}
parent = reviewed['codex-rs/windows-sandbox-rs/src/unified_exec/tests.rs']['content']
sibling = reviewed['codex-rs/windows-sandbox-rs/src/unified_exec/acl_setup_tests.rs']['content']
cargo = reviewed['codex-rs/windows-sandbox-rs/Cargo.toml']['content']
pty_parent = reviewed['codex-rs/utils/pty/src/win/mod.rs']['content']
assert explicit_macro in parent and explicit_macro in sibling
assert '#[path = "delete_permission_tests.rs"]\nmod delete_permission_tests;' in parent
assert 'pretty_assertions = { workspace = true }' in cargo
assert 'impl Child for WinChild' in pty_parent
assert '#[path = "native_observation_tests.rs"]\nmod observation_tests;' in pty_parent

file_rows = []
combined_patch = ''
for source, new in [(pty, new_pty), (sandbox, new_sandbox)]:
    path = source['path']
    old = source['content']
    write_source('before', path, old)
    write_source('after', path, new)
    diff = ''.join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True),
                                       fromfile='a/' + path, tofile='b/' + path))
    patch = f'diff --git a/{path} b/{path}\nindex {blob(old.encode())}..{blob(new.encode())} 100644\n' + diff
    combined_patch += patch
    counters = {}
    for macro in ['assert', 'assert_eq', 'assert_ne', 'matches']:
        pattern = r'\b' + macro + r'\s*!'
        before_count = len(re.findall(pattern, old))
        after_count = len(re.findall(pattern, new))
        assert before_count == after_count
        counters[macro] = before_count
    assert re.findall(r'\bfn\s+(\w+)', old) == re.findall(r'\bfn\s+(\w+)', new)
    assert re.findall(r'"(?:\\.|[^"\\])*"', old) == re.findall(r'"(?:\\.|[^"\\])*"', new)
    assert re.findall(r'(?<!\w)\d[\d_]*(?!\w)', old) == re.findall(r'(?<!\w)\d[\d_]*(?!\w)', new)
    assert len(re.findall(r'\bunsafe\b', old)) == len(re.findall(r'\bunsafe\b', new))
    file_rows.append({
        'path': path, 'beforeBlob': blob(old.encode()), 'afterBlob': blob(new.encode()),
        'beforeSha256': sha256(old.encode()), 'afterSha256': sha256(new.encode()),
        'beforeBytes': len(old.encode()), 'afterBytes': len(new.encode()),
        'postimagePath': str(ROOT / 'after' / path),
        'assertionMacroCountsUnchanged': counters,
        'functionNamesUnchanged': True, 'stringLiteralsUnchanged': True,
        'numericLiteralsUnchanged': True, 'unsafeTokenCountUnchanged': True,
    })
for record in INPUT['reviewedParents']:
    write_source('reviewed-source', record['path'], record['content'])

patch_path = ROOT / 'windows-native-name-resolution.patch'
patch_path.write_text(combined_patch)
check = subprocess.run(['git', 'apply', '--check', '--whitespace=error-all', str(patch_path)],
                       cwd=ROOT / 'before', capture_output=True, text=True)
assert check.returncode == 0, check.stderr

source_commit_path = WORKSPACE / 'candidate-review/platform-797/candidate-source-commit.raw.json'
commit = json.loads(source_commit_path.read_text())
assert commit['sha'] == INPUT['sourceCommit']
assert commit['tree']['sha'] == INPUT['sourceTree']
failure_path = WORKSPACE / 'candidate-review/platform-bb55/failure-details.json'
all_failures = json.loads(failure_path.read_text())['failures']
selected_jobs = {127354042203, 127354042307, 127354042573, 127354042546}
failures = []
for failure in all_failures:
    if failure['jobId'] not in selected_jobs:
        continue
    log = failure_path.parent / failure['fullLog']
    failures.append({
        'runId': failure['runId'], 'jobId': failure['jobId'],
        'headSha': failure['sourceHeadSha'], 'executionBinding': failure['executionBinding'],
        'observedJobStatus': failure['jobStatus'], 'observedJobConclusion': failure['jobConclusion'],
        'jobTerminalAtObservation': failure['jobTerminalAtObservation'],
        'firstError': failure['firstConcreteError'], 'firstErrorAt': failure['firstConcreteErrorAt'],
        'fullLogPath': str(log), 'fullLogSha256': sha256(log.read_bytes()),
    })
assert len(failures) == 4

manifest = {
    'kind': 'minimal_source_only_windows_test_name_resolution_fix',
    'sourceCommit': INPUT['sourceCommit'], 'sourceTree': INPUT['sourceTree'],
    'executedFailureSource': INPUT['executedPreimageCommit'],
    'bothTargetPreimagesIdenticalBetweenFailureSourceAndFrozenSource': True,
    'files': file_rows,
    'patch': {'path': str(patch_path), 'sha256': sha256(patch_path.read_bytes()), 'bytes': patch_path.stat().st_size},
    'changes': {
        'pty': 'Three method calls explicitly resolve the existing std::os::windows::io::AsRawHandle trait; one now-long match header is wrapped without token changes. Both original trait imports remain.',
        'sandbox': 'One explicit pretty_assertions::assert_eq import matches the parent and sibling modules. All eight assertion invocations and the entire test body remain byte-identical.',
    },
    'reviewFindings': {
        'nativeHandle': 'NativeChild.child is std::process::Child. The existing AsRawHandle import is the Windows std trait. Qualified trait calls keep the same borrowed native HANDLE and cast; no handle transfer, fallback, null substitute, access-mask change or process replacement is introduced.',
        'portableTraitRetained': 'portable_pty::Child as _ remains needed to resolve WinChild.wait and WinChild.try_wait; the production parent implements that trait for WinChild.',
        'unsafeBoundary': 'DuplicateHandle and both WaitForSingleObject calls retain their original unsafe scopes, arguments and result handling; OwnedHandle::from_raw_handle stays unchanged.',
        'macro': 'The immediate parent tests.rs imports pretty_assertions::assert_eq, declares the delete-permission child module, and sibling acl_setup_tests.rs uses the same explicit import. The crate already declares pretty_assertions as a dev dependency.',
        'oracle': 'All native access-denied and exit-code-259 checks, child release protocol, delete-route physical readback, host controls, allowed-file deletion, outside-path deletion denials and original assertion operands remain.',
        'budget': 'The original five-second PTY deadline, host wait 5000ms, sandbox timeout 5000ms and collector ten-second limit remain unchanged.',
    },
    'reviewedParentSources': [{'path': item['path'], 'blob': item['sha'], 'sha256': sha256(item['content'].encode())} for item in INPUT['reviewedParents']],
    'failureEvidence': failures,
    'validation': {
        'allFetchedGitBlobsVerified': True,
        'exactAllowedReplacementAndImportChecks': True,
        'originalFunctionStringNumericAndAssertionSequencesOrCountsPreserved': True,
        'localGitApplyCheckWhitespaceErrorAllExitCode': check.returncode,
        'nativeExecuted': False, 'windowsCompilationExecuted': False, 'formatterExecuted': False,
        'sourceReviewOnly': True,
    },
    'scope': {'targetFiles': 2, 'productionSourceChanged': False, 'assertionsRemovedOrWeakened': False,
              'budgetRetryOrSkipChanges': False, 'dependencyOrCiChanges': False,
              'bazelChanges': False, 'remoteSourceRefsOrCiMutated': False},
    'executionBoundary': 'Historical bb55 Windows failures remain bound to their actual run/job source. The 797 Linux/native results are not Windows compilation evidence. This local patch requires the original Windows checks on the next fixed candidate; no Windows pass is claimed.',
}
review_path = ROOT / 'REVIEW.md'
if review_path.exists():
    manifest['reviewDocument'] = {'path': str(review_path), 'sha256': sha256(review_path.read_bytes())}
save_json(ROOT / 'manifest.json', manifest)
print(json.dumps({'patchSha256': manifest['patch']['sha256'], 'manifestSha256': sha256((ROOT / 'manifest.json').read_bytes()),
                  'files': [{'path': item['path'], 'afterBlob': item['afterBlob'], 'afterSha256': item['afterSha256']} for item in file_rows],
                  'gitApplyCheckExitCode': check.returncode}, ensure_ascii=False))
