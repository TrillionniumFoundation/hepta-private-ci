"""Prepared source48 two-package gate. Frozen input identities must be filled before use."""
from pathlib import Path
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time

FROZEN = True
INPUT_BYTES = 12342
INPUT_SHA256 = '6d352c25cda712f83b1e9eecce3fd19ff6b51e15f8780015e5ac001e2322c8b3'
EXPECTED_COMMIT = '07699df6fb5bfb46562ecb0c2eccd0d232d18eac'
EXPECTED_TREE = 'e65356fc570296b74644967054eaded15b8ed440'
EXPECTED_CHANGED_COUNT = 187
T = Path('/home/alex/work/hepta-cell-unified-20261106-a')
S = T / 'source'
E = T / 'evidence'
D = T / 'stage48-r20-input'
BASE = 'cc2b01c2f69f43d63f8f5c561abd5e941d645769'
BASE_MANIFEST_SHA = '64e26c5c3340b27d6b64b7342fac8561300224f9f1e96c22f2aa23b184eafee3'
BASE_TEST_RESULTS_SHA = '6c5cab1f1ea9db4433f7112f5577b38f0d385ad3b9a26c834de19f67383f8c44'
LOCK_SHA = '4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c'
FRAMEWORK_PARENT = 'bef6fa7645df9df12b69fda499e97eed25de6c75'
PACKAGES = ['codex-app-server', 'codex-linux-sandbox']
PREFIX = 'native-app-server-r20'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=S, text=True).strip()


def write(path, value):
    raw = (json.dumps(value, indent=2) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)


def pin(path, tree):
    raw = (S / path).read_bytes()
    mode, kind, blob = git('ls-tree', tree, '--', path).split('\t')[0].split()
    actual_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    actual_mode = '100755' if (S / path).stat().st_mode & 0o111 else '100644'
    assert kind == 'blob' and blob == actual_blob and mode == actual_mode, path
    return {'path': path, 'bytes': len(raw), 'sha256': sha(raw), 'git_blob': blob, 'mode': mode}


def guard(tree, files):
    mismatches = []
    for item in files:
        try:
            if pin(item['path'], tree) != item:
                mismatches.append(item['path'])
        except Exception as error:
            mismatches.append({'path': item['path'], 'error': repr(error)})
    result = {'expected_tree': tree, 'actual_tree': git('write-tree'),
              'unstaged_paths': git('diff', '--name-only').splitlines(),
              'untracked_paths': git('ls-files', '--others', '--exclude-standard').splitlines(),
              'file_mismatches': mismatches, 'lock_sha256': sha((S / 'codex-rs/Cargo.lock').read_bytes()),
              'changed_file_count': len(files)}
    result['pass'] = (result['actual_tree'] == tree and not result['unstaged_paths']
                      and not result['untracked_paths'] and not mismatches and result['lock_sha256'] == LOCK_SHA)
    return result


