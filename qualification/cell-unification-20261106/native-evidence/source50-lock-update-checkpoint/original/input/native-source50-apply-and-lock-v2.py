import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import time


T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
OUT = E / 'native-source50-lock-update'
INPUT = T / 'stage50-provisional-input.tar.gz'
INPUT_SHA = 'f306c8175dd1a72ca3e5182203a8ca66340640bdac6040a88ea532e003e53a53'
PLAN_SHA = 'a85089c946bb093dbb3a1afcc7899ead8122dd442b54471d13e5769ac539beb5'
PATCH_SHA = '849ad4b6e9e0000ff940fe559d8ec7c8ebf2c648c7eec9d33026f17e3d02f027'
BEFORE_TREE = 'be34ab1afe622ad3b8f030c8c5018f4f54fbc304'
PROVISIONAL_TREE = 'ea48acf562499192a25e05ae28926a32632dee62'
BASE = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
SOURCE49_SHA = '8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5'
OLD_LOCK_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
BAZEL_SHA = 'd302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8'
LOCK_PATHS = ['MODULE.bazel.lock', 'codex-rs/Cargo.lock']
COMMAND = ['just', 'bazel-lock-update']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(raw):
    return {'bytes': len(raw), 'sha256': sha(raw),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)


def write_json(path, value):
    write(path, (json.dumps(value, indent=2) + '\n').encode())


