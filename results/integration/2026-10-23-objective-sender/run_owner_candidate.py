#!/usr/bin/env python3
"""Run original owning-package commands; bind results to the complete overlay."""
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

VALIDATION = Path(__file__).resolve().parent
TASK_ROOT = Path('/dev/shm/organ-3d6a75235bcb-hepta3398')
SOURCE = TASK_ROOT / 'source'
TARGET = TASK_ROOT / 'target'
MIB = 1024 ** 2
GIB = 1024 ** 3

def snapshot():
    available = next(int(line.split()[1]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
    return {'recorded_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'shm_available_bytes': shutil.disk_usage(TASK_ROOT).free, 'memory_available_bytes': available, 'target_bytes': int(subprocess.check_output(['du', '-sb', str(TARGET)], text=True).split()[0])}

def main():
    scope, run = sys.argv[1:]
    assert re.fullmatch('[a-z0-9-]+', run)
    prefix = VALIDATION / run
    assert not prefix.with_suffix('.json').exists(), 'Never replace an execution receipt.'
    command = ['just', 'test', '--locked', '--cargo-profile', 'dev-small', '--build-jobs', '1', '--test-threads', '1', '-p', 'codex-hepta-memory', '--lib']
    if scope == 'sender-schema-recovery':
        command += ['-E', 'test(objective_sender::) | test(schema) | test(recovery)']
    elif scope == 'memory-all':
        pass
    elif scope == 'agentd-sender':
        command[command.index('codex-hepta-memory')] = 'codex-hepta-agentd'
        command += ['-E', 'test(production_composition::objective_sender_tests::)']
    else:
        raise ValueError(scope)
    rows = owner_overlay.changes()
    verified = owner_overlay.verify(rows)
    identity = json.loads((VALIDATION / 'overlay-identity.json').read_text())
    assert rows == identity['changes']
    environment = os.environ.copy()
    overrides = {
        'PATH': '/tmp/hepta-native-rustup/toolchains/1.95.0-x86_64-unknown-linux-gnu/bin:/tmp/hepta-native-cargo/bin:/tmp/hepta-output-portfolio-env/bin:/usr/local/bin:/usr/bin:/bin',
        'CARGO_HOME': str(TASK_ROOT / 'cargo-home'),
        'CARGO_TARGET_DIR': str(TARGET),
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
    }
    environment.update(overrides)
    tools = {}
    for invocation in [['rustc', '--version', '--verbose'], ['cargo', '--version'], ['cargo', 'nextest', '--version'], ['just', '--version']]:
        observed = subprocess.run(invocation, env=environment, text=True, capture_output=True)
        tools[' '.join(invocation)] = {'exit_code': observed.returncode, 'stdout': observed.stdout, 'stderr': observed.stderr}
    lock = SOURCE / 'codex-rs/Cargo.lock'
    lock_before = hashlib.sha256(lock.read_bytes()).hexdigest()
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    measurements = [snapshot()]
    assert measurements[0]['memory_available_bytes'] >= 1.5 * GIB, measurements[0]
    assert measurements[0]['shm_available_bytes'] >= 256 * MIB, measurements[0]
    stop_reason = None
    with prefix.with_suffix('.stdout').open('w') as stdout, prefix.with_suffix('.stderr').open('w') as stderr:
        process = subprocess.Popen(command, cwd=SOURCE, env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
        print(json.dumps({'command': command, 'candidate_overlay': True, 'initial_resources': measurements[0]}), flush=True)
        last = time.monotonic()
        while process.poll() is None:
            time.sleep(1)
            if time.monotonic() - last < 10:
                continue
            last = time.monotonic()
            measured = snapshot()
            measurements.append(measured)
            print(json.dumps(measured), flush=True)
            if measured['memory_available_bytes'] < 1.5 * GIB:
                stop_reason = 'Available memory fell below the coordinated 1.5 GiB boundary.'
            elif measured['shm_available_bytes'] < 256 * MIB:
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
    verified_after = owner_overlay.verify(rows)
    junit = SOURCE / 'codex-rs/target/nextest/local/junit.xml'
    if junit.is_file():
        prefix.with_suffix('.junit.xml').write_bytes(junit.read_bytes())
    measurements.append(snapshot())
    receipt = {'base_head': identity['base_head'], 'base_tree': identity['base_tree'], 'source_is_candidate_overlay': True, 'overlay_changes': rows, 'source_verification_before': verified, 'source_verification_after': verified_after, 'command': command, 'cwd': str(SOURCE), 'environment_overrides': overrides, 'tool_versions': tools, 'started_at': started, 'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'exit_code': result, 'controlled_stop_reason': stop_reason, 'Cargo_lock_sha256_before': lock_before, 'Cargo_lock_sha256_after': hashlib.sha256(lock.read_bytes()).hexdigest(), 'resources': measurements, 'stdout_file': prefix.with_suffix('.stdout').name, 'stderr_file': prefix.with_suffix('.stderr').name}
    for extension in ['stdout', 'stderr']:
        data = prefix.with_suffix('.' + extension).read_bytes()
        receipt[extension + '_sha256'] = hashlib.sha256(data).hexdigest()
    prefix.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'receipt': str(prefix.with_suffix('.json')), 'exit_code': result, 'controlled_stop_reason': stop_reason, 'stderr_tail': prefix.with_suffix('.stderr').read_text()[-6500:]}), flush=True)

if __name__ == '__main__':
    main()
