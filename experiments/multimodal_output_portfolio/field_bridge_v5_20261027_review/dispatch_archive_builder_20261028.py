"""Local deterministic preservation; no model calls, uploads, or Git mutations."""

import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import subprocess
import tarfile
import tempfile
import zipfile
import zlib


ROOT = Path('/workspace/scratch/e8a4dc33549f')
REPO = ROOT / 'hepta'
OUT = ROOT / 'v5_archive'
ARCHIVE = OUT / 'hepta_field_bridge_v5_20261028_dispatch_evidence.tar.gz'
VERIFICATION = OUT / 'hepta_field_bridge_v5_20261028_dispatch_archive_verification.json'
RESERVE = 256 * 1024 * 1024
CHUNK = 1024 * 1024
PREFIX = 'experiments/multimodal_output_portfolio/field_bridge_v5_20261027_review/'
FIRST_COMMIT = '57a42933da685425fc714eb9b45cb3cb08f2f77a'
SECOND_COMMIT = '8e09fee8a59f2de40acbb2595f01f648fe8b1ed8'
OLD_ARCHIVE_SHA = '58b00c94da32eec4565e49e66a72d98c38f619c6dd2baeeb8a4318a7984fcdc2'
OLD_VERIFICATION_SHA = '95b6d5ce785763284b57ea35141fec73915818b22961af1c104e927eec8074e5'
SECOND_SUMMARY_SHA = 'cf13fa5f2ea53f0b1e14321f6f6239ed11d5ac60c919a5d89c5ec0fd8a1b2d41'
CASES = ('unset_before', 'avx2', 'avx512', 'default', 'unset_after')


class ResourceBlocked(RuntimeError):
    pass


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def identity(path):
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError(f'Not a regular file: {path}')
    digest = hashlib.sha256()
    count = 0
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as source:
        while block := source.read(CHUNK):
            digest.update(block)
            count += len(block)
        after = os.fstat(source.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ) or count != before.st_size:
        raise ValueError(f'File changed during hashing: {path}')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def disk():
    state = os.statvfs(OUT)
    allocatable = state.f_bfree if os.geteuid() == 0 else state.f_bavail
    return {
        'f_bfree_bytes': state.f_bfree * state.f_frsize,
        'f_bavail_bytes': state.f_bavail * state.f_frsize,
        'effective_uid': os.geteuid(),
        'allocatable_basis': 'f_bfree' if os.geteuid() == 0 else 'f_bavail',
        'allocatable_bytes': allocatable * state.f_frsize,
        'reserve_bytes': RESERVE,
    }


def require_space(additional):
    result = disk()
    result['additional_bytes'] = additional
    result['required_bytes'] = additional + RESERVE
    result['passed'] = result['allocatable_bytes'] >= result['required_bytes']
    if not result['passed']:
        raise ResourceBlocked(json.dumps(result, sort_keys=True))
    return result


def checkpoint(receipt, phase):
    receipt['phase'] = phase
    receipt['recorded_at_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    temporary = VERIFICATION.with_suffix('.json.tmp')
    with temporary.open('wb') as output:
        output.write(canonical(receipt))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, VERIFICATION)


def tree_files(path):
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError(f'Not a directory: {path}')
    found = set()
    for base, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            child = Path(base) / name
            mode = child.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError(f'Unsafe filesystem entry: {child}')
            if stat.S_ISREG(mode):
                found.add(child.relative_to(path).as_posix())
    return found


def expected_result_names(second):
    names = {'CPUINFO.txt', 'START.json', 'SUMMARY.json'}
    if second:
        names.add('REGISTRATION.json')
    for case in CASES:
        names.update((case + '.stdout', case + '.stderr'))
        names.update((case + '/START.json', case + '/RESULT.json'))
        if second or case != 'default':
            names.update(case + '/' + name for name in (
                'clean.npz', 'task.npz', 'clean_components.json.gz', 'task_components.json.gz'
            ))
        if second:
            names.update((case + '/clean_forward_fields.json', case + '/task_forward_fields.json'))
            names.add(case + '_LAUNCH.json')
    if second:
        names.update(('prepare.stdout', 'prepare.stderr', 'prepare_LAUNCH.json',
                      'prepare/START.json', 'prepare/RESULT.json',
                      'prepare/RECONSTRUCTED_PANELS.json', 'input_snapshot/MANIFEST.json'))
        names.update(f'input_snapshot/clean-{i:03d}.npz' for i in range(4))
        names.update(f'input_snapshot/task-{i:03d}.npz' for i in range(16))
    return names


