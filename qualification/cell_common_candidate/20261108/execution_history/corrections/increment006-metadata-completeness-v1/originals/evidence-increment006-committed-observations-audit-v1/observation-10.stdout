"""Publish the reviewed 006a evidence checkpoint once, with exact source and transport gates."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
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
PREVIOUS = '97543a30b941122ee42c99ab95c2dbf639ac6576'
PREVIOUS_INDEX = '33da1f4d0d31c0251fb5a303e72aa31a561b961e01e0c6495b6b234b6857cf9e'
SOURCE = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
SOURCE_TREE = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
CURRENT = 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'
APPEND_RESULT = RECORDS / 'evidence-addendum-increment-006a/RESULT.json'
APPEND_RESULT_SHA = 'b22755ed31cb6a7843d0bb591262c25dea33dd5b914b3485c8d4bfeed9661573'
APPEND_MANIFEST_SHA = '0a39abef29aaecb84805cd02eb546285ed52a460bb4acc69edc19c433ab5fce6'
INPUTS = RECORDS / 'increment006a-inputs.json'
INPUTS_SHA = '9b843f8b5f55aff31be778170b6fe48755886ccc947f00b2a1d46b0bbab7fae4'
APPENDER = RECORDS / 'append-evidence-increment-006-v1.py'
APPENDER_SHA = 'bfa2d336896c2b062c46c98aa09d7d65d8633503fdc3e244730721326d5b91d3'
POST_BUFFER_BYTES = 268435456
OBJECT_OVERHEAD_RESERVE_BYTES = 33554432
EXPECTED_PACKETS = 81
EXPECTED_MEMBERS_WITH_OVERLAP = 9136
OUTPUT = RECORDS / 'evidence-increment006-publication-v1'
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
        'recover-evidence-increment005-publication-',
        'recover-evidence-increment006-publication-',
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
    assert args.expected_index == APPEND_MANIFEST_SHA
    assert args.packet_count == EXPECTED_PACKETS
    out = OUTPUT
    out.mkdir(exist_ok=False)
    _output_created_by_this_invocation = True
    (out / 'driver.py').write_bytes(Path(__file__).read_bytes())
    commands = []

    def run(label, argv, cwd=WORK, input_bytes=None):
        receipt = {'label': label, 'argv': argv, 'cwd': str(cwd), 'started_at': now(),
                   'output_mode': 'file_backed_no_subprocess_kill_timeout'}
        if input_bytes is not None:
            receipt['stdin_bytes'] = len(input_bytes)
            receipt['stdin_sha256'] = sha(input_bytes)
        commands.append(receipt)
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        clock = time.monotonic()
        stdout, stderr = out / (label + '.stdout'), out / (label + '.stderr')
        with stdout.open('xb') as sout, stderr.open('xb') as serr:
            completed = subprocess.run(argv, cwd=cwd, input=input_bytes, stdout=sout, stderr=serr)
        data, errors = stdout.read_bytes(), stderr.read_bytes()
        receipt.update(finished_at=now(), elapsed_seconds=time.monotonic() - clock,
                       exit_code=completed.returncode, stdout_bytes=len(data), stdout_sha256=sha(data),
                       stderr_bytes=len(errors), stderr_sha256=sha(errors))
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert completed.returncode == 0, label
        return data

    def git(label, *argv, cwd=WORK):
        return run(label, ['git', *argv], cwd=cwd).decode().strip()

    def common_clean(label):
        assert git(label + '-head', 'rev-parse', 'HEAD', cwd=COMMON) == SOURCE
        assert git(label + '-tree', 'rev-parse', 'HEAD^{tree}', cwd=COMMON) == SOURCE_TREE
        assert git(label + '-branch', 'branch', '--show-current', cwd=COMMON) == COMMON_BRANCH
        assert not git(label + '-status', 'status', '--porcelain=v1', '--untracked-files=all', cwd=COMMON)
        assert sha((COMMON / 'qualification/cell-research-stages-20261108/CURRENT_RESULT.json').read_bytes()) == CURRENT

    def inspect_new_objects(commit):
        object_bytes = run('new-reachable-object-ids', [
            'git', 'rev-list', '--objects', '--no-object-names', commit, '^' + PREVIOUS,
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
            'observed_at': now(), 'old_commit': PREVIOUS, 'new_commit': commit,
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

    assert git('evidence-head-before', 'rev-parse', 'HEAD') == PREVIOUS
    assert git('evidence-branch-before', 'branch', '--show-current') == BRANCH
    common_clean('common-before')
    remote = git('evidence-publish-endpoint', 'remote', 'get-url', 'publish')
    assert remote == 'https://github.com/' + REPO + '.git'
    assert git('evidence-remote-before', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [PREVIOUS, 'refs/heads/' + BRANCH]
    api_before = json.loads(run('evidence-ref-api-before', ['gh', 'api', f'repos/{REPO}/git/ref/heads/{BRANCH}']))
    assert api_before['object']['sha'] == PREVIOUS
    runs = json.loads(run('preceding-evidence-ci', ['gh', 'api', f'repos/{REPO}/actions/runs?head_sha={PREVIOUS}&per_page=100']))
    assert runs['total_count'] == len(runs['workflow_runs']) and runs['total_count'] <= 100
    assert all(row['head_sha'] == PREVIOUS and row['status'] == 'completed' for row in runs['workflow_runs'])
    prior_bytes = run('previous-index', ['git', 'show', PREVIOUS + ':' + REL + '/manifest.json'])
    assert sha(prior_bytes) == PREVIOUS_INDEX
    prior = json.loads(prior_bytes)
    assert len(prior['packets']) == 72
    protected = tuple(REL + '/packets/' + row['packet_id'] + '/' for row in prior['packets'])
    for label, argv in [('changed-before', ['git', 'diff', '--no-renames', '--name-only', '-z', 'HEAD']),
                        ('untracked-before', ['git', 'ls-files', '--others', '--exclude-standard', '-z'])]:
        paths = run(label, argv).split(b'\0')
        assert all(name.decode().startswith(REL + '/') for name in paths if name)
        assert not any(name.decode().startswith(protected) for name in paths if name)
    original_packet_bytes = {path.relative_to(ROOT).as_posix(): sha(path.read_bytes())
                             for path in (ROOT / 'packets').rglob('*') if path.is_file()}
    index_path = ROOT / 'manifest.json'
    assert sha(index_path.read_bytes()) == args.expected_index
    index = json.loads(index_path.read_bytes())
    assert len(index['packets']) == args.packet_count == EXPECTED_PACKETS
    assert sum(row['file_member_count'] for row in index['packets']) == EXPECTED_MEMBERS_WITH_OVERLAP
    assert same_typed(index['packets'][:72], prior['packets'])
    assert index['status'] == 'bounded_checkpoint_verified_pending_increment_publication'
    assert index['latest_reviewed_common_source_sha'] == SOURCE and index['latest_reviewed_common_source_tree'] == SOURCE_TREE
    assert index['current_common_validation']['source_sha'] == SOURCE
    assert index['current_common_validation']['source_tree'] == SOURCE_TREE
    assert same_typed(index['historical_ba4_original_native_ci'], prior['historical_ba4_original_native_ci'])
    assert index['complete_execution_history'] is False and index['full_history_cost'] is None
    assert index['stages'] == {f'S{i}': 'HOLD' for i in range(6)} and index['stage_advancement_claimed'] is False
    assert sha((ROOT / 'verify_packets.py').read_bytes()) == '50e086000bf0a2a414a00e0afb6010bec0394c9b5553e159b80fa9526f3846d7'
    append_bytes, input_bytes, appender_bytes = (
        APPEND_RESULT.read_bytes(), INPUTS.read_bytes(), APPENDER.read_bytes()
    )
    assert sha(append_bytes) == APPEND_RESULT_SHA
    assert sha(input_bytes) == INPUTS_SHA and sha(appender_bytes) == APPENDER_SHA
    appended, inputs = json.loads(append_bytes), json.loads(input_bytes)
    assert appended['phase'] == inputs['phase'] == 'increment-006a'
    assert appended['status'] == 'appended_verified_not_committed'
    assert appended['prior_head'] == PREVIOUS
    assert type(appended['packet_count']) is int and appended['packet_count'] == EXPECTED_PACKETS
    assert appended['manifest_sha256'] == APPEND_MANIFEST_SHA == args.expected_index
    assert appended['prior_packet_bytes_unchanged'] is True
    assert appended['original_72_packet_index_entries_unchanged'] is True
    assert appended['required_json_bindings_verified'] is True
    assert appended['new_tests_executed'] is False
    assert appended['full_history_cost'] is None and appended['stage_advancement_claimed'] is False
    assert len(appended['added_packets']) == 9
    assert same_typed(index['packets'][72:], appended['added_packets'])
    assert same_typed(index['current_common_validation'], inputs['current_common_validation'])
    assert index['common_full_repository_ci_green'] is False
    assert index['current_common_validation']['full_repository_ci']['green'] is False
    expected_common = {
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE, 'branch': COMMON_BRANCH,
        'status': '', 'current_sha256': CURRENT,
    }
    assert same_typed(appended['common_before'], expected_common)
    assert same_typed(appended['common_after'], expected_common)
    assert appended['pattern_review']['input_sha256'] == INPUTS_SHA
    assert appended['pattern_review']['findings'] == []
    assert (ROOT / 'increment-006a-inputs.json').read_bytes() == input_bytes
    for name, data in (
        ('original-append-result.json', append_bytes),
        ('original-inputs.json', input_bytes),
        ('original-appender.py', appender_bytes),
    ):
        (out / name).write_bytes(data)
    readme = RECORDS / 'evidence-increment006-final-README.md'
    readme_bytes = readme.read_bytes()
    assert sha(readme_bytes) == args.readme_sha256
    assert SOURCE in readme_bytes.decode() and 'S0, S1, S2, S3, S4 and S5 remain HOLD' in readme_bytes.decode()
    metadata_path = RECORDS / 'evidence-increment006-metadata.json'
    metadata_bytes = metadata_path.read_bytes()
    assert sha(metadata_bytes) == args.metadata_sha256
    metadata = json.loads(metadata_bytes)
    assert metadata['source_sha'] == SOURCE and metadata['source_tree'] == SOURCE_TREE
    assert metadata['full_history_cost'] is None and metadata['physical_cost'] is None
    assert metadata['new_tests_executed'] is False and metadata['stages'] == index['stages']
    assert type(metadata['packet_count']) is int and metadata['packet_count'] == EXPECTED_PACKETS
    assert len({row['relative_path'] for row in metadata['observations']}) == len(metadata['observations'])
    assert any(row == {'relative_path': APPEND_RESULT.relative_to(RECORDS).as_posix(),
                       'bytes': len(append_bytes), 'sha256': APPEND_RESULT_SHA}
               for row in metadata['observations'])
    observations = []
    for row in metadata['observations']:
        relative = Path(row['relative_path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        source = RECORDS / relative
        assert source.is_file() and not source.is_symlink() and source.stat().st_nlink == 1
        data = source.read_bytes()
        assert len(data) == row['bytes'] and sha(data) == row['sha256']
        target = ROOT / 'observations' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
        observations.append({'path': target.relative_to(ROOT).as_posix(), 'bytes': len(data), 'sha256': sha(data)})
    with (ROOT / 'increment006-metadata.json').open('xb') as output:
        output.write(metadata_bytes)
    (ROOT / 'README.md').write_bytes(readme_bytes)
    index['increment006_original_metadata_observations'] = observations
    index['status'] = 'bounded_checkpoint_publication_pending_verification'
    index_path.write_text(json.dumps(index, indent=2) + '\n')
    run('canonical-readme-format', [str(COMMON / 'node_modules/.bin/prettier'), '--write', str(ROOT / 'README.md')])
    run('verify-all-original-packets', ['python3', str(ROOT / 'verify_packets.py')])
    assert all(sha((ROOT / path).read_bytes()) == digest for path, digest in original_packet_bytes.items())
    assert all(sha((ROOT / row['path']).read_bytes()) == row['sha256'] for row in observations)
    assert metadata_path.read_bytes() == metadata_bytes and readme.read_bytes() == readme_bytes
    assert APPEND_RESULT.read_bytes() == append_bytes and INPUTS.read_bytes() == input_bytes
    assert APPENDER.read_bytes() == appender_bytes
    assert same_typed(index['packets'][:72], prior['packets'])
    assert same_typed(index['current_common_validation'], inputs['current_common_validation'])
    common_clean('common-after-verification')
    index['status'] = 'bounded_checkpoint_verified'
    index_path.write_text(json.dumps(index, indent=2) + '\n')
    run('diff-check', ['git', 'diff', '--check'])
    files = [path for path in ROOT.rglob('*') if path.is_file()]
    assert all(path.stat().st_size <= 512000 for path in files)
    run('stage-evidence-only', ['git', 'add', '--', REL])
    staged = run('staged-paths', ['git', 'diff', '--cached', '--name-only', '-z']).split(b'\0')
    assert any(staged) and all(path.decode().startswith(REL + '/') for path in staged if path)
    assert not any(path.decode().startswith(protected) for path in staged if path)
    run('staged-check', ['git', 'diff', '--cached', '--check'])
    run('staged-stat', ['git', 'diff', '--cached', '--stat'])
    run('commit-evidence', ['git', 'commit', '-m', 'docs: retain full CI failures and separate source execution histories'])
    commit = git('evidence-head-after', 'rev-parse', 'HEAD')
    tree = git('evidence-tree-after', 'rev-parse', 'HEAD^{tree}')
    assert git('evidence-parent-after', 'rev-parse', 'HEAD^') == PREVIOUS
    assert not git('evidence-status-after', 'status', '--porcelain=v1', '--untracked-files=all')
    common_clean('common-before-push')
    assert git('evidence-remote-final-check', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [PREVIOUS, 'refs/heads/' + BRANCH]
    api_final_before = json.loads(run('evidence-ref-api-final-check', ['gh', 'api', f'repos/{REPO}/git/ref/heads/{BRANCH}']))
    assert api_final_before['object']['sha'] == PREVIOUS
    new_objects = inspect_new_objects(commit)
    transport_admission = fresh_transport_admission(new_objects)
    # One normal fast-forward push. These options apply only to this invocation;
    # they do not change global configuration, TLS, credentials, or any test budget.
    # A failure is preserved for read-only reconciliation, never retried here.
    run('push-evidence', [
        'git', '-c', 'http.version=HTTP/1.1', '-c', f'http.postBuffer={POST_BUFFER_BYTES}',
        'push', '--progress', 'publish', 'HEAD:refs/heads/' + BRANCH,
    ])
    assert git('evidence-remote-after', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [commit, 'refs/heads/' + BRANCH]
    api_after = json.loads(run('evidence-ref-api-after', ['gh', 'api', f'repos/{REPO}/git/ref/heads/{BRANCH}']))
    assert api_after['object']['sha'] == commit
    remote_commit = json.loads(run('evidence-commit-api-after', ['gh', 'api', f'repos/{REPO}/git/commits/{commit}']))
    assert remote_commit['sha'] == commit and remote_commit['tree']['sha'] == tree
    assert [row['sha'] for row in remote_commit['parents']] == [PREVIOUS]
    assert git('common-remote-after', 'ls-remote', 'publish', 'refs/heads/' + COMMON_BRANCH).split() == [SOURCE, 'refs/heads/' + COMMON_BRANCH]
    assert git('evidence-local-head-final', 'rev-parse', 'HEAD') == commit
    assert not git('evidence-local-status-final', 'status', '--porcelain=v1', '--untracked-files=all')
    common_clean('common-final')
    result = {
        'status': 'published_and_remote_readback_verified', 'finished_at': now(),
        'branch': BRANCH, 'commit': commit, 'tree': tree, 'parent': PREVIOUS,
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE,
        'original_metadata_observations': observations, 'prior_packet_bytes_unchanged': True,
        'original_72_packet_index_entries_unchanged': True, 'source_worktree_clean_and_unmodified': True,
        'packet_count': len(index['packets']),
        'file_member_count_with_overlap': sum(row['file_member_count'] for row in index['packets']),
        'published_file_count': len(files), 'max_blob_bytes': max(path.stat().st_size for path in files),
        'manifest_sha256': sha(index_path.read_bytes()), 'readme_sha256': sha((ROOT / 'README.md').read_bytes()),
        'complete_execution_history': False, 'full_history_cost': None, 'stages': index['stages'],
        'publication_receipt_is_external_to_its_own_commit': True,
        'append_receipt_sha256': APPEND_RESULT_SHA,
        'append_manifest_sha256_before_publication_metadata': APPEND_MANIFEST_SHA,
        'input_sha256': INPUTS_SHA, 'appender_sha256': APPENDER_SHA,
        'transport_admission': transport_admission,
        'new_git_objects': new_objects,
        'normal_push_attempt_count': 1, 'automatic_retry': False,
        'native_tests_executed_by_publisher': False,
        'physical_cost': None, 'stage_advancement_claimed': False,
        'commands_receipt_sha256': sha((out / 'commands.json').read_bytes()),
        'url': f'https://github.com/{REPO}/tree/{commit}/{REL}',
    }
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Preserve this invocation's observed failure. Do not infer remote absence
        # after a failed/uncertain push, and do not overwrite an earlier directory.
        if _output_created_by_this_invocation and not (OUTPUT / 'RESULT.json').exists():
            commands_path = OUTPUT / 'commands.json'
            commands_bytes = commands_path.read_bytes() if commands_path.exists() else None
            commands = json.loads(commands_bytes) if commands_bytes is not None else []
            head_path, tree_path = OUTPUT / 'evidence-head-after.stdout', OUTPUT / 'evidence-tree-after.stdout'
            failure = {
                'status': 'publication_not_confirmed', 'finished_at': now(),
                'error_type': type(error).__name__, 'error': str(error),
                'branch': BRANCH, 'parent': PREVIOUS, 'source_sha': SOURCE, 'source_tree': SOURCE_TREE,
                'local_commit': head_path.read_text().strip() if head_path.exists() else None,
                'local_tree': tree_path.read_text().strip() if tree_path.exists() else None,
                'remote_publication_state': 'unknown_until_readback',
                'push_launch_recorded': any(row['label'] == 'push-evidence' for row in commands),
                'automatic_retry': False, 'native_tests_executed': False,
                'complete_execution_history': False, 'full_history_cost': None, 'physical_cost': None,
                'stages': {f'S{i}': 'HOLD' for i in range(6)}, 'stage_advancement_claimed': False,
                'commands_sha256': sha(commands_bytes) if commands_bytes is not None else None,
                'publication_receipt_is_external_to_its_own_commit': True,
            }
            with (OUTPUT / 'RESULT.json').open('x') as output:
                output.write(json.dumps(failure, indent=2) + '\n')
        raise
