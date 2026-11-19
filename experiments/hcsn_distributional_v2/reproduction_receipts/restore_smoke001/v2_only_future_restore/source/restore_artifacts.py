"""Discover and restore the published HCSN evidence bundles without overwrites.

Uses the frozen v1 streaming archive verifier. Receipts live outside sealed
results/data/artifact directories. No numerical or neural runtime is imported.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from experiments.hcsn_free_boundary_v1 import archive


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'hcsn-evidence-bundle.v1'
V1_MANIFESTS = (
    ('original_data.json', 'raw'),
    ('auxiliary_evidence.json', 'v1'),
    ('study001_evidence.json', 'v1'),
    ('conditional001_evidence.json', 'v1'),
    ('equal_updates_core002_evidence.json', 'equal_updates'),
)


def digest(path):
    return archive.sha256(path)


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_json(path, record):
    with Path(path).open('x') as handle:
        json.dump(record, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write('\n')


def discover(checkout_root=ROOT, raw_root=None, only_v2=False):
    """Catalog manifest bytes and correct destinations; never read tar parts."""
    checkout_root = Path(checkout_root).resolve()
    v1 = checkout_root / 'experiments/hcsn_free_boundary_v1'
    v2 = checkout_root / 'experiments/hcsn_distributional_v2'
    destinations = {'raw': str(Path(raw_root).resolve()) if raw_root is not None else None,
                    'v1': str(v1), 'equal_updates': str(v1 / 'results/equal_updates_core002')}
    candidates, missing = [], []
    if not only_v2:
        for name, kind in V1_MANIFESTS:
            path = v1 / 'artifacts' / name
            if not path.is_file():
                missing.append(str(path))
            else:
                candidates.append((path, destinations[kind], 'v1:' + kind))
    for path in sorted((v2 / 'artifacts').rglob('*.json')):
        record = read_json(path)
        if isinstance(record, dict) and record.get('schema') == SCHEMA:
            candidates.append((path, str(v2), 'v2:auto'))
    bundles, target_hashes = [], {}
    for path, destination, kind in candidates:
        manifest = read_json(path)
        if manifest.get('schema') != SCHEMA:
            raise ValueError('Wrong v1 bundle contract: ' + str(path))
        seen = set()
        for member in manifest['members']:
            name = archive.safe_name(member['path'])
            if member['path'] in seen:
                raise ValueError('Duplicate declared member: ' + str(path))
            seen.add(member['path'])
            if destination is not None:
                target = str(Path(destination).joinpath(*name.parts))
                identity = (member['bytes'], member['sha256'])
                if target in target_hashes and target_hashes[target] != identity:
                    raise ValueError('Bundles declare different bytes for one destination: ' + target)
                target_hashes[target] = identity
        absent_parts = []
        for part in manifest['parts']:
            name = archive.safe_name(part['path'])
            if len(name.parts) != 1:
                raise ValueError('Archive parts must be adjacent to their manifest')
            if not (path.parent / part['path']).is_file():
                absent_parts.append(part['path'])
        bundles.append({'manifest': str(path.resolve()), 'manifest_sha256': digest(path),
            'name': manifest['name'], 'kind': kind, 'destination': destination,
            'member_count': len(manifest['members']), 'parts_count': len(manifest['parts']),
            'compressed_bytes': manifest['compressed_bytes'],
            'uncompressed_file_bytes': manifest['uncompressed_file_bytes'],
            'archive_sha256': manifest['archive_sha256'], 'missing_parts': absent_parts})
    return {'schema': 'hcsn-restore-catalog.v1', 'checkout_root': str(checkout_root),
            'raw_root': destinations['raw'], 'only_v2': bool(only_v2),
            'bundles': bundles, 'missing_v1_manifests': missing,
            'listing_verifies': 'Manifest identity, member names, destination mapping, declared cross-bundle conflicts and part presence only; no compressed/member payload validation until restore',
            'future_v2_discovery': 'Every artifacts/**/*.json with schema hcsn-evidence-bundle.v1; sidecar receipts are excluded by schema'}


def ensure_receipt_scope(path, checkout_root=ROOT):
    """Enforce this even in the internal worker entry point."""
    path = Path(path).resolve()
    for root in {ROOT.resolve(), Path(checkout_root).resolve()}:
        allowed = root / 'experiments/hcsn_distributional_v2/reproduction_receipts'
        if path.is_relative_to(root / 'experiments') and not path.is_relative_to(allowed):
            raise ValueError('Within experiments/, receipts must use hcsn_distributional_v2/reproduction_receipts/, never sealed results/data/artifacts')


def receipt_destination(path, checkout_root=ROOT):
    """Receipt directories may not be placed inside a sealed study tree."""
    checkout_root = Path(checkout_root).resolve()
    allowed = checkout_root / 'experiments/hcsn_distributional_v2/reproduction_receipts'
    if path is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        path = allowed / (stamp + '_' + uuid.uuid4().hex[:10])
    path = Path(path).resolve()
    ensure_receipt_scope(path, checkout_root)
    if path.exists():
        raise FileExistsError('Use a new receipt directory')
    return path


def verify_plan(plan):
    for path, expected in plan['implementation_sha256'].items():
        if digest(path) != expected:
            raise ValueError('Restore implementation changed: ' + path)
    for row in plan['catalog']['bundles']:
        if digest(row['manifest']) != row['manifest_sha256']:
            raise ValueError('Input manifest changed: ' + row['manifest'])


def worker(plan_path, expected_sha):
    if digest(plan_path) != expected_sha:
        raise ValueError('Restore plan changed before execution')
    plan = read_json(plan_path)
    if plan['schema'] != 'hcsn-restore-plan.v1':
        raise ValueError('Unknown restore plan')
    receipt = Path(plan_path).resolve().parent
    if receipt != Path(plan['receipt_dir']).resolve():
        raise ValueError('Worker receipt directory differs from its bound plan')
    ensure_receipt_scope(receipt, plan['catalog']['checkout_root'])
    verify_plan(plan)
    records = []
    try:
        for row in plan['catalog']['bundles']:
            cpu, wall = time.process_time(), time.monotonic()
            result = (archive.restore(row['manifest'], row['destination'])
                      if plan['operation'] == 'restore' else {'listed_only': True})
            if digest(row['manifest']) != row['manifest_sha256']:
                raise ValueError('Manifest changed during restore/list')
            records.append({'manifest': row['manifest'], 'input_manifest_sha256': row['manifest_sha256'],
                            'destination': row['destination'], 'result': result,
                            'body_cpu_seconds': time.process_time() - cpu,
                            'body_wall_seconds': time.monotonic() - wall})
        verify_plan(plan)
    finally:
        write_json(Path(plan_path).parent / 'BUNDLE_RECEIPTS.json', {
            'records': records, 'completed_bundles': len(records),
            'expected_bundles': len(plan['catalog']['bundles']),
            'body_times_nested_in_complete_worker_cpu': True})


def run(operation, *, only_v2=False, raw_root=None, receipt_dir=None, checkout_root=ROOT):
    """Public helper also permits an isolated fixture checkout for small tests."""
    if operation not in ('list', 'restore'):
        raise ValueError('Expected list or restore')
    receipt = receipt_destination(receipt_dir, checkout_root)
    receipt.mkdir(parents=True, exist_ok=False)
    success, failure, child_cpu = False, None, 0.
    try:
        catalog = discover(checkout_root, raw_root, only_v2)
        write_json(receipt / 'CATALOG.json', catalog)
        if operation == 'restore':
            if catalog['missing_v1_manifests']:
                raise FileNotFoundError('Required v1 manifests missing: ' + str(catalog['missing_v1_manifests']))
            if not only_v2 and raw_root is None:
                raise ValueError('Full restoration requires an explicit --raw-root')
            if not catalog['bundles']:
                raise ValueError('No published bundles discovered')
            absent = [r['manifest'] for r in catalog['bundles'] if r['missing_parts']]
            if absent:
                raise FileNotFoundError('Bundle parts missing: ' + str(absent))
        plan = {'schema': 'hcsn-restore-plan.v1', 'operation': operation,
                'created_utc': datetime.now(timezone.utc).isoformat(), 'catalog': catalog,
                'implementation_sha256': {str(Path(__file__).resolve()): digest(__file__),
                                          str(Path(archive.__file__).resolve()): digest(archive.__file__)},
                'receipt_dir': str(receipt),
                'overwrite_policy': 'Frozen v1 archive.restore: identical bytes verified/reused; different existing bytes rejected',
                'transaction_scope': 'Each member validated before its write; no rollback of earlier valid members on later failure'}
        snapshot = receipt / 'source'
        snapshot.mkdir()
        for filename in plan['implementation_sha256']:
            with (snapshot / Path(filename).name).open('xb') as handle:
                handle.write(Path(filename).read_bytes())
        write_json(receipt / 'PLAN.json', plan)
        command = [sys.executable, '-m', 'experiments.hcsn_distributional_v2.restore_artifacts',
                   '--worker-plan', str(receipt / 'PLAN.json'), '--plan-sha256', digest(receipt / 'PLAN.json')]
        started = time.monotonic()
        with (receipt / 'worker.log').open('x') as log:
            process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        child_cpu = usage.ru_utime + usage.ru_stime
        write_json(receipt / 'WORKER_EXECUTION.json', {
            'command': command, 'exit_code': process.returncode,
            'complete_child_cpu_seconds': child_cpu, 'wall_seconds': time.monotonic() - started,
            'peak_rss_kib_linux': usage.ru_maxrss,
            'scope': 'wait4 covers the complete worker including interpreter/imports/payload verification/restore/serialization/exit'})
        if process.returncode:
            raise RuntimeError('Restore/list failed; prior valid files and complete receipts retained at ' + str(receipt))
        verify_plan(plan)
        success = True
        for row in catalog['bundles']:
            print(json.dumps({key: row[key] for key in ('name', 'kind', 'destination', 'member_count',
                                                        'compressed_bytes', 'manifest_sha256')}, ensure_ascii=False))
        if catalog['missing_v1_manifests']:
            print(json.dumps({'missing_v1_manifests': catalog['missing_v1_manifests']}))
        return {'receipt_dir': str(receipt), 'bundles': len(catalog['bundles']), 'operation': operation}
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        # This is the parent process's whole self CPU, including startup/imports.
        # Per-bundle body times are nested inside worker wait4 and are not added.
        write_json(receipt / 'EXECUTION.json', {
            'status': 'completed' if success else 'failed', 'failure': failure,
            'complete_worker_cpu_seconds': child_cpu,
            'coordinator_whole_self_cpu_seconds_through_cutoff': time.process_time(),
            'accounting': 'For this CLI process add whole parent self CPU and complete worker CPU once; bundle body timings are nested. Repeated run() calls within one interpreter share parent CPU and must not sum those cumulative values.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('list', 'restore'), nargs='?', default='list')
    parser.add_argument('--only-v2', action='store_true')
    parser.add_argument('--raw-root', type=Path)
    parser.add_argument('--receipt-dir', type=Path)
    parser.add_argument('--worker-plan', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--plan-sha256', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_plan:
        if not args.plan_sha256:
            raise ValueError('Worker requires a bound plan digest')
        worker(args.worker_plan, args.plan_sha256)
    else:
        result = run(args.operation, only_v2=args.only_v2, raw_root=args.raw_root,
                     receipt_dir=args.receipt_dir)
        print(json.dumps(result))


if __name__ == '__main__':
    main()