def git(*args):
    result = subprocess.run(['git', *args], cwd=S, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise RuntimeError(f'git {args!r}: {result.returncode}: {result.stderr.decode()}')
    return result.stdout


def announce(value):
    try:
        print(json.dumps(value), flush=True)
    except OSError:
        pass


def tree():
    return git('write-tree').decode().strip()


def no_extras():
    assert not git('ls-files', '--others', '--exclude-standard')


def changed_paths():
    return git('diff', '--cached', '--name-only', '-z', BASE).decode().split('\0')[:-1]


def verify_entries(entries):
    for entry in entries:
        raw = (S / entry['path']).read_bytes()
        assert pin(raw) == {key: entry[key] for key in ['bytes', 'sha256', 'git_blob']}, entry['path']
        stage = git('ls-files', '-s', '--', entry['path']).decode().strip().split()
        assert stage[:3] == [entry['mode'], entry['git_blob'], '0'], (entry['path'], stage)


def main():
    assert not OUT.exists()
    assert shutil.disk_usage(T).free > 20 * 1024**3
    assert tree() == BEFORE_TREE and not git('diff', '--name-only')
    no_extras()
    old_source_raw = (E / 'native-candidate-r22-source.json').read_bytes()
    assert sha(old_source_raw) == SOURCE49_SHA
    old_source = json.loads(old_source_raw)
    assert old_source['source_tree'] == BEFORE_TREE and len(old_source['changed_files']) == 188
    assert set(changed_paths()) == {entry['path'] for entry in old_source['changed_files']}
    verify_entries(old_source['changed_files'])
    assert sha((S / 'codex-rs/Cargo.lock').read_bytes()) == OLD_LOCK_SHA
    prep_raw = (E / 'native-r24-bazel-tool-preparation.json').read_bytes()
    prep = json.loads(prep_raw)
    assert prep['exit_code'] == 0 and prep['official_checksum'] == BAZEL_SHA
    assert prep['version_probe']['exit_code'] == 0
    assert prep['version_probe']['stdout'].strip() == 'bazel 9.3.0'
    assert (S / '.bazelversion').read_text() == '9.3.0\n'
    assert sha((T / 'bin/bazel').read_bytes()) == BAZEL_SHA
    archive_raw = INPUT.read_bytes()
    assert sha(archive_raw) == INPUT_SHA
    with tarfile.open(INPUT) as archive:
        members = archive.getmembers()
        assert len(members) == 11 and len({member.name for member in members}) == 11
        assert all(member.isfile() and not PurePosixPath(member.name).is_absolute()
                   and '..' not in PurePosixPath(member.name).parts for member in members)
        contents = {member.name: archive.extractfile(member).read() for member in members}
    assert sha(contents['PLAN.json']) == PLAN_SHA and sha(contents['combined.patch']) == PATCH_SHA
    plan = json.loads(contents['PLAN.json'])
    assert plan['before_tree'] == BEFORE_TREE and plan['provisional_after_tree'] == PROVISIONAL_TREE
    assert len(plan['files']) == 9 and len(plan['changed_files_over_framework']) == 194
    for entry in plan['files']:
        assert pin((S / entry['path']).read_bytes()) == entry['before']
        assert pin(contents['source/' + entry['path']]) == entry['after']
    OUT.mkdir()
    write(OUT / 'input/PLAN.json', contents['PLAN.json'])
    write(OUT / 'input/combined.patch', contents['combined.patch'])
    write(OUT / 'input/source49-manifest.json', old_source_raw)
    write(OUT / 'input/bazel-tool-preparation.json', prep_raw)
    for entry in plan['files']:
        write(OUT / 'before-source' / entry['path'], (S / entry['path']).read_bytes())
    for path in LOCK_PATHS:
        write(OUT / 'before-locks' / path, (S / path).read_bytes())
    git('apply', '--check', str(OUT / 'input/combined.patch'))
    git('apply', str(OUT / 'input/combined.patch'))
    for entry in plan['files']:
        assert pin((S / entry['path']).read_bytes()) == entry['after']
    git('add', '--', *[entry['path'] for entry in plan['files']])
    assert tree() == PROVISIONAL_TREE and not git('diff', '--name-only')
    no_extras()
    expected = plan['changed_files_over_framework']
    assert set(changed_paths()) == {entry['path'] for entry in expected}
    verify_entries(expected)
    applied = {'schema': 'hepta.source50-provisional-applied.v1',
               'source_commit': None, 'source_tree': PROVISIONAL_TREE,
               'before_tree': BEFORE_TREE, 'input_archive_sha256': INPUT_SHA,
               'plan_sha256': PLAN_SHA, 'changed_files': expected,
               'lock_sha256_before_update': OLD_LOCK_SHA,
               'source_identity_is_provisional_until_lock_update': True,
               'free_bytes_before_command': shutil.disk_usage(T).free}
    write_json(OUT / 'applied-source.json', applied)
    announce({'phase': 'applied-provisional-source50', 'source_tree': tree(), 'changed_paths': 194})
    assert shutil.disk_usage(T).free > 20 * 1024**3
    env = dict(os.environ)
    env['PATH'] = str(T / 'bin') + ':/home/alex/.cargo/bin:' + env.get('PATH', '')
    log_path = OUT / 'lock-update.log'
    resources_path = OUT / 'lock-update.resources.txt'
    started = time.time()
    process = None
    raw_result = None
    try:
        with log_path.open('xb') as log:
            process = subprocess.Popen(['/usr/bin/time', '-v', '-o', str(resources_path), *COMMAND],
                                       cwd=S, env=env, stdout=log, stderr=subprocess.STDOUT)
            returncode = process.wait()
        ended = time.time()
        raw_result = {'schema': 'hepta.original-command-raw-result.v1', 'command': COMMAND,
                      'cwd': str(S), 'source_tree_before_command': PROVISIONAL_TREE,
                      'exit_code': returncode, 'started_unix': started, 'ended_unix': ended,
                      'elapsed_seconds': ended - started}
        write_json(OUT / 'lock-update-raw-process-result.json', raw_result)
        announce(raw_result)
    finally:
        if process is not None and raw_result is None:
            returncode = process.wait()
            ended = time.time()
            raw_result = {'schema': 'hepta.original-command-raw-result.v1', 'command': COMMAND,
                          'cwd': str(S), 'source_tree_before_command': PROVISIONAL_TREE,
                          'exit_code': returncode, 'started_unix': started, 'ended_unix': ended,
                          'elapsed_seconds': ended - started, 'recorded_during_finally': True}
            write_json(OUT / 'lock-update-raw-process-result.json', raw_result)
            announce(raw_result)
    receipt = {**raw_result, 'log': pin(log_path.read_bytes()),
               'resources': pin(resources_path.read_bytes()), 'free_bytes_after': shutil.disk_usage(T).free}
    write_json(OUT / 'lock-update-receipt.json', receipt)
    write(OUT / 'generated-lock.patch', git('diff', '--binary'))
    for path in LOCK_PATHS:
        write(OUT / 'after-locks' / path, (S / path).read_bytes())
    worktree_changes = git('diff', '--name-only', '-z').decode().split('\0')[:-1]
    post = {'schema': 'hepta.source50-lock-postguard.v1', 'source_tree_index_before_lock_stage': tree(),
            'working_tree_changed_paths': worktree_changes, 'locks': {}, 'guard_pass': False,
            'generated_source_tree': None, 'rust_tests_started': False, 'fix_fmt_executed': False}
    for path in LOCK_PATHS:
        post['locks'][path] = {'before': pin((OUT / 'before-locks' / path).read_bytes()),
                               'after': pin((S / path).read_bytes())}
    try:
        assert tree() == PROVISIONAL_TREE
        assert set(worktree_changes) <= set(LOCK_PATHS), worktree_changes
        no_extras()
        verify_entries(expected)
        post['guard_pass'] = True
        if returncode == 0:
            if worktree_changes:
                git('add', '--', *worktree_changes)
            actual = []
            for path in changed_paths():
                data = (S / path).read_bytes()
                mode, blob, stage = git('ls-files', '-s', '--', path).decode().split()[:3]
                assert stage == '0' and blob == pin(data)['git_blob']
                actual.append({'path': path, 'mode': mode, **pin(data)})
            post['generated_source_tree'] = tree()
            post['actual_changed_file_count'] = len(actual)
            write_json(OUT / 'generated-source.json', {
                'schema': 'hepta.source50-generated-lock-source.v1', 'source_commit': None,
                'source_tree': tree(), 'provisional_before_lock_tree': PROVISIONAL_TREE,
                'changed_files': actual, 'cargo_lock_sha256': sha((S / 'codex-rs/Cargo.lock').read_bytes()),
                'bazel_lock_sha256': sha((S / 'MODULE.bazel.lock').read_bytes()),
                'root_source_identity_freeze_pending': True})
    except BaseException as error:
        post['guard_pass'] = False
        post['guard_error'] = {'type': type(error).__name__, 'message': str(error)}
    write_json(OUT / 'postguard.json', post)
    if returncode != 0 or not post['guard_pass'] or post['generated_source_tree'] is None:
        write_json(OUT / 'failure.json', {'receipt': receipt, 'postguard': post,
                                       'source_not_restored_or_discarded': True})
        return returncode if returncode else 2
    write_json(OUT / 'complete.json', {'status': 'LOCK_UPDATE_PASSED_SOURCE_FREEZE_PENDING',
                                     'receipt': receipt, 'postguard': post,
                                     'rust_tests_started': False, 'fix_fmt_executed': False})
    announce({'phase': 'lock-update-complete', 'source_tree': post['generated_source_tree'],
              'changed_paths': post['actual_changed_file_count'], 'lock_changed_paths': worktree_changes})
    return 0


if __name__ == '__main__':
    try:
        status = main()
    except BaseException as error:
        if OUT.exists() and not (OUT / 'orchestration-error.json').exists():
            write_json(OUT / 'orchestration-error.json', {'type': type(error).__name__, 'message': str(error),
                                                        'source_not_restored_or_discarded': True})
        raise
    sys.exit(status)
