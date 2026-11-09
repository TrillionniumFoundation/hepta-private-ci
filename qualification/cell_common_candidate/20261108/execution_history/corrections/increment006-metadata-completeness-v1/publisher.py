"""Add only the approved missing supplementary log and its explicit correction history."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import time

REPO = 'TrillionniumFoundation/hepta-private-ci'
R = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
W = Path('/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e')
C = Path('/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e')
D = R / 'increment006-metadata-correction-preparation-v2'
REL = 'qualification/cell_common_candidate/20261108/execution_history'
ROOT = W / REL
CORRECTION_REL = REL + '/corrections/increment006-metadata-completeness-v1'
BRANCH = 'codex/cell-s0-evidence-20261108-898e'
COMMON_BRANCH = 'codex/cell-s0-common-20261108-898e'
PARENT = 'a9116a22d4cc429e9b34a1327bcb3945280d72d4'
PARENT_TREE = 'cc2aabdda8e465e88279b858e940ce62dd83273f'
PARENT_INDEX = '3a2771028bdcb0778eb4266a02994255d63e7875a1996d2fe6411e800f934664'
PARENT_README = 'b9974c7cd013790544f3284b92a08b4b8958abcd54e9e82397670367a9190744'
PARENT_METADATA = 'cbb251ffaf62807b01d5c10739ce2a65325c4dc1733632cfb3b93923e4af87e0'
SOURCE = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
SOURCE_TREE = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
CURRENT = 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'
MISSING_PATH = REL + '/observations/evidence-addendum-increment-006a/VERIFY.log'
MISSING_BYTES = 6186
MISSING_SHA = '176aa75a9743028dc3d158b52d1a4fdb3fdd0a26bba8eed530eb25cac8a677a2'
ORIGINAL_PUBLISHER_RESULT_SHA = '2a47c7ae33765e64c12c6e32ce2614078077b8dac048bb10e4b1cb069ee30260'
POST_BUFFER_BYTES = 268435456
OBJECT_OVERHEAD_RESERVE_BYTES = 33554432
OUT = R / 'evidence-increment006-metadata-correction-publication-v1'
_created_output = False

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
        'recover-evidence-increment005-publication-',
        'recover-evidence-increment006-publication-',
    )
    return name.endswith('.py') and name.startswith(prefixes)


def main():
    global _created_output
    if not __debug__:
        raise RuntimeError('Admission assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-manifest-sha256', required=True)
    args = parser.parse_args()
    assert len(args.input_manifest_sha256) == 64
    assert all(c in '0123456789abcdef' for c in args.input_manifest_sha256)
    OUT.mkdir(exist_ok=False)
    _created_output = True
    out = OUT
    own_bytes = Path(__file__).read_bytes()
    (out / 'driver.py').write_bytes(own_bytes)
    commands = []

    def write(name, data):
        with (out / name).open('xb') as target:
            target.write(data)

    def run(label, argv, cwd=W, input_bytes=None):
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

    def git(label, *argv, cwd=W):
        return run(label, ['git', *argv], cwd).decode().strip()

    def api(label, path):
        return json.loads(run(label, ['gh', 'api', '--method', 'GET', f'repos/{REPO}/' + path]))

    def common(label):
        identity = {
            'head': git(label + '-head', 'rev-parse', 'HEAD', cwd=C),
            'tree': git(label + '-tree', 'rev-parse', 'HEAD^{tree}', cwd=C),
            'branch': git(label + '-branch', 'branch', '--show-current', cwd=C),
            'status': git(label + '-status', 'status', '--porcelain=v1', '--untracked-files=all', cwd=C),
            'current_sha256': sha((C / 'qualification/cell-research-stages-20261108/CURRENT_RESULT.json').read_bytes()),
        }
        assert identity == {'head': SOURCE, 'tree': SOURCE_TREE, 'branch': COMMON_BRANCH,
                            'status': '', 'current_sha256': CURRENT}
        return identity

    def safe_regular(path):
        info = path.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not path.is_symlink()
        return path.read_bytes()

    def show(label, revision, relative):
        return run(label, ['git', 'show', revision + ':' + relative])

    def additions(label, args_tail, expected):
        data = run(label, ['git', 'diff', '--no-renames', '--name-status', '-z', *args_tail])
        parts = data.split(b'\0')
        assert parts[-1] == b'' and len(parts[:-1]) % 2 == 0
        rows = [(parts[i].decode(), parts[i + 1].decode()) for i in range(0, len(parts) - 1, 2)]
        assert len(rows) == len(expected)
        assert all(status == 'A' for status, _ in rows)
        assert {path for _, path in rows} == set(expected)
        return rows

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
                in_worktree = cwd == str(W) or cwd.startswith(str(W) + '/')
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

    manifest_path = D / 'CORRECTION_INPUTS.json'
    manifest_bytes = safe_regular(manifest_path)
    assert sha(manifest_bytes) == args.input_manifest_sha256
    inputs = json.loads(manifest_bytes)
    assert inputs['parent_commit'] == PARENT and inputs['parent_tree'] == PARENT_TREE
    assert inputs['parent_index_sha256'] == PARENT_INDEX
    assert inputs['parent_readme_sha256'] == PARENT_README
    assert inputs['parent_metadata_sha256'] == PARENT_METADATA
    assert inputs['source_sha'] == SOURCE and inputs['source_tree'] == SOURCE_TREE
    assert inputs['formal_current_sha256'] == CURRENT
    assert inputs['packet_count'] == 81 and inputs['file_member_count_with_overlap'] == 9136
    assert inputs['new_native_tests_executed'] is False
    assert inputs['full_history_cost'] is None and inputs['physical_cost'] is None
    assert inputs['stages'] == {f'S{i}': 'HOLD' for i in range(6)}
    assert inputs['stage_advancement_claimed'] is False
    assert inputs['missing_observation'] == {
        'path': MISSING_PATH, 'bytes': MISSING_BYTES, 'sha256': MISSING_SHA,
    }
    manifest_target = CORRECTION_REL + '/CORRECTION_INPUTS.json'
    audit_target = CORRECTION_REL + '/INDEX_CLOSURE.json'
    assert inputs['manifest_target'] == manifest_target and inputs['runtime_audit_target'] == audit_target
    assert not (W / CORRECTION_REL).exists() and not (W / CORRECTION_REL).is_symlink()
    assert not (ROOT / 'corrections').is_symlink()
    files = inputs['prepared_files']
    assert len(files) == inputs['prepared_file_count']
    assert len({row['target_path'] for row in files}) == len(files)
    prepared = {}
    for row in files:
        relative = Path(row['prepared_relative_path'])
        target = Path(row['target_path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        assert not target.is_absolute() and '..' not in target.parts
        assert target.as_posix().startswith(CORRECTION_REL + '/')
        assert target.as_posix() not in (manifest_target, audit_target)
        data = safe_regular(D / relative)
        assert len(data) == row['bytes'] and sha(data) == row['sha256'] and len(data) <= 512000
        assert not (W / target).exists()
        prepared[target.as_posix()] = data
    assert prepared[CORRECTION_REL + '/publisher.py'] == own_bytes
    assert len(manifest_bytes) <= 512000
    write('original-input-manifest.json', manifest_bytes)

    assert git('evidence-head-before', 'rev-parse', 'HEAD') == PARENT
    assert git('evidence-tree-before', 'rev-parse', 'HEAD^{tree}') == PARENT_TREE
    assert git('evidence-branch-before', 'branch', '--show-current') == BRANCH
    assert not git('evidence-status-before', 'status', '--porcelain=v1', '--untracked-files=all')
    assert not git('evidence-index-before', 'diff', '--cached', '--name-only')
    before_common = common('common-before')
    assert git('publish-url', 'remote', 'get-url', 'publish') == 'https://github.com/' + REPO + '.git'
    assert git('remote-before', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        PARENT, 'refs/heads/' + BRANCH]
    assert api('remote-ref-before', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    original_publication = (R / 'evidence-increment006-publication-v1/RESULT.json').read_bytes()
    assert sha(original_publication) == ORIGINAL_PUBLISHER_RESULT_SHA
    protected = {
        REL + '/manifest.json': PARENT_INDEX,
        REL + '/README.md': PARENT_README,
        REL + '/increment006-metadata.json': PARENT_METADATA,
    }
    protected_bytes = {}
    for number, (path, digest) in enumerate(protected.items(), 1):
        raw = show(f'original-protected-{number}', PARENT, path)
        assert sha(raw) == digest and safe_regular(W / path) == raw
        protected_bytes[path] = raw
    index = json.loads(protected_bytes[REL + '/manifest.json'])
    assert len(index['packets']) == 81
    assert sum(row['file_member_count'] for row in index['packets']) == 9136
    assert index['common_full_repository_ci_green'] is False
    assert index['stages'] == inputs['stages'] and index['full_history_cost'] is None
    metadata = json.loads(protected_bytes[REL + '/increment006-metadata.json'])
    observations = [
        {'path': REL + '/observations/' + row['relative_path'], 'bytes': row['bytes'], 'sha256': row['sha256']}
        for row in metadata['observations']
    ]
    assert len(observations) == 15 and len({row['path'] for row in observations}) == 15
    assert [row for row in observations if row['path'] == MISSING_PATH] == [inputs['missing_observation']]
    expected_index_observations = [
        {'path': row['path'].removeprefix(REL + '/'), 'bytes': row['bytes'], 'sha256': row['sha256']}
        for row in observations
    ]
    assert same_typed(index['increment006_original_metadata_observations'], expected_index_observations)
    original_observation_bytes = {}
    for number, row in enumerate(observations, 1):
        local = safe_regular(W / row['path'])
        assert len(local) == row['bytes'] and sha(local) == row['sha256']
        if row['path'] == MISSING_PATH:
            assert not run('missing-path-absent-from-parent', ['git', 'ls-tree', '-r', '--name-only', PARENT, '--', MISSING_PATH])
        else:
            raw = show(f'original-observation-{number:02}', PARENT, row['path'])
            assert raw == local
        original_observation_bytes[row['path']] = local
    assert safe_regular(R / 'evidence-addendum-increment-006a/VERIFY.log') == original_observation_bytes[MISSING_PATH]
    original_tree_files = run('original-root-file-list', ['git', 'ls-tree', '-r', '--name-only', '-z', PARENT, '--', REL]).split(b'\0')
    original_tree_count = len([x for x in original_tree_files if x])
    assert original_tree_count == inputs['parent_tracked_file_count']

    # Every new destination was enumerated and hashed before touching this tree.
    for target, data in prepared.items():
        destination = W / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as file:
            file.write(data)
    with (W / manifest_target).open('xb') as file:
        file.write(manifest_bytes)
    staged_expected = {MISSING_PATH: original_observation_bytes[MISSING_PATH],
                       **prepared, manifest_target: manifest_bytes}
    run('stage-only-approved-missing-log', ['git', 'add', '-f', '--', MISSING_PATH])
    run('stage-only-enumerated-correction-files', ['git', 'add', '--', *sorted(prepared), manifest_target])
    additions('staged-initial-exact-additions', ['--cached', 'HEAD'], staged_expected)
    stage_observations = []
    for number, row in enumerate(observations, 1):
        raw = show(f'index-original-observation-{number:02}', '', row['path'])
        assert raw == original_observation_bytes[row['path']]
        stage_observations.append(row)
    for number, (path, expected) in enumerate(sorted(staged_expected.items()), 1):
        assert show(f'index-prepared-file-{number:03}', '', path) == expected
    for number, (path, expected) in enumerate(protected_bytes.items(), 1):
        assert show(f'index-protected-{number}', '', path) == expected
    # This audit is emitted only after the actual index checks above succeeded.
    # Its own bytes are subsequently checked in the index and final commit.
    audit = {
        'status': 'prepared_payload_and_original_fifteen_observations_verified_in_git_index',
        'parent_commit': PARENT, 'input_manifest_sha256': sha(manifest_bytes),
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'formal_current_sha256': CURRENT,
        'original_packet_count': 81, 'original_member_entries_with_overlap': 9136,
        'original_index_readme_metadata_bytes_unchanged': True,
        'original_fifteen_observations': stage_observations,
        'initial_additions_verified': [
            {'path': path, 'bytes': len(data), 'sha256': sha(data)}
            for path, data in sorted(staged_expected.items())
        ],
        'audit_self_entry_excluded_to_avoid_recursive_hash': True,
        'audit_own_index_and_commit_checks_required_before_push': True,
        'original_failure_records_unchanged': True,
        'native_tests_executed': False, 'full_history_cost': None, 'physical_cost': None,
        'stages': inputs['stages'], 'stage_advancement_claimed': False,
    }
    audit_bytes = (json.dumps(audit, indent=2) + '\n').encode()
    assert len(audit_bytes) <= 512000
    with (W / audit_target).open('xb') as file:
        file.write(audit_bytes)
    staged_expected[audit_target] = audit_bytes
    run('stage-runtime-index-audit-only', ['git', 'add', '--', audit_target])
    additions('staged-final-exact-additions', ['--cached', 'HEAD'], staged_expected)
    assert show('index-audit-own-bytes', '', audit_target) == audit_bytes
    assert common('common-before-commit') == before_common
    assert safe_regular(manifest_path) == manifest_bytes
    assert git('head-before-commit', 'rev-parse', 'HEAD') == PARENT
    run('staged-whitespace-check', ['git', 'diff', '--cached', '--check'])
    run('normal-additive-commit', ['git', 'commit', '-m', 'docs: preserve omitted verifier log and committed-object readback failure'])
    commit = git('correction-head', 'rev-parse', 'HEAD')
    tree = git('correction-tree', 'rev-parse', 'HEAD^{tree}')
    assert git('correction-parent', 'rev-parse', 'HEAD^') == PARENT
    assert not git('correction-status', 'status', '--porcelain=v1', '--untracked-files=all')
    additions('committed-final-exact-additions', [PARENT, commit], staged_expected)
    for number, (path, expected) in enumerate(sorted(staged_expected.items()), 1):
        assert show(f'committed-added-file-{number:03}', commit, path) == expected
    for number, row in enumerate(observations, 1):
        assert show(f'committed-original-observation-{number:02}', commit, row['path']) == original_observation_bytes[row['path']]
    for number, (path, expected) in enumerate(protected_bytes.items(), 1):
        assert show(f'committed-protected-{number}', commit, path) == expected
    new_tree_files = run('corrected-root-file-list', ['git', 'ls-tree', '-r', '--name-only', '-z', commit, '--', REL]).split(b'\0')
    new_tree_count = len([x for x in new_tree_files if x])
    assert new_tree_count == original_tree_count + len(staged_expected)
    assert common('common-before-push') == before_common
    assert git('remote-final-before', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        PARENT, 'refs/heads/' + BRANCH]
    assert api('remote-ref-final-before', 'git/ref/heads/' + BRANCH)['object']['sha'] == PARENT
    new_objects = inspect_new_objects(commit)
    transport = fresh_transport_admission(new_objects)
    run('push-correction-once', [
        'git', '-c', 'http.version=HTTP/1.1', '-c', f'http.postBuffer={POST_BUFFER_BYTES}',
        'push', '--progress', 'publish', 'HEAD:refs/heads/' + BRANCH,
    ])
    assert git('remote-after', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        commit, 'refs/heads/' + BRANCH]
    assert api('remote-ref-after', 'git/ref/heads/' + BRANCH)['object']['sha'] == commit
    remote_commit = api('remote-commit-after', 'git/commits/' + commit)
    assert remote_commit['sha'] == commit and remote_commit['tree']['sha'] == tree
    assert [row['sha'] for row in remote_commit['parents']] == [PARENT]
    assert git('common-remote-after', 'ls-remote', 'publish', 'refs/heads/' + COMMON_BRANCH).split() == [
        SOURCE, 'refs/heads/' + COMMON_BRANCH]
    assert common('common-after') == before_common
    assert git('evidence-head-final', 'rev-parse', 'HEAD') == commit
    assert not git('evidence-status-final', 'status', '--porcelain=v1', '--untracked-files=all')
    assert safe_regular(manifest_path) == manifest_bytes
    assert (R / 'evidence-increment006-publication-v1/RESULT.json').read_bytes() == original_publication
    result = {
        'status': 'metadata_correction_published_and_exact_commit_objects_verified',
        'finished_at': now(), 'commit': commit, 'tree': tree, 'parent': PARENT, 'branch': BRANCH,
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'formal_current_sha256': CURRENT,
        'packet_count': 81, 'file_member_count_with_overlap': 9136,
        'original_81_packet_paths_and_bytes_unchanged': True,
        'root_index_sha256_unchanged': PARENT_INDEX,
        'root_readme_sha256_unchanged': PARENT_README,
        'original_metadata_sha256_unchanged': PARENT_METADATA,
        'original_observations_complete_in_index_and_commit': 15,
        'new_paths': [
            {'path': path, 'bytes': len(data), 'sha256': sha(data)}
            for path, data in sorted(staged_expected.items())
        ],
        'new_path_count': len(staged_expected),
        'parent_tracked_root_file_count': original_tree_count,
        'corrected_tracked_root_file_count': new_tree_count,
        'old_local_directory_count_is_not_a_committed_file_count': True,
        'input_manifest_sha256': sha(manifest_bytes), 'index_audit_sha256': sha(audit_bytes),
        'original_publisher_receipt_retained_with_its_incomplete_metadata_boundary': True,
        'normal_push_attempt_count': 1, 'automatic_retry': False,
        'git_add_force_was_limited_to_exact_approved_missing_log': MISSING_PATH,
        'no_amend_or_force_push': True, 'transport_admission': transport, 'new_git_objects': new_objects,
        'complete_execution_history': False, 'physical_cost': None, 'full_history_cost': None,
        'native_tests_executed': False, 'stage_advancement_claimed': False, 'stages': inputs['stages'],
        'commands_sha256': sha((out / 'commands.json').read_bytes()),
        'publication_receipt_external_to_its_own_commit': True,
    }
    write('RESULT.json', (json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if _created_output and not (OUT / 'RESULT.json').exists():
            commands = OUT / 'commands.json'
            failure = {
                'status': 'metadata_correction_not_confirmed', 'finished_at': now(),
                'error_type': type(error).__name__, 'error': str(error),
                'remote_publication_state': 'unknown_until_readback',
                'original_published_commit_and_failure_records_not_rewritten': True,
                'native_tests_executed': False, 'automatic_retry': False,
                'full_history_cost': None, 'physical_cost': None,
                'commands_sha256': sha(commands.read_bytes()) if commands.exists() else None,
            }
            with (OUT / 'RESULT.json').open('x') as output:
                output.write(json.dumps(failure, indent=2) + '\n')
        raise
