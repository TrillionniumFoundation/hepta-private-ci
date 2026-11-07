"""Original default workspace gate; source49 project PASS is a hard prerequisite."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

FROZEN = True
T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
TREE = 'be34ab1afe622ad3b8f030c8c5018f4f54fbc304'
COMMIT = '50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a'
SOURCE_NAME = 'native-candidate-r22-source.json'
SOURCE_SHA = '8cd1ec59c95d6c777d887f3302b257dc5230a7bfa5570fe9df0f0b2ef361aba5'
LOCK_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
PREFIX = 'native-workspace-r23'
PACKAGES = ['codex-app-server-client']
COMMAND = ['just', 'test', '--locked', '--retries', '0']


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value, indent=2) + '\n').encode())


def announce(value):
    try:
        print(json.dumps(value), flush=True)
    except OSError:
        # A lost controller stream must not prevent durable receipt/guard writes.
        pass


def git(*args):
    return subprocess.check_output(['git', *args], cwd=S, text=True).strip()


def guard(files):
    mismatches = []
    for item in files:
        try:
            raw = (S / item['path']).read_bytes()
            mode, kind, blob = git('ls-tree', TREE, '--', item['path']).split('\t')[0].split()
            actual_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            actual_mode = '100755' if (S / item['path']).stat().st_mode & 0o111 else '100644'
            if (kind != 'blob' or len(raw) != item['bytes'] or sha(raw) != item['sha256']
                    or actual_blob != item['git_blob'] or blob != item['git_blob']
                    or mode != item['mode'] or actual_mode != item['mode']):
                mismatches.append(item['path'])
        except Exception as error:
            mismatches.append({'path': item['path'], 'error': repr(error)})
    result = {'expected_tree': TREE, 'actual_tree': git('write-tree'),
              'unstaged_paths': git('diff', '--name-only').splitlines(),
              'untracked_paths': git('ls-files', '--others', '--exclude-standard').splitlines(),
              'file_mismatches': mismatches, 'changed_file_count': len(files),
              'lock_sha256': sha((S / 'codex-rs/Cargo.lock').read_bytes())}
    result['pass'] = (result['actual_tree'] == TREE and not result['unstaged_paths']
                      and not result['untracked_paths'] and not mismatches
                      and result['lock_sha256'] == LOCK_SHA)
    return result


def run():
    assert FROZEN, 'Preparation must not execute'
    source_raw = (E / SOURCE_NAME).read_bytes()
    assert sha(source_raw) == SOURCE_SHA
    source = json.loads(source_raw)
    files = source['changed_files']
    assert source['source_tree'] == TREE and source['source_commit'] == COMMIT and len(files) == 188
    assert guard(files)['pass']
    prerequisites = []
    package_args = [argument for package in PACKAGES for argument in ('-p', package)]
    expected_commands = {'strict': ['just', 'clippy', '--locked', *package_args, '--', '-D', 'warnings'],
                         'tests': ['just', 'test', '--locked', *package_args, '--retries', '0']}
    for phase, expected_command in expected_commands.items():
        stem = 'native-app-server-client-r22-' + phase
        receipt_raw = (E / (stem + '-receipt.json')).read_bytes()
        receipt = json.loads(receipt_raw)
        raw_process = json.loads((E / (stem + '-raw-process-result.json')).read_bytes())
        post = json.loads((E / (stem + '-source-post-verification.json')).read_bytes())
        for item in (receipt, raw_process):
            assert item['source_tree'] == TREE and item['source_commit'] == COMMIT
            assert item['exit_code'] == 0 and item['command'] == expected_command
        assert receipt['packages'] == PACKAGES
        assert post['pass'] and post['actual_tree'] == TREE and post['gate_exit_code'] == 0
        assert sha((E / (stem + '.log')).read_bytes()) == receipt['log_sha256']
        assert sha((E / (stem + '-resources.txt')).read_bytes()) == receipt['resources_sha256']
        prerequisites.append({'path': stem + '-receipt.json', 'sha256': sha(receipt_raw),
                              'source_tree': TREE, 'exit_code': 0,
                              'log_sha256': receipt['log_sha256'],
                              'resources_sha256': receipt['resources_sha256']})
    complete_raw = (E / 'native-app-server-client-r22-complete.json').read_bytes()
    complete = json.loads(complete_raw)
    assert complete['source_tree'] == TREE and complete['source_commit'] == COMMIT
    assert complete['strict_exit'] == complete['tests_exit'] == 0 and complete['packages'] == PACKAGES
    review_raw = (E / 'native-app-server-client-r22-result-review.json').read_bytes()
    review = json.loads(review_raw)
    assert review['source_tree'] == TREE and review['source_commit'] == COMMIT
    assert review['per_package']['codex-app-server-client']['PASS'] > 0
    assert not review['duplicate_execution_ids']
    assert review['all_results_pass'] and len(review['summary_lines']) == 1
    assert shutil.disk_usage(T).free > 20 * 1024**3
    env = os.environ.copy()
    env.update({'PATH': str(T / 'bin') + ':/home/alex/.cargo/bin:' + env.get('PATH', ''),
                'RUSTUP_TOOLCHAIN': '1.96.0', 'CARGO_BUILD_JOBS': '2', 'CARGO_TARGET_DIR': str(T / 'target'),
                'CARGO_NET_GIT_FETCH_WITH_CLI': 'true', 'NEXTEST_TEST_THREADS': '2', 'PYTHONDONTWRITEBYTECODE': '1',
                'CARGO_PROFILE_TEST_DEBUG': '0', 'CARGO_PROFILE_DEV_DEBUG': '0'})
    for key in ('CARGO_INCREMENTAL', 'CARGO_BUILD_TARGET', 'RUSTFLAGS'):
        env.pop(key, None)
    for key, value in json.loads((E / 'agentd-prerequisite-env.json').read_bytes()).items():
        if key in ('RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'PROTOC', 'PROTOC_INCLUDE', 'DOTSLASH_CACHE'):
            env[key] = value
    selection = {key: env.get(key) for key in (
        'RUSTUP_TOOLCHAIN', 'CARGO_BUILD_JOBS', 'CARGO_TARGET_DIR', 'CARGO_NET_GIT_FETCH_WITH_CLI',
        'NEXTEST_TEST_THREADS', 'NEXTEST_PROFILE', 'HEPTA_NEXTTEST_FULL_METADATA',
        'CARGO_PROFILE_TEST_DEBUG', 'CARGO_PROFILE_DEV_DEBUG', 'CARGO_INCREMENTAL',
        'CARGO_BUILD_TARGET', 'RUSTFLAGS', 'DOTSLASH_CACHE', 'RUST_MIN_STACK')}
    metadata_command = ['cargo', 'metadata', '--locked', '--no-deps', '--format-version', '1']
    metadata_raw = subprocess.check_output(metadata_command, cwd=S / 'codex-rs', env=env)
    metadata = json.loads(metadata_raw)
    with (E / (PREFIX + '-metadata.json')).open('xb') as stream:
        stream.write(metadata_raw)
    names = {package['id']: package['name'] for package in metadata['packages']}
    members = metadata['workspace_members']
    defaults = metadata['workspace_default_members']
    assert len(members) == len(defaults) == 193 and set(members) == set(defaults)
    scope = {'metadata_command': metadata_command, 'metadata_sha256': sha(metadata_raw),
             'workspace_members': [{'id': package, 'name': names[package]} for package in members],
             'workspace_default_members': [{'id': package, 'name': names[package]} for package in defaults]}
    write(E / (PREFIX + '-scope.json'), scope)
    write(E / (PREFIX + '-environment.json'), {
        'source_tree': TREE, 'source_commit': COMMIT, 'source_manifest': SOURCE_NAME,
        'source_manifest_sha256': SOURCE_SHA, 'selection': selection,
        'free_bytes_before': shutil.disk_usage(T).free, 'project_gate_prerequisites': prerequisites,
        'project_complete_sha256': sha(complete_raw), 'project_readback_sha256': sha(review_raw),
        'original_default_workspace_selection': True, 'workspace_member_count': 193,
        'workspace_default_member_count': 193, 'test_deadlines_features_filters_retries_unchanged': True})
    pre = guard(files)
    write(E / (PREFIX + '-source-pre-verification.json'), pre)
    assert pre['pass']
    log = E / (PREFIX + '-tests.log')
    resource = E / (PREFIX + '-tests-resources.txt')
    started = time.time()
    announce({'phase': 'original-default-workspace-start', 'command': COMMAND,
              'source_tree': TREE, 'source_commit': COMMIT, 'workspace_member_count': 193,
              'workspace_default_member_count': 193})
    with log.open('xb') as output:
        process = subprocess.Popen(['/usr/bin/time', '-v', '-o', str(resource), *COMMAND],
                                   cwd=S / 'codex-rs', env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            rc = process.wait()
        finally:
            if process.poll() is None:
                rc = process.wait()
            else:
                rc = process.returncode
            ended = time.time()
            raw_result = {'schema': 'hepta.native-raw-process-result.v1', 'phase': 'workspace-tests',
                          'source_tree': TREE, 'source_commit': COMMIT, 'command': COMMAND,
                          'cwd': str(S / 'codex-rs'), 'start_unix': started, 'end_unix': ended,
                          'exit_code': rc, 'log_and_resource_hashing_pending': True}
            write(E / (PREFIX + '-tests-raw-process-result.json'), raw_result)
            announce({**raw_result, 'event': 'workspace-raw-process-return'})
    receipt = {'schema': 'hepta.native-workspace-gate-receipt.v1', 'source_tree': TREE,
               'source_manifest': SOURCE_NAME, 'source_commit': COMMIT, 'command': COMMAND,
               'cwd': str(S / 'codex-rs'), 'start_unix': started, 'end_unix': ended,
               'elapsed_seconds': ended - started, 'exit_code': rc,
               'log_sha256': sha(log.read_bytes()), 'resources_sha256': sha(resource.read_bytes()),
               'environment_manifest': PREFIX + '-environment.json', 'test_scope': 'original_default_workspace',
               'workspace_member_count': 193, 'workspace_default_member_count': 193,
               'retries': 0, 'features': 'unchanged_defaults', 'filters': 'no_additions',
               'free_bytes_after': shutil.disk_usage(T).free}
    write(E / (PREFIX + '-tests-receipt.json'), receipt)
    announce(receipt)
    try:
        post = guard(files)
    except Exception as error:
        post = {'pass': False, 'expected_tree': TREE, 'error': repr(error)}
    post.update(gate_exit_code=rc, source_commit=COMMIT)
    write(E / (PREFIX + '-source-post-test-verification.json'), post)
    if not post['pass']:
        return 2
    if rc == 0:
        write(E / (PREFIX + '-complete.json'), {'source_tree': TREE, 'source_commit': COMMIT,
              'command': COMMAND, 'workspace_exit': rc, 'source_guards_pass': True,
              'fix_fmt_executed': False, 'free_bytes_after': shutil.disk_usage(T).free})
    return rc


if __name__ == '__main__':
    sys.exit(run())
