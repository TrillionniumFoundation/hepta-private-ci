"""Publish the reviewed 009a checkpoint with exact staged and committed file closure."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import time

REPO = 'TrillionniumFoundation/hepta-private-ci'
WORK = Path('/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e')
COMMON = Path('/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e')
RECORDS = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
REL = 'qualification/cell_common_candidate/20261108/execution_history'
ROOT = WORK / REL
BRANCH = 'codex/cell-s0-evidence-20261108-898e'
COMMON_BRANCH = 'codex/cell-s0-common-20261108-898e'
PARENT = '8ca3f19c69f2f14a42aa5fbe3ff72af807c65ff2'
PARENT_TREE = '2e734a7f4bf5a24b9876f44b303e96e36a8cd5ec'
PARENT_INDEX = 'e2cf90360430c0db3dde19f3ef1e00466469b363f23b338e1f9db24a114edd7b'
PARENT_README = 'e0c3e6c5005974dc04a205b83061b2d2cae520f9966d5333b4bbf20deaf7113b'
SOURCE = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
SOURCE_TREE = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
CURRENT = 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'
APPEND_RESULT = RECORDS / 'evidence-addendum-increment-009a/RESULT.json'
APPEND_RESULT_SHA = 'ac8fc7048f5d5f9976a4ee3ab1f9689f1679a8732346ef6de6cec4b5a112ea82'
APPEND_MANIFEST_SHA = 'c8351b7d4bb6071ff594432a5ba2b318204475c3561f77665340b43310e38f19'
INPUTS = RECORDS / 'increment009-six-ready-packet-preparation-v2/DRAFT_INPUTS.json'
INPUTS_SHA = '6cda57d0cd1dc1ec4c25248285c1c55549ab7c6511d8b0d7a8040e15ef782f77'
APPENDER = RECORDS / 'append-evidence-increment-009-draft-v1.py'
APPENDER_SHA = '02b05621f874c64dd39831f1ec252a9f53ccdb3d2c153b140f50936a045e4080'
HELPER_SHA = '3282737cc2d660a95a157ea43c222922a3753e3dd6ed5a39456d7ea36615f660'
VERIFIER_SHA = '50e086000bf0a2a414a00e0afb6010bec0394c9b5553e159b80fa9526f3846d7'
EXPECTED_PACKETS = 93
EXPECTED_MEMBERS_WITH_OVERLAP = 11108
PARENT_FILE_COUNT = 1348
MAX_FILE_BYTES = 512000
POST_BUFFER_BYTES = 268435456
OBJECT_OVERHEAD_RESERVE_BYTES = 33554432
OUTPUT = RECORDS / 'evidence-increment009-publication-v1'
OWN_NAME = 'publish-evidence-increment-009-v1.py'
METADATA_REL = REL + '/increment009-metadata.json'
AUDIT_REL = REL + '/increment009-publication-index-closure.json'
PATTERN_REL = REL + '/increment009-publication-pattern-review.json'
VERIFY_REL = REL + '/observations/evidence-addendum-increment-009a/VERIFY.log'
SUPPLEMENTARY_PATHS = (
    'core-output-6ec5993-desktop-dependency-strict-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-core-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-appserver-failed-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-agentd-root-history-independent-verification-v2/RESULT.json',
    'core-output-6ec5993-desktop-posthoc-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json',
    'evidence-increment008-publication-v1/RESULT.json',
    'evidence-increment008-publication-v1/commands.json',
    'evidence-increment008-independent-readback-v1/RESULT.json',
    'evidence-increment008-independent-readback-v1/commands.json',
    'pr5397-status009-v6-publication-observation-v1.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/H_PTY_READ_ORIGINAL.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/v1-to-v2.patch',
    'verify-desktop-6ec-source-publication-history-v1.py',
    'verify-desktop-6ec-source-publication-history-v2.py',
    'desktop-6ec-source-publication-history-seal-launch-v1/RESULT.json',
    'desktop-6ec-source-publication-history-seal-launch-v1/stdout',
    'desktop-6ec-source-publication-history-seal-launch-v1/stderr',
)
OBSERVATION_PATHS = (
    'core-output-6ec5993-desktop-dependency-strict-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-core-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-appserver-failed-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-desktop-agentd-root-history-independent-verification-v2/RESULT.json',
    'core-output-6ec5993-desktop-posthoc-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v2/RESULT.json',
    'evidence-increment008-publication-v1/RESULT.json',
    'evidence-increment008-publication-v1/commands.json',
    'evidence-increment008-independent-readback-v1/RESULT.json',
    'evidence-increment008-independent-readback-v1/commands.json',
    'pr5397-status009-v6-publication-observation-v1.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/RESULT.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/H_PTY_READ_ORIGINAL.json',
    'core-output-6ec5993-source-publication-history-independent-verification-v1/v1-to-v2.patch',
    'verify-desktop-6ec-source-publication-history-v1.py',
    'verify-desktop-6ec-source-publication-history-v2.py',
    'desktop-6ec-source-publication-history-seal-launch-v1/RESULT.json',
    'desktop-6ec-source-publication-history-seal-launch-v1/stdout',
    'desktop-6ec-source-publication-history-seal-launch-v1/stderr',
    'evidence-addendum-increment-009a/RESULT.json',
    'evidence-addendum-increment-009a/PATTERN_REVIEW.json',
    'evidence-addendum-increment-009a/VERIFY.log',
    'increment009-six-ready-packet-preparation-v2/DRAFT_INPUTS.json',
    'append-evidence-increment-009-draft-v1.py',
    'prepare-increment009-six-ready-packets-v2.py',
    'increment009-six-ready-packet-preparation-v2/RESULT.json',
    'increment009-six-ready-packet-preparation-v2/NEW_SOURCE_OBSERVATIONS.json',
    'increment009-six-ready-packet-preparation-v2/METADATA-BUDGET.json',
    'increment009-six-ready-packet-preparation-v2/EXACT_INPUT_WHITELIST.json',
    'increment009-six-ready-packet-preparation-v2/SUPPLEMENTARY_METADATA_SCOPE.json',
    'increment009-six-ready-packet-preparation-v2/INPUTS_AFTER.json',
    'increment009-six-ready-packet-preparation-v2/READ_ONLY_COMMANDS.json',
    'increment009-appender-independent-candidate-review-v1.json',
    'increment009-actual-inputs-independent-candidate-review-v1/RESULT.json',
    'read-increment009-actual-inputs-independent-candidate-v1.py',
    'publish-evidence-increment-009-v1.py',
    'check-increment009-publisher-preparation-v1.py',
    'increment009-publisher-preparation-v1/CHECKS.json',
    'evidence-addendum-increment-009a-launch-v1/REQUEST.json',
    'evidence-addendum-increment-009a-launch-v1/RESULT.json',
    'evidence-addendum-increment-009a-launch-v1/stdout',
    'evidence-addendum-increment-009a-launch-v1/stderr',
    'increment009-publication-draft-v1/README_PREPARATION.json',
    'increment009-publication-draft-v1/readme-check.stdout',
    'increment009-publication-draft-v1/readme-check.stderr',
    'increment009-publication-draft-v1/SUPPLEMENTARY_WHITESPACE.json',
    'evidence-increment009-final-README.md',
    'increment009-readme-final-preparation-v2/RESULT.json',
    'increment009-readme-final-preparation-v2/commands.json',
)
REVIEWED_PATCH_WHITESPACE_EXEMPTIONS = {
    REL + '/reviewed_changes/core-output-45a-reviewed.patch': {'bytes': 25852, 'sha256': 'b7e4cfb754a4c0bad55dc15ad9ee67a2932dc4a386223845a5686be275e04e6f', 'reason': 'Preserve reviewed Git diff context-only blank lines byte-for-byte'},
    REL + '/reviewed_changes/remote-timer-6ec-reviewed.patch': {'bytes': 1651, 'sha256': '4b7a8813bd83b07a26050d9859bbbf5d0f20a914ca1d378804cf5530dae88a42', 'reason': 'Preserve reviewed Git diff context-only blank lines byte-for-byte'},
    REL + '/reviewed_changes/remote-timer-6ec-frozen.patch': {'bytes': 1919, 'sha256': '4a5b2dba27bc88ca5ad16a909dc66a7368f08c23096917e3139618a609fb3866', 'reason': 'Preserve reviewed Git diff context-only blank lines byte-for-byte'},
}
_output_created_by_this_invocation = False


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def same_typed(actual, expected):
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(
            same_typed(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            same_typed(left, right) for left, right in zip(actual, expected)
        )
    return actual == expected


def is_evidence_python_script(argv):
    # Inspect the interpreter's script argument, not text supplied to -c or -m.
    # Option values are not scripts, and a standalone '-' means stdin.
    options = iter(argv[1:])
    script = None
    for arg in options:
        if arg in (b'-c', b'-m', b'-'):
            return False
        if arg == b'--':
            script = next(options, None)
            break
        if arg in (b'-W', b'-X', b'--check-hash-based-pycs'):
            next(options, None)
            continue
        if arg.startswith(b'-'):
            continue
        script = arg
        break
    if script is None:
        return False
    name = Path(os.fsdecode(script)).name
    prefixes = (
        'publish-evidence-increment-005', 'publish-evidence-increment-006',
        'publish-evidence-increment-007', 'publish-evidence-increment-008',
        'recover-evidence-increment005-publication-',
        'recover-evidence-increment006-publication-',
        'recover-evidence-increment007-publication-', 'recover-evidence-increment008-publication-',
        'publish-evidence-increment-009', 'recover-evidence-increment009-publication-',
    )
    return name.endswith('.py') and name.startswith(prefixes)


def main():
    global _output_created_by_this_invocation
    if not __debug__:
        raise RuntimeError('All admission assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-index', required=True)
    parser.add_argument('--readme-sha256', required=True)
    parser.add_argument('--metadata-sha256', required=True)
    parser.add_argument('--packet-count', type=int, required=True)
    args = parser.parse_args()
    for digest in (APPEND_RESULT_SHA, APPEND_MANIFEST_SHA):
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'Draft is not executable before actual append pins are reviewed'
    assert args.expected_index == APPEND_MANIFEST_SHA
    assert args.packet_count == EXPECTED_PACKETS
    for digest in (args.readme_sha256, args.metadata_sha256):
        assert len(digest) == 64 and all(c in '0123456789abcdef' for c in digest)
    out = OUTPUT
    out.mkdir(exist_ok=False)
    _output_created_by_this_invocation = True
    own_bytes = Path(__file__).read_bytes()
    (out / 'driver.py').write_bytes(own_bytes)
    commands = []

    def write(name, data):
        with (out / name).open('xb') as target:
            target.write(data)

    def run(label, argv, cwd=WORK, input_bytes=None):
        assert label not in {row['label'] for row in commands}
        row = {'label': label, 'argv': argv, 'cwd': str(cwd), 'started_at': now(),
               'output_mode': 'file_backed_no_subprocess_kill_timeout'}
        if input_bytes is not None:
            row.update(stdin_bytes=len(input_bytes), stdin_sha256=sha(input_bytes))
        commands.append(row)
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        started = time.monotonic()
        stdout, stderr = out / (label + '.stdout'), out / (label + '.stderr')
        with stdout.open('xb') as sout, stderr.open('xb') as serr:
            process = subprocess.run(argv, cwd=cwd, input=input_bytes, stdout=sout, stderr=serr)
        data, errors = stdout.read_bytes(), stderr.read_bytes()
        row.update(exit_code=process.returncode, finished_at=now(),
                   elapsed_seconds=time.monotonic() - started,
                   stdout_bytes=len(data), stdout_sha256=sha(data),
                   stderr_bytes=len(errors), stderr_sha256=sha(errors))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert process.returncode == 0, label
        return data

    def git(label, *argv, cwd=WORK):
        return run(label, ['git', *argv], cwd=cwd).decode().strip()

    def api(label, path):
        return json.loads(run(label, ['gh', 'api', '--method', 'GET', f'repos/{REPO}/' + path]))

    def common_clean(label):
        identity = {
            'source_sha': git(label + '-head', 'rev-parse', 'HEAD', cwd=COMMON),
            'source_tree': git(label + '-tree', 'rev-parse', 'HEAD^{tree}', cwd=COMMON),
            'branch': git(label + '-branch', 'branch', '--show-current', cwd=COMMON),
            'status': git(label + '-status', 'status', '--porcelain=v1', '--untracked-files=all', cwd=COMMON),
            'current_sha256': sha((COMMON / 'qualification/cell-research-stages-20261108/CURRENT_RESULT.json').read_bytes()),
        }
        assert identity == {'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'branch': COMMON_BRANCH,
                            'status': '', 'current_sha256': CURRENT}
        return identity

    def safe_regular(path):
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink(), str(path)
        assert info.st_size <= MAX_FILE_BYTES, str(path)
        raw = path.read_bytes()
        after = path.lstat()
        assert (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) == (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), str(path)
        assert len(raw) == info.st_size
        return raw

    def blob(raw):
        return hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()

    def inventory():
        assert ROOT.is_dir() and not ROOT.is_symlink()
        result = {}
        for path in sorted(ROOT.rglob('*')):
            assert not path.is_symlink(), str(path)
            if path.is_dir():
                continue
            raw = safe_regular(path)
            result[path.relative_to(WORK).as_posix()] = {
                'mode': '100755' if path.stat().st_mode & 0o111 else '100644',
                'oid': blob(raw), 'bytes': len(raw), 'sha256': sha(raw),
            }
        return result

    def tree_map(label, revision):
        raw = run(label, ['git', 'ls-tree', '-r', '-z', revision, '--', REL])
        result = {}
        for row in raw.split(b'\0'):
            if not row:
                continue
            head, encoded_path = row.split(b'\t', 1)
            mode, kind, oid = head.decode('ascii').split()
            path = encoded_path.decode('utf-8')
            assert path.startswith(REL + '/') and kind == 'blob' and mode in ('100644', '100755')
            assert path not in result and len(oid) == 40
            result[path] = {'mode': mode, 'oid': oid}
        return result

    def index_map(label):
        raw = run(label, ['git', 'ls-files', '--stage', '-z', '--', REL])
        result = {}
        for row in raw.split(b'\0'):
            if not row:
                continue
            head, encoded_path = row.split(b'\t', 1)
            mode, oid, stage = head.decode('ascii').split()
            path = encoded_path.decode('utf-8')
            assert stage == '0' and mode in ('100644', '100755') and path.startswith(REL + '/')
            assert path not in result and len(oid) == 40
            result[path] = {'mode': mode, 'oid': oid}
        return result

    def git_projection(files):
        return {path: {'mode': row['mode'], 'oid': row['oid']} for path, row in files.items()}

    def exact_changes(label, args_tail, expected):
        raw = run(label, ['git', 'diff', '--no-renames', '--name-status', '-z', *args_tail])
        parts = raw.split(b'\0')
        assert parts[-1] == b'' and len(parts[:-1]) % 2 == 0
        result = {}
        for offset in range(0, len(parts) - 1, 2):
            status, path = parts[offset].decode(), parts[offset + 1].decode()
            assert path not in result and status in ('A', 'M')
            result[path] = status
        assert result == expected, (label, result, expected)

    def verify_blobs(label, revision, paths, expected_files):
        selected = sorted(paths)
        assert selected and len(selected) == len(set(selected))
        request = ''.join(revision + ':' + path + '\n' for path in selected).encode()
        raw = run(label, ['git', 'cat-file', '--batch'], input_bytes=request)
        cursor = 0
        for path in selected:
            end = raw.index(b'\n', cursor)
            header = raw[cursor:end].decode('ascii').split()
            expected = expected_files[path]
            assert header == [expected['oid'], 'blob', str(expected['bytes'])], path
            cursor = end + 1
            data = raw[cursor:cursor + expected['bytes']]
            assert len(data) == expected['bytes'] and sha(data) == expected['sha256'], path
            assert data == safe_regular(WORK / path), path
            cursor += expected['bytes']
            assert raw[cursor:cursor + 1] == b'\n'
            cursor += 1
        assert cursor == len(raw), label

    def unchanged_old(files, baseline, allowed):
        for path, old in baseline.items():
            if path not in allowed:
                assert files.get(path) == old, path

    def inspect_new_objects(commit):
        object_bytes = run('new-reachable-object-ids', [
            'git', 'rev-list', '--objects', '--no-object-names', commit, '^' + PARENT,
        ])
        object_ids = object_bytes.decode('ascii').splitlines()
        assert 0 < len(object_ids) <= 10000 and len(set(object_ids)) == len(object_ids)
        assert all(len(oid) == 40 and all(c in '0123456789abcdef' for c in oid)
                   for oid in object_ids)
        assert commit in object_ids
        batch_input = ('\n'.join(object_ids) + '\n').encode('ascii')
        sizes_bytes = run('new-reachable-object-sizes', [
            'git', 'cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)',
        ], input_bytes=batch_input)
        rows = [line.split() for line in sizes_bytes.decode('ascii').splitlines()]
        assert len(rows) == len(object_ids)
        assert all(len(row) == 3 and row[0] == oid
                   and row[1] in ('commit', 'tree', 'blob', 'tag')
                   and row[2].isdigit() for row, oid in zip(rows, object_ids))
        total = sum(int(row[2]) for row in rows)
        counts = {kind: sum(row[1] == kind for row in rows)
                  for kind in ('commit', 'tree', 'blob', 'tag')}
        fact = {
            'observed_at': now(), 'old_commit': PARENT, 'new_commit': commit,
            'reachable_new_object_count': len(rows),
            'reachable_new_object_uncompressed_bytes': total,
            'object_type_counts': counts,
            'object_ids_sha256': sha(object_bytes), 'object_sizes_sha256': sha(sizes_bytes),
            'request_local_post_buffer_bytes': POST_BUFFER_BYTES,
            'reserved_overhead_bytes': OBJECT_OVERHEAD_RESERVE_BYTES,
            'is_actual_pack_or_network_byte_count': False,
            'not_a_network_root_cause_claim': True,
        }
        (out / 'new-git-object-observation.json').write_text(json.dumps(fact, indent=2) + '\n')
        assert 0 < total < POST_BUFFER_BYTES - OBJECT_OVERHEAD_RESERVE_BYTES
        return fact

    def fresh_transport_admission(new_objects):
        related = []
        for proc in Path('/proc').glob('[0-9]*'):
            try:
                if int(proc.name) == os.getpid():
                    continue
                executable = Path(os.readlink(proc / 'exe')).name
                is_git = executable in ('git', 'git-remote-https', 'git-remote-http')
                is_python = executable.startswith('python')
                if not (is_git or is_python):
                    continue
                argv = (proc / 'cmdline').read_bytes().split(b'\0')
                cwd = os.readlink(proc / 'cwd')
                in_worktree = cwd == str(WORK) or cwd.startswith(str(WORK) + '/')
                evidence_refs = {BRANCH.encode(), ('refs/heads/' + BRANCH).encode(),
                                 ('HEAD:refs/heads/' + BRANCH).encode()}
                targeted = (is_git and (in_worktree or any(arg in evidence_refs for arg in argv))) or (
                    is_python and is_evidence_python_script(argv))
                if targeted:
                    related.append({'pid': int(proc.name), 'executable_basename': executable,
                                    'in_evidence_worktree_or_descendant': in_worktree})
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                pass
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, value = line.split(':', 1)
            if key in ('MemTotal', 'MemAvailable'):
                memory[key + '_bytes'] = int(value.split()[0]) * 1024
        admitted = {
            'observed_at': now(), 'related_processes': related, 'memory': memory,
            'signals_sent': False, 'scope': 'observable Git or evidence publisher processes',
            'request_local_http_version': 'HTTP/1.1',
            'request_local_post_buffer_bytes': POST_BUFFER_BYTES,
            'reachable_new_object_uncompressed_bytes': new_objects['reachable_new_object_uncompressed_bytes'],
            'network_cause_not_established': True,
            'tls_auth_proxy_and_endpoint_unchanged': True,
            'global_git_configuration_modified': False,
        }
        (out / 'fresh-transport-admission.json').write_text(json.dumps(admitted, indent=2) + '\n')
        assert not related and memory['MemAvailable_bytes'] > 4 * POST_BUFFER_BYTES
        return admitted


    assert git('evidence-head-before', 'rev-parse', 'HEAD') == PARENT
    assert git('evidence-tree-before', 'rev-parse', 'HEAD^{tree}') == PARENT_TREE
    assert git('evidence-branch-before', 'branch', '--show-current') == BRANCH
    assert not git('evidence-staged-before', 'diff', '--cached', '--name-only')
    before_common = common_clean('common-before')
    assert git('evidence-publish-endpoint', 'remote', 'get-url', 'publish') == 'https://github.com/' + REPO + '.git'
    assert git('evidence-remote-before', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        PARENT, 'refs/heads/' + BRANCH]
    assert api('evidence-ref-api-before', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    runs = api('preceding-evidence-ci', f'actions/runs?head_sha={PARENT}&per_page=100')
    assert runs['total_count'] == len(runs['workflow_runs']) and runs['total_count'] <= 100
    assert all(row['head_sha'] == PARENT and row['status'] == 'completed' for row in runs['workflow_runs'])
    parent_files = tree_map('parent-root-tree', PARENT)
    assert len(parent_files) == PARENT_FILE_COUNT
    before_files = inventory()
    assert set(parent_files) <= set(before_files)
    for path, expected in parent_files.items():
        if path != REL + '/manifest.json':
            assert git_projection({path: before_files[path]})[path] == expected, path
    prior_bytes = run('previous-index', ['git', 'show', PARENT + ':' + REL + '/manifest.json'])
    prior_readme = run('previous-readme', ['git', 'show', PARENT + ':' + REL + '/README.md'])
    assert sha(prior_bytes) == PARENT_INDEX and sha(prior_readme) == PARENT_README
    assert safe_regular(ROOT / 'README.md') == prior_readme
    prior = json.loads(prior_bytes)
    assert len(prior['packets']) == 87
    assert sum(row['file_member_count'] for row in prior['packets']) == 10104
    protected_baseline = {path: row for path, row in before_files.items() if path in parent_files}
    write('parent-file-inventory.json', (json.dumps(protected_baseline, indent=2) + '\n').encode())
    exact_changes('tracked-changes-before', ['HEAD'], {REL + '/manifest.json': 'M'})

    append_bytes, input_bytes, appender_bytes = (
        safe_regular(APPEND_RESULT), safe_regular(INPUTS), safe_regular(APPENDER))
    assert sha(append_bytes) == APPEND_RESULT_SHA
    assert sha(input_bytes) == INPUTS_SHA and sha(appender_bytes) == APPENDER_SHA
    appended, inputs = json.loads(append_bytes), json.loads(input_bytes)
    assert appended['phase'] == inputs['phase'] == 'increment-009a'
    assert appended['status'] == 'appended_verified_not_committed'
    assert appended['prior_head'] == inputs['expected_evidence_head'] == PARENT
    assert type(appended['packet_count']) is int and appended['packet_count'] == EXPECTED_PACKETS
    assert inputs['expected_prior_packet_count'] == 87 and inputs['expected_final_packet_count'] == EXPECTED_PACKETS
    assert appended['manifest_sha256'] == APPEND_MANIFEST_SHA
    for field in ('prior_packet_bytes_unchanged', 'original_87_packet_index_entries_unchanged',
                  'required_json_bindings_verified',
                  'original_87_packet_and_all_existing_nonmanifest_file_bytes_unchanged',
                  'supplementary_original_result_commands_links_verified'):
        assert appended[field] is True, field
    assert appended['new_tests_executed'] is False and appended['full_history_cost'] is None
    assert appended['stage_advancement_claimed'] is False
    assert same_typed(appended['common_before'], before_common)
    assert same_typed(appended['common_after'], before_common)
    assert appended['pattern_review']['input_sha256'] == INPUTS_SHA
    assert appended['pattern_review']['findings'] == []
    assert len(appended['added_packets']) == len(inputs['packets']) == 6
    index_path = ROOT / 'manifest.json'
    assert sha(safe_regular(index_path)) == APPEND_MANIFEST_SHA
    index = json.loads(safe_regular(index_path))
    expected_index = json.loads(json.dumps(prior))
    expected_index.update(
        packets=prior['packets'] + appended['added_packets'],
        status='bounded_checkpoint_verified_pending_increment_publication',
        preceding_evidence_commit=PARENT,
        current_common_validation=inputs['current_common_validation'],
        increment009a_supplementary_metadata_observations=appended['supplementary_observations'],
        increment009a_supplementary_metadata_scope=inputs['supplementary_observation_scope'])
    assert same_typed(index, expected_index)
    retained_validation = json.loads(json.dumps(index['current_common_validation']))
    added_keys = (
        'desktop_6ec_dependency_strict_history',
        'desktop_6ec_core_owning_history',
        'desktop_6ec_appserver_failed_owning_history',
        'desktop_6ec_agentd_root_owning_history',
        'desktop_6ec_posthoc_diagnostics_history',
        'quiet_6ec_source_publication_history',
    )
    added = {key: retained_validation['separate_source_observations'].pop(key) for key in added_keys}
    assert same_typed(retained_validation, prior['current_common_validation'])
    source_sha = '6ec5993fec3dcd6a3c569498a1d5b4c277f1c142'
    source_tree = 'b0ddbe6b6f83dc42657260b266774f79c9d1ed90'
    for observation in added.values():
        assert observation['source_sha'] == source_sha and observation['source_tree'] == source_tree
        assert observation['common_source_advanced'] is False and observation['scientific_acceptance'] is False
        assert observation['physical_cost'] is None and observation['full_history_cost'] is None
    strict = added['desktop_6ec_dependency_strict_history']
    assert strict['strict_preparation_status'] == 'prepared_clean' and strict['strict_phase_count'] == 9
    assert same_typed(strict['all_original_phase_returncodes'], [0] * 9) and strict['native_cases_in_this_packet'] == 0
    core = added['desktop_6ec_core_owning_history']
    assert core['status'] == 'PASS' and same_typed(core['counts'], {
        'selected_executed_unique': 3827, 'passed': 3827, 'failed': 0,
        'original_ignored': 9, 'retries': 0, 'leaks': 0, 'required_passed_subset': 4})
    app = added['desktop_6ec_appserver_failed_owning_history']
    assert app['status'] == 'FAIL' and app['driver_returncode'] == app['collect_returncode'] == 1
    assert app['test_returncode'] == 100 and same_typed(app['counts'], {
        'selected_executed_unique': 1348, 'passed': 1345, 'failed_exit101': 3,
        'original_ignored': 2, 'retries': 0, 'leaks': 0, 'required_passed_subset': 5})
    assert app['original_required_five_overall_passed_field'] is False and app['root_cause_all_failures'] is None
    agentd = added['desktop_6ec_agentd_root_owning_history']
    assert agentd['agentd_status'] == 'PASS' and same_typed(agentd['agentd_counts'], {
        'selected_executed_unique': 781, 'passed': 781, 'failed': 0, 'original_ignored': 71,
        'retries': 0, 'leaks': 0, 'required_checkpoint_passed_subset': 13})
    assert same_typed(agentd['Root_counts'], {'separate_ignored_parent_executed': 1, 'parent_passed': 1,
        'child_summaries_additional_acceptance': False})
    assert agentd['host_only_binary_count'] == 29 and agentd['binary_bytes_archived'] is False
    posthoc = added['desktop_6ec_posthoc_diagnostics_history']
    assert posthoc['new_native_tests'] == 0 and posthoc['appserver_original_status'] == 'FAIL'
    assert posthoc['all_appserver_failures_assigned_one_environment_cause'] is False
    publication = added['quiet_6ec_source_publication_history']
    assert publication['status'] == 'existing_frozen_source_normally_published_and_readback_verified'
    assert publication['actual_normal_push_count'] == 1 and publication['source_publication_claimed_by_this_observation'] is True
    assert publication['new_native_tests'] == 0 and publication['actions_count_at_original_observation'] == 0
    assert publication['actions_zero_is_not_CI_success'] is True and publication['workspace_v2_result_not_read_or_inferred'] is True
    assert index['latest_reviewed_common_source_sha'] == SOURCE
    assert index['latest_reviewed_common_source_tree'] == SOURCE_TREE
    assert index['current_common_validation']['source_sha'] == SOURCE
    assert index['current_common_validation']['source_tree'] == SOURCE_TREE
    assert index['common_full_repository_ci_green'] is False
    assert index['current_common_validation']['full_repository_ci']['green'] is False
    assert index['complete_execution_history'] is False and index['full_history_cost'] is None
    assert index['stages'] == {f'S{i}': 'HOLD' for i in range(6)}
    assert index['stage_advancement_claimed'] is False
    assert len(index['packets']) == EXPECTED_PACKETS
    assert sum(row['file_member_count'] for row in index['packets']) == EXPECTED_MEMBERS_WITH_OVERLAP
    assert sha(safe_regular(ROOT / 'verify_packets.py')) == VERIFIER_SHA

    # Derive the exact appender-created file set from the six pinned manifests.
    append_paths = {REL + '/increment-009a-inputs.json', REL + '/increment-009a-pattern-review.json'}
    assert safe_regular(ROOT / 'increment-009a-inputs.json') == input_bytes
    pattern_bytes = safe_regular(RECORDS / 'evidence-addendum-increment-009a/PATTERN_REVIEW.json')
    assert safe_regular(ROOT / 'increment-009a-pattern-review.json') == pattern_bytes
    assert same_typed(json.loads(pattern_bytes), appended['pattern_review'])
    for packet, original in zip(appended['added_packets'], inputs['packets']):
        manifest_path = REL + '/' + packet['manifest_path']
        assert manifest_path == REL + '/packets/' + packet['packet_id'] + '/manifest.json'
        raw = safe_regular(WORK / manifest_path)
        assert sha(raw) == packet['manifest_sha256']
        published = json.loads(raw)
        assert all(same_typed(published[key], value) for key, value in original.items())
        assert len(published['file_members']) == packet['file_member_count']
        assert published['all_original_file_members_verified'] is True
        assert published['required_json_member_bindings_verified'] is True
        append_paths.add(manifest_path)
        chunks, offset = [], 0
        for sequence, chunk in enumerate(published['publication_chunks'], 1):
            path = REL + '/' + chunk['path']
            assert path == REL + '/packets/' + packet['packet_id'] + f'/archive.part{sequence:03}'
            assert chunk['sequence'] == sequence and chunk['offset'] == offset
            data = safe_regular(WORK / path)
            assert len(data) == chunk['bytes'] and sha(data) == chunk['sha256']
            append_paths.add(path)
            chunks.append(data)
            offset += len(data)
        archive = b''.join(chunks)
        assert len(archive) == packet['archive_bytes'] == original['bytes']
        assert sha(archive) == packet['archive_sha256'] == original['sha256']
    supplementary = appended['supplementary_observations']
    assert len(supplementary) == len(SUPPLEMENTARY_PATHS) == 19
    expected_supplementary_paths = {'observations/' + path for path in SUPPLEMENTARY_PATHS}
    assert {row['path'] for row in supplementary} == expected_supplementary_paths
    for row in supplementary:
        path = REL + '/' + row['path']
        raw = safe_regular(WORK / path)
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
        append_paths.add(path)
    assert len(append_paths) == 46
    assert set(before_files) == set(parent_files) | append_paths
    untracked = run('untracked-before', ['git', 'ls-files', '--others', '--exclude-standard', '-z'])
    assert {p.decode() for p in untracked.split(b'\0') if p} == append_paths

    readme_path = RECORDS / 'evidence-increment009-final-README-v2.md'
    metadata_path = RECORDS / 'evidence-increment009-metadata.json'
    readme_bytes, metadata_bytes = safe_regular(readme_path), safe_regular(metadata_path)
    assert sha(readme_bytes) == args.readme_sha256 and sha(metadata_bytes) == args.metadata_sha256
    assert readme_bytes.endswith(prior_readme) and len(readme_bytes) > len(prior_readme)
    assert SOURCE in readme_bytes.decode() and 'S0, S1, S2, S3, S4 and S5 remain HOLD' in readme_bytes.decode()
    metadata = json.loads(metadata_bytes)
    assert metadata['source_sha'] == SOURCE and metadata['source_tree'] == SOURCE_TREE
    assert metadata['parent_evidence_commit'] == PARENT and metadata['parent_evidence_tree'] == PARENT_TREE
    assert metadata['formal_current_sha256'] == CURRENT
    assert metadata['packet_count'] == EXPECTED_PACKETS and type(metadata['packet_count']) is int
    assert metadata['member_entries_with_overlap'] == EXPECTED_MEMBERS_WITH_OVERLAP
    assert metadata['full_history_cost'] is None and metadata['physical_cost'] is None
    assert metadata['new_tests_executed'] is False and metadata['complete_execution_history'] is False
    assert metadata['stages'] == index['stages'] and metadata['stage_advancement_claimed'] is False
    assert same_typed(metadata['append_result'], appended)
    assert same_typed(metadata['supplementary_observation_scope'], inputs['supplementary_observation_scope'])
    assert metadata['readme_sha256'] == args.readme_sha256
    assert metadata['new_observations_index_and_commit_blob_verification_required'] is True
    rows = metadata['observations']
    assert len(rows) == len(OBSERVATION_PATHS) == 49
    assert [row['relative_path'] for row in rows] == list(OBSERVATION_PATHS)
    source_originals, observation_bytes, observations = {}, {}, []
    for row in rows:
        path = Path(row['relative_path'])
        assert not path.is_absolute() and '..' not in path.parts
        source = RECORDS / path
        raw = safe_regular(source)
        assert type(row['bytes']) is int and len(raw) == row['bytes'] and sha(raw) == row['sha256']
        target = REL + '/observations/' + path.as_posix()
        assert target not in observation_bytes
        source_originals[str(source)] = raw
        observation_bytes[target] = raw
        observations.append({'path': target.removeprefix(REL + '/'), 'bytes': len(raw), 'sha256': sha(raw)})
        if target in append_paths:
            assert safe_regular(WORK / target) == raw
        else:
            assert not (WORK / target).exists()
    assert source_originals[str(RECORDS / OWN_NAME)] == own_bytes
    assert source_originals[str(APPEND_RESULT)] == append_bytes
    assert source_originals[str(INPUTS)] == input_bytes
    assert source_originals[str(APPENDER)] == appender_bytes
    # The three readable reviewed patches belong to the immutable 008 baseline.
    # This increment adds no source-patch object and grants no new whitespace exemption.
    assert all(row['kind'] != 'reviewed_source_patch' for row in inputs['supplementary_observations'])
    for path, pin in REVIEWED_PATCH_WHITESPACE_EXEMPTIONS.items():
        data = safe_regular(WORK / path)
        assert len(data) == pin['bytes'] and sha(data) == pin['sha256']
        assert path in parent_files and path not in append_paths
        assert git_projection({path: before_files[path]})[path] == parent_files[path]
    launch = json.loads(source_originals[str(RECORDS / 'evidence-addendum-increment-009a-launch-v1/RESULT.json')])
    assert type(launch['returncode']) is int and launch['returncode'] == 0
    assert launch['append_result']['sha256'] == APPEND_RESULT_SHA
    assert launch['script_sha256'] == APPENDER_SHA and launch['inputs_sha256'] == INPUTS_SHA
    for stream in ('stdout', 'stderr'):
        data = source_originals[str(RECORDS / 'evidence-addendum-increment-009a-launch-v1' / stream)]
        assert same_typed(launch[stream], {'path': str(RECORDS / 'evidence-addendum-increment-009a-launch-v1' / stream), 'bytes': len(data), 'sha256': sha(data)})
    for name, data in (
        ('original-append-result.json', append_bytes), ('original-inputs.json', input_bytes),
        ('original-appender.py', appender_bytes), ('approved-readme.md', readme_bytes),
        ('approved-metadata.json', metadata_bytes)):
        write(name, data)

    # Reuse the original bounded pattern scanner; archive contents are not executed.
    helper_path = RECORDS / 'append-evidence-increment-002-v1.py'
    helper_bytes = safe_regular(helper_path)
    assert sha(helper_bytes) == HELPER_SHA
    spec = importlib.util.spec_from_file_location('reviewed_evidence_patterns', helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    findings, inspected = [], []
    scan_inputs = {**observation_bytes, REL + '/README.md': readme_bytes, METADATA_REL: metadata_bytes}
    for path, data in scan_inputs.items():
        helper.scan('publication-metadata!/' + path, data, findings, inspected)
    pattern = {
        'scope': 'reviewed 009 publication metadata only; archive scan is retained in append result',
        'patterns': list(helper.PATTERNS), 'inspected_item_count_with_overlap': len(inspected),
        'findings': findings, 'not_a_complete_secret_detection_claim': True,
        'append_pattern_review_sha256': sha(pattern_bytes),
    }
    pattern_raw = (json.dumps(pattern, indent=2) + '\n').encode()
    write('METADATA_PATTERN_REVIEW.json', pattern_raw)
    assert not findings
    assert inventory() == before_files
    assert common_clean('common-before-copy') == before_common

    for path, data in observation_bytes.items():
        if path in append_paths:
            continue
        target = WORK / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
    for path, data in ((METADATA_REL, metadata_bytes), (PATTERN_REL, pattern_raw)):
        with (WORK / path).open('xb') as output:
            output.write(data)
    (ROOT / 'README.md').write_bytes(readme_bytes)
    index['increment009_original_metadata_observations'] = observations
    index['status'] = 'bounded_checkpoint_publication_pending_verification'
    index_path.write_text(json.dumps(index, indent=2) + '\n')
    # Format was prepared before approval; this command checks without editing bytes.
    run('canonical-readme-format-check', [str(COMMON / 'node_modules/.bin/prettier'), '--check', str(ROOT / 'README.md')])
    run('verify-all-original-packets', ['python3', str(ROOT / 'verify_packets.py')])
    assert safe_regular(ROOT / 'README.md') == readme_bytes
    assert same_typed(index['packets'][:87], prior['packets'])
    assert same_typed(index['current_common_validation'], inputs['current_common_validation'])
    assert all(safe_regular(Path(path)) == data for path, data in source_originals.items())
    assert safe_regular(readme_path) == readme_bytes and safe_regular(metadata_path) == metadata_bytes
    assert safe_regular(helper_path) == helper_bytes
    index['status'] = 'bounded_checkpoint_verified'
    index_path.write_text(json.dumps(index, indent=2) + '\n')
    modified = {REL + '/manifest.json', REL + '/README.md'}
    new_paths = append_paths | (set(observation_bytes) - append_paths) | {METADATA_REL, PATTERN_REL}
    assert not (new_paths & set(parent_files))
    final_files = inventory()
    assert set(final_files) == set(parent_files) | new_paths
    unchanged_old(final_files, protected_baseline, modified)
    for path, raw in observation_bytes.items():
        assert safe_regular(WORK / path) == raw
    for path in append_paths:
        assert final_files[path] == before_files[path], path
    expected_changes = {path: 'A' for path in new_paths}
    expected_changes.update({path: 'M' for path in modified})
    assert VERIFY_REL in new_paths
    run('tracked-whitespace-check', ['git', 'diff', '--check'])
    run('stage-explicit-file-set', ['git', 'add', '--', *sorted((new_paths | modified) - {VERIFY_REL})])
    run('stage-only-explicit-verifier-log', ['git', 'add', '-f', '--', VERIFY_REL])
    exact_changes('staged-initial-closed-set', ['--cached', 'HEAD'], expected_changes)
    assert index_map('staged-initial-all-file-identities') == git_projection(final_files)
    verify_blobs('index-initial-raw-blob-closure', '', expected_changes, final_files)
    # Emit this audit only after every enumerated new/changed index blob is checked.
    audit = {
        'status': 'all_initial_new_and_modified_git_index_blobs_verified',
        'parent_commit': PARENT, 'parent_tree': PARENT_TREE,
        'parent_committed_root_file_count': PARENT_FILE_COUNT,
        'original_87_packets_and_all_other_parent_blobs_and_modes_unchanged': True,
        'permitted_existing_changes': sorted(modified),
        'append_result_sha256': APPEND_RESULT_SHA, 'append_manifest_sha256': APPEND_MANIFEST_SHA,
        'input_sha256': INPUTS_SHA, 'metadata_sha256': args.metadata_sha256,
        'observations': observations, 'observation_count': len(observations),
        'staged_whitespace_exact_reviewed_patch_exemptions': REVIEWED_PATCH_WHITESPACE_EXEMPTIONS,
        'all_other_staged_paths_remain_subject_to_whitespace_check': True,
        'whitespace_exemption_paths_are_unchanged_historical_blobs': True,
        'new_whitespace_exemptions_added': False,
        'initial_changed_files': [
            {'path': path, 'status': expected_changes[path], **final_files[path]}
            for path in sorted(expected_changes)],
        'parent_file_inventory_sha256': sha((out / 'parent-file-inventory.json').read_bytes()),
        'audit_self_entry_excluded_to_avoid_recursive_hash': True,
        'audit_own_index_and_all_commit_blob_checks_required_before_push': True,
        'publication_file_count_must_come_from_git_tree': True,
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'formal_current_sha256': CURRENT,
        'new_tests_executed': False, 'full_history_cost': None, 'physical_cost': None,
        'stages': index['stages'], 'stage_advancement_claimed': False,
    }
    audit_raw = (json.dumps(audit, indent=2) + '\n').encode()
    assert len(audit_raw) <= MAX_FILE_BYTES
    with (WORK / AUDIT_REL).open('xb') as output:
        output.write(audit_raw)
    new_paths.add(AUDIT_REL)
    expected_changes[AUDIT_REL] = 'A'
    run('stage-runtime-index-audit-only', ['git', 'add', '--', AUDIT_REL])
    final_files = inventory()
    assert set(final_files) == set(parent_files) | new_paths
    unchanged_old(final_files, protected_baseline, modified)
    exact_changes('staged-final-closed-set', ['--cached', 'HEAD'], expected_changes)
    final_index = index_map('staged-final-all-file-identities')
    assert final_index == git_projection(final_files)
    verify_blobs('index-audit-raw-bytes', '', [AUDIT_REL], final_files)
    assert common_clean('common-before-commit') == before_common
    assert git('evidence-head-before-commit', 'rev-parse', 'HEAD') == PARENT
    assert all(safe_regular(Path(path)) == data for path, data in source_originals.items())
    assert safe_regular(readme_path) == readme_bytes and safe_regular(metadata_path) == metadata_bytes
    # Only these three fixed reviewed patch objects may retain Git diff context spaces.
    for path, pin in REVIEWED_PATCH_WHITESPACE_EXEMPTIONS.items():
        raw = safe_regular(WORK / path)
        assert len(raw) == pin['bytes'] and sha(raw) == pin['sha256']
    run('staged-whitespace-check', [
        'git', 'diff', '--cached', '--check', '--', '.',
        *[':(exclude)' + path for path in sorted(REVIEWED_PATCH_WHITESPACE_EXEMPTIONS)],
    ])
    run('staged-stat', ['git', 'diff', '--cached', '--stat'])
    run('commit-evidence', ['git', 'commit', '-m', 'docs: retain desktop owner outcomes and quiet source publication history'])
    commit = git('evidence-head-after', 'rev-parse', 'HEAD')
    tree = git('evidence-tree-after', 'rev-parse', 'HEAD^{tree}')
    assert git('evidence-parent-after', 'rev-parse', 'HEAD^') == PARENT
    assert not git('evidence-status-after', 'status', '--porcelain=v1', '--untracked-files=all')
    exact_changes('committed-final-closed-set', [PARENT, commit], expected_changes)
    committed_files = tree_map('committed-root-file-identities', commit)
    assert committed_files == final_index
    verify_blobs('committed-raw-blob-closure', commit, expected_changes, final_files)
    assert len(committed_files) == PARENT_FILE_COUNT + len(new_paths)
    for path, expected in parent_files.items():
        if path not in modified:
            assert committed_files[path] == expected, path
    assert inventory() == final_files
    assert common_clean('common-before-push') == before_common
    assert git('evidence-remote-final-check', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        PARENT, 'refs/heads/' + BRANCH]
    assert api('evidence-ref-api-final-check', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    new_objects = inspect_new_objects(commit)
    transport_admission = fresh_transport_admission(new_objects)
    # One normal fast-forward push, with request-local transport settings only.
    # Failure or uncertain acknowledgement is retained; this script never retries.
    run('push-evidence', [
        'git', '-c', 'http.version=HTTP/1.1', '-c', f'http.postBuffer={POST_BUFFER_BYTES}',
        'push', '--progress', 'publish', 'HEAD:refs/heads/' + BRANCH,
    ])
    assert git('evidence-remote-after', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        commit, 'refs/heads/' + BRANCH]
    assert api('evidence-ref-api-after', 'git/ref/heads/' + BRANCH)['object']['sha'] == commit
    remote_commit = api('evidence-commit-api-after', 'git/commits/' + commit)
    assert remote_commit['sha'] == commit and remote_commit['tree']['sha'] == tree
    assert [row['sha'] for row in remote_commit['parents']] == [PARENT]
    assert git('common-remote-after', 'ls-remote', 'publish', 'refs/heads/' + COMMON_BRANCH).split() == [
        SOURCE, 'refs/heads/' + COMMON_BRANCH]
    assert git('evidence-local-head-final', 'rev-parse', 'HEAD') == commit
    assert not git('evidence-local-status-final', 'status', '--porcelain=v1', '--untracked-files=all')
    assert common_clean('common-final') == before_common
    assert inventory() == final_files
    assert all(safe_regular(Path(path)) == data for path, data in source_originals.items())
    assert safe_regular(readme_path) == readme_bytes and safe_regular(metadata_path) == metadata_bytes
    result = {
        'status': 'published_and_all_new_metadata_commit_blobs_remote_readback_verified',
        'finished_at': now(), 'branch': BRANCH, 'commit': commit, 'tree': tree, 'parent': PARENT,
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'formal_current_sha256': CURRENT,
        'packet_count': EXPECTED_PACKETS, 'file_member_count_with_overlap': EXPECTED_MEMBERS_WITH_OVERLAP,
        'original_87_packet_paths_bytes_and_index_entries_unchanged': True,
        'all_parent_files_unchanged_except_explicit_manifest_and_readme': True,
        'original_006_correction_and_failure_history_unchanged': True,
        'permitted_existing_changes': sorted(modified),
        'new_paths': sorted(new_paths), 'new_path_count': len(new_paths),
        'all_new_metadata_verified_in_index_and_commit': True,
        'original_metadata_observations': observations, 'metadata_observation_count': len(observations),
        'index_closure_sha256': sha(audit_raw), 'publication_pattern_review_sha256': sha(pattern_raw),
        'published_file_count': len(committed_files), 'published_file_count_source': 'exact committed Git tree',
        'parent_committed_root_file_count': PARENT_FILE_COUNT,
        'max_committed_file_bytes': max(row['bytes'] for row in final_files.values()),
        'manifest_sha256': sha(safe_regular(index_path)), 'readme_sha256': args.readme_sha256,
        'metadata_sha256': args.metadata_sha256,
        'append_receipt_sha256': APPEND_RESULT_SHA, 'append_manifest_sha256': APPEND_MANIFEST_SHA,
        'input_sha256': INPUTS_SHA, 'appender_sha256': APPENDER_SHA,
        'supplementary_008_and_posthoc_original_scope': inputs['supplementary_observation_scope'],
        'staged_whitespace_exact_reviewed_patch_exemptions': REVIEWED_PATCH_WHITESPACE_EXEMPTIONS,
        'all_nonexempt_staged_paths_checked_for_whitespace': True,
        'all_three_historical_readable_patch_blobs_and_modes_preserved': True,
        'transport_admission': transport_admission, 'new_git_objects': new_objects,
        'normal_push_attempt_count': 1, 'automatic_retry': False, 'no_amend_or_force_push': True,
        'git_add_force_limited_to_exact_verifier_log': VERIFY_REL,
        'publication_receipt_is_external_to_its_own_commit': True,
        'complete_execution_history': False, 'full_history_cost': None, 'physical_cost': None,
        'native_tests_executed_by_publisher': False, 'stage_advancement_claimed': False,
        'stages': index['stages'], 'commands_receipt_sha256': sha((out / 'commands.json').read_bytes()),
        'url': f'https://github.com/{REPO}/tree/{commit}/{REL}',
    }
    write('RESULT.json', (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if _output_created_by_this_invocation and not (OUTPUT / 'RESULT.json').exists():
            command_path = OUTPUT / 'commands.json'
            command_bytes = command_path.read_bytes() if command_path.exists() else None
            commands = json.loads(command_bytes) if command_bytes is not None else []
            head, tree = OUTPUT / 'evidence-head-after.stdout', OUTPUT / 'evidence-tree-after.stdout'
            failure = {
                'status': 'publication_not_confirmed', 'finished_at': now(),
                'error_type': type(error).__name__, 'error': str(error),
                'branch': BRANCH, 'parent': PARENT, 'source_sha': SOURCE, 'source_tree': SOURCE_TREE,
                'local_commit': head.read_text().strip() if head.exists() else None,
                'local_tree': tree.read_text().strip() if tree.exists() else None,
                'remote_publication_state': 'unknown_until_readback',
                'push_launch_recorded': any(row['label'] == 'push-evidence' for row in commands),
                'automatic_retry': False, 'native_tests_executed': False,
                'complete_execution_history': False, 'full_history_cost': None, 'physical_cost': None,
                'stages': {f'S{i}': 'HOLD' for i in range(6)}, 'stage_advancement_claimed': False,
                'commands_sha256': sha(command_bytes) if command_bytes is not None else None,
                'publication_receipt_is_external_to_its_own_commit': True,
            }
            with (OUTPUT / 'RESULT.json').open('x') as output:
                output.write(json.dumps(failure, indent=2) + '\n')
        raise
