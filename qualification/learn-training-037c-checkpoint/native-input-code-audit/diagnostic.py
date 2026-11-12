"""Run source-bound native observations through the repository's original tools.

This driver does not grant ordinary Adopt, NoUpdate, or daemon/Root recovery
qualification. It retains the actual requested native tests and their failures.
It performs no format/fix pass and never repeats a process with uncertain state.
"""

import argparse
import ast
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import textwrap
import xml.etree.ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--records', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--suite', choices=('diagnostic-four',),
                        required=True)
    parser.add_argument('--root-parent', type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    records = args.records.resolve()
    target = Path(os.environ['CARGO_TARGET_DIR']).resolve()
    if (re.fullmatch('[0-9a-f]{40}', args.source) is None
            or records.is_relative_to(repo) or target.is_relative_to(repo)
            or os.geteuid() == 0):
        parser.error('requires non-root runner, exact SHA, external records and target')
    needs_root = args.suite in ('root', 'all')
    root_dir = args.root_parent
    if needs_root and (root_dir is None or not root_dir.is_absolute()
                       or root_dir.parent != Path('/run')):
        parser.error('Root suite requires a fresh direct child of /run as --root-parent')
    records.mkdir(parents=True, exist_ok=False)
    os.chdir(repo)
    sys.path.insert(0, str(repo / 'scripts'))
    from hepta_ci_exec import run, execute_logged
    from hepta_ci_junit import collect
    from hepta_c_observer_coverage import assess_retained_original_observer_coverage

    os.environ.update(SOURCE_SHA=args.source, TESTED_SHA=args.source,
                      HEPTA_CI_LANE='source-head', PYTHONDONTWRITEBYTECODE='1',
                      CARGO_NET_OFFLINE='true')

    def git(*arguments):
        return subprocess.check_output(['git', *arguments], cwd=repo)

    def save(name, value):
        with (records / name).open('x') as stream:
            json.dump(value, stream, sort_keys=True, indent=2)
            stream.write('\n')

    def snapshot(label):
        names = git('ls-files', '-z') + git('ls-files', '--others', '--exclude-standard', '-z')
        rows = []
        for raw in sorted(set(names.split(b'\0')) - {b''}):
            path = os.fsdecode(raw)
            source = repo / path
            if not source.exists() and not source.is_symlink():
                rows.append({'path': path, 'missing': True})
                continue
            data = os.fsencode(os.readlink(source)) if source.is_symlink() else source.read_bytes()
            mode = '120000' if source.is_symlink() else (
                '100755' if source.stat().st_mode & 0o111 else '100644')
            rows.append({'path': path, 'mode': mode, 'bytes': len(data),
                         'sha256': hashlib.sha256(data).hexdigest(),
                         'blob': hashlib.sha1(b'blob ' + str(len(data)).encode()
                                              + b'\0' + data).hexdigest()})
        encoded = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
        with gzip.open(records / (label + '.files.json.gz'), 'xb') as output:
            output.write(encoded)
        value = {'commit': git('rev-parse', 'HEAD').decode().strip(),
                 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(),
                 'status': git('status', '--porcelain=v1', '--untracked-files=all').decode(),
                 'files': len(rows), 'inventory_sha256': hashlib.sha256(encoded).hexdigest()}
        save(label + '.json', value)
        print(json.dumps({'source_snapshot': label, **value}), flush=True)
        return value

    workflow = repo / '.github/workflows/hepta-daemon-learning-native.yml'
    workflow_raw = workflow.read_bytes()
    marker = '          cat > "$RUNNER_TEMP/daemon-learning-driver.py" <<\'PY\'\n'
    original_driver = textwrap.dedent(
        workflow_raw.decode().split(marker, 1)[1].split('          PY\n', 1)[0])
    original_constants = {}
    for node in ast.parse(original_driver).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], 'id', None)
            if name in ('parents', 'packages'):
                original_constants[name] = ast.literal_eval(node.value)
    parents, packages = original_constants['parents'], original_constants['packages']
    if (not parents or len(parents) != len(set(parents))
            or not all(isinstance(item, str) for item in parents + packages)):
        raise ValueError('invalid original workflow package/Root-parent declarations')

    helpers = ['python3', 'scripts/hepta_cell_test_helpers.py', '--package',
               'codex-hepta-infer-worker-host', '--output-dir', str(records / 'helpers')]
    root_setup_attempted = False
    before = None
    failures = []
    final_snapshot = None

    def stage(name, command, timeout=7200, minimum_tests=0):
        result = run(records / (name + '.json'), command,
                     minimum_tests=minimum_tests, timeout_seconds=timeout)
        if result:
            raise RuntimeError(name + ' failed; original execution retained')

    def restore_ownership():
        paths = [path for path in (target, records, repo / 'codex-rs/target/nextest')
                 if path.exists()]
        if paths:
            subprocess.run(['sudo', '-n', 'chown', '-R',
                            f'{os.getuid()}:{os.getgid()}', *map(str, paths)], check=True)

    def test(name, arguments, root=False):
        report = repo / 'codex-rs/target/nextest/local/junit.xml'
        if report.exists():
            report.rename(records / (name + '-prior-junit-excluded.xml'))
        command = ['python3', 'scripts/hepta_ci_exec.py', '--timeout-seconds', '7200',
                   '--minimum-tests', '1', '--output', str(records / (name + '.json')),
                   '--', 'just', 'test', '--locked', '--offline', *arguments,
                   '--retries', '0', '--status-level', 'pass',
                   '--success-output', 'final', '--failure-output', 'final']
        if root:
            names = ('PATH', 'SOURCE_SHA', 'TESTED_SHA', 'HEPTA_CI_LANE',
                     'PYTHONDONTWRITEBYTECODE', 'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS',
                     'CARGO_PROFILE_TEST_DEBUG', 'CARGO_PROFILE_DEV_DEBUG', 'CARGO_TARGET_DIR',
                     'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'LIBCLANG_PATH',
                     'RUSTUP_TOOLCHAIN', 'BINDGEN_EXTRA_CLANG_ARGS', 'CARGO_NET_OFFLINE',
                     'CARGO_NET_GIT_FETCH_WITH_CLI', 'PYTHONPATH', 'CMAKE', 'PROTOC',
                     'CARGO_TERM_COLOR', 'CODEX_REPO_ROOT')
            environment = {key: os.environ[key] for key in names if key in os.environ}
            environment.update(CARGO_HOME=os.environ.get('CARGO_HOME', str(Path.home() / '.cargo')),
                               RUSTUP_HOME=os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup')),
                               GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory',
                               GIT_CONFIG_VALUE_0=str(repo),
                               HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=str(root_dir / 'bind'),
                               HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=str(root_dir / 'source'),
                               HEPTA_CHECKPOINT_TEST_ROOT=str(root_dir / 'checkpoints'))
            environment.update(json.loads((records / 'helpers/env.json').read_text()))
            check_uid = ("import os,runpy,sys; assert os.geteuid()==0; "
                         "print('Root test uid=0',flush=True); "
                         "runpy.run_path(sys.argv.pop(1),run_name='__main__')")
            command = ['sudo', '-n', 'env', '-i',
                       *(key + '=' + value for key, value in sorted(environment.items())),
                       'python3', '-c', check_uid, *command[1:]]
        save(name + '-launch.json', {'command': command, 'required_euid': 0 if root else os.geteuid()})
        result = subprocess.run(command, check=False).returncode
        if root:
            restore_ownership()
        retained = collect(records / (name + '.json'), report, records / (name + '.xml'))
        if name == 'ordinary' and retained == 0:
            coverage = assess_retained_original_observer_coverage(
                records / (name + '.json'), records / (name + '.xml'))
            save('original-learning-owner-coverage.json', {'source_sha': args.source, **coverage})
            if not coverage['exact_pass_coverage']:
                raise RuntimeError('ordinary suite lacks exact named owner case coverage')
        if root and retained == 0:
            cases = list(ET.parse(records / (name + '.xml')).iter('testcase'))
            observed = [case.attrib['name'] for case in cases if case.find('skipped') is None]
            save('root-parent-coverage.json', {'expected': parents, 'observed': observed})
            if sorted(observed) != sorted(parents):
                raise RuntimeError('Root JUnit does not contain exactly the original requested parents')
        if result or retained:
            raise RuntimeError(name + ' failed; original execution and JUnit collection retained')

    try:
        before = snapshot('source-before')
        if before['commit'] != args.source or before['status']:
            raise RuntimeError('source is not the exact clean requested commit')
        save('driver-input.json', {
            'source_sha': args.source, 'repo': str(repo), 'records': str(records),
            'target': str(target), 'suite': args.suite, 'root_parent': str(root_dir),
            'host': socket.gethostname(), 'ordinary_uid': os.geteuid(),
            'started_at': datetime.now(timezone.utc).isoformat(),
            'workflow_sha256': hashlib.sha256(workflow_raw).hexdigest(),
            'native_driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'parents': parents, 'packages': packages,
            'qualification_claim': 'diagnostic four-case only; no formal focused, ordinary or Root qualification',
            'environment': {key: os.environ.get(key) for key in (
                'CARGO_TARGET_DIR', 'CARGO_HOME', 'RUSTUP_HOME', 'RUSTUP_TOOLCHAIN',
                'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL', 'CARGO_PROFILE_TEST_DEBUG',
                'CARGO_PROFILE_DEV_DEBUG', 'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH',
                'LIBCLANG_PATH', 'BINDGEN_EXTRA_CLANG_ARGS')},
        })
        stage('toolchain', ['python3', '-c',
              "import subprocess; commands=[['rustc','--version','--verbose'],"
              "['cargo','--version'],['just','--version'],['cargo','nextest','--version']];"
              "[subprocess.run(c,check=True) for c in commands]"], 120)
        stage('helper-build', helpers, 3600)
        stage('helper-verification-before', [*helpers, '--verify-only'], 120)
        helper_environment = json.loads((records / 'helpers/env.json').read_text())
        os.environ.update(helper_environment)
        if args.suite == 'diagnostic-four':
            filters = ['runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures', 'runtime::tests::circuit_task_ingress::q24_tests::next_use_observer::observer_support::selection_owner::published_read::command_owner::next_use_command::q24_next_use_command_readback_refuses_actual_publication_withdrawal', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_and_cold_readback_preserve_sources', 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::deep_readonly::q24_deep_original_no_update_selection_c_hot_readback_preserves_sources']
            test('diagnostic-four', ['-p', 'codex-hepta-agentd', '-p', 'codex-hepta-intelligence-eval',
                             '--lib', '-E', ' | '.join('test(=' + name + ')' for name in filters),
                             '--test-threads', '2'])
        if args.suite in ('ordinary', 'all'):
            test('ordinary', [*packages, '--lib', '--test-threads', '2'])
        if needs_root:
            root_setup_attempted = True
            setup = ("import os,subprocess,sys; from pathlib import Path; "
                     "p=Path(sys.argv[1]); p.mkdir(mode=0o700); "
                     "[(p/n).mkdir(mode=0o700) for n in ('source','bind','checkpoints')]; "
                     "subprocess.run(['mount','--bind',str(p/'source'),str(p/'bind')],check=True); "
                     "print('Root fixture uid='+str(os.geteuid())+' path='+str(p),flush=True)")
            stage('root-setup', ['sudo', '-n', 'python3', '-c', setup, str(root_dir)], 60)
            test('root', ['-p', 'codex-hepta-agentd', '--lib', '--run-ignored', 'only',
                          '-E', ' | '.join('test(=' + name + ')' for name in parents),
                          '--test-threads', '1'], root=True)
        stage('helper-verification-after', [*helpers, '--verify-only'], 120)
    except Exception as error:
        failures.append(f'{type(error).__name__}: {error}')
        print(f'native driver failed: {error}', flush=True)
    finally:
        if root_setup_attempted:
            try:
                restore_ownership()
                if subprocess.run(['sudo', '-n', 'mountpoint', '-q',
                                   str(root_dir / 'bind')]).returncode == 0:
                    result = execute_logged(['sudo', '-n', 'umount', str(root_dir / 'bind')],
                                            records / 'root-unmount.log', timeout_seconds=60)
                    save('root-unmount.json', result)
                    if result['returncode']:
                        failures.append('Root bind unmount failed; fixture retained')
            except Exception as error:
                failures.append(f'Root cleanup: {type(error).__name__}: {error}')
        try:
            final_snapshot = snapshot('source-after')
            if before != final_snapshot:
                failures.append('source bytes or identity changed during native observations')
        except Exception as error:
            failures.append(f'Final snapshot: {type(error).__name__}: {error}')
        save('driver-result.json', {
            'source_sha': args.source, 'suite': args.suite, 'failures': failures,
            'source_before': before, 'source_after': final_snapshot,
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'status': 'failed' if failures else 'passed',
            'qualification_claim': 'diagnostic four-case only; no formal focused, ordinary or Root qualification',
        })
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
