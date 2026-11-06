import datetime
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

root = pathlib.Path('/home/qq/work/hepta-portfolio-816d-20261106')
source = root / 'source'
expected_head, expected_tree, label, raw_command = sys.argv[1:]
assert re.fullmatch('[0-9a-f]{40}', expected_head)
assert re.fullmatch('[0-9a-f]{40}', expected_tree)
assert re.fullmatch('[a-z0-9-]+', label)
command = json.loads(raw_command)
assert isinstance(command, list) and command and all(isinstance(v, str) for v in command)
records = root / 'records' / label
records.mkdir(exist_ok=False)
env = os.environ.copy()
env.update(json.loads((root / 'env.json').read_text()))
env.update(CARGO_TERM_COLOR='never', CARGO_NET_OFFLINE='true', GIT_TERMINAL_PROMPT='0', GIT_LFS_SKIP_SMUDGE='1', CODEX_REPO_ROOT=str(source), BINDGEN_EXTRA_CLANG_ARGS='-isystem /usr/lib/gcc/x86_64-linux-gnu/15/include', LIBCLANG_PATH='/usr/lib/x86_64-linux-gnu')
def git(*args):
    return subprocess.check_output(['git', *args], cwd=source, text=True).strip()
def identity():
    return {'head': git('rev-parse', 'HEAD'), 'tree': git('rev-parse', 'HEAD^{tree}'), 'status': git('status', '--porcelain=v1', '--untracked-files=all')}
def resources():
    r = {'at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'disk_free': shutil.disk_usage(root).free, 'load_average': os.getloadavg()}
    for line in pathlib.Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in ['MemAvailable', 'SwapFree']:
            r[key + '_bytes'] = int(value.split()[0]) * 1024
    return r
before = identity()
assert before == {'head': expected_head, 'tree': expected_tree, 'status': ''}, before
v8 = {
    'RUSTY_V8_ARCHIVE': ('librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz', 'a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583'),
    'RUSTY_V8_SRC_BINDING_PATH': ('src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs', '7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506'),
}
v8_identity = {}
for key, (name, expected_hash) in v8.items():
    p = pathlib.Path('/home/qq/work/hepta-neuron-framework-734df8eaf8dc-20261106/v8-preparation-tmp/codex-package/rusty-v8-150.4.0-x86_64-unknown-linux-gnu') / name
    if p.is_file():
        h = hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda: f.read(1048576), b''):
                h.update(block)
        assert h.hexdigest() == expected_hash, str(p)
        env[key] = str(p)
        v8_identity[key] = {'path': str(p), 'sha256': h.hexdigest(), 'size': p.stat().st_size}
receipt = {'runner_sha256': hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(), 'source_before': before, 'command': command, 'cwd': str(source / 'codex-rs'), 'label': label, 'environment': {k: env[k] for k in ['PATH', 'RUSTUP_TOOLCHAIN', 'CARGO_HOME', 'RUSTUP_HOME', 'CARGO_TARGET_DIR', 'CARGO_BUILD_JOBS', 'CARGO_INCREMENTAL', 'CARGO_NET_OFFLINE', 'BINDGEN_EXTRA_CLANG_ARGS', 'LIBCLANG_PATH']}, 'v8_build_assets': v8_identity, 'resource_before': resources(), 'stdout': str(records / 'stdout.log'), 'stderr': str(records / 'stderr.log'), 'started_ns': time.time_ns(), 'state': 'running'}
assert receipt['resource_before']['disk_free'] >= 8 * 1024**3
if command[:2] == ['just', 'test']:
    helper_env = root / 'records' / 'rebound-helper-env.json'
    if helper_env.is_file():
        manifest = json.loads((root / 'records/rebound-helper-manifest.json').read_text())
        assert manifest['complete'] and manifest['exit_code'] == 0
        assert manifest['source_sha'] == manifest['source_sha_after'] == expected_head
        assert manifest['source_status_before'] == manifest['source_status_after'] == ''
        receipt['helper_manifest_path'] = str(root / 'records/rebound-helper-manifest.json')
        receipt['helper_manifest_sha256'] = hashlib.sha256((root / 'records/rebound-helper-manifest.json').read_bytes()).hexdigest()
        receipt['helper_before'] = []
        shutil.copy2(root / 'records/rebound-helper-manifest.json', records / 'pre-test-helper-manifest.json')
        shutil.copy2(helper_env, records / 'pre-test-helper-env.json')
        for artifact in manifest['artifacts'].values():
            executable = pathlib.Path(artifact['executable'])
            assert executable.is_relative_to(root / 'target')
            assert hashlib.sha256(executable.read_bytes()).hexdigest() == artifact['sha256']
            receipt['helper_before'].append({'executable': str(executable), 'sha256': artifact['sha256'], 'mtime_ns': executable.stat().st_mtime_ns, 'bytes': executable.stat().st_size})
        env.update(json.loads(helper_env.read_text()))
    prior = source / 'codex-rs/target/nextest/local/junit.xml'
    if prior.is_file():
        prior.rename(records / 'prior-junit.xml')
