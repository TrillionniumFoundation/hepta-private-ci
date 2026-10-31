"""Reclaim explicitly selected duplicate generated media after byte verification.

Every complete historical archive, its manifest, its selected members and each
expanded copy are verified. Models, source recordings, current run directories,
repository files and all protected input paths remain in place. This script
never extracts, changes or removes an authoritative archive.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import tarfile
import time


WORKSPACE = Path('/workspace/scratch/87e43aa872f5')
OLD_ROOTS = tuple(WORKSPACE / name for name in (
    'ndu-runs/next-native', 'ndu-runs/action-value-prospective-001',
    'ndu-runs/action-value-smoke-001', 'ndu-runs/control-next-prospective-001',
    'ndu-runs/control-next-development-001', 'ndu-runs/control-next-development-002',
    'ndu-runs/control', 'ndu-runs/media', 'ndu-next-assets/media/evidence')) + (
    Path('/tmp/hepta-ndu-next-media-cache'), Path('/tmp/hepta-ndu-next-joint'))
MEDIA_NAMES = {'caption.txt', 'image.png', 'audio.wav', 'video.mp4',
               'neural-event-0.wav', 'neural-event-1.wav', 'media.bin', 'actual-media.bin'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_identity(path, expected):
    if sha(path) != expected:
        raise ValueError('Identity changed: ' + str(path))


def write_new(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')


def absolute_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from absolute_strings(key)
            yield from absolute_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from absolute_strings(item)
    elif isinstance(value, str) and value.startswith('/'):
        yield Path(value).resolve()


def run(args):
    check_identity(args.report, args.report_sha256)
    report = json.loads(args.report.read_text())
    check_identity(report['candidate_file'], report['candidate_file_sha256'])
    check_identity(report['protected_paths_file'], report['protected_paths_sha256'])
    guard = json.loads(Path(report['protected_paths_file']).read_text())
    protected = {Path(row['path']).resolve() for row in guard['paths']}
    protected_roots = [Path(path).resolve() for path in report['protect_descendant_roots']]
    for entry in report['protected_protocols']:
        check_identity(entry['path'], entry['sha256'])
        protected.add(Path(entry['path']).resolve())
        protected.update(absolute_strings(json.loads(Path(entry['path']).read_text())))
    with Path(report['candidate_file']).open() as stream:
        candidates = [json.loads(line) for line in stream]
    originals = [row['original_path'] for row in candidates]
    if len(originals) != len(set(originals)) or len(candidates) != report['candidate_count']:
        raise ValueError('Candidate census contains omissions or duplicate original paths')
    groups = defaultdict(lambda: defaultdict(list))
    for row in candidates:
        path = Path(row['original_path'])
        if (not path.is_absolute() or path.is_symlink() or path.resolve() != path
                or path.name not in MEDIA_NAMES or not any(path.is_relative_to(root) for root in OLD_ROOTS)
                or path in protected or any(path.is_relative_to(root) for root in protected_roots)
                or any(part.startswith(('input-', 'source-', 'worker-')) or part == 'observed-events'
                       for part in path.parts)):
            raise ValueError('Ineligible source, current dependency, or unsafe path: ' + str(path))
        groups[row['archive_id']][row['member']].append(row)
    archives = {entry['archive_id']: entry for entry in report['archives']}
    if set(groups) != set(archives):
        raise ValueError('Every selected archive requires its exact custody record')
    # Verify all authoritative compressed files before any expanded file removal.
    for entry in archives.values():
        check_identity(entry['archive'], entry['archive_sha256'])
        check_identity(entry['manifest'], entry['manifest_sha256'])
        check_identity(entry['receipt'], entry['receipt_sha256'])
        manifest = json.loads(Path(entry['manifest']).read_text())
        members = {row.get('member', row.get('path')): row for row in manifest['files']}
        for member, copies in groups[entry['archive_id']].items():
            source = members.get(member)
            if source is None or any(row['bytes'] != source['bytes'] or row['sha256'] != source['sha256'] for row in copies):
                raise ValueError('Selected member is not the exact archived artifact')
            for row in copies:
                if entry['archive_id'] == 'old_media':
                    path = Path(row['original_path'])
                    roots = (WORKSPACE / 'ndu-runs/media', WORKSPACE / 'ndu-next-assets/media/evidence')
                    if not any(path.is_relative_to(root) and member == 'evidence/' + path.relative_to(root).as_posix() for root in roots):
                        raise ValueError('Unrecognized historical expanded-copy mapping')
                elif row['original_path'] != source['original_path']:
                    raise ValueError('Historical original path differs')
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.time_ns(), time.process_time_ns()
    disk = os.statvfs(WORKSPACE)
    result = {'schema': 'hepta.advance.verified-multi-archive-reclaim.v1', 'status': 'running',
        'started_unix_ns': started, 'plan_sha256': args.report_sha256,
        'protected_paths': len(protected), 'candidate_files': len(candidates),
        'execute': args.execute, 'actual_free_before': disk.f_bfree * disk.f_frsize,
        'authoritative_archives_retained': True, 'source_and_current_inputs_retained': True,
        'concurrent_activity': 'Joint confirmation remained running; this necessary storage operation is not a model run and may affect shared-host wall timings.'}
    write_new(args.output / 'STARTED.json', result)
    verified_members, removed, allocated, logical = 0, 0, 0, 0
    try:
        with (args.output / 'MEMBERS.jsonl').open('x') as log:
            for key, entry in archives.items():
                selected, seen = groups[key], set()
                with tarfile.open(entry['archive'], 'r|gz') as archive:
                    for member in archive:
                        if member.name not in selected:
                            continue
                        copies = selected[member.name]
                        if member.name in seen or not member.isfile() or member.size != copies[0]['bytes']:
                            raise ValueError('Repeated or invalid archived member')
                        check = hashlib.file_digest(archive.extractfile(member), 'sha256').hexdigest()
                        if check != copies[0]['sha256']:
                            raise ValueError('Archive member bytes differ from the manifest')
                        seen.add(member.name); verified_members += 1
                        for row in copies:
                            path = Path(row['original_path']); stat = path.lstat()
                            if (path.is_symlink() or not path.is_file() or stat.st_nlink != 1
                                    or stat.st_size != row['bytes'] or stat.st_ino != row['st_ino']
                                    or stat.st_dev != row['st_dev'] or stat.st_mtime_ns != row['st_mtime_ns']):
                                raise ValueError('Expanded artifact metadata changed: ' + str(path))
                            check_identity(path, row['sha256'])
                            now = path.lstat()
                            if (now.st_ino, now.st_size, now.st_mtime_ns) != (stat.st_ino, stat.st_size, stat.st_mtime_ns):
                                raise ValueError('Expanded artifact changed during verification')
                            log.write(json.dumps({**row, 'verified_member_and_live_bytes': True,
                                                  'removed': args.execute}, sort_keys=True) + '\n')
                            if args.execute:
                                path.unlink(); removed += 1
                                allocated += stat.st_blocks * 512; logical += stat.st_size
                            if removed and removed % 2000 == 0:
                                log.flush(); os.fsync(log.fileno())
                                print(json.dumps({'removed_files': removed, 'allocated_bytes': allocated}), flush=True)
                if seen != set(selected):
                    raise ValueError('An archived selected member was missing')
        for entry in report['protected_protocols']:
            check_identity(entry['path'], entry['sha256'])
        result['status'] = 'completed'
    except Exception as error:
        result.update(status='failed_with_partial_removal_custody', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        disk = os.statvfs(WORKSPACE)
        result.update(completed_unix_ns=time.time_ns(), elapsed_ns=time.time_ns() - started,
            cpu_ns=time.process_time_ns() - cpu, verified_archive_members=verified_members,
            removed_files=removed, removed_allocated_bytes=allocated, removed_logical_bytes=logical,
            actual_free_after=disk.f_bfree * disk.f_frsize, removal_ledger_sha256=sha(args.output / 'MEMBERS.jsonl'),
            restoration='Use each original_path and archive_id/member in the immutable plan and ledger; exact complete archives and original manifests are retained.')
        write_new(args.output / 'RESULT.json', result)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--report-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    run(parser.parse_args())
