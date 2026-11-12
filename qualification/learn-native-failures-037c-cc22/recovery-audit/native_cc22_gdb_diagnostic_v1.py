import datetime
import gzip
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

REPO = pathlib.Path('/home/qian-qi/hepta-learn-common-20261112-037c')
ROOT = pathlib.Path('/home/qian-qi/hepta-learn-037c-evidence')
RECORDS = ROOT / 'stack-diagnostic-cc22-v1'
SOURCE = 'cc22a69972d029d3ef28d49096f396eb5214c616'
TREE = '827fb70ed75d30c48d4693cbd0d23ea04f5744da'
INVENTORY = '89070a776816852bd4a8e3101a95ed789ddd8eb64660192467b88cfa6aa60144'
BINARY = pathlib.Path('/data/hepta-learn-037c-20261112/target-cache-v1/debug/deps/codex_hepta_agentd-0bb720b95785b5fd')
CASE = 'runtime::tests::circuit_task_ingress::q24_tests::model_selection_owner::original::evaluation_provider::panel_members::original_panel_reads_actual_b_and_retention_with_full_original_signatures'

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

def save(name, value):
    with (RECORDS / name).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')

def git(*args):
    return subprocess.check_output(['git', '--no-optional-locks', *args], cwd=REPO)

def snapshot(label):
    rows = []
    paths = set((git('ls-files', '-z') + git('ls-files', '--others', '--exclude-standard', '-z')).split(b'\0')) - {b''}
    for raw in sorted(paths):
        rel = os.fsdecode(raw)
        path = REPO / rel
        if not path.exists() and not path.is_symlink():
            rows.append({'path': rel, 'missing': True})
            continue
        data = os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()
        mode = '120000' if path.is_symlink() else ('100755' if path.stat().st_mode & 0o111 else '100644')
        rows.append({'path': rel, 'mode': mode, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()})
    encoded = json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()
    with gzip.open(RECORDS / (label + '.files.json.gz'), 'xb') as stream:
        stream.write(encoded)
    value = {'commit': git('rev-parse', 'HEAD').decode().strip(), 'tree': git('rev-parse', 'HEAD^{tree}').decode().strip(), 'status': git('status', '--porcelain=v1', '--untracked-files=all').decode(), 'files': len(rows), 'inventory_sha256': hashlib.sha256(encoded).hexdigest()}
    save(label + '.json', value)
    return value

GDB_PROGRAM = '''import gdb, json, pathlib, time
events = []
def stopped(event):
    events.append({'kind': 'stop', 'signal': getattr(event, 'stop_signal', None), 'wall_time': time.time()})
def exited(event):
    events.append({'kind': 'exit', 'exit_code': getattr(event, 'exit_code', None), 'wall_time': time.time()})
gdb.events.stop.connect(stopped)
gdb.events.exited.connect(exited)
try:
    gdb.execute('run')
    while gdb.selected_inferior().pid:
        gdb.write('HEPTA_GDB_STOP ' + json.dumps(events[-1] if events else {}) + '\\n')
        for command in ['thread apply all bt 60', 'info registers rsp rbp rip', 'info symbol $rip']:
            try:
                gdb.execute(command)
            except gdb.error as error:
                gdb.write('HEPTA_GDB_INSPECTION_ERROR ' + str(error) + '\\n')
        # Deliver the original signal, including SIGSEGV and SIGABRT, so Rust's
        # handler and the kernel finish the original failing process naturally.
        gdb.execute('continue')
finally:
    pathlib.Path(EVENTS_PATH).write_text(json.dumps({'events': events, 'inferior_pid_at_end': gdb.selected_inferior().pid, 'manual_inferior_kill': False}, indent=2) + '\\n')
'''

