from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True)
parser.add_argument('--head', required=True)
parser.add_argument('--output', required=True)
parser.add_argument('--target', required=True)
parser.add_argument('--negative', action='store_true')
args = parser.parse_args()
data = Path('/data/asterinas-audit-build.8tdrjboi')
source, output, target = map(Path, [args.source, args.output, args.target])
assert source.parent == data and output.parent == data and target.is_dir()
assert str(target) in {str(data / 'root-final-use-target'), '/data/hepta-root-service-196-target.e3i3hcbg'}
output.mkdir(mode=0o700, exist_ok=False)
temporary = Path(tempfile.mkdtemp(prefix='hn.', dir='/data'))
toolchain = Path.home() / '.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu'

def snapshot():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip()
    assert head == args.head
    assert not subprocess.check_output(['git', 'status', '--porcelain=v1', '--untracked-files=all'], cwd=source)
    rows = []
    for entry in subprocess.check_output(['git', 'ls-files', '-s', '-z'], cwd=source).split(b'\0'):
        if not entry:
            continue
        attributes, name = entry.split(b'\t', 1)
        mode, blob, stage = attributes.decode().split()
        assert stage == '0'
        path = source / os.fsdecode(name)
        raw = os.readlink(path).encode() if mode == '120000' else path.read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blob
        rows.append({'path': os.fsdecode(name), 'mode': mode, 'blob': blob,
                     'sha256': hashlib.sha256(raw).hexdigest()})
    return {'head': head, 'tree': subprocess.check_output(['git', 'rev-parse', 'HEAD^{tree}'], cwd=source, text=True).strip(), 'files': rows}

before = snapshot()
(output / 'source-before.json').write_text(json.dumps(before, indent=2) + '\n')
env = os.environ.copy()
env.update(PATH=str(toolchain / 'bin') + ':' + str(Path.home() / '.cargo/bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
    RUSTUP_TOOLCHAIN='1.96.0', RUSTC=str(toolchain / 'bin/rustc'),
    CARGO_TARGET_DIR=str(target), TMPDIR=str(temporary), CARGO_BUILD_JOBS='2',
    CARGO_NET_OFFLINE='true', PYTHONDONTWRITEBYTECODE='1')
if target.name == 'root-final-use-target':
    env.update(CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0')
else:
    env.pop('CARGO_INCREMENTAL', None)
    env.pop('CARGO_PROFILE_DEV_DEBUG', None)
pair = Path('/data/hepta-dependency-v8-pair/rusty-v8-150.4.0-x86_64-unknown-linux-gnu')
env.update(RUSTY_V8_ARCHIVE=str(pair / 'librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz'),
           RUSTY_V8_SRC_BINDING_PATH=str(pair / 'src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs'))
report = {'schema': 'hepta.root-notes-admission-qualification.v1', 'source_head': args.head,
    'source_tree': before['tree'], 'target': str(target), 'commands': [],
    'negative_control': args.negative, 'passed': False, 'status': 'running',
    'production_authority': False, 'actual_session_reserved_qualified': False,
    'actual_five_lane_dynamic_notes_qualified': False}

def save():
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

def run(name, command, deadline, stdout_file=None, accepted=(0,)):
    row = {'stage': name, 'argv': command}
    report['commands'].append(row)
    save()
    start = time.monotonic()
    with (output / (name + '.log')).open('xb') as log:
        if stdout_file:
            with stdout_file.open('xb') as stream:
                result = subprocess.run(command, cwd=source / 'codex-rs', env=env,
                                        stdout=stream, stderr=log, timeout=deadline)
        else:
            result = subprocess.run(command, cwd=source / 'codex-rs', env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=deadline)
    row.update(exit_code=result.returncode, seconds=round(time.monotonic() - start, 3))
    save()
    assert result.returncode in accepted, name
    return result.returncode

save()
try:
    metadata, binaries = output / 'cargo-metadata.json', output / 'binaries-metadata.json'
    run('manifest-metadata', [str(toolchain / 'bin/cargo'), 'metadata', '--no-deps', '--format-version=1', '--offline', '--locked'], 300, metadata)
    run('compile-original-test-binaries', [str(toolchain / 'bin/cargo'), 'nextest', 'list', '--cargo-profile', 'dev', '--locked', '--offline',
        '-p', 'codex-hepta-agentd', '--lib', '--cargo-metadata', str(metadata), '--list-type', 'binaries-only', '--message-format', 'json'], 14400, binaries)
    expression = 'test(deployment_notes_preserves_original_objective_route_across_exact_policy_replacement)' if args.negative else (
        'test(deployment_) | test(authority_host_service) | test(authority_host_consumer_frontier) | '
        'test(authority_host_wire) | test(root_writer_proof) | test(production_composition::objective_sender_tests)')
    code = run('original-owner-tests', [str(Path.home() / '.cargo/bin/just'), 'test', '--cargo-metadata', str(metadata),
        '--binaries-metadata', str(binaries), '-E', expression, '--test-threads', '2'], 7200, accepted=(100,) if args.negative else (0,))
    log = (output / 'original-owner-tests.log').read_text()
    if args.negative:
        assert code == 100 and 'exact single Notes policy required' in log
        assert 'deployment_notes_preserves_original_objective_route_across_exact_policy_replacement' in log
        report['expected_original_objective_composition_refusal_observed'] = True
    else:
        assert 'deployment_notes_preserves_original_objective_route_across_exact_policy_replacement' in log
        assert 'deployment_notes_ambiguous_notes_slot_cannot_install_or_replace_policy' in log
        keys = ['PATH', 'RUSTUP_TOOLCHAIN', 'RUSTC', 'CARGO_TARGET_DIR', 'TMPDIR', 'CARGO_NET_OFFLINE', 'PYTHONDONTWRITEBYTECODE']
        root_env = [f'{key}={env[key]}' for key in keys] + [
            'CARGO_HOME=' + str(Path.home() / '.cargo'),
            'HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT=/var/lib/hepta-authority-os3-ssd-20261023']
        run('actual-root-notes-test', ['sudo', '-n', '/usr/bin/env', *root_env, '/usr/bin/python3', '-I', '-B', '-c',
            'import os,sys; os.umask(0o077); os.execv(sys.argv[1],sys.argv[1:])', str(Path.home() / '.cargo/bin/just'),
            'test', '--cargo-metadata', str(metadata), '--binaries-metadata', str(binaries), '--run-ignored', 'only',
            '-E', 'test(deployment_notes_actual_root_clock_registry_and_canonical_issuer_issue_distinct_payloads)', '--test-threads', '1'], 7200)
        report['passed'] = True
finally:
    after = snapshot()
    assert after == before
    (output / 'source-after.json').write_text(json.dumps(after, indent=2) + '\n')
    report.update(status='complete', source_inputs_unchanged=True)
    save()
