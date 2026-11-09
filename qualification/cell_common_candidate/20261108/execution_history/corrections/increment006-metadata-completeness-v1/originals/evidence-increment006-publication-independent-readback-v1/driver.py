"""Independently read back an already terminal 006a publication; never publish or test."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

R = Path('/home/qian-qi/work/hepta-cell-s0-records-20261108-898e')
W = Path('/home/qian-qi/worktrees/hepta-cell-s0-evidence-20261108-898e')
C = Path('/home/qian-qi/worktrees/hepta-cell-s0-common-20261108-898e')
REL = 'qualification/cell_common_candidate/20261108/execution_history'
REPO = 'TrillionniumFoundation/hepta-private-ci'
BRANCH = 'codex/cell-s0-evidence-20261108-898e'
COMMON_BRANCH = 'codex/cell-s0-common-20261108-898e'
PARENT = '97543a30b941122ee42c99ab95c2dbf639ac6576'
PARENT_INDEX = '33da1f4d0d31c0251fb5a303e72aa31a561b961e01e0c6495b6b234b6857cf9e'
SOURCE = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
SOURCE_TREE = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
CURRENT = 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'
README = 'b9974c7cd013790544f3284b92a08b4b8958abcd54e9e82397670367a9190744'
METADATA = 'cbb251ffaf62807b01d5c10739ce2a65325c4dc1733632cfb3b93923e4af87e0'
INPUTS = '9b843f8b5f55aff31be778170b6fe48755886ccc947f00b2a1d46b0bbab7fae4'
APPEND_RESULT = 'b22755ed31cb6a7843d0bb591262c25dea33dd5b914b3485c8d4bfeed9661573'
PUBLISHER = '75e1371df941e7c3d456a3d0b1b492b3d3a7be6e8db5bbeb98d26bf9eeb12792'
OUT = R / 'evidence-increment006-publication-independent-readback-v1'
_created_output = False


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def same_typed(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_typed(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_typed(a, b) for a, b in zip(left, right))
    return left == right


def main():
    global _created_output
    if not __debug__:
        raise RuntimeError('Admission assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-commit', required=True)
    parser.add_argument('--expected-tree', required=True)
    parser.add_argument('--publication-receipt-sha256', required=True)
    args = parser.parse_args()
    for value, size in ((args.expected_commit, 40), (args.expected_tree, 40),
                        (args.publication_receipt_sha256, 64)):
        assert len(value) == size and all(c in '0123456789abcdef' for c in value)
    OUT.mkdir(exist_ok=False)
    _created_output = True
    (OUT / 'driver.py').write_bytes(Path(__file__).read_bytes())
    commands = []

    def write(name, data):
        with (OUT / name).open('xb') as target:
            target.write(data)

    def run(label, argv, cwd=W):
        row = {'label': label, 'argv': argv, 'cwd': str(cwd), 'started_at': now(),
               'scope': 'read_only', 'subprocess_kill_timeout': None}
        commands.append(row)
        (OUT / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        started = time.monotonic()
        stdout, stderr = OUT / (label + '.stdout'), OUT / (label + '.stderr')
        with stdout.open('xb') as sout, stderr.open('xb') as serr:
            process = subprocess.run(argv, cwd=cwd, stdout=sout, stderr=serr)
        data, errors = stdout.read_bytes(), stderr.read_bytes()
        row.update(exit_code=process.returncode, finished_at=now(),
                   elapsed_seconds=time.monotonic() - started,
                   stdout_bytes=len(data), stdout_sha256=sha(data),
                   stderr_bytes=len(errors), stderr_sha256=sha(errors))
        (OUT / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        assert process.returncode == 0, label
        return data

    def git(label, *argv, cwd=W):
        return run(label, ['git', *argv], cwd).decode().strip()

    def api(label, path):
        return json.loads(run(label, ['gh', 'api', '--method', 'GET', f'repos/{REPO}/' + path]))

    def source_identity(label):
        value = {
            'head': git(label + '-head', 'rev-parse', 'HEAD', cwd=C),
            'tree': git(label + '-tree', 'rev-parse', 'HEAD^{tree}', cwd=C),
            'branch': git(label + '-branch', 'branch', '--show-current', cwd=C),
            'status': git(label + '-status', 'status', '--porcelain=v1', '--untracked-files=all', cwd=C),
            'current_sha256': sha((C / 'qualification/cell-research-stages-20261108/CURRENT_RESULT.json').read_bytes()),
        }
        assert value == {'head': SOURCE, 'tree': SOURCE_TREE, 'branch': COMMON_BRANCH,
                         'status': '', 'current_sha256': CURRENT}
        return value

    publication_dir = R / 'evidence-increment006-publication-v1'
    original = (publication_dir / 'RESULT.json').read_bytes()
    assert sha(original) == args.publication_receipt_sha256
    result = json.loads(original)
    assert result['status'] == 'published_and_remote_readback_verified'
    assert result['commit'] == args.expected_commit and result['tree'] == args.expected_tree
    assert result['parent'] == PARENT and result['branch'] == BRANCH
    assert result['source_sha'] == SOURCE and result['source_tree'] == SOURCE_TREE
    assert result['packet_count'] == 81 and result['file_member_count_with_overlap'] == 9136
    assert result['original_72_packet_index_entries_unchanged'] is True
    assert result['prior_packet_bytes_unchanged'] is True
    assert result['source_worktree_clean_and_unmodified'] is True
    assert result['complete_execution_history'] is False and result['full_history_cost'] is None
    assert result['physical_cost'] is None
    assert result['stages'] == {f'S{i}': 'HOLD' for i in range(6)}
    assert result['stage_advancement_claimed'] is False and result['automatic_retry'] is False
    assert result['native_tests_executed_by_publisher'] is False
    assert result['normal_push_attempt_count'] == 1
    assert result['append_receipt_sha256'] == APPEND_RESULT and result['input_sha256'] == INPUTS
    assert sha((publication_dir / 'driver.py').read_bytes()) == PUBLISHER
    original_commands = (publication_dir / 'commands.json').read_bytes()
    assert sha(original_commands) == result['commands_receipt_sha256']
    command_rows = json.loads(original_commands)
    assert command_rows and all(row.get('exit_code') == 0 for row in command_rows)
    pushes = [row for row in command_rows if row['label'] == 'push-evidence']
    expected_push = ['git', '-c', 'http.version=HTTP/1.1', '-c', 'http.postBuffer=268435456',
                     'push', '--progress', 'publish', 'HEAD:refs/heads/' + BRANCH]
    assert len(pushes) == 1 and pushes[0]['argv'] == expected_push
    for row in command_rows:
        for channel in ('stdout', 'stderr'):
            data = (publication_dir / (row['label'] + '.' + channel)).read_bytes()
            assert len(data) == row[channel + '_bytes'] and sha(data) == row[channel + '_sha256']
    write('original-publication-result.json', original)
    write('original-publication-commands.json', original_commands)
    before = source_identity('common-before')
    assert git('evidence-local-head-before', 'rev-parse', 'HEAD') == args.expected_commit
    assert git('evidence-local-tree-before', 'rev-parse', 'HEAD^{tree}') == args.expected_tree
    assert git('evidence-local-parent-before', 'rev-parse', 'HEAD^') == PARENT
    assert git('evidence-branch-before', 'branch', '--show-current') == BRANCH
    assert not git('evidence-local-status-before', 'status', '--porcelain=v1', '--untracked-files=all')
    assert git('evidence-publish-url', 'remote', 'get-url', 'publish') == 'https://github.com/' + REPO + '.git'
    assert git('evidence-ref-git', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [
        args.expected_commit, 'refs/heads/' + BRANCH]
    ref = api('evidence-ref-api', 'git/ref/heads/' + BRANCH)
    assert ref['object']['type'] == 'commit' and ref['object']['sha'] == args.expected_commit
    commit = api('evidence-commit-api', 'git/commits/' + args.expected_commit)
    assert commit['sha'] == args.expected_commit and commit['tree']['sha'] == args.expected_tree
    assert [row['sha'] for row in commit['parents']] == [PARENT]
    current_index_bytes = run('committed-index', ['git', 'show', args.expected_commit + ':' + REL + '/manifest.json'])
    old_index_bytes = run('predecessor-index', ['git', 'show', PARENT + ':' + REL + '/manifest.json'])
    assert sha(current_index_bytes) == result['manifest_sha256']
    assert sha(old_index_bytes) == PARENT_INDEX
    current, prior = json.loads(current_index_bytes), json.loads(old_index_bytes)
    assert len(current['packets']) == 81 and len(prior['packets']) == 72
    assert sum(row['file_member_count'] for row in current['packets']) == 9136
    assert same_typed(current['packets'][:72], prior['packets'])
    assert current['status'] == 'bounded_checkpoint_verified'
    assert current['latest_reviewed_common_source_sha'] == SOURCE
    assert current['latest_reviewed_common_source_tree'] == SOURCE_TREE
    assert current['common_full_repository_ci_green'] is False
    assert current['stages'] == result['stages'] and current['stage_advancement_claimed'] is False
    assert current['complete_execution_history'] is False and current['full_history_cost'] is None
    inputs_bytes = (R / 'increment006a-inputs.json').read_bytes()
    assert sha(inputs_bytes) == INPUTS
    assert same_typed(current['current_common_validation'], json.loads(inputs_bytes)['current_common_validation'])
    protected = tuple(REL + '/packets/' + row['packet_id'] + '/' for row in prior['packets'])
    changes = run('committed-changed-paths', ['git', 'diff', '--no-renames', '--name-only', '-z',
                                            PARENT, args.expected_commit]).split(b'\0')
    assert any(changes) and all(p.decode().startswith(REL + '/') for p in changes if p)
    assert not any(p.decode().startswith(protected) for p in changes if p)
    readme_bytes = run('committed-readme', ['git', 'show', args.expected_commit + ':' + REL + '/README.md'])
    metadata_bytes = run('committed-metadata', ['git', 'show', args.expected_commit + ':' + REL + '/increment006-metadata.json'])
    assert sha(readme_bytes) == README == result['readme_sha256']
    assert sha(metadata_bytes) == METADATA
    metadata = json.loads(metadata_bytes)
    assert metadata['source_sha'] == SOURCE and metadata['source_tree'] == SOURCE_TREE
    assert metadata['physical_cost'] is None and metadata['full_history_cost'] is None
    assert metadata['new_tests_executed'] is False and metadata['packet_count'] == 81
    expected_observations = [
        {'path': 'observations/' + row['relative_path'], 'bytes': row['bytes'], 'sha256': row['sha256']}
        for row in metadata['observations']
    ]
    assert len(expected_observations) == 15
    assert same_typed(current['increment006_original_metadata_observations'], expected_observations)
    assert same_typed(result['original_metadata_observations'], expected_observations)
    for number, row in enumerate(expected_observations, 1):
        relative = Path(row['path'])
        assert not relative.is_absolute() and '..' not in relative.parts
        raw = run(f'committed-observation-{number:02}', ['git', 'show',
                  args.expected_commit + ':' + REL + '/' + relative.as_posix()])
        assert len(raw) == row['bytes'] and sha(raw) == row['sha256']
    assert git('common-ref-git', 'ls-remote', 'publish', 'refs/heads/' + COMMON_BRANCH).split() == [
        SOURCE, 'refs/heads/' + COMMON_BRANCH]
    common_ref = api('common-ref-api', 'git/ref/heads/' + COMMON_BRANCH)
    assert common_ref['object']['sha'] == SOURCE
    after = source_identity('common-after')
    assert before == after
    assert git('evidence-local-head-after', 'rev-parse', 'HEAD') == args.expected_commit
    assert not git('evidence-local-status-after', 'status', '--porcelain=v1', '--untracked-files=all')
    assert (publication_dir / 'RESULT.json').read_bytes() == original
    assert (publication_dir / 'commands.json').read_bytes() == original_commands
    final = {
        'status': 'independent_remote_readback_verified', 'finished_at': now(),
        'commit': args.expected_commit, 'tree': args.expected_tree, 'parent': PARENT,
        'branch': BRANCH, 'source_sha': SOURCE, 'source_tree': SOURCE_TREE,
        'publication_receipt_sha256': sha(original), 'publication_commands_sha256': sha(original_commands),
        'all_original_command_outputs_hash_verified': True,
        'manifest_sha256': sha(current_index_bytes), 'readme_sha256': sha(readme_bytes),
        'metadata_sha256': sha(metadata_bytes), 'packet_count': 81,
        'file_member_count_with_overlap': 9136, 'original_72_entries_and_paths_unchanged': True,
        'metadata_observations_verified': len(expected_observations),
        'full_packet_archive_reconstruction_repeated': False,
        'original_packet_verifier_result_is_retained_publisher_evidence': True,
        'original_single_normal_push_argv_and_exit_verified': True,
        'common_before': before, 'common_after': after,
        'commit_push_dispatch_cancel_or_test_performed_by_this_reader': False,
        'complete_execution_history': False, 'full_history_cost': None, 'physical_cost': None,
        'stages': {f'S{i}': 'HOLD' for i in range(6)}, 'stage_advancement_claimed': False,
        'commands_sha256': sha((OUT / 'commands.json').read_bytes()),
    }
    write('RESULT.json', (json.dumps(final, indent=2) + '\n').encode())
    print(json.dumps(final), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if _created_output and not (OUT / 'RESULT.json').exists():
            commands_path = OUT / 'commands.json'
            failure = {
                'status': 'independent_readback_failed', 'finished_at': now(),
                'error_type': type(error).__name__, 'error': str(error),
                'this_is_not_a_native_failure_or_reversal_of_a_publication_receipt': True,
                'commit_push_dispatch_cancel_or_test_performed_by_this_reader': False,
                'remote_state_not_inferred_from_reader_failure': True,
                'full_history_cost': None, 'physical_cost': None,
                'commands_sha256': sha(commands_path.read_bytes()) if commands_path.exists() else None,
            }
            with (OUT / 'RESULT.json').open('x') as output:
                output.write(json.dumps(failure, indent=2) + '\n')
        raise