RUNNER_PROGRAM = '''import hashlib, json, os, pathlib, sys
records = pathlib.Path(RECORDS_PATH)
admission = json.loads((records / 'debug-admission.json').read_text())
binary = pathlib.Path(sys.argv[1]).resolve()
arguments = sys.argv[2:]
def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()
assert os.environ.get('RUST_MIN_STACK') == '8388608'
# Cargo-nextest asks the original libtest binary to enumerate tests. Listing
# does not run a fixture, and only the exact requested case enters GDB.
if '--list' in arguments:
    assert binary.parent == pathlib.Path(admission['binary']['path']).parent
    assert binary.name.startswith(('codex_hepta_agentd-', 'codex_hepta_intelligence_eval-'))
    if str(binary) == admission['binary']['path']:
        assert sha(binary) == admission['binary']['sha256']
    os.execv(str(binary), [str(binary), *arguments])
assert str(binary) == admission['binary']['path'], str(binary)
assert sha(binary) == admission['binary']['sha256']
assert admission['case'] in arguments, arguments
assert '--exact' in arguments, arguments
invocation = {'binary': str(binary), 'binary_sha256': admission['binary']['sha256'], 'arguments': arguments, 'rust_min_stack': os.environ['RUST_MIN_STACK'], 'nextest_profile': os.environ.get('NEXTEST_PROFILE'), 'diagnostic_only': True}
with (records / 'runner-invocation.json').open('x') as stream:
    json.dump(invocation, stream, indent=2)
    stream.write('\\n')
gdb = admission['gdb']['path']
commands = ['set pagination off', 'set confirm off', 'set print frame-arguments none', 'set print thread-events off', 'set disable-randomization off', 'set auto-load python-scripts off', 'set auto-load local-gdbinit off', 'set debuginfod enabled off', 'handle SIGPIPE nostop noprint pass', 'handle SIGSEGV stop print pass', 'handle SIGABRT stop print pass', 'set logging file ' + str(records / 'gdb.raw.log'), 'set logging overwrite off', 'set logging enabled on', 'python exec(compile(open(' + repr(str(records / 'gdb-program.py')) + ').read(), ' + repr(str(records / 'gdb-program.py')) + ", 'exec'))"]
argv = [gdb, '--nx', '--batch', '--quiet', '--return-child-result']
for command in commands:
    argv.extend(['-ex', command])
argv.extend(['--args', str(binary), *arguments])
# Replace the runner process. GDB's --return-child-result propagates the actual
# inferior exit, while nextest remains responsible for the unchanged 60s cap.
os.execv(gdb, argv)
'''