GROUPS = [
    ('first', ROOT / 'v5_dispatch_diagnostic_20261028', expected_result_names(False)),
    ('second', ROOT / 'v5_fixed_inputs_diagnostic_20261028', expected_result_names(True)),
    ('preregistration/first', REPO / PREFIX / 'historical_dispatch_20261028', {
        'run.py', 'tests.py', 'PROTOCOL.json', 'PRE_EXECUTION_INVESTIGATION.json',
        'PRE_EXECUTION_REVIEW.json', 'FIRST_EXECUTION_REVIEW.json',
    }),
    ('preregistration/second', REPO / PREFIX / 'historical_fixed_inputs_20261028', {
        'run.py', 'tests.py', 'PROTOCOL.json', 'fixed_inputs_common.py',
        'fixed_inputs_snapshot.py', 'fixed_inputs_score.py', 'PRE_EXECUTION_REVIEW.json',
        'EXECUTION_REVIEW.json', 'EXECUTION_REVIEW.md',
    }),
]
EXTRA = {
    'driver_logs/first.log': ROOT / 'v5_dispatch_diagnostic_driver.log',
    'driver_logs/second.log': ROOT / 'v5_fixed_inputs_diagnostic_driver.log',
    'independent_review/second/review.py': ROOT / 'v5_fixed_inputs_independent_review_20261028.py',
}


def inventory():
    sources = dict(EXTRA)
    groups = []
    for prefix, root, expected in GROUPS:
        actual = tree_files(root)
        if actual != expected:
            raise ValueError(f'Unexpected inventory at {root}: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}')
        for name in actual:
            sources[prefix + '/' + name] = root / name
        groups.append({'archive_prefix': prefix, 'source_root': str(root.relative_to(ROOT)), 'files': len(actual)})
    entries = []
    for name, path in sorted(sources.items()):
        if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
            raise ValueError(f'Unsafe archive path: {name}')
        entry = {'name': name, 'source': path.relative_to(ROOT).as_posix(), **identity(path)}
        if name.startswith('preregistration/'):
            post = path.name in {'FIRST_EXECUTION_REVIEW.json', 'EXECUTION_REVIEW.json', 'EXECUTION_REVIEW.md'}
            entry['provenance_stage'] = 'postexecution_appendix_not_preregistered' if post else 'registered_before_execution'
            entry['registered_commit'] = None if post else (FIRST_COMMIT if name.startswith('preregistration/first/') else SECOND_COMMIT)
        entries.append(entry)
    return entries, groups


def registered_sources():
    results = []
    for directory, expected_commit in [('v5_dispatch_diagnostic_20261028', FIRST_COMMIT),
                                       ('v5_fixed_inputs_diagnostic_20261028', SECOND_COMMIT)]:
        registration = json.loads((ROOT / directory / 'START.json').read_text())['source_registration']
        if registration['commit'] != expected_commit:
            raise ValueError('Unexpected registration commit')
        verified = []
        for path, expected in registration['files'].items():
            data = (REPO / path).read_bytes()
            git_blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
            tree_blob = subprocess.check_output(
                ['git', 'rev-parse', expected_commit + ':' + path], cwd=REPO,
                env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'}, text=True
            ).strip()
            if hashlib.sha256(data).hexdigest() != expected['sha256'] or git_blob != expected['git_blob'] or tree_blob != git_blob:
                raise ValueError(f'Registered source mismatch: {path}')
            verified.append({'path': path, 'git_blob': git_blob, 'sha256': expected['sha256'], 'bytes': len(data)})
        results.append({'commit': expected_commit, 'files': verified, 'registered_tree_blobs_verified': True})
    return results


