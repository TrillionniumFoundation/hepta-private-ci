#!/usr/bin/env python3
"""Run an already-built real ledger_scale executable in fresh processes.

Build separately: cargo build --locked --release -p codex-hepta-learning-ledger
--example ledger_scale. This measures the in-memory core; it cannot certify
segmented disk recovery, checkpoints, module concurrency, or write amplification.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys

METRICS = ('append_ns', 'retry_1000_ns', 'lookup_10000_ns', 'page_scan_ns', 'snapshot_ns', 'full_recovery_ns')


def validate(value: object, count: int) -> dict:
    if not isinstance(value, dict) or value.get('schema') != 'hepta.ledger-core-scale.v1':
        raise ValueError('unexpected native benchmark schema')
    if value.get('records') != count or value.get('persistence_measured') is not False:
        raise ValueError('incorrect record count or unsupported persistence claim')
    for key in METRICS:
        if type(value.get(key)) is not int or value[key] < 0:
            raise ValueError('invalid native measurement: ' + key)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', required=True, type=Path)
    parser.add_argument('--source-sha', required=True, help='caller-provided build source identity (not an attestation)')
    parser.add_argument('--sizes', default='1000,10000,100000')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        sizes = [int(x) for x in args.sizes.split(',')]
        if not sizes or sizes != sorted(set(sizes)) or any(not 1 <= x <= 900000 for x in sizes):
            raise ValueError('sizes must be unique increasing integers in 1..900000')
        if not 1 <= args.repeats <= 20 or not re.fullmatch('[0-9a-f]{40}', args.source_sha):
            raise ValueError('invalid repeats or source SHA')
        executable = args.exe.resolve(strict=True)
        binary_digest = hashlib.sha256(executable.read_bytes()).hexdigest()
        rows = []
        for count in sizes:
            for repeat in range(args.repeats):
                process = subprocess.run([str(executable), str(count)], capture_output=True,
                                         text=True, check=True, timeout=1800)
                rows.append({'repeat': repeat + 1, **validate(json.loads(process.stdout), count)})
        if hashlib.sha256(executable.read_bytes()).hexdigest() != binary_digest:
            raise ValueError('executable changed during measurement')
        summary = [{"records": count, **{f'median_{key}': statistics.median(row[key] for row in rows
                    if row['records'] == count) for key in METRICS}} for count in sizes]
        result = {'schema': 'hepta.ledger-core-scale-run.v1', 'binary_sha256': binary_digest,
                  'declared_source_sha': args.source_sha, 'source_identity_attested': False,
                  'environment': platform.platform(), 'raw_samples': rows, 'summary': summary,
                  'persistence_measured': False,
                  'limitations': ['Core only; no durable disk, checkpoint, write amplification, or concurrent agents.',
                                  'Source SHA is recorded, not cryptographically bound to the supplied executable.']}
        with args.output.open('x', encoding='utf-8') as output:
            json.dump(result, output, indent=2)
            output.write('\n')
        print(f'Wrote {len(rows)} real native samples to {args.output}')
        return 0
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'BENCHMARK_NOT_COMPLETED: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
