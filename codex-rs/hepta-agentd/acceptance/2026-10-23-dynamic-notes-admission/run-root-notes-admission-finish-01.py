from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import time

data = Path('/data/asterinas-audit-build.8tdrjboi')
source = data / 'root-notes-objective-negative'
qualified = data / 'root-notes-admission-positive-02'
result = json.loads((qualified / 'result.json').read_text())
assert result['status'] == 'complete' and result['passed'] and result['source_inputs_unchanged']
assert result['source_head'] == 'b6a22e1552a2b530a2b5eeb41d2f0710ae82c0cd'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == result['source_head']
assert not subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=source)
output = data / 'root-notes-admission-finish-01'
output.mkdir(mode=0o700, exist_ok=False)
target = Path('/data/hepta-root-service-196-target.e3i3hcbg')
toolchain = Path.home() / '.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu'
temporary = Path(tempfile.mkdtemp(prefix='hf.', dir='/data'))
env = os.environ.copy()
env.update(PATH=str(toolchain / 'bin') + ':' + str(Path.home() / '.cargo/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
    RUSTUP_TOOLCHAIN='1.96.0', RUSTC=str(toolchain / 'bin/rustc'), CARGO_TARGET_DIR=str(target),
    TMPDIR=str(temporary), CARGO_BUILD_JOBS='2', CARGO_NET_OFFLINE='true', PYTHONDONTWRITEBYTECODE='1')
env.pop('CARGO_INCREMENTAL', None)
env.pop('CARGO_PROFILE_DEV_DEBUG', None)
pair = Path('/data/hepta-dependency-v8-pair/rusty-v8-150.4.0-x86_64-unknown-linux-gnu')
env.update(RUSTY_V8_ARCHIVE=str(pair / 'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz'),
    RUSTY_V8_SRC_BINDING_PATH=str(pair / 'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs'))

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

metadata = json.loads((qualified / 'binaries-metadata.json').read_text())
binary = Path(metadata['rust-binaries']['codex-hepta-agentd']['binary-path'])
retained = output / 'original-positive-libtest'
subprocess.run(['cp', '--reflink=auto', '--update=none', str(binary), str(retained)], check=True)
retained.chmod(0o555)
assert retained.stat().st_nlink == 1 and sha(binary) == sha(retained)
report = {'schema': 'hepta.root-notes-admission-finish.v1', 'qualified_source': result['source_head'],
    'target': str(target), 'qualified_test_binary': str(binary), 'retained_test_binary': str(retained),
    'retained_test_sha256': sha(retained), 'commands': [], 'passed': False,
    'semantic_tests_after_finish': False, 'production_authority': False, 'status': 'running'}

def snapshot():
    rows = []
    for entry in subprocess.check_output(['git', 'ls-files', '-s', '-z'], cwd=source).split(b'\0'):
        if not entry:
            continue
        attributes, name = entry.split(b'\t', 1)
        mode, blob, stage = attributes.decode().split()
        assert stage == '0'
        path = source / os.fsdecode(name)
        raw = os.readlink(path).encode() if mode == '120000' else path.read_bytes()
        rows.append({'path': os.fsdecode(name), 'mode': mode, 'blob': blob, 'sha256': hashlib.sha256(raw).hexdigest()})
    return {'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip(),
        'status': subprocess.check_output(['git', 'status', '--porcelain=v1'], cwd=source, text=True), 'files': rows}

before = snapshot()
(output / 'source-before.json').write_text(json.dumps(before, indent=2) + '\n')
assert before['files'] == json.loads((qualified / 'source-after.json').read_text())['files']

def save():
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

save()
try:
    just = str(Path.home() / '.cargo/bin/just')
    for name, command in [
        ('scoped-fix', [just, 'fix', '-p', 'codex-hepta-agentd']),
        ('range-format', [just, 'fmt', '--base', 'ad9c1b552']),
        ('default-format', [just, 'fmt']),
        ('range-format-check', [just, 'fmt', '--base', 'ad9c1b552', '--check']),
    ]:
        row = {'stage': name, 'argv': command}
        report['commands'].append(row)
        save()
        started = time.monotonic()
        with (output / (name + '.log')).open('xb') as stream:
            run = subprocess.run(command, cwd=source / 'codex-rs', env=env,
                stdout=stream, stderr=subprocess.STDOUT, timeout=7200)
        row.update(exit_code=run.returncode, seconds=round(time.monotonic() - started, 3))
        save()
        assert run.returncode == 0, name
    report['passed'] = True
finally:
    (output / 'source-after.json').write_text(json.dumps(snapshot(), indent=2) + '\n')
    (output / 'finish.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary', result['source_head']], cwd=source))
    report['status'] = 'complete'
    save()
