"""Run exact-source scoped Rust validation with isolated writable caches."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


ROOT = Path('/workspace/scratch/337c309bc660')
SOURCE = ROOT / 'hepta-native-qualification'
AUDIT = ROOT / 'hepta-audit/research/native'


def source_identity():
    diff = subprocess.check_output(['git', 'diff', '--binary', 'HEAD'], cwd=SOURCE)
    names = subprocess.check_output(
        ['git', 'diff', '--name-only', '-z', 'HEAD'], cwd=SOURCE
    ).decode().split('\0')
    return {
        'working_diff_sha256': hashlib.sha256(diff).hexdigest(),
        'modified_files': {
            name: hashlib.sha256((SOURCE / name).read_bytes()).hexdigest()
            for name in names if name
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('test', 'clippy', 'focus', 'cargo-bin-test', 'cargo-bin-clippy'))
    parser.add_argument('--expected-sha', required=True)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    mode = args.mode
    commands = {
        'test': ['just', 'test', '-p', 'codex-hepta-memory', '--lib', '--locked'],
        'focus': [
            'just', 'test', '-p', 'codex-hepta-memory', '--lib', '--locked',
            '-E', 'test(v2_fixture_migrates_forward_preserving_memory_and_revoking_legacy_projection)',
        ],
        'cargo-bin-test': ['just', 'test', '-p', 'codex-utils-cargo-bin', '--locked'],
        'clippy': [
            'just', 'clippy', '-p', 'codex-hepta-memory', '--locked', '--',
            '-D', 'clippy::correctness', '-D', 'clippy::await_holding_lock',
            '-D', 'clippy::await_holding_invalid_type',
            '-D', 'clippy::expect_used', '-D', 'clippy::unwrap_used',
        ],
    }
    commands['cargo-bin-clippy'] = [
        value if value != 'codex-hepta-memory' else 'codex-utils-cargo-bin'
        for value in commands['clippy']
    ]
    command = commands[mode]
    AUDIT.mkdir(parents=True, exist_ok=True)
    source_sha = subprocess.check_output(
        ['git', '--no-replace-objects', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True
    ).strip()
    assert source_sha == args.expected_sha, source_sha
    assert args.tag.replace('-', '').replace('_', '').isalnum(), args.tag
    result_path = AUDIT / f'{args.tag}-result.json'
    log_path = AUDIT / f'{args.tag}.log'
    assert not result_path.exists() and not log_path.exists(), args.tag
    tree = subprocess.check_output(
        ['git', '--no-replace-objects', 'rev-parse', 'HEAD^{tree}'],
        cwd=SOURCE, text=True,
    ).strip()
    lock_path = SOURCE / 'codex-rs/Cargo.lock'
    lock_before = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    env = os.environ.copy()
    env.update({
        'PATH': '/tmp/hepta-wave2-tools/bin:' + env['PATH'],
        'CARGO_HOME': str(ROOT / 'hepta-native-cache'),
        'CARGO_TARGET_DIR': str(ROOT / 'hepta-native-target'),
        'CARGO_INCREMENTAL': '0',
        'CARGO_BUILD_JOBS': '2',
        'CARGO_PROFILE_DEV_DEBUG': '0',
        'CARGO_PROFILE_TEST_DEBUG': '0',
        'CARGO_NET_GIT_FETCH_WITH_CLI': 'true',
        'RUSTFLAGS': '--sysroot /tmp/hepta-wave2-tools/unpack/rust-std.tar.xz/rust-std-1.95.0-x86_64-unknown-linux-gnu/rust-std-x86_64-unknown-linux-gnu',
    })
    result = {
        'source_sha': source_sha,
        'tree_sha': tree,
        'command': command,
        'cwd': str(SOURCE / 'codex-rs'),
        'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'cargo_lock_sha256_before': lock_before,
        'environment_overrides': {
            key: env[key] for key in (
                'CARGO_HOME', 'CARGO_TARGET_DIR', 'CARGO_INCREMENTAL',
                'CARGO_BUILD_JOBS', 'CARGO_PROFILE_DEV_DEBUG',
                'CARGO_PROFILE_TEST_DEBUG', 'CARGO_NET_GIT_FETCH_WITH_CLI',
                'RUSTFLAGS',
            )
        },
        'free_disk_bytes_before': shutil.disk_usage(ROOT).free,
        'status': 'RUNNING',
        'runner_pid': os.getpid(),
        'runner_parent_pid': os.getppid(),
        'source_identity_before': source_identity(),
        'log_path': str(log_path),
    }
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    started = time.monotonic()
    with log_path.open('w') as log:
        process = subprocess.Popen(
            command, cwd=SOURCE / 'codex-rs', env=env,
            stdout=log, stderr=subprocess.STDOUT,
        )
        result['command_pid'] = process.pid
        result_path.write_text(json.dumps(result, indent=2) + '\n')
        print('command_pid=' + str(process.pid), flush=True)
        process.wait()
    lock_after = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    result.update({
        'finished_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'duration_seconds': time.monotonic() - started,
        'exit_code': process.returncode,
        'cargo_lock_sha256_after': lock_after,
        'cargo_lock_unchanged': lock_before == lock_after,
        'free_disk_bytes_after': shutil.disk_usage(ROOT).free,
        'status': 'PASS' if process.returncode == 0 else 'FAIL',
        'source_identity_after': source_identity(),
        'log_sha256': hashlib.sha256(log_path.read_bytes()).hexdigest(),
    })
    result['source_unchanged_during_command'] = result['source_identity_before'] == result['source_identity_after']
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return process.returncode


if __name__ == '__main__':
    sys.exit(main())
