"""Normally publish the reviewed bf42 evidence increment with exact readback."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
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
PREVIOUS = '5a3137e8ed198a07eb63bd97b5bb639f4471011f'
PREVIOUS_INDEX = '511513fbba0e5b260687e75e1835e15d12e008789e569631e5d53dcbdf18f212'
SOURCE = 'bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d'
SOURCE_TREE = 'f7b65a747a1d2f585be38a4665ab2b4f1b07efb6'
CURRENT = 'c8b2bbb955272dde7679f86a7f0bf6113c46d7d4fbba3496446399c3615e10e4'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    if not __debug__:
        raise RuntimeError('All admission assertions must remain enabled')
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-index', required=True)
    parser.add_argument('--readme-sha256', required=True)
    parser.add_argument('--metadata-sha256', required=True)
    parser.add_argument('--packet-count', type=int, required=True)
    args = parser.parse_args()
    out = RECORDS / 'evidence-increment005-publication-v1'
    out.mkdir(exist_ok=False)
    (out / 'driver.py').write_bytes(Path(__file__).read_bytes())
    commands = []

    def run(label, argv, cwd=WORK):
        receipt = {'label': label, 'argv': argv, 'cwd': str(cwd), 'started_at': now(),
                   'output_mode': 'file_backed_no_subprocess_kill_timeout'}
        commands.append(receipt)
        (out / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
        clock = time.monotonic()
        stdout, stderr = out / (label + '.stdout'), out / (label + '.stderr')
        with stdout.open('xb') as sout, stderr.open('xb') as serr:
            completed = subprocess.run(argv, cwd=cwd, stdout=sout, stderr=serr)
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

    assert git('evidence-head-before', 'rev-parse', 'HEAD') == PREVIOUS
    assert git('evidence-branch-before', 'branch', '--show-current') == BRANCH
    common_clean('common-before')
    remote = git('evidence-publish-endpoint', 'remote', 'get-url', 'publish')
    assert remote.rstrip('/').removesuffix('.git') in {'https://github.com/' + REPO, 'git@github.com:' + REPO}
    assert git('evidence-remote-before', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [PREVIOUS, 'refs/heads/' + BRANCH]
    runs = json.loads(run('preceding-evidence-ci', ['gh', 'api', f'repos/{REPO}/actions/runs?head_sha={PREVIOUS}&per_page=100']))
    assert runs['total_count'] == len(runs['workflow_runs']) and runs['total_count'] <= 100
    assert all(row['head_sha'] == PREVIOUS and row['status'] == 'completed' for row in runs['workflow_runs'])
    prior_bytes = run('previous-index', ['git', 'show', PREVIOUS + ':' + REL + '/manifest.json'])
    assert sha(prior_bytes) == PREVIOUS_INDEX
    prior = json.loads(prior_bytes)
    assert len(prior['packets']) == 66
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
    assert len(index['packets']) == args.packet_count and args.packet_count >= 72
    assert index['packets'][:66] == prior['packets']
    assert index['status'] == 'bounded_checkpoint_verified_pending_increment_publication'
    assert index['latest_reviewed_common_source_sha'] == SOURCE and index['latest_reviewed_common_source_tree'] == SOURCE_TREE
    assert index['current_common_validation']['source_sha'] == SOURCE
    assert index['current_common_validation']['source_tree'] == SOURCE_TREE
    assert index['historical_ba4_original_native_ci'] == prior['historical_ba4_original_native_ci']
    assert index['complete_execution_history'] is False and index['full_history_cost'] is None
    assert index['stages'] == {f'S{i}': 'HOLD' for i in range(6)} and index['stage_advancement_claimed'] is False
    assert sha((ROOT / 'verify_packets.py').read_bytes()) == '50e086000bf0a2a414a00e0afb6010bec0394c9b5553e159b80fa9526f3846d7'
    readme = RECORDS / 'evidence-increment005-final-README.md'
    readme_bytes = readme.read_bytes()
    assert sha(readme_bytes) == args.readme_sha256
    assert SOURCE in readme_bytes.decode() and 'S0, S1, S2, S3, S4 and S5 remain HOLD' in readme_bytes.decode()
    metadata_path = RECORDS / 'evidence-increment005-metadata.json'
    metadata_bytes = metadata_path.read_bytes()
    assert sha(metadata_bytes) == args.metadata_sha256
    metadata = json.loads(metadata_bytes)
    assert metadata['source_sha'] == SOURCE and metadata['source_tree'] == SOURCE_TREE
    assert metadata['full_history_cost'] is None and metadata['stages'] == index['stages']
    assert len({row['relative_path'] for row in metadata['observations']}) == len(metadata['observations'])
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
    with (ROOT / 'increment005-metadata.json').open('xb') as output:
        output.write(metadata_bytes)
    (ROOT / 'README.md').write_bytes(readme_bytes)
    index['increment005_original_metadata_observations'] = observations
    index['status'] = 'bounded_checkpoint_publication_pending_verification'
    index_path.write_text(json.dumps(index, indent=2) + '\n')
    run('canonical-readme-format', [str(COMMON / 'node_modules/.bin/prettier'), '--write', str(ROOT / 'README.md')])
    run('verify-all-original-packets', ['python3', str(ROOT / 'verify_packets.py')])
    assert all(sha((ROOT / path).read_bytes()) == digest for path, digest in original_packet_bytes.items())
    assert all(sha((ROOT / row['path']).read_bytes()) == row['sha256'] for row in observations)
    assert metadata_path.read_bytes() == metadata_bytes and readme.read_bytes() == readme_bytes
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
    run('commit-evidence', ['git', 'commit', '-m', 'docs: retain original UI Windows and checkpoint delivery evidence'])
    commit = git('evidence-head-after', 'rev-parse', 'HEAD')
    tree = git('evidence-tree-after', 'rev-parse', 'HEAD^{tree}')
    assert git('evidence-parent-after', 'rev-parse', 'HEAD^') == PREVIOUS
    assert not git('evidence-status-after', 'status', '--porcelain=v1', '--untracked-files=all')
    common_clean('common-before-push')
    assert git('evidence-remote-final-check', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [PREVIOUS, 'refs/heads/' + BRANCH]
    run('push-evidence', ['git', 'push', 'publish', 'HEAD:refs/heads/' + BRANCH])
    assert git('evidence-remote-after', 'ls-remote', 'publish', 'refs/heads/' + BRANCH).split() == [commit, 'refs/heads/' + BRANCH]
    remote_commit = json.loads(run('evidence-commit-api-after', ['gh', 'api', f'repos/{REPO}/git/commits/{commit}']))
    assert remote_commit['sha'] == commit and remote_commit['tree']['sha'] == tree
    assert [row['sha'] for row in remote_commit['parents']] == [PREVIOUS]
    assert git('common-remote-after', 'ls-remote', 'publish', 'refs/heads/' + COMMON_BRANCH).split() == [SOURCE, 'refs/heads/' + COMMON_BRANCH]
    common_clean('common-final')
    result = {
        'status': 'published_and_remote_readback_verified', 'finished_at': now(),
        'branch': BRANCH, 'commit': commit, 'tree': tree, 'parent': PREVIOUS,
        'source_sha': SOURCE, 'source_tree': SOURCE_TREE,
        'original_metadata_observations': observations, 'prior_packet_bytes_unchanged': True,
        'original_66_packet_index_entries_unchanged': True, 'source_worktree_clean_and_unmodified': True,
        'packet_count': len(index['packets']),
        'file_member_count_with_overlap': sum(row['file_member_count'] for row in index['packets']),
        'published_file_count': len(files), 'max_blob_bytes': max(path.stat().st_size for path in files),
        'manifest_sha256': sha(index_path.read_bytes()), 'readme_sha256': sha((ROOT / 'README.md').read_bytes()),
        'complete_execution_history': False, 'full_history_cost': None, 'stages': index['stages'],
        'publication_receipt_is_external_to_its_own_commit': True,
        'commands_receipt_sha256': sha((out / 'commands.json').read_bytes()),
        'url': f'https://github.com/{REPO}/tree/{commit}/{REL}',
    }
    (out / 'RESULT.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
