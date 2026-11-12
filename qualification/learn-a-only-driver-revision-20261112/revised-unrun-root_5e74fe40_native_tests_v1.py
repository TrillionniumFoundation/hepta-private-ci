"""Run actual source-bound native processes; never infer qualification from compilation."""
import ast
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

BASE = Path('/home/qq/hepta-learn-ff41-tools')
REPO = Path('/home/qq/hepta-learn-ff41-native-root-279deb99-v1')
TARGET = Path('/home/qq/hepta-learn-ff41-target-f73704ac-v1')
OUT = BASE / 'validation/root-5e74fe40-native-tests-v1'
HEAD = '5e74fe4031213d14729a1de1d7c8cb9f0fadfbe9'
TREE = '32a98b17e61e7fa11a482de764b217a2e1666eb4'
PUBLIC = Path('/tmp/hepta-native-5e74fe40-ff41-v1')
ROOT = Path('/run/hepta-daemon-learning-5e74fe40-ff41-v1')
A_PARENT = ('neuron_generation_current::initial_root_tests::ordinary::'
            'ordinary_main_a_records_independent_outcome_and_retires_original_processes')


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO)


def snapshot():
    digest = hashlib.sha256()
    count = 0
    for entry in git('ls-files', '-s', '-z').split(b'\0'):
        if not entry:
            continue
        meta, name = entry.split(b'\t', 1)
        path = REPO / os.fsdecode(name)
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        digest.update(meta.split()[0] + b'\0' + name + b'\0' + hashlib.sha256(data).digest())
        count += 1
    return dict(head=git('rev-parse', 'HEAD').decode().strip(),
                tree=git('rev-parse', 'HEAD^{tree}').decode().strip(),
                status=git('status', '--porcelain', '--untracked-files=all').decode(),
                tracked_files=count, tracked_sha256=digest.hexdigest())


OUT.mkdir(parents=True, exist_ok=False)
result = dict(status='preflight', started=utc(), head=HEAD, tree=TREE,
              uid=os.getuid(), target=str(TARGET), stages=[],
              scope='Actual ordinary A parent only on the integrated source with private Root control and workspace fixes. Completed-history revisions are being qualified separately; this run includes neither post-A nor whole cold and transfers no earlier PASS.')


def save(path, value):
    pending = path.with_suffix(path.suffix + '.tmp')
    pending.write_text(json.dumps(value, indent=2) + '\n')
    pending.replace(path)


def persist():
    save(OUT / 'result.json', result)


def command(name, argv, cwd=REPO):
    item = dict(name=name, command=argv, cwd=str(cwd), started=utc(), status='running')
    result['stages'].append(item)
    persist()
    with (OUT / (name + '.stdout.log')).open('xb') as stdout, (OUT / (name + '.stderr.log')).open('xb') as stderr:
        child = subprocess.Popen(argv, cwd=cwd, stdout=stdout, stderr=stderr)
        item['pid'] = child.pid
        persist()
        code = child.wait()
    item.update(status='completed', exit_code=code, finished=utc())
    persist()
    return code