RECORDS.mkdir(mode=0o700)
result = {'diagnostic_only': True, 'acceptance_pass': False, 'source_sha': SOURCE, 'case': CASE, 'started_at': now(), 'manual_rust_kill': False, 'ordinary_or_root_run': False}
before = None
returncode = 1
try:
    before = snapshot('source-before')
    assert before == {'commit': SOURCE, 'tree': TREE, 'status': '', 'files': 14842, 'inventory_sha256': INVENTORY}, before
    focused = json.loads((ROOT / 'native-cc22a69972d0-focused-v1/driver-result.json').read_text())
    assert focused['source_before'] == focused['source_after'] == before
    assert focused['status'] == 'failed'
    env_record = json.loads((ROOT / 'maintenance-cc22a69972d0-v1/native-environment.json').read_text())
    environment = os.environ.copy()
    for key, value in env_record['environment'].items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    for item in env_record['native_inputs']:
        assert pathlib.Path(item['path']).stat().st_size == item['bytes'] and sha(item['path']) == item['sha256']
    helper = ROOT / 'native-cc22a69972d0-focused-v1/helpers'
    helper_manifest = json.loads((helper / 'manifest.json').read_text())
    assert helper_manifest['complete'] and helper_manifest['exit_code'] == 0
    for artifact in helper_manifest['artifacts'].values():
        assert sha(artifact['executable']) == artifact['sha256']
    environment.update(json.loads((helper / 'env.json').read_text()))
    environment.update(RUST_MIN_STACK='8388608', RUST_BACKTRACE='full', DEBUGINFOD_URLS='')
    assert sha(REPO / 'codex-rs/Cargo.lock') == '98b3767c6e74bf6eeb5894db760259dbc400cbfd0685af8ad915c92d25408d69'
    config = (REPO / 'codex-rs/.config/nextest.toml').read_bytes()
    assert hashlib.sha1(b'blob ' + str(len(config)).encode() + b'\0' + config).hexdigest() == '0904c42a41594d3ae4dc6f196e64f35f0b85bd2c'
    assert 'slow-timeout = { period = "30s", terminate-after = 2 }' in config.decode()
    gdb = shutil.which('gdb', path=environment['PATH'])
    if not gdb:
        result.update(status='debugger_unavailable', debugger_installed=False)
        raise RuntimeError('No GDB available; no debugger installed and no Rust test started')
    help_result = subprocess.run([gdb, '--nx', '--help'], capture_output=True, text=True, env=environment, check=True)
    assert '--return-child-result' in help_result.stdout
    version = subprocess.check_output([gdb, '--nx', '--version'], env=environment).decode()
    assert BINARY.is_file() and os.access(BINARY, os.X_OK)
    with BINARY.open('rb') as stream:
        assert stream.read(4) == b'\x7fELF'
    admission = {'source_before': before, 'case': CASE, 'binary': {'path': str(BINARY), 'bytes': BINARY.stat().st_size, 'sha256': sha(BINARY), 'mtime_ns': BINARY.stat().st_mtime_ns}, 'gdb': {'path': gdb, 'bytes': pathlib.Path(gdb).stat().st_size, 'sha256': sha(gdb), 'version': version}, 'helper_manifest_sha256': sha(helper / 'manifest.json'), 'original_nextest_config_git_blob': '0904c42a41594d3ae4dc6f196e64f35f0b85bd2c', 'original_case_timeout_seconds': 60, 'rust_min_stack': 8388608, 'acceptance_pass': False}
    save('debug-admission.json', admission)
    (RECORDS / 'gdb-program.py').write_text('EVENTS_PATH = ' + repr(str(RECORDS / 'gdb-events.json')) + '\n' + GDB_PROGRAM)
    (RECORDS / 'runner.py').write_text('RECORDS_PATH = ' + repr(str(RECORDS)) + '\n' + RUNNER_PROGRAM)
    environment['CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER'] = '/usr/bin/python3 ' + str(RECORDS / 'runner.py')
    save('environment.json', {'original': env_record['environment'], 'helper': json.loads((helper / 'env.json').read_text()), 'diagnostic_additions': {name: environment[name] for name in ['RUST_MIN_STACK', 'RUST_BACKTRACE', 'DEBUGINFOD_URLS', 'CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_RUNNER']}})
    report = REPO / 'codex-rs/target/nextest/local/junit.xml'
    if report.exists():
        prior = {'path': str(report), 'bytes': report.stat().st_size, 'sha256': sha(report), 'status': 'stale_for_this_diagnostic'}
        report.rename(RECORDS / 'cc22-focused-prior-junit-excluded.xml')
        save('prior-junit-excluded.json', prior)
    command = ['python3', 'scripts/hepta_ci_exec.py', '--timeout-seconds', '7200', '--minimum-tests', '1', '--output', str(RECORDS / 'single-case.json'), '--', 'just', 'test', '--locked', '--offline', '-p', 'codex-hepta-agentd', '-p', 'codex-hepta-intelligence-eval', '--lib', '-E', 'test(=' + CASE + ')', '--test-threads', '1', '--retries', '0', '--status-level', 'pass', '--success-output', 'final', '--failure-output', 'final']
    save('invocation.json', {'command': command, 'cwd': str(REPO), 'diagnostic_only': True})
    print(json.dumps({'debug_admission': admission, 'command': command}, indent=2), flush=True)
    returncode = subprocess.run(command, cwd=REPO, env=environment).returncode
    result.update(status='diagnostic_execution_finished', actual_process_exit_observed=True, original_runner_returncode=returncode)
    assert sha(BINARY) == admission['binary']['sha256'], 'binary changed during diagnostic'
    assert (RECORDS / 'runner-invocation.json').is_file(), 'target runner was not invoked for the requested case'
    if (RECORDS / 'gdb-events.json').is_file():
        result['gdb_events'] = json.loads((RECORDS / 'gdb-events.json').read_text())
    if (RECORDS / 'gdb.raw.log').is_file():
        result['gdb_log'] = {'path': str(RECORDS / 'gdb.raw.log'), 'bytes': (RECORDS / 'gdb.raw.log').stat().st_size, 'sha256': sha(RECORDS / 'gdb.raw.log')}
    if report.exists():
        shutil.copy2(report, RECORDS / 'single-case.xml')
        nodes = list(ET.parse(report).getroot().iter('testcase'))
        result['junit'] = {'sha256': sha(report), 'case_count': len(nodes), 'cases': [{'attributes': dict(node.attrib), 'result_tags': [child.tag for child in node]} for node in nodes]}
        assert len(nodes) == 1 and nodes[0].attrib['name'] == CASE
except BaseException as error:
    result.update(status='diagnostic_error', error=repr(error))
    traceback.print_exc()
    returncode = returncode or 1
finally:
    try:
        after = snapshot('source-after')
        result['source_after'] = after
        result['source_unchanged'] = before == after
        if before != after:
            returncode = returncode or 1
    except BaseException as error:
        result['snapshot_error'] = repr(error)
        returncode = returncode or 1
    result.update(finished_at=now(), returncode=returncode)
    save('result.json', result)
    print(json.dumps(result, indent=2), flush=True)
sys.exit(returncode)