def run():
    assert FROZEN, 'Preparation must not execute'
    assert isinstance(INPUT_BYTES, int) and INPUT_BYTES > 0
    assert len(INPUT_SHA256) == 64 and len(EXPECTED_COMMIT) == len(EXPECTED_TREE) == 40
    assert isinstance(EXPECTED_CHANGED_COUNT, int)
    baseline_raw = (E / 'native-candidate-r19-source.json').read_bytes()
    assert sha(baseline_raw) == BASE_MANIFEST_SHA
    baseline = json.loads(baseline_raw)
    assert len(baseline['changed_files']) == 181 and guard(BASE, baseline['changed_files'])['pass']
    baseline_results_raw = (E / 'r19-disconnect-diagnostic/test-results.json').read_bytes()
    assert sha(baseline_results_raw) == BASE_TEST_RESULTS_SHA
    baseline_ids = {(item['binary'], item['name']) for item in json.loads(baseline_results_raw)}
    assert len(baseline_ids) == 1345
    assert all(binary.split('::', 1)[0] == 'codex-app-server' for binary, _ in baseline_ids)
    natural = json.loads((E / 'r19-disconnect-diagnostic/natural-exit-check.json').read_bytes())
    assert natural['all_observed_identities_not_live'] and natural['signals_sent'] is False
    assert shutil.disk_usage(T).free > 20 * 1024**3
    data = (T / 'stage48-r20-input.tar.gz').read_bytes()
    assert len(data) == INPUT_BYTES and sha(data) == INPUT_SHA256
    D.mkdir(exist_ok=False)
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            assert member.isfile() and not relative.is_absolute() and '..' not in relative.parts
            path = D / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('xb') as stream:
                stream.write(archive.extractfile(member).read())
    m = json.loads((D / 'manifest.json').read_bytes())
    assert m['source_commit'] == EXPECTED_COMMIT and m['expected_after_tree'] == EXPECTED_TREE
    assert m['before_tree'] == BASE and m['expected_changed_file_count'] == EXPECTED_CHANGED_COUNT
    for name, key in [('root-published-source.json', 'root_published_source_sha256'),
                      ('root-publish-manifest.json', 'root_publish_manifest_sha256')]:
        assert sha((D / name).read_bytes()) == m[key]
    patch = D / m['combined_patch']['path']
    assert sha(patch.read_bytes()) == m['combined_patch']['sha256']
    for item in m['files']:
        if item['before'] is None:
            assert not (S / item['path']).exists(), item['path']
        else:
            assert sha((S / item['path']).read_bytes()) == item['before']['sha256'], item['path']
    subprocess.run(['git', 'apply', '--check', '--index', str(patch)], cwd=S, check=True)
    subprocess.run(['git', 'apply', '--index', str(patch)], cwd=S, check=True)
    tree = git('write-tree')
    assert tree == EXPECTED_TREE
    for item in m['files']:
        actual = pin(item['path'], tree)
        for key in ('bytes', 'sha256', 'git_blob', 'mode'):
            assert actual[key] == item['after'][key], (item['path'], key)
    paths = git('diff', '--name-only', FRAMEWORK_PARENT, tree).splitlines()
    assert len(paths) == EXPECTED_CHANGED_COUNT
    files = [pin(path, tree) for path in paths]
    assert guard(tree, files)['pass']
    source = {'schema': 'hepta.native-candidate-r20.v1', 'source_tree': tree, 'source_commit': EXPECTED_COMMIT,
              'parent_identities': [FRAMEWORK_PARENT, 'caf06e0d9c78ba2b8e2ab860ec1b37f049e30f1b'],
              'before_tree': BASE, 'applied_stage': 48, 'input_archive_sha256': sha(data),
              'input_combined_patch_sha256': m['combined_patch']['sha256'], 'changed_files': files,
              'lock_sha256': LOCK_SHA,
              'workflow_sha256': sha((S / '.github/workflows/hepta-cell-framework-native.yml').read_bytes())}
    write(E / 'native-candidate-r20-source.json', source)
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
        'CARGO_BUILD_TARGET', 'RUSTFLAGS', 'DOTSLASH_CACHE')}
    write(E / (PREFIX + '-environment.json'), {'source_tree': tree, 'selection': selection,
          'free_bytes_before': shutil.disk_usage(T).free, 'source_environment_immutable_during_gates': True,
          'test_deadlines_features_filters_retries_unchanged': True})
    print(json.dumps({'phase': 'stage48-applied', 'source_tree': tree,
                      'changed_file_count': len(files), 'source_commit': EXPECTED_COMMIT}), flush=True)
    package_args = [argument for package in PACKAGES for argument in ('-p', package)]
    phases = [('strict', ['just', 'clippy', '--locked', *package_args, '--', '-D', 'warnings']),
              ('tests', ['just', 'test', '--locked', *package_args, '--retries', '0'])]
    for phase, command in phases:
        assert guard(tree, files)['pass']
        stem = PREFIX + '-' + phase
        log = E / (stem + '.log')
        resource = E / (stem + '-resources.txt')
        started = time.time()
        print(json.dumps({'phase': phase + '-start', 'command': command, 'source_tree': tree}), flush=True)
        with log.open('xb') as output:
            process = subprocess.Popen(['/usr/bin/time', '-v', '-o', str(resource), *command],
                                       cwd=S / 'codex-rs', env=env, stdout=output, stderr=subprocess.STDOUT)
            try:
                rc = process.wait()
            finally:
                # No cleanup/source mutation may race an uncertain Rust subprocess.
                if process.poll() is None:
                    rc = process.wait()
                else:
                    rc = process.returncode
                ended = time.time()
                raw_result = {'schema': 'hepta.native-raw-process-result.v1', 'phase': phase,
                              'source_tree': tree, 'source_commit': EXPECTED_COMMIT, 'command': command,
                              'cwd': str(S / 'codex-rs'), 'start_unix': started, 'end_unix': ended,
                              'exit_code': rc, 'log_and_resource_hashing_pending': True}
                write(E / (stem + '-raw-process-result.json'), raw_result)
                print(json.dumps({**raw_result, 'event': phase + '-raw-process-return'}), flush=True)
        receipt = {'schema': 'hepta.native-gate-receipt.v1', 'phase': phase, 'source_tree': tree,
                   'source_manifest': 'native-candidate-r20-source.json', 'source_commit': EXPECTED_COMMIT,
                   'command': command, 'cwd': str(S / 'codex-rs'), 'start_unix': started, 'end_unix': ended,
                   'elapsed_seconds': ended - started, 'exit_code': rc, 'log_sha256': sha(log.read_bytes()),
                   'resources_sha256': sha(resource.read_bytes()), 'environment_manifest': PREFIX + '-environment.json',
                   'packages': PACKAGES, 'retries': 0 if phase == 'tests' else None}
        write(E / (stem + '-receipt.json'), receipt)
        print(json.dumps(receipt), flush=True)
        post = guard(tree, files)
        post.update(phase=phase, gate_exit_code=rc)
        write(E / (stem + '-source-post-verification.json'), post)
        assert post['pass'], 'source changed during original gate; source is retained for review'
        if rc:
            return rc
    # Verify the original complete App-server set before allowing the following
    # workspace gate. This reads original nextest output; it adds no filter/run.
    test_log = E / (PREFIX + '-tests.log')
    text = test_log.read_text()
    body = re.split(r'^\s*Summary\s+\[', text, maxsplit=1, flags=re.M)[0]
    pattern = re.compile(r'^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$', re.M)
    results = [{'status': status, 'seconds': float(seconds), 'binary': binary, 'name': name.strip()}
               for status, seconds, binary, name in pattern.findall(body)]
    current_ids = {(item['binary'], item['name']) for item in results}
    counts = {package: {status: sum(item['binary'].split('::', 1)[0] == package
                                   and item['status'] == status for item in results)
                        for status in ('PASS', 'FAIL', 'TIMEOUT')} for package in PACKAGES}
    review = {'source_tree': tree, 'source_commit': EXPECTED_COMMIT, 'log_sha256': sha(test_log.read_bytes()),
              'baseline_results_sha256': BASE_TEST_RESULTS_SHA, 'original_app_server_count': len(baseline_ids),
              'original_app_server_missing_ids': sorted(baseline_ids - current_ids),
              'unique_test_count': len(current_ids), 'per_package': counts,
              'summary_lines': [line for line in text.splitlines() if re.match(r'^\s*Summary\s+\[', line)],
              'all_results_pass': bool(results) and all(item['status'] == 'PASS' for item in results),
              'duplicate_execution_ids': len(results) != len(current_ids)}
    write(E / (PREFIX + '-test-results.json'), results)
    write(E / (PREFIX + '-result-review.json'), review)
    assert not review['original_app_server_missing_ids'] and not review['duplicate_execution_ids']
    assert review['all_results_pass'] and len(review['summary_lines']) == 1
    assert all(counts[package]['PASS'] > 0 for package in PACKAGES)
    write(E / (PREFIX + '-complete.json'), {'source_tree': tree, 'source_commit': EXPECTED_COMMIT,
          'strict_exit': 0, 'tests_exit': 0, 'packages': PACKAGES, 'free_bytes_after': shutil.disk_usage(T).free,
          'fix_fmt_executed': False, 'workspace_not_started_by_this_runner': True})
    return 0


if __name__ == '__main__':
    sys.exit(run())