(records / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps({'stage': label, 'command': command, 'source': before, 'state': 'running'}), flush=True)
start = time.monotonic()
with (records / 'stdout.log').open('wb') as stdout, (records / 'stderr.log').open('wb') as stderr:
    proc = subprocess.Popen(command, cwd=source / 'codex-rs', env=env, stdout=stdout, stderr=stderr)
    while True:
        try:
            rc = proc.wait(timeout=20)
            break
        except subprocess.TimeoutExpired:
            sample = resources()
            with (records / 'resources.jsonl').open('a') as f:
                f.write(json.dumps(sample) + '\n')
            print(json.dumps({'stage': label, 'state': 'running', 'elapsed_seconds': time.monotonic() - start, 'resource': sample}), flush=True)
if command[:2] == ['just', 'test']:
    receipt['helper_after'] = []
    for artifact in manifest['artifacts'].values():
        executable = pathlib.Path(artifact['executable'])
        actual_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
        receipt['helper_after'].append({'executable': str(executable), 'sha256': actual_hash, 'mtime_ns': executable.stat().st_mtime_ns, 'bytes': executable.stat().st_size})
    receipt['helper_unchanged'] = receipt['helper_before'] == receipt['helper_after']
    if not receipt['helper_unchanged'] and rc == 0:
        receipt['command_exit_code'] = 0
        rc = 78
after = identity()
diagnostic_errors = []
if command[:2] == ['just', 'fix'] or command[:2] == ['cargo', 'clippy']:
    markers = ['errors present after applying fixes', 'failed to apply fixes', 'failed to automatically apply', 'failed to automatically fix', 'could not apply fixes', 'fixes failed to apply']
    for number, line in enumerate((records / 'stderr.log').read_text(errors='replace').splitlines(), 1):
        clean = line.lstrip().lower()
        if clean.startswith(('error:', 'error[')) or any(marker in clean for marker in markers):
            diagnostic_errors.append({'line': number, 'text': line})
    receipt['diagnostic_errors'] = diagnostic_errors
    if diagnostic_errors and rc == 0:
        receipt['command_exit_code'] = 0
        rc = 77
receipt.update(exit_code=rc, elapsed_seconds=time.monotonic() - start, source_after=after, source_unchanged=before == after, resource_after=resources(), state='succeeded' if rc == 0 and before == after else 'failed')
if before != after:
    (records / 'source.diff').write_text(subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=source, text=True))
if command[:2] == ['just', 'test']:
    junit = source / 'codex-rs/target/nextest/local/junit.xml'
    if junit.is_file() and junit.stat().st_mtime_ns >= receipt['started_ns']:
        saved = records / 'junit.xml'
        shutil.copy2(junit, saved)
        parsed = ET.parse(saved)
        cases = list(parsed.iter('testcase'))
        receipt['junit'] = {'origin': str(junit), 'origin_mtime_ns': junit.stat().st_mtime_ns, 'started_ns': receipt['started_ns'], 'path': str(saved), 'sha256': hashlib.sha256(saved.read_bytes()).hexdigest(), 'testcases': len(cases), 'failures': sum(c.find('failure') is not None for c in cases), 'errors': sum(c.find('error') is not None for c in cases), 'skipped': sum(c.find('skipped') is not None for c in cases)}
(records / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt), flush=True)
if rc:
    print((records / 'stderr.log').read_text(errors='replace')[-10000:], flush=True)
raise SystemExit(rc or (66 if before != after else 0))
