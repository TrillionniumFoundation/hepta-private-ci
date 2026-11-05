#!/usr/bin/env python3
"""Hash and remove only a completed, named Automation test executable."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time


ROOT = Path('/workspace/scratch/48266f5bd43f')
RECEIPTS = ROOT / 'effects-receipts'
TARGET = ROOT / 'hepta-effects-target'


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--kind', choices=('lib', 'bin', 'test'), required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--empty-target', action='store_true')
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.label)
    receipt = RECEIPTS / f'{args.label}.json'
    native = json.loads(receipt.read_text())
    if args.empty_target:
        log = (RECEIPTS / f'{args.label}.log').read_text()
        assert native['exit_code'] == 4 and native['source_before']['passed'] and native['source_after']['passed'] and native['raw_source_unchanged']
        assert re.search(r'Starting 0 tests across 1 binary', log)
        assert re.search(r'Summary \[\s+0\.000s\] 0 tests run: 0 passed, 0 skipped', log)
        assert 'error: no tests to run' in log
    else:
        assert native['command_and_source_guards_passed'], 'native command and source guards must be complete'
    inventory = json.loads((RECEIPTS / 'final-automation-target-inventory.json').read_text())
    selected = [target for target in inventory['selected_default_test_targets'] if target['kind'] == args.kind and target['name'] == args.name]
    assert len(selected) == 1
    expected = ['just', 'test', '--locked', '-p', 'codex-hepta-automation', *selected[0]['selection_argv'], '--no-capture']
    assert native['argv'] == expected
    name = {'lib': f'test-lib-{args.name}.json', 'bin': f'test-bin-{args.name}.json', 'test': f'test-integration-test-{args.name}.json'}[args.kind]
    candidates = []
    for fingerprint in sorted((TARGET / 'debug/.fingerprint').glob(f'codex-hepta-automation-*/{name}')):
        artifact_hash = fingerprint.parent.name.rsplit('-', 1)[1]
        assert re.fullmatch('[0-9a-f]{16}', artifact_hash)
        executable = TARGET / 'debug/deps' / f'{args.name.replace("-", "_")}-{artifact_hash}'
        if executable.is_file():
            assert not executable.is_symlink()
            with executable.open('rb') as stream:
                assert stream.read(4) == b'\x7fELF'
            candidates.append((executable, fingerprint))
    assert len(candidates) == 1, f'expected one unambiguous completed test ELF, found {candidates}'
    executable, fingerprint = candidates[0]
    active = []
    unreadable_maps = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            argv = (process / 'cmdline').read_bytes().split(b'\0')
            first = Path(os.fsdecode(argv[0])).name if argv and argv[0] else ''
            own_path = any(os.fsencode(TARGET) in arg for arg in argv)
            if own_path and (first in ('rustc', 'cargo', 'cargo-nextest', 'clippy-driver', 'cc', 'ld', 'ld.lld') or argv[0] == os.fsencode(executable)):
                active.append({'pid': int(process.name), 'command': first})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            pass
        try:
            maps = (process / 'maps').read_bytes()
            if os.fsencode(executable) in maps:
                active.append({'pid': int(process.name), 'mapped_executable': str(executable)})
        except PermissionError:
            unreadable_maps.append(int(process.name))
        except (FileNotFoundError, ProcessLookupError):
            pass
    assert not active, f'own build or selected test executable remains active: {active}'
    output = RECEIPTS / f'{args.label}-binary.json'
    assert not output.exists(), 'do not overwrite earlier binary receipt'
    stat = executable.stat()
    record = {
        'runtime_commit': native['runtime_commit'], 'runtime_tree': native['runtime_tree'],
        'paired_chain_commit': native['paired_chain_commit'], 'native_receipt': receipt.name,
        'native_receipt_sha256': sha256(receipt), 'test_target': selected[0],
        'cleanup_helper_sha256': sha256(Path(__file__)),
        'classification': 'empty target; original exit 4 preserved, no passing tests claimed' if args.empty_target else 'all collected tests passed',
        'path': str(executable), 'size': stat.st_size, 'allocated_bytes': stat.st_blocks * 512,
        'sha256': sha256(executable), 'fingerprint_path': str(fingerprint),
        'fingerprint_sha256': sha256(fingerprint), 'active_own_processes': active,
        'unreadable_unrelated_maps': unreadable_maps,
        'cleanup_scope': 'only this completed test ELF; dependency libraries, production binaries, sources, and receipts preserved',
        'recorded_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'free_before': shutil.disk_usage(TARGET).free, 'removed': False,
    }
    output.write_text(json.dumps(record, indent=2) + '\n')
    executable.unlink()
    record['removed'] = True
    record['free_after'] = shutil.disk_usage(TARGET).free
    output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
