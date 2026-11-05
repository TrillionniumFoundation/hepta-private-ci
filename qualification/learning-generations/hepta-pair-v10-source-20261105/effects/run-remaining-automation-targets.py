#!/usr/bin/env python3
"""Run every remaining frozen Cargo target, preserving each original command result."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


ROOT = Path('/workspace/scratch/48266f5bd43f')
RECEIPTS = ROOT / 'effects-receipts'
INVENTORY = RECEIPTS / 'final-automation-target-inventory.json'


def main():
    inventory = json.loads(INVENTORY.read_text())
    assert inventory['commit'] == 'd7c32f38ae1c3890e73ff48ef8ee725ba4e80c58'
    assert inventory['no_test_targets_omitted'] and inventory['target_count'] == 12
    for target in inventory['selected_default_test_targets']:
        suffix = {'lib': 'lib', 'bin': 'bin'}.get(target['kind'], target['name'].replace('_', '-'))
        label = f'final-automation-{suffix}'
        path = RECEIPTS / f'{label}.json'
        if path.exists():
            existing = json.loads(path.read_text())
            assert existing.get('command_and_source_guards_passed') or (target['kind'] == 'bin' and existing.get('exit_code') == 4 and existing.get('source_after', {}).get('passed') and existing.get('raw_source_unchanged')), f'earlier incomplete or failed result: {label}'
            assert (RECEIPTS / f'{label}-binary.json').exists(), f'completed ELF has not been recorded: {label}'
            print(json.dumps({'target': target['name'], 'state': 'already completed; original receipt preserved'}), flush=True)
            continue
        available = shutil.disk_usage(ROOT).free
        if available < 400_000_000:
            print(json.dumps({'target': target['name'], 'state': 'not started; insufficient disk', 'free_bytes': available}), flush=True)
            return 3
        print(json.dumps({'target': target['name'], 'state': 'starting', 'free_bytes': available}), flush=True)
        argv = [sys.executable, str(RECEIPTS / 'run-final-native.py'), '--label', label, '--', 'just', 'test', '--locked', '-p', 'codex-hepta-automation', *target['selection_argv'], '--no-capture']
        result = subprocess.run(argv, cwd=ROOT / 'hepta-effects-green', stdout=subprocess.DEVNULL)
        native = json.loads(path.read_text())
        log = (RECEIPTS / f'{label}.log').read_text()
        summaries = re.findall(r'^\s*Summary \[[^\n]*$', log, re.MULTILINE)
        print(json.dumps({'target': target['name'], 'exit_code': result.returncode, 'summary': summaries, 'log_sha256': native.get('log_sha256'), 'source_guards_passed': native.get('command_and_source_guards_passed'), 'free_bytes': shutil.disk_usage(ROOT).free}), flush=True)
        if result.returncode != 0 or not native.get('command_and_source_guards_passed'):
            print(log[-6000:], flush=True)
            return result.returncode or 2
        cleanup = subprocess.run([sys.executable, str(RECEIPTS / 'retain-completed-test-binary.py'), '--label', label, '--kind', target['kind'], '--name', target['name']], stdout=subprocess.DEVNULL)
        if cleanup.returncode != 0:
            return cleanup.returncode
        print(json.dumps({'target': target['name'], 'state': 'completed ELF hash retained and file removed', 'free_bytes': shutil.disk_usage(ROOT).free}), flush=True)
    print(json.dumps({'state': 'all frozen targets have receipts', 'target_count': inventory['target_count'], 'inventory_sha256': hashlib.sha256(INVENTORY.read_bytes()).hexdigest()}), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
