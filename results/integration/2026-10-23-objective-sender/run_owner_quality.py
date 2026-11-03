#!/usr/bin/env python3
"""Run the original scoped quality entry points and record every source rewrite."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import owner_overlay
from run_owner_candidate import snapshot

ROOT = Path(__file__).resolve().parent.parent
VALIDATION = ROOT / 'validation'
TASK_ROOT = Path('/dev/shm/organ-3d6a75235bcb-hepta3398')
SOURCE = TASK_ROOT / 'source'

def main():
    mode, run = sys.argv[1:]
    assert re.fullmatch('[a-z0-9-]+', run)
    prefix = VALIDATION / run
    assert not prefix.with_suffix('.json').exists()
    if mode == 'fix-memory':
        command = ['just', 'fix', '-p', 'codex-hepta-memory', '--locked', '--profile', 'dev-small', '--lib']
    elif mode == 'format':
        command = ['just', 'fmt']
    elif mode == 'format-check':
        command = ['just', 'fmt', '--check']
    else:
        raise ValueError(mode)
    before = owner_overlay.changes()
    verified_before = owner_overlay.verify(before)
    backups = VALIDATION / 'quality-preimages' / run
    for row in before:
        dest = backups / row['path']
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((SOURCE / row['path']).read_bytes())
    environment = os.environ.copy()
    overrides = {
        'PATH': '/tmp/hepta-native-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin:/tmp/hepta-native-cargo/bin:/tmp/hepta-output-portfolio-env/bin:/usr/local/bin:/usr/bin:/bin',
        'CARGO_HOME': str(TASK_ROOT / 'cargo-home'),
        'CARGO_TARGET_DIR': str(TASK_ROOT / 'target'),
        'TMPDIR': str(TASK_ROOT / 'tmp'),
        'RUSTUP_HOME': '/tmp/hepta-native-rustup',
        'RUSTUP_TOOLCHAIN': '1.95.0',
        'RUSTUP_AUTO_INSTALL': '0',
        'CARGO_INCREMENTAL': '0',
        'CARGO_BUILD_JOBS': '1',
        'CARGO_HTTP_TIMEOUT': '30',
        'CARGO_NET_RETRY': '1',
        'OPENSSL_LIB_DIR': '/usr/lib/x86_64-linux-gnu',
        'OPENSSL_INCLUDE_DIR': '/usr/include',
        'GIT_DIR': str(VALIDATION / 'format-baseline.git'),
        'GIT_WORK_TREE': str(SOURCE),
    }
    environment.update(overrides)
    tool_versions = {}
    for invocation in [['rustc', '--version'], ['rustfmt', '--version'], ['cargo', 'clippy', '--version'], ['just', '--version']]:
        output = subprocess.run(invocation, env=environment, capture_output=True, text=True)
        tool_versions[' '.join(invocation)] = {'exit_code': output.returncode, 'stdout': output.stdout, 'stderr': output.stderr}
    lock = SOURCE / 'codex-rs/Cargo.lock'
    lock_before = hashlib.sha256(lock.read_bytes()).hexdigest()
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    measurements = [snapshot()]
    stop_reason = None
    with prefix.with_suffix('.stdout').open('w') as stdout, prefix.with_suffix('.stderr').open('w') as stderr:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        print(json.dumps({'command': command, 'initial_resources': measurements[0]}), flush=True)
        last = time.monotonic()
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic() - last < 10:
                continue
            last = time.monotonic()
            measured = snapshot()
            measurements.append(measured)
            print(json.dumps(measured), flush=True)
            if measured['memory_available_bytes'] < 1.5 * 1024 ** 3:
                stop_reason = 'Available memory fell below the coordinated 1.5 GiB boundary.'
            elif measured['shm_available_bytes'] < 256 * 1024 ** 2:
                stop_reason = 'Shared-memory space fell below the coordinated 256 MiB boundary.'
            if stop_reason:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                break
        result = process.wait()
    rewrites = []
    for row in before:
        data = (SOURCE / row['path']).read_bytes()
        after_hash = hashlib.sha256(data).hexdigest()
        if after_hash != row['candidate_sha256']:
            rewrites.append({'path': row['path'], 'before_sha256': row['candidate_sha256'], 'after_sha256': after_hash})
            (ROOT / 'change' / row['path']).write_bytes(data)
    after = owner_overlay.changes()
    verification_error = None
    try:
        verified_after = owner_overlay.verify(after)
    except Exception as error:
        verification_error = repr(error)
        verified_after = None
    receipt = {'base_head': owner_overlay.BASELINE['head'], 'base_tree': owner_overlay.BASELINE['tree'], 'source_is_candidate_overlay': True, 'command': command, 'cwd': str(SOURCE), 'environment_overrides': overrides, 'tool_versions': tool_versions, 'started_at': started, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'exit_code': result, 'controlled_stop_reason': stop_reason, 'before_changes': before, 'after_changes': after, 'rewrites': rewrites, 'source_verification_before': verified_before, 'source_verification_after': verified_after, 'source_verification_error': verification_error, 'Cargo_lock_sha256_before': lock_before, 'Cargo_lock_sha256_after': hashlib.sha256(lock.read_bytes()).hexdigest(), 'resources': measurements}
    for extension in ['stdout', 'stderr']:
        data = prefix.with_suffix('.' + extension).read_bytes()
        receipt[extension + '_file'] = prefix.with_suffix('.' + extension).name
        receipt[extension + '_sha256'] = hashlib.sha256(data).hexdigest()
    prefix.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    if verified_after is not None:
        (VALIDATION / 'overlay-identity.json').write_text(json.dumps({'base_head': owner_overlay.BASELINE['head'], 'base_tree': owner_overlay.BASELINE['tree'], 'candidate_is_uncommitted_overlay': True, 'changes': after, 'verification': verified_after}, indent=2) + '\n')
    print(json.dumps({'receipt': str(prefix.with_suffix('.json')), 'exit_code': result, 'controlled_stop_reason': stop_reason, 'source_verification_error': verification_error, 'rewritten_paths': [row['path'] for row in rewrites], 'stderr_tail': prefix.with_suffix('.stderr').read_text()[-6500:]}), flush=True)
    if verification_error:
        raise RuntimeError(verification_error)

if __name__ == '__main__':
    main()