def bundle_provenance(entries):
    result = []
    for entry in entries:
        if not entry['name'].startswith('preregistration/'):
            continue
        commit = FIRST_COMMIT if entry['name'].startswith('preregistration/first/') else SECOND_COMMIT
        path = (ROOT / entry['source']).relative_to(REPO).as_posix()
        probe = subprocess.run(
            ['git', 'rev-parse', '--verify', commit + ':' + path], cwd=REPO,
            env={**os.environ, 'GIT_NO_LAZY_FETCH': '1'}, capture_output=True, text=True
        )
        registered = entry['registered_commit'] is not None
        if (probe.returncode == 0) != registered:
            raise ValueError(f'Unexpected pre/post execution membership: {path}')
        blob = None
        if registered:
            data = (REPO / path).read_bytes()
            blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
            if probe.stdout.strip() != blob:
                raise ValueError(f'Preregistered bundle file changed: {path}')
        result.append({'name': entry['name'], 'provenance_stage': entry['provenance_stage'],
                       'registered_commit': entry['registered_commit'], 'git_blob_at_registration': blob})
    return result


def duplicate_reviews():
    pairs = [
        ('historical_dispatch_20261028/FIRST_EXECUTION_REVIEW.json', 'v5_dispatch_first_review_20261028.json'),
        ('historical_fixed_inputs_20261028/PRE_EXECUTION_REVIEW.json', 'FIXED_INPUTS_INDEPENDENT_PREEXECUTION_REVIEW_20261028.json'),
        ('historical_fixed_inputs_20261028/EXECUTION_REVIEW.json', 'V5_FIXED_INPUTS_SCIENTIFIC_REVIEW_20261028.json'),
        ('historical_fixed_inputs_20261028/EXECUTION_REVIEW.md', 'V5_FIXED_INPUTS_SCIENTIFIC_REVIEW_20261028.md'),
    ]
    result = []
    for included, duplicate in pairs:
        included_path = REPO / PREFIX / included
        expected = identity(included_path)
        if identity(ROOT / duplicate) != expected:
            raise ValueError(f'Review copy identity mismatch: {duplicate}')
        result.append({'included_source': str(included_path.relative_to(ROOT)),
                       'identical_copy_not_repeated': duplicate, **expected})
    return result


def old_files():
    names = {'hepta_field_bridge_v5_20261027_evidence.tar.gz': OLD_ARCHIVE_SHA,
             'hepta_field_bridge_v5_20261027_archive_verification.json': OLD_VERIFICATION_SHA}
    result = []
    for name, expected in names.items():
        path = OUT / name
        item = identity(path)
        if item['sha256'] != expected:
            raise ValueError(f'Original canonical file mismatch: {name}')
        state = path.stat()
        result.append({'path': str(path), **item, 'mtime_ns': state.st_mtime_ns,
                       'inode': state.st_ino, 'device': state.st_dev})
    return result


class HashSink:
    def __init__(self, output=None, expected_max=None):
        self.output = output
        self.expected_max = expected_max
        self.count = 0
        self.digest = hashlib.sha256()

    def write(self, value):
        if self.expected_max is not None and self.count + len(value) > self.expected_max:
            raise ValueError('Compressed output exceeded exact estimate')
        if self.output is not None:
            require_space(len(value))
            self.output.write(value)
        self.count += len(value)
        self.digest.update(value)
        return len(value)

    def flush(self):
        if self.output is not None:
            self.output.flush()


class VerifiedReader:
    def __init__(self, path, expected):
        self.stream = os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb')
        self.expected = expected
        self.count = 0
        self.digest = hashlib.sha256()
        if os.fstat(self.stream.fileno()).st_size != expected['bytes']:
            self.stream.close()
            raise ValueError(f'Source size changed: {path}')

    def read(self, size=-1):
        value = self.stream.read(size)
        self.count += len(value)
        self.digest.update(value)
        return value

    def finish(self):
        self.stream.close()
        if self.count != self.expected['bytes'] or self.digest.hexdigest() != self.expected['sha256']:
            raise ValueError('Source bytes changed during tar emission')