def restore_ownership():
    paths = [str(p) for p in [TARGET, OUT, REPO / 'codex-rs/target'] if p.exists()]
    subprocess.run(['sudo', '-n', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', *paths], check=True)


def test(name, arguments, expected=None):
    restore_ownership()
    reports = [TARGET / 'nextest/local/junit.xml', REPO / 'codex-rs/target/nextest/local/junit.xml']
    for index, report in enumerate(reports):
        if report.exists():
            report.rename(OUT / f'{name}-prior-junit-{index}-excluded.xml')
    argv = ['python3', 'scripts/hepta_ci_exec.py', '--timeout-seconds', '7200',
            '--minimum-tests', '1', '--output', str(OUT / (name + '.json')), '--',
            'just', 'test', '--locked', '--offline', *arguments, '--retries', '0',
            '--success-output', 'final', '--failure-output', 'final', '--no-tests', 'fail']
    root = expected is not None
    if root:
        keys = ['PATH', 'SOURCE_SHA', 'TESTED_SHA', 'HEPTA_CI_LANE', 'PYTHONDONTWRITEBYTECODE',
                'CARGO_INCREMENTAL', 'CARGO_BUILD_JOBS', 'CARGO_TARGET_DIR', 'CARGO_NET_OFFLINE',
                'RUSTY_V8_ARCHIVE', 'RUSTY_V8_SRC_BINDING_PATH', 'LIBCLANG_PATH',
                'RUSTUP_TOOLCHAIN', 'BINDGEN_EXTRA_CLANG_ARGS', 'RUSTFLAGS', 'LD_LIBRARY_PATH']
        environment = {key: os.environ[key] for key in keys if key in os.environ}
        environment.update(CARGO_HOME=os.environ.get('CARGO_HOME', '/home/qq/.cargo'),
                           RUSTUP_HOME=os.environ.get('RUSTUP_HOME', '/home/qq/.rustup'),
                           GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory',
                           GIT_CONFIG_VALUE_0=str(REPO),
                           HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=str(ROOT / 'bind'),
                           HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE=str(ROOT / 'source'),
                           HEPTA_Q24_FACTORY_WITNESS_BIND=str(ROOT / 'witness-bind'),
                           HEPTA_Q24_FACTORY_WITNESS_SOURCE=str(ROOT / 'witness-source'),
                           HEPTA_CHECKPOINT_TEST_ROOT=str(ROOT / 'checkpoints'),
                           HEPTA_ORDINARY_SOURCE_COMMIT=HEAD, HEPTA_ORDINARY_SOURCE_TREE=TREE)
        environment.update(json.loads((PUBLIC / 'helpers/env.json').read_text()))
        environment.update(json.loads((PUBLIC / 'product-env.json').read_text()))
        wrapper = "import os,runpy,sys; assert os.geteuid()==0; print('Root test uid=0',flush=True); runpy.run_path(sys.argv.pop(1),run_name='__main__')"
        argv = ['sudo', '-n', 'env', '-i', *(k + '=' + v for k, v in sorted(environment.items())),
                'python3', '-c', wrapper, *argv[1:]]
    try:
        code = command(name + '-execution', argv)
    finally:
        if root:
            restore_ownership()
    observed = [p for p in reports if p.exists()]
    collection = dict(status='missing-fresh-native-report', paths=[str(p) for p in observed])
    for index, report in enumerate(observed):
        shutil.copyfile(report, OUT / f'{name}-fresh-native-observed-{index}.xml')
    if len(observed) == 1:
        collected = collect(OUT / (name + '.json'), observed[0], OUT / (name + '.xml'))
        collection = json.loads((OUT / (name + '.summary.json')).read_text())
        collection['collector_exit_code'] = collected
        if expected is not None and (OUT / (name + '.xml')).exists():
            cases = list(ET.parse(OUT / (name + '.xml')).iter('testcase'))
            actual = [c.attrib['name'] for c in cases if c.find('skipped') is None]
            coverage = dict(expected=expected, observed=actual,
                            skipped=sum(c.find('skipped') is not None for c in cases),
                            exact=len(cases) == len(expected) and sorted(actual) == sorted(expected))
            save(OUT / (name + '-parent-coverage.json'), coverage)
            collection['exact_parent_coverage'] = coverage['exact']
    save(OUT / (name + '-collection.json'), collection)
    result[name] = dict(command_exit_code=code, collection=collection)
    persist()
    assert snapshot() == result['before'], 'source changed during actual tests'


def prepare_products():
    binaries = {'codex-hepta-agentd', 'hepta-authority-host'}
    argv = ['cargo', 'build', '--locked', '--offline', '-p', 'codex-hepta-agentd',
            '--bin', 'codex-hepta-agentd', '--bin', 'hepta-authority-host',
            '--message-format=json-render-diagnostics']
    assert command('product-build', argv, REPO / 'codex-rs') == 0, 'actual product build failed'
    artifacts, finished = {}, None
    (PUBLIC / 'bin').mkdir(mode=0o755)
    for line in (OUT / 'product-build.stdout.log').read_text().splitlines():
        record = json.loads(line)
        if record.get('reason') == 'build-finished':
            finished = record.get('success')
        target = record.get('target', {})
        name = target.get('name')
        if record.get('reason') != 'compiler-artifact' or name not in binaries or not record.get('executable'):
            continue
        assert 'bin' in target['kind'] and not record['profile']['test']
        source = Path(record['executable'])
        assert source.is_absolute() and source.is_file()
        pinned = PUBLIC / 'bin' / name
        digest = hashlib.sha256()
        with source.open('rb') as stream, pinned.open('xb') as output:
            before = os.fstat(stream.fileno())
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
            after = os.fstat(stream.fileno())
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        assert all(getattr(before, k) == getattr(after, k) for k in fields)
        pinned.chmod(0o555)
        with pinned.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest.hexdigest()
        assert pinned.stat().st_size == before.st_size and stat.S_ISREG(before.st_mode)
        artifacts[name] = dict(package_id=record['package_id'], profile=record['profile'],
                               compiler_executable=str(source), pinned=str(pinned),
                               bytes=before.st_size, sha256=digest.hexdigest())
    assert finished is True and set(artifacts) == binaries
    save(PUBLIC / 'product-manifest.json', dict(head=HEAD, tree=TREE, artifacts=artifacts))
    environment = {f'CARGO_BIN_EXE_{variant}': a['pinned'] for name, a in artifacts.items()
                   for variant in {name, name.replace('-', '_')}}
    save(PUBLIC / 'product-env.json', environment)
    os.environ.update(environment)


def prepare_a_library_binaries():
    # Actual UID1000 preparation only: no tests execute and no native PASS is
    # inferred. The sole execution below remains the exact A parent via just.
    assert os.getuid() == os.geteuid() == 1000
    argv = ['cargo', 'nextest', 'list', '--locked', '--offline',
            '-p', 'codex-hepta-agentd', '-p', 'codex-hepta-contracts', '--lib',
            '--list-type', 'binaries-only', '--message-format', 'json']
    assert command('a-library-binaries-build-uid1000', argv, REPO / 'codex-rs') == 0, 'actual UID1000 test-binary preparation failed'
    assert snapshot() == result['before'], 'source changed during UID1000 test-binary preparation'


persist()
started = time.monotonic()
owner = None
mounts_created = False
try:
    assert os.getuid() == 1000
    fix = json.loads((BASE / 'validation/root-5e74fe40-scoped-fix-v1/result.json').read_text())
    assert fix['status'] == 'completed' and fix['exit_code'] == 0 and fix['source_unchanged']
    owner = (TARGET / '.hepta-root-native-owner.lock').open('a+b')
    fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with (TARGET / 'debug/.cargo-lock').open('rb') as probe:
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe, fcntl.LOCK_UN)
    result['before'] = snapshot()
    assert result['before']['head'] == HEAD and result['before']['tree'] == TREE and not result['before']['status']
    assert all(value == fix['before'][key] for key, value in result['before'].items())
    original = json.loads((BASE / 'env.json').read_text())
    os.environ.update(original)
    for key in list(os.environ):
        if key.startswith('CARGO_PROFILE_'):
            del os.environ[key]
    os.environ.update(RUSTUP_TOOLCHAIN='1.96.0', CARGO_BUILD_JOBS='1', CARGO_INCREMENTAL='0',
                      CARGO_TARGET_DIR=str(TARGET), CARGO_NET_OFFLINE='true',
                      SOURCE_SHA=HEAD, TESTED_SHA=HEAD, HEPTA_CI_LANE='source-head',
                      PYTHONDONTWRITEBYTECODE='1', GIT_TERMINAL_PROMPT='0')
    os.environ['PATH'] = str(BASE / 'bin') + ':/home/qq/.cargo/bin:' + os.environ['PATH']
    os.chdir(REPO)
    sys.path.insert(0, str(REPO / 'scripts'))
    from hepta_ci_junit import collect
    PUBLIC.mkdir(mode=0o755)
    result.update(status='preparing', driver_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    persist()
    assert command('helper-build', ['python3', 'scripts/hepta_cell_test_helpers.py', '--package',
                                   'codex-hepta-infer-worker-host', '--output-dir', str(PUBLIC / 'helpers')]) == 0
    (PUBLIC / 'helpers').chmod(0o755)
    (PUBLIC / 'helpers/bin').chmod(0o755)
    assert command('helper-verify', ['python3', 'scripts/hepta_cell_test_helpers.py', '--package',
                                    'codex-hepta-infer-worker-host', '--output-dir', str(PUBLIC / 'helpers'), '--verify-only']) == 0
    os.environ.update(json.loads((PUBLIC / 'helpers/env.json').read_text()))
    prepare_products()
    prepare_a_library_binaries()
    assert snapshot() == result['before']
    setup = '''import os,pathlib,subprocess,json
assert os.geteuid()==0
root=pathlib.Path(%r);root.mkdir(mode=0o700)
for name in ['source','bind','witness-source','witness-bind','checkpoints']:(root/name).mkdir(mode=0o700)
for source,target in [('source','bind'),('witness-source','witness-bind')]:
 subprocess.run(['mount','--bind',str(root/source),str(root/target)],check=True)
 assert (root/source).stat().st_dev==(root/target).stat().st_dev
 assert (root/source).stat().st_ino==(root/target).stat().st_ino
rows=[line for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines() if str(root) in line]
assert len(rows)==2
print(json.dumps({'uid':os.geteuid(),'root':str(root),'actual_mountinfo':rows}))
''' % str(ROOT)
    mounts_created = True
    assert command('root-mount-setup', ['sudo', '-n', 'python3', '-c', setup]) == 0
    save(OUT / 'ordinary-a-parent-roster.json', [A_PARENT])
    result['status'] = 'testing'
    persist()
    root_args = ['-p', 'codex-hepta-agentd', '-p', 'codex-hepta-contracts', '--lib',
                 '--run-ignored', 'only', '--test-threads', '1', '-E']
    test('ordinary-a', [*root_args, f'test(={A_PARENT})'], [A_PARENT])
    result['status'] = 'completed'
except BaseException as error:
    result.update(status='driver_failed', error=repr(error))
    (OUT / 'driver-error.log').write_text(traceback.format_exc())
finally:
    if mounts_created:
        try:
            cleanup = []
            for name in ['witness-bind', 'bind']:
                active = [line.split()[4] for line in Path('/proc/self/mountinfo').read_text().splitlines()]
                if str(ROOT / name) not in active:
                    continue
                p = subprocess.run(['sudo', '-n', 'umount', str(ROOT / name)], capture_output=True, text=True)
                cleanup.append(dict(path=str(ROOT / name), code=p.returncode, stdout=p.stdout, stderr=p.stderr))
            save(OUT / 'mount-cleanup.json', cleanup)
        except BaseException as error:
            result['cleanup_error'] = repr(error)
    try:
        result['after'] = snapshot()
        result['source_unchanged'] = result.get('before') == result['after']
    except BaseException as error:
        result['snapshot_error'] = repr(error)
    result.update(finished=utc(), elapsed=time.monotonic() - started)
    result['logs'] = {}
    for path in sorted(OUT.rglob('*')):
        if path.is_file() and path.name not in ['result.json', 'result.json.tmp']:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            result['logs'][str(path.relative_to(OUT))] = dict(bytes=path.stat().st_size, sha256=digest)
    persist()
    if owner is not None:
        owner.close()
    print('ROOT_5E74_NATIVE_TESTS_TERMINAL ' + json.dumps(result), flush=True)
