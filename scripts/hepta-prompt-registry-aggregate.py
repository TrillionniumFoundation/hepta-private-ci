#!/usr/bin/env python3
"""Aggregate four exact-run receipts. Never activates, accepts, or releases."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re

LANES = {(profile, lane) for profile in ('core', 'product') for lane in ('exact-head', 'base-merge')}
COMMON = {'clean-before', 'harness-tests', 'map', 'toolchain', 'source-graph', 'format', 'all-targets', 'lint', 'clean-after'}
REQUIRED = {'core': COMMON | {'registry-inventory', 'registry', 'operational-profiles'},
            'product': COMMON | {'agentd-inventory', 'extension-inventory', 'optimizer', 'extension', 'agentd', 'pipeline-profile'}}


def aggregate(root: Path, source: str, base: str, run: str, attempt: str) -> dict:
    receipts = {}
    digests = {}
    for path in sorted(root.glob('*/receipt.json')):
        receipt = json.loads(path.read_text())
        key = (receipt.get('profile'), receipt.get('lane'))
        if key not in LANES or key in receipts:
            raise ValueError('unknown or duplicate qualification lane')
        if receipt.get('schema') != 'hepta.prompt-registry.qualification-receipt.v2':
            raise ValueError('unsupported qualification receipt')
        for name, expected in [('sourceSha', source), ('baseSha', base), ('runId', run), ('runAttempt', attempt)]:
            if str(receipt.get(name)) != expected:
                raise ValueError('receipt identity or run attempt mismatch: ' + name)
        for name in ('sourceSha', 'baseSha', 'testedSha', 'testedTree'):
            if not re.fullmatch(r'[a-f0-9]{40}', receipt.get(name, '')):
                raise ValueError('invalid exact identity')
        if key[1] == 'exact-head' and receipt['testedSha'] != source:
            raise ValueError('wrong exact-head candidate')
        if receipt.get('allRequiredChecksPassed') is not True:
            raise ValueError('lane did not pass every required check')
        if any(receipt.get(name) is not False for name in ('qualified', 'productionReady', 'productActivated', 'accepted', 'released')):
            raise ValueError('lane crossed its claim boundary')
        checks = receipt.get('checks', [])
        if len(checks) != len(REQUIRED[key[0]]) or {c.get('name') for c in checks} != REQUIRED[key[0]]:
            raise ValueError('missing or unexpected required checks')
        for check in checks:
            if check.get('state') != 'passed' or check.get('exitCode') != 0 or check.get('postconditionFailures') != []:
                raise ValueError('failed, interrupted or skipped check')
            log = path.parent / (check['name'] + '.log')
            if not log.is_file() or log.is_symlink() or hashlib.sha256(log.read_bytes()).hexdigest() != check.get('logSha256'):
                raise ValueError('raw log missing or digest mismatch')
        if not receipt.get('sourceFiles'):
            raise ValueError('source blob manifest missing')
        receipts[key] = receipt
        digests['/'.join(key)] = hashlib.sha256(path.read_bytes()).hexdigest()
    if set(receipts) != LANES:
        raise ValueError('all four lanes are mandatory')
    for lane in ('exact-head', 'base-merge'):
        core, product = (receipts[(p, lane)] for p in ('core', 'product'))
        if any(core[name] != product[name] for name in ('testedSha', 'testedTree', 'sourceFiles')):
            raise ValueError('core and product tested different source')
    return {'schema': 'hepta.prompt-registry.qualification-summary.v1', 'sourceSha': source,
            'baseSha': base, 'runId': run, 'runAttempt': attempt, 'sourceQualified': True,
            'productActivated': False, 'accepted': False, 'released': False,
            'receiptSha256': digests,
            'tested': {lane: {'sha': receipts[('core', lane)]['testedSha'], 'tree': receipts[('core', lane)]['testedTree']}
                       for lane in ('exact-head', 'base-merge')}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--attempt', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = aggregate(args.root, args.source, args.base, args.run, args.attempt)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, sort_keys=True))

if __name__ == '__main__':
    main()