def emit_archive(sink, manifest_bytes, entries):
    all_entries = [{'name': 'MANIFEST.json', 'bytes': len(manifest_bytes),
                    'sha256': hashlib.sha256(manifest_bytes).hexdigest()}] + entries
    with gzip.GzipFile(filename='', mode='wb', compresslevel=6, mtime=0, fileobj=sink) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
            for entry in sorted(all_entries, key=lambda row: row['name']):
                info = tarfile.TarInfo(entry['name'])
                info.size = entry['bytes']
                info.mode = 0o644
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.type = tarfile.REGTYPE
                if entry['name'] == 'MANIFEST.json':
                    archive.addfile(info, io.BytesIO(manifest_bytes))
                else:
                    reader = VerifiedReader(ROOT / entry['source'], entry)
                    try:
                        archive.addfile(info, reader)
                    finally:
                        reader.finish()


def inner_integrity(path, name):
    if name.endswith('.npz'):
        with zipfile.ZipFile(path) as container:
            infos = container.infolist()
            names = [item.filename for item in infos]
            if len(set(names)) != len(names):
                raise ValueError(f'Duplicate inner NPZ member: {name}')
            for item in infos:
                mode = item.external_attr >> 16
                if (PurePosixPath(item.filename).is_absolute() or '..' in PurePosixPath(item.filename).parts
                        or item.is_dir() or stat.S_ISLNK(mode)):
                    raise ValueError(f'Unsafe NPZ member: {name}/{item.filename}')
            bad = container.testzip()
            if bad is not None:
                raise ValueError(f'NPZ CRC mismatch: {name}/{bad}')
            return {'format': 'npz_zip', 'crc_verified': True, 'members': len(infos),
                    'uncompressed_bytes': sum(item.file_size for item in infos)}
    if name.endswith('.gz'):
        count = 0
        with gzip.open(path, 'rb') as compressed:
            while block := compressed.read(CHUNK):
                count += len(block)
        return {'format': 'gzip', 'crc_verified_to_eof': True, 'uncompressed_bytes': count}
    return None


