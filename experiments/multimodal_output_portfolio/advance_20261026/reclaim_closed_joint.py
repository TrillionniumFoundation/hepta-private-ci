"""Verify a complete sealed joint output partition before reclaiming its copies."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import tarfile
import time
from .reclaim_verified_members import absolute_strings, check_identity, sha, write_new

AREA = Path(__file__).resolve().parent
RUN = Path('/tmp/hepta-ndu-advance-joint/confirmation-001')
NAMES = ('caption.txt', 'image.png', 'audio.wav', 'video.mp4')
PROTOCOL = AREA / 'joint/CONFIRMATION_PROTOCOL.json'

def read(path):
    return json.loads(Path(path).read_text())

def resources():
    disk = os.statvfs(RUN)
    return {'actual_free_bytes': disk.f_bfree * disk.f_frsize,
        'peak_rss_bytes': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        'cgroup_current_bytes': int(Path('/sys/fs/cgroup/memory.current').read_text()),
        'cgroup_events': dict(line.split() for line in Path('/sys/fs/cgroup/memory.events').read_text().splitlines())}

def guards():
    documents = set(AREA.rglob('*PROTOCOL*.json')) | set(AREA.rglob('FROZEN*.json'))
    identities, protected = {}, set()
    while documents:
        path = documents.pop().resolve()
        if str(path) in identities:
            continue
        value = read(path); identities[str(path)] = sha(path)
        protected.add(path); protected.update(absolute_strings(value))
        if 'spec_path' in value:
            target = Path(value['spec_path']); check_identity(target, value['spec_sha256'])
            documents.add(target)
    final = read(AREA / 'native/FROZEN_CONFIRMATION_FINAL.json')
    native = read(final['spec_path'])
    if final['exact_dependency_count'] != 5561 or len(native['frozen_candidate_sha256']) != 5561:
        raise ValueError('The complete registered native dependency set is required')
    return identities, protected

def identity(path):
    value = path.lstat()
    if path.resolve() != path or not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('Unsafe, linked or nonregular file: ' + str(path))
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

def run(args):
    if args.output.resolve().is_relative_to(RUN.parent):
        raise ValueError('The removal ledger must remain outside the complete joint study')
    args.output.mkdir(parents=True, exist_ok=False)
    began, cpu = time.monotonic_ns(), time.process_time_ns()
    result = {'schema': 'hepta.advance.closed-joint-copy-reclaim.v1', 'status': 'validating',
        'execute': args.execute, 'started_unix_ns': time.time_ns(), 'before': resources(),
        'receipt': str(args.receipt), 'receipt_sha256': args.receipt_sha256,
        'process': str(args.process), 'process_sha256': args.process_sha256,
        'source_sha256': {str(Path(__file__)): sha(__file__),
            str(AREA / 'reclaim_verified_members.py'): sha(AREA / 'reclaim_verified_members.py')}}
    write_new(args.output / 'STARTED.json', result)
    removed = logical = allocated = verified = 0
    try:
        check_identity(args.receipt, args.receipt_sha256); receipt = read(args.receipt)
        if (receipt['schema'] != 'hepta.advance.closed-evidence.v1' or receipt['status'] != 'passed'
                or receipt['all_member_bytes_rehashed_after_archive_close'] is not True):
            raise ValueError('A successful complete advance archive receipt is mandatory')
        archive, manifest_path = Path(receipt['archive']), Path(receipt['member_manifest'])
        archive_identity = identity(archive)
        if archive_identity[2] != receipt['archive_bytes']:
            raise ValueError('Complete archive size differs')
        check_identity(archive, receipt['archive_sha256'])
        check_identity(manifest_path, receipt['manifest_sha256'])
        rows = read(manifest_path)['files']
        members = {row['member']: row for row in rows}
        originals = {row['original_path']: row for row in rows}
        if len(members) != len(rows) or len(originals) != len(rows) or 'MANIFEST.json' in members:
            raise ValueError('Duplicate or reserved archive manifest entry')
        seen = set()
        with tarfile.open(archive, 'r|gz') as packed:
            for item in packed:
                if not item.isfile() or item.name in seen:
                    raise ValueError('Nonregular or repeated archive member')
                seen.add(item.name)
                digest = hashlib.file_digest(packed.extractfile(item), 'sha256').hexdigest()
                if item.name == 'MANIFEST.json':
                    check = digest == receipt['manifest_sha256']
                else:
                    expected = members.get(item.name)
                    check = expected is not None and item.size == expected['bytes'] and digest == expected['sha256']
                if not check:
                    raise ValueError('Archive member failed complete byte verification: ' + item.name)
        if (seen != set(members) | {'MANIFEST.json'} or len(seen) != receipt['verified_members_including_manifest']
                or identity(archive) != archive_identity):
            raise ValueError('Incomplete or changed authoritative archive')
        check_identity(args.definition, receipt['definition_sha256'])
        partition = read(args.definition)['generated_output_partition']
        count = 128 * (args.case_end - args.case_start)
        if (args.case_start not in range(0, 170, 32) or args.case_end != min(args.case_start + 32, 170)
                or partition != {'case_start': args.case_start, 'case_end': args.case_end,
                    'expected_generated_files': count, 'total_cases': 170,
                    'selection': 'Consecutive registered case indices; no outcome selection'}):
            raise ValueError('A fixed consecutive registered partition is required')
        result['generated_output_partition'] = partition
        check_identity(args.process, args.process_sha256); process = read(args.process)
        command = read(args.process.with_name('started.json'))['argv']
        if (process['returncode'] != 0 or command[command.index('--output') + 1] != str(RUN)
                or command[command.index('-m') + 1] != 'experiments.multimodal_output_portfolio.advance_20261026.joint.confirm_checked'):
            raise ValueError('The exact checked collector must have exited successfully')
        checked, collected, audit = (read(RUN / name) for name in
            ('CHECKED_RESULT.json', 'RESULTS.json', 'COMPLETENESS_AUDIT.json'))
        check_identity(RUN / 'RESULTS.json', checked['results_sha256'])
        check_identity(RUN / 'COMPLETENESS_AUDIT.json', checked['audit_sha256'])
        check_identity(RUN / 'ROWS.json', collected['rows_sha256'])
        if not (checked['audit_passed'] is True and audit['passed'] is True
                and collected['status'] == 'completed' and collected['actual_output_file_count'] == 21760
                and audit['actual_output_files_checked'] == 21760 and audit['complete_registered_cases'] == 5440
                and collected['protocol_sha256'] == audit['protocol_sha256'] == sha(PROTOCOL)):
            raise ValueError('Complete successful engineering audit and exact protocol are required')
        result['scientific_primary_passed_preserved'] = checked['passed']
        for path in [args.definition, args.process, args.process.with_name('started.json'), PROTOCOL, *(RUN / name for name in
                     ('CHECKED_RESULT.json', 'RESULTS.json', 'COMPLETENESS_AUDIT.json', 'ROWS.json'))]:
            check_identity(path, originals[str(path.resolve())]['sha256'])
        guard_hashes, protected = guards(); spec = read(PROTOCOL)
        candidates = [RUN / 'raw' / f'case-{case:03d}' / route / arm['name'] / 'output' / name
            for case in range(args.case_start, args.case_end) for route in spec['routes'] for arm in spec['arms'] for name in NAMES]
        output_members = {Path(row['original_path']) for row in rows if Path(row['original_path']).name in NAMES}
        if len(candidates) != count or len(set(candidates)) != count or output_members != set(candidates):
            raise ValueError('The exact partition output set has omissions, extras or duplicates')
        plan = []
        for path in candidates:
            if path in protected or not path.is_relative_to(RUN / 'raw') or len(path.relative_to(RUN / 'raw').parts) != 5:
                raise ValueError('Current dependency or ineligible path: ' + str(path))
            saved = originals[str(path)]; live = identity(path)
            if live[2] != saved['bytes']:
                raise ValueError('Live media size differs from the closed archive')
            plan.append({**saved, 'live_identity': live, 'allocated_bytes': path.stat().st_blocks * 512})
        write_new(args.output / 'PLAN.json', {'guards': guard_hashes, 'archive': str(archive), 'files': plan})
        if guards()[0] != guard_hashes:
            raise ValueError('Protected protocols changed before any removal')
        with (args.output / 'LEDGER.jsonl').open('x') as log:
            fd = os.open(args.output, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(fd)
            finally: os.close(fd)
            def event(row):
                log.write(json.dumps(row, sort_keys=True) + '\n'); log.flush(); os.fsync(log.fileno())
            for row in plan:
                path = Path(row['original_path']); check_identity(path, row['sha256'])
                if identity(path) != tuple(row['live_identity']):
                    raise ValueError('Live media changed after validation')
                verified += 1; event({'event': 'verified_before_unlink', **row})
                if args.execute:
                    path.unlink(); removed += 1; logical += row['bytes']; allocated += row['allocated_bytes']
                    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(fd)
                    finally: os.close(fd)
                    event({'event': 'removed', 'original_path': str(path), 'sha256': row['sha256']})
        if guards()[0] != guard_hashes:
            raise ValueError('Protected protocols changed during removal')
        result['status'] = 'completed'
    except Exception as error:
        result.update(status='failed_retaining_partial_removal_ledger', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        result.update(after=resources(), wall_ns=time.monotonic_ns() - began, cpu_ns=time.process_time_ns() - cpu,
            removed_files=removed, removed_logical_bytes=logical, removed_allocated_bytes=allocated,
            live_files_verified=verified, authoritative_archive_retained=True,
            ledger_sha256=sha(args.output / 'LEDGER.jsonl') if (args.output / 'LEDGER.jsonl').exists() else None)
        write_new(args.output / 'RESULT.json', result)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('receipt', 'definition', 'process', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    for name in ('receipt-sha256', 'process-sha256'): parser.add_argument('--' + name, required=True)
    for name in ('case-start', 'case-end'): parser.add_argument('--' + name, type=int, required=True)
    parser.add_argument('--execute', action='store_true')
    run(parser.parse_args())
