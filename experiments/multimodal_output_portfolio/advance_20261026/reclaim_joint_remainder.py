"""Reclaim only sealed joint metadata/media copies; default is verified dry-run.
All bytes remain in the immutable seven-volume custody set, not all expanded.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time
from .reclaim_closed_joint import AREA, RUN, NAMES, PROTOCOL, guards, identity, read, resources
from .reclaim_verified_members import check_identity, sha, write_new

RAW = RUN.parent
METADATA = ('RECORD.json', 'PUBLIC_DECISION.json', 'TARGET_FREE_OBSERVATION.json')

def require(condition, message):
    if not condition:
        raise ValueError(message)

def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)

def durable(path, value):
    write_new(path, value)
    with path.open('rb') as stream:
        os.fsync(stream.fileno())
    sync_directory(path.parent)

def candidates():
    spec, smoke = read(PROTOCOL), read(AREA / 'joint/SMOKE_PROTOCOL.json')
    require(spec['pair_count'] == 170 and len(spec['arms']) == 8 and len(spec['routes']) == 4,
            'Expected complete frozen confirmation')
    groups = {'confirmation_metadata': [RUN / 'raw' / f'case-{i:03d}' / route / arm['name'] / name
        for i in range(spec['pair_count']) for route in spec['routes'] for arm in spec['arms'] for name in METADATA],
        'smoke_media': [RAW / 'smoke-001/raw' / f'case-{i:03d}' / route / arm['name'] / 'output' / name
        for i in range(smoke['pair_count']) for route in smoke['routes'] for arm in smoke['arms'] for name in NAMES],
        'endpoint_media': [RAW / 'endpoints-001/raw' / f'action-{i:02d}' / name for i in range(100) for name in NAMES]}
    require({key: len(value) for key, value in groups.items()} ==
            {'confirmation_metadata': 16320, 'smoke_media': 1024, 'endpoint_media': 400}, 'Allowlist census changed')
    return groups

def verify_archive(receipt):
    archive, manifest_path = Path(receipt['archive']), Path(receipt['member_manifest'])
    saved_identity = identity(archive)
    require(saved_identity[2] == receipt['archive_bytes'], 'Archive size changed')
    check_identity(archive, receipt['archive_sha256'])
    check_identity(manifest_path, receipt['manifest_sha256'])
    manifest = read(manifest_path)
    check_identity(Path(receipt['expanded_inputs']), manifest['input_spec_sha256'])
    rows = manifest['files']
    members = {row['member']: row for row in rows}
    originals = {row['original_path']: row for row in rows}
    require(len(members) == len(originals) == len(rows) == receipt['member_count'] and 'MANIFEST.json' not in members,
            'Duplicate or invalid archive mapping')
    seen = set()
    with tarfile.open(archive, 'r|gz') as packed:
        for member in packed:
            require(member.isfile() and member.name not in seen, 'Repeated or non-file archive member')
            seen.add(member.name)
            digest = hashlib.file_digest(packed.extractfile(member), 'sha256').hexdigest()
            if member.name == 'MANIFEST.json':
                require(digest == receipt['manifest_sha256'], 'Internal manifest differs')
            else:
                expected = members.get(member.name)
                require(expected is not None and member.size == expected['bytes'] and digest == expected['sha256'],
                        'Archive member failed full byte verification: ' + member.name)
    require(seen == set(members) | {'MANIFEST.json'} and len(seen) == receipt['verified_members_including_manifest']
            and identity(archive) == saved_identity, 'Incomplete or changed archive')
    return archive, saved_identity, originals, len(seen)

def run(args):
    require(not args.output.resolve().is_relative_to(RAW)
            and not args.output.resolve().is_relative_to(AREA / 'joint'), 'Ledger must be outside frozen joint trees')
    args.output.mkdir(parents=True, exist_ok=False)
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    result = {'schema': 'hepta.advance.joint-remainder-copy-reclaim.v1', 'status': 'validating',
        'execute': args.execute, 'started_unix_ns': time.time_ns(), 'before': resources(),
        'receipt': str(args.receipt), 'receipt_sha256': args.receipt_sha256,
        'coverage': str(args.coverage), 'coverage_sha256': args.coverage_sha256,
        'concurrent_activity': args.concurrent_activity,
        'source_sha256': {str(path): sha(path) for path in (Path(__file__),
            AREA / 'reclaim_closed_joint.py', AREA / 'reclaim_verified_members.py')},
        'retention_scope': 'Original bytes retained in immutable archives; selected expanded copies may be removed.'}
    durable(args.output / 'STARTED.json', result)
    removed = logical = allocated = verified = 0
    try:
        check_identity(args.receipt, args.receipt_sha256)
        check_identity(args.coverage, args.coverage_sha256)
        receipt, coverage = read(args.receipt), read(args.coverage)
        require(receipt['schema'] == 'hepta.advance.closed-evidence.v1' and receipt['status'] == 'passed'
                and receipt['all_member_bytes_rehashed_after_archive_close'] is True, 'Complete sealed remainder required')
        linked = [row for row in coverage['archives'] if row['role'] == 'final_remainder']
        require(coverage['passed'] and len(linked) == 1 and linked[0]['receipt_sha256'] == args.receipt_sha256
                and all(linked[0][key] == receipt[key] for key in ('archive', 'archive_sha256', 'manifest_sha256')),
                'Remainder is not the verified complete-study custody member')
        require(coverage['actual_output_paths'] == 21760 and coverage['record_paths'] == 5440
                and coverage['input_video_paths'] == 170 and coverage['training_checkpoints'] == 12
                and coverage['training_exports'] == 12, 'Full study coverage required')
        archive, archive_identity, originals, count = verify_archive(receipt)
        result['archive_members_reverified'] = count
        checked, collected, audit = (read(RUN / name) for name in
            ('CHECKED_RESULT.json', 'RESULTS.json', 'COMPLETENESS_AUDIT.json'))
        for path, expected in ((PROTOCOL, coverage['protocol_sha256']), (RUN / 'RESULTS.json', checked['results_sha256']),
                              (RUN / 'COMPLETENESS_AUDIT.json', checked['audit_sha256']),
                              (RUN / 'ROWS.json', collected['rows_sha256'])):
            check_identity(path, expected)
            require(originals[str(path.resolve())]['sha256'] == expected, 'Closed evidence absent from archive')
        require(checked['audit_passed'] and audit['passed'] and collected['status'] == 'completed'
                and checked['passed'] == coverage['scientific_primary_passed']
                and read(RAW / 'confirmation-001-process/receipt.json')['returncode'] == 0,
                'Completed checked study required; failed science must remain unchanged')
        result['scientific_primary_passed_preserved'] = checked['passed']
        guard_hashes, protected = guards()
        plan, groups, excluded = [], {}, []
        for group, paths in candidates().items():
            groups[group] = {'files': 0, 'logical_bytes': 0, 'allocated_bytes': 0}
            for path in paths:
                require(path.is_relative_to(RAW), 'Path outside exact joint allowlist')
                if path in protected:
                    excluded.append(str(path))
                    continue
                require(str(path) in originals, 'Candidate lacks authoritative archive bytes: ' + str(path))
                saved, live = originals[str(path)], identity(path)
                require(saved['bytes'] == live[2], 'Expanded copy size changed')
                blocks = path.stat().st_blocks * 512
                plan.append((path, saved, live, blocks))
                groups[group]['files'] += 1
                groups[group]['logical_bytes'] += live[2]
                groups[group]['allocated_bytes'] += blocks
        require(len({str(row[0]) for row in plan}) == len(plan), 'Duplicate removal candidate')
        durable(args.output / 'PLAN.json', {'archive': str(archive), 'archive_sha256': receipt['archive_sha256'],
            'manifest_sha256': receipt['manifest_sha256'], 'guards': guard_hashes, 'groups': groups,
            'protected_candidates_retained': excluded, 'exact_allowlist': list(METADATA) + list(NAMES),
            'candidate_paths_sha256': hashlib.sha256(json.dumps([str(row[0]) for row in plan]).encode()).hexdigest()})
        require(guards()[0] == guard_hashes, 'Protected protocols changed before removal')
        with (args.output / 'LEDGER.jsonl').open('x') as log:
            sync_directory(args.output)
            def event(value):
                log.write(json.dumps(value, sort_keys=True) + '\n')
                log.flush()
                os.fsync(log.fileno())
            for index, (path, saved, live, blocks) in enumerate(plan):
                check_identity(path, saved['sha256'])
                require(identity(path) == live and path not in protected, 'Expanded copy changed or protected')
                verified += 1
                event({'event': 'verified_before_unlink', 'index': index, 'original_path': str(path),
                       'sha256': saved['sha256'], 'bytes': saved['bytes'], 'live_identity': live})
                if args.execute:
                    path.unlink()
                    sync_directory(path.parent)
                    removed += 1
                    logical += live[2]
                    allocated += blocks
                    event({'event': 'removed', 'index': index})
        require(identity(archive) == archive_identity and guards()[0] == guard_hashes, 'Archive or guards changed')
        check_identity(args.coverage, args.coverage_sha256)
        result.update(status='completed', candidate_groups=groups, protected_candidates_retained=len(excluded))
    except Exception as error:
        result.update(status='failed_retaining_partial_removal_ledger', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        result.update(after=resources(), wall_ns=time.monotonic_ns() - began, cpu_ns=time.process_time_ns() - cpu,
            removed_files=removed, removed_logical_bytes=logical, removed_allocated_bytes=allocated,
            live_files_verified=verified, authoritative_archives_retained=True, models_and_inputs_retained=True,
            ledger_sha256=sha(args.output / 'LEDGER.jsonl') if (args.output / 'LEDGER.jsonl').exists() else None)
        durable(args.output / 'RESULT.json', result)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', type=Path, default=AREA / 'evidence/JOINT_REMAINDER_RECEIPT.json')
    parser.add_argument('--coverage', type=Path, default=AREA / 'evidence/JOINT_CUSTODY_COVERAGE.json')
    for name in ('receipt-sha256', 'coverage-sha256', 'concurrent-activity'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    run(parser.parse_args())