def verify_restore(manifest_bytes, entries, receipt):
    expected = {'MANIFEST.json': {'bytes': len(manifest_bytes), 'sha256': hashlib.sha256(manifest_bytes).hexdigest()}}
    expected.update({item['name']: item for item in entries})
    restored = []
    temporary_dir = Path(tempfile.mkdtemp(prefix='dispatch_member_restore_', dir=OUT))
    receipt['restore_temporary_directory'] = str(temporary_dir)
    checkpoint(receipt, 'per_member_literal_restore')
    with ARCHIVE.open('rb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='rb') as compressed:
            with tarfile.open(fileobj=compressed, mode='r|') as archive:
                seen = set()
                for member in archive:
                    if (member.name not in expected or member.name in seen or not member.isfile()
                            or member.type != tarfile.REGTYPE or member.pax_headers or member.linkname
                            or PurePosixPath(member.name).is_absolute() or '..' in PurePosixPath(member.name).parts):
                        raise ValueError(f'Unknown or unsafe tar member: {member.name}')
                    wanted = expected[member.name]
                    if member.size != wanted['bytes'] or (member.mode, member.uid, member.gid, member.mtime, member.uname, member.gname) != (0o644, 0, 0, 0, '', ''):
                        raise ValueError(f'Tar metadata mismatch: {member.name}')
                    require_space(member.size)
                    destination = temporary_dir / 'member.bin'
                    with destination.open('xb') as output, archive.extractfile(member) as source:
                        while block := source.read(CHUNK):
                            output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
                    actual = identity(destination)
                    if actual != {key: wanted[key] for key in ('bytes', 'sha256')}:
                        raise ValueError(f'Restored bytes mismatch: {member.name}')
                    if member.name == 'MANIFEST.json' and destination.read_bytes() != manifest_bytes:
                        raise ValueError('Restored manifest mismatch')
                    inner = inner_integrity(destination, member.name)
                    destination.unlink()
                    restored.append({'name': member.name, **actual, 'literal_restore_verified': True,
                                     'verified_replica_deleted': True, 'inner_integrity': inner})
                    seen.add(member.name)
                if seen != set(expected):
                    raise ValueError('Missing expected tar members')
            while tail := compressed.read(CHUNK):
                if any(tail):
                    raise ValueError('Unexpected nonzero decompressed trailing data')
        if raw.tell() != ARCHIVE.stat().st_size:
            raise ValueError('Outer archive physical EOF not reached')
    temporary_dir.rmdir()
    return restored


def main():
    if ARCHIVE.exists() or VERIFICATION.exists():
        raise RuntimeError('Refusing to replace an existing dispatch deliverable')
    receipt = {
        'schema': 'hepta.field-bridge.v5.dispatch-archive-verification.1',
        'status': 'IN_PROGRESS', 'admission': False, 'scientific_status': 'FAIL',
        'all_original_substantive_blockers_closed': False,
        'purpose': 'Local byte preservation and integrity verification only',
        'qualification': False, 'historical_raw_file_recovered': False,
        'historical_gate_changed': False, 'new_holdout_access': False,
        'raw_upload_attempts': 0, 'external_durable_save': False,
        'custody_status': 'LOCAL_ONLY_PENDING_NAMED_LIBRARY_AUTHORIZATION',
        'literal_restore_scope': 'per-member literal byte restoration; not full tree replay',
        'full_tree_replay': False, 'model_calls': 0, 'git_mutations': 0,
        'builder': {'path': str(Path(__file__)), **identity(Path(__file__))},
        'runtime': {'python': platform.python_version(), 'zlib': zlib.ZLIB_RUNTIME_VERSION},
    }
    checkpoint(receipt, 'initializing')
    try:
        original = old_files()
        receipt['original_canonical_before'] = original
        entries, groups = inventory()
        if len(entries) != 143:
            raise ValueError('Unexpected payload count')
        registrations = registered_sources()
        provenance = bundle_provenance(entries)
        duplicates = duplicate_reviews()
        prior_attempt_path = ROOT / 'dispatch_archive_attempt_1_inventory_rejection.json'
        prior_attempt = {'path': str(prior_attempt_path), **identity(prior_attempt_path),
                         'status': 'FAILED_CLOSED_INVENTORY_CHANGE_BEFORE_ARCHIVE_WRITE',
                         'reason': 'Two exact postexecution review copies appeared in the second source directory after the initial inventory. No archive was written; all existing inputs were preserved.'}
        summaries = {}
        for label, folder in [('first', 'v5_dispatch_diagnostic_20261028'), ('second', 'v5_fixed_inputs_diagnostic_20261028')]:
            path = ROOT / folder / 'SUMMARY.json'
            value = json.loads(path.read_text())
            if value['admission'] is not False or value['scientific_status'] != 'FAIL':
                raise ValueError('Scientific disposition changed')
            summaries[label] = {**identity(path), 'execution_complete': value['execution_complete'],
                                'diagnostic_interpretable': value['diagnostic_interpretable'],
                                'scientific_status': value['scientific_status'], 'admission': value['admission']}
        if summaries['second']['sha256'] != SECOND_SUMMARY_SHA:
            raise ValueError('Second summary identity changed')
        manifest = {
            'schema': 'hepta.field-bridge.v5.dispatch-archive-manifest.1',
            'entries': entries, 'groups': groups, 'payload_files': len(entries),
            'payload_bytes': sum(item['bytes'] for item in entries),
            'source_registrations': registrations, 'diagnostic_summaries': summaries,
            'registration_bundle_file_provenance': provenance,
            'postexecution_appendices_are_not_preregistered': True,
            'identical_review_copies_not_repeated': duplicates,
            'prior_canonical_files_referenced_not_embedded': [
                {key: item[key] for key in ('path', 'bytes', 'sha256')} for item in original
            ],
            'admission': False, 'scientific_status': 'FAIL', 'historical_raw_file_recovered': False,
            'scope': 'All first and second diagnostic files, driver logs, exact preregistration sources and pre/post reviews. Existing canonical archive is referenced, not repeated.',
        }
        manifest_bytes = canonical(manifest)
        receipt.update({'manifest': {'bytes': len(manifest_bytes), 'sha256': hashlib.sha256(manifest_bytes).hexdigest()},
                        'payload_files': len(entries), 'payload_bytes': manifest['payload_bytes'],
                        'groups': groups, 'source_registrations': registrations, 'diagnostic_summaries': summaries,
                        'registration_bundle_file_provenance': provenance,
                        'identical_review_copies_not_repeated': duplicates,
                        'prior_packaging_attempt': prior_attempt})
        checkpoint(receipt, 'counting_deterministic_compressed_stream_without_disk')
        counter = HashSink()
        emit_archive(counter, manifest_bytes, entries)
        estimate = {'bytes': counter.count, 'sha256': counter.digest.hexdigest(), 'disk_bytes_written': 0}
        receipt['exact_compressed_estimate'] = estimate
        receipt['prewrite_disk_check'] = require_space(counter.count)
        if inventory()[0] != entries:
            raise ValueError('Source inventory changed before write')
        checkpoint(receipt, 'writing_archive')
        partial = ARCHIVE.with_suffix('.gz.partial')
        with partial.open('xb') as output:
            sink = HashSink(output, expected_max=counter.count)
            emit_archive(sink, manifest_bytes, entries)
            output.flush()
            os.fsync(output.fileno())
        written = identity(partial)
        if written != {'bytes': estimate['bytes'], 'sha256': estimate['sha256']}:
            raise ValueError('Actual compressed archive differs from no-disk deterministic stream')
        if ARCHIVE.exists():
            raise ValueError('Archive target appeared during creation')
        os.replace(partial, ARCHIVE)
        receipt['archive'] = {'path': str(ARCHIVE), **written, 'compression': 'gzip level6, mtime0, empty filename; USTAR regular files only',
                              'same_bytes_as_no_disk_stream': True}
        members = verify_restore(manifest_bytes, entries, receipt)
        if identity(ARCHIVE) != written:
            raise ValueError('Archive bytes changed during restore verification')
        if inventory()[0] != entries:
            raise ValueError('Source inventory changed after restore')
        if duplicate_reviews() != duplicates:
            raise ValueError('Review copies changed after restore')
        after = old_files()
        if original != after:
            raise ValueError('Original canonical files changed')
        receipt['original_canonical_after'] = after
        receipt['original_canonical_files_untouched'] = True
        receipt['all_source_files_unchanged'] = True
        receipt['archive_bytes_unchanged_after_restore'] = True
        receipt['verification'] = {
            'all_member_sha256_and_lengths_verified': True,
            'all_expected_members_present': True, 'unknown_or_unsafe_members': 0,
            'regular_members_including_manifest': len(members),
            'payload_members': len(entries), 'outer_gzip_crc_verified_to_physical_eof': True,
            'npz_zip_crc_files': sum(bool(x['inner_integrity']) and x['inner_integrity']['format'] == 'npz_zip' for x in members),
            'inner_gzip_crc_files': sum(bool(x['inner_integrity']) and x['inner_integrity']['format'] == 'gzip' for x in members),
            'literal_restore': 'per member, materialize one file, read back SHA256 and length, verify inner CRC, delete verified replica',
            'maximum_simultaneously_restored_files': 1,
            'maximum_restored_member_bytes': max(x['bytes'] for x in members),
            'temporary_restore_directory_removed': True, 'full_tree_replay': False,
        }
        receipt['members'] = members
        receipt['disk_after'] = disk()
        receipt['status'] = 'PASS'
        checkpoint(receipt, 'completed')
    except Exception as error:
        receipt['status'] = 'BLOCKED_RESOURCE' if isinstance(error, ResourceBlocked) else 'FAILED'
        receipt['error'] = {'type': type(error).__name__, 'message': str(error)}
        receipt['disk_at_failure'] = disk()
        checkpoint(receipt, 'blocked_or_failed')
        raise
    print(json.dumps({'archive': identity(ARCHIVE), 'verification': identity(VERIFICATION),
                      'payload_files': receipt['payload_files'], 'verification_results': receipt['verification'],
                      'original_canonical_files_untouched': True, 'disk_after': receipt['disk_after']}, sort_keys=True))


if __name__ == '__main__':
    main()
