#!/usr/bin/env python3
"""Record one final-source native command with complete raw tracked-file guards."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


ROOT = Path('/workspace/scratch/48266f5bd43f/hepta-effects-green')
OUTPUT = Path('/workspace/scratch/48266f5bd43f/effects-receipts')
COMMIT = 'd7c32f38ae1c3890e73ff48ef8ee725ba4e80c58'
TREE = 'b79a4a4677b672a89cce53c9abe6f6c71810ee88'
CHAIN = '04be5f02c84cf5cb626a53f34bc03a5bd6ff5137'
TARGET = '/workspace/scratch/48266f5bd43f/hepta-effects-target'


def git(*args):
    env = os.environ.copy()
    env['GIT_NO_LAZY_FETCH'] = '1'
    return subprocess.check_output(['git', *args], cwd=ROOT, env=env)


def guard(label, stage):
    head = git('rev-parse', 'HEAD').decode().strip()
    tree = git('rev-parse', 'HEAD^{tree}').decode().strip()
    status = git('status', '--porcelain=v1').decode()
    flags = git('ls-files', '-v', '-z').split(b'\0')
    hidden = [item.decode() for item in flags if item and (item[:1] == b'S' or item[:1].islower())]
    tracked = set(filter(None, git('ls-files', '-z').split(b'\0')))
    rows = []
    mismatches = []
    head_paths = set()
    for entry in git('ls-tree', '-rz', '--full-tree', 'HEAD').split(b'\0'):
        if not entry:
            continue
        header, name = entry.split(b'\t', 1)
        mode, kind, expected_blob = header.decode().split(' ')
        path = name.decode('utf-8', 'surrogateescape')
        head_paths.add(name)
        full = ROOT / path
        if kind != 'blob' or mode not in ('100644', '100755', '120000'):
            mismatches.append({'path': path, 'reason': 'unsupported tracked object', 'mode': mode, 'kind': kind})
            continue
        try:
            if mode == '120000':
                data = os.readlink(full).encode('utf-8', 'surrogateescape')
                actual_mode = '120000'
            else:
                data = full.read_bytes()
                actual_mode = '100755' if full.stat().st_mode & 0o111 else '100644'
            actual_blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            raw_sha256 = hashlib.sha256(data).hexdigest()
            rows.append([path, mode, expected_blob, raw_sha256, len(data)])
            if actual_blob != expected_blob or actual_mode != mode:
                mismatches.append({'path': path, 'expected_blob': expected_blob, 'raw_blob': actual_blob, 'expected_mode': mode, 'actual_mode': actual_mode})
        except OSError as error:
            mismatches.append({'path': path, 'reason': str(error)})
    manifest = json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode()
    compressed = gzip.compress(manifest, mtime=0)
    manifest_name = f'{label}-{stage}-raw-tracked.json.gz'
    (OUTPUT / manifest_name).write_bytes(compressed)
    material = (ROOT / 'scripts/hepta_smollm_execution_source_v1.py').read_text()
    pin = re.search(r'^CHAIN_COMMIT_V10 = "([0-9a-f]{40})"$', material, re.MULTILINE)
    passed = head == COMMIT and tree == TREE and not status and not hidden and not mismatches and tracked == head_paths and pin is not None and pin.group(1) == CHAIN
    return {'passed': passed, 'head': head, 'tree': tree, 'status': status, 'tracked_count': len(tracked), 'raw_blob_count': len(rows), 'hidden_flags': hidden, 'path_set_matches_head': tracked == head_paths, 'raw_blob_mismatches': mismatches, 'paired_chain_commit': pin.group(1) if pin else None, 'manifest_file': manifest_name, 'manifest_sha256': hashlib.sha256(manifest).hexdigest(), 'compressed_manifest_sha256': hashlib.sha256(compressed).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('argv', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    argv = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
    assert argv and re.fullmatch('[a-z0-9-]+', args.label)
    receipt = OUTPUT / f'{args.label}.json'
    log_path = OUTPUT / f'{args.label}.log'
    assert not receipt.exists() and not log_path.exists(), 'preserve earlier command receipts'
    record = {'argv': argv, 'cwd': str(ROOT / 'codex-rs'), 'runtime_commit': COMMIT, 'runtime_tree': TREE, 'paired_chain_commit': CHAIN, 'build_jobs': 1, 'cargo_target_dir': TARGET, 'offline': True, 'profile_override': None, 'rustflags': os.environ.get('RUSTFLAGS'), 'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    record['source_before'] = guard(args.label, 'before')
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    if not record['source_before']['passed']:
        print(json.dumps(record, indent=2), flush=True)
        return 2
    env = os.environ.copy()
    env['PATH'] = '/workspace/scratch/822cc50e24f0/authority-recovery/native-20261105/bin:/root/.cargo/bin:' + env['PATH']
    env['CARGO_TARGET_DIR'] = TARGET
    env['CARGO_BUILD_JOBS'] = '1'
    env['CARGO_NET_OFFLINE'] = 'true'
    start = time.monotonic()
    print(json.dumps({'source_before': record['source_before'], 'argv': argv}), flush=True)
    with log_path.open('w') as log:
        process = subprocess.Popen(argv, cwd=ROOT / 'codex-rs', env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
        process.wait()
    record.update(exit_code=process.returncode, elapsed_seconds=time.monotonic() - start, finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), log_sha256=hashlib.sha256(log_path.read_bytes()).hexdigest())
    record['source_after'] = guard(args.label, 'after')
    record['raw_source_unchanged'] = record['source_before']['manifest_sha256'] == record['source_after']['manifest_sha256']
    record['command_and_source_guards_passed'] = process.returncode == 0 and record['source_after']['passed'] and record['raw_source_unchanged']
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2), flush=True)
    return 0 if record['command_and_source_guards_passed'] else process.returncode or 2


if __name__ == '__main__':
    sys.exit(main())
