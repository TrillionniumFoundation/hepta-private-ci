#!/usr/bin/env python3
"""Capture completed research evidence only; never execute its contents."""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import tarfile

ROOT = Path('/home/qian-qi/work/hepta-architecture-20261025')
OUT = ROOT / 'native-composition-evidence-snapshot-v3'
DIRS = [
    'evidence/runtime-provider-process-build-v1',
    'evidence/runtime-provider-process-build-v2',
    'evidence/runtime-provider-process-build-v3',
    'evidence/runtime-provider-process-build-v4',
    'native-runtime-scoped-clippy-v1',
    'evidence/runtime-controller-crash-new-driver-v1',
    'evidence/runtime-driver-readonly-v1',
    'provider-runtime-process-standalone-v4',
]
RUNTIME_FILES = [
    'Cargo.toml', 'Cargo.lock', 'examples/native_process_driver.rs',
    'src/mcp/runtime/jobs.rs', 'src/mcp/runtime/jobs_native_lookup.rs',
    'src/mcp/runtime/jobs_native_lookup_tests.rs', 'src/native.rs', 'src/native_tests.rs',
]
PACKAGES = [
    'runtime-provider-process-port-v1.tgz',
    'runtime-provider-process-build-wrapper-v1.tgz',
    'runtime-provider-process-build-wrapper-v2.tgz',
    'runtime-provider-process-build-wrapper-v3.tgz',
    'runtime-provider-effect-key-error-followup-v1.tgz',
    'runtime-provider-admission-input-followup-v1.tgz',
    'runtime-provider-preflight-diagnostics-v1.tgz',
    'runtime-driver-qualification-plan-v1.tgz',
    'runtime-real-canary-v1.tgz',
    'runtime-real-canary-operator-owner-v1.tgz',
    'runtime-real-canary-snapshot-scope-v1.tgz',
]
PINS = {
    'evidence/runtime-provider-process-build-v4/stages/test/stage-result.json':
        'fc9bde14461d0b72ba906fbbe0d02791e11de5f185f938d607c41c246426b6bb',
    'evidence/runtime-provider-process-build-v4/stages/clippy/stage-result.json':
        'a199c932f2a49afdb7b6a7b43226818862c9c3a23bda4170608b44afbd79302c',
    'evidence/runtime-provider-process-build-v4/stages/build-harness/stage-result.json':
        'b5bbb9d065b8e442e328e7a187c930ac26727c60cb44c5224978fd24c6bfe855',
    'evidence/runtime-provider-process-build-v3/stages/build-driver/stage-result.json':
        'b383feee5346a1bdb8dea54bb152465158cf69e1baf2be8f0a7282245da180cc',
    'evidence/runtime-controller-crash-new-driver-v1/native-readonly-crash-f6do5_2k/report.json':
        '3ea43fab535a5fd27e5d141b71aa860d9247e443a8a22f6d161b310a118b60a1',
    'evidence/runtime-driver-readonly-v1/report.json':
        '0bc19becf7db2a758395b2e6cff9bcd96a18d7973d9aace280181c870ab4de69',
    'native-runtime-scoped-clippy-v1/result.json':
        'efe5f0f04e7f007059f77a092904e9a49642a0714f5c077dc3e2ff4162f2395e',
}
EXCLUDED = {'evidence/runtime-provider-process-build-v3/stages/build-driver/previous-driver.bin'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def read_regular(path):
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'Expected regular single-link input: ' + str(path))
    require(before.st_size <= 4 * 1024 * 1024, 'Input exceeds declared four-MiB bound: ' + str(path))
    raw = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Input changed during read')
    return raw


def main():
    os.umask(0o077)
    require(not OUT.exists(), 'Create-only output already exists')
    for name, sha in PINS.items():
        require(digest(read_regular(ROOT / name)) == sha, 'Original terminal receipt differs: ' + name)
    v4 = ROOT / 'evidence/runtime-provider-process-build-v4'
    for stage in ['test', 'fmt', 'clippy', 'build-harness']:
        require(json.loads(read_regular(v4 / 'stages' / stage / 'stage-result.json'))['passed'] is True, 'Incomplete v4 stage')
    final_source = json.loads(read_regular(v4 / 'stages/build-harness/source-after.json'))
    runtime_pins = final_source['runtime']['files']
    for name in RUNTIME_FILES:
        require(name in runtime_pins, 'Runtime path not covered by final build inventory: ' + name)
        raw = read_regular(ROOT / 'runtime' / name)
        require({'bytes': len(raw), 'sha256': digest(raw)} == runtime_pins[name], 'Runtime input differs: ' + name)
    paths = []
    for name in DIRS:
        directory = ROOT / name
        require(directory.is_dir() and not directory.is_symlink(), 'Missing completed input directory: ' + name)
        for path in sorted(directory.rglob('*')):
            require(not path.is_symlink(), 'Unexpected symlink: ' + str(path))
            if path.is_file() and str(path.relative_to(ROOT)) not in EXCLUDED:
                paths.append(path)
    paths += [ROOT / 'runtime' / name for name in RUNTIME_FILES]
    paths += [ROOT / name for name in PACKAGES]
    names = [str(path.relative_to(ROOT)) for path in paths]
    require(len(set(names)) == len(names), 'Duplicate input')
    require(len(paths) < 1000, 'Unexpected input census')
    payload = {}
    for path in paths:
        name = str(path.relative_to(ROOT))
        payload[name] = read_regular(path)
    require(sum(map(len, payload.values())) < 100 * 1024 * 1024, 'Unexpected total bytes')
    manifest = {
        'schema': 'hepta-native-composition-raw-snapshot:v1',
        'scope': 'Completed standalone/native-driver source and evidence. No archived code execution or new qualification.',
        'source_root': str(ROOT),
        'original_full_runtime_gate': 'failed/open; retained in the previous #3979 archive',
        'live_provider_cap_two_round_and_primary_ab': 'not_admitted',
        'binaries_distributed': False,
        'exclusions': sorted(EXCLUDED),
        'binary_evidence': [
            json.loads(payload['evidence/runtime-provider-process-build-v3/stages/build-driver/stage-result.json'])['artifact'],
            json.loads(payload['evidence/runtime-provider-process-build-v4/stages/build-harness/stage-result.json'])['artifact'],
        ],
        'file_count': len(payload),
        'files': [{'path': name, 'bytes': len(raw), 'sha256': digest(raw)} for name, raw in sorted(payload.items())],
    }
    manifest_raw = encoded(manifest)
    OUT.mkdir(mode=0o700)
    (OUT / 'SNAPSHOT_MANIFEST.json').write_bytes(manifest_raw)
    archive_path = OUT / 'native-composition-receipts.tar.gz'
    with archive_path.open('xb') as out:
        with gzip.GzipFile(fileobj=out, mode='wb', filename='', mtime=0, compresslevel=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
                for name, raw in sorted({**payload, 'SNAPSHOT_MANIFEST.json': manifest_raw}.items()):
                    info = tarfile.TarInfo(name)
                    info.size = len(raw)
                    info.mode = 0o600
                    archive.addfile(info, io.BytesIO(raw))
    for name, raw in payload.items():
        require(read_regular(ROOT / name) == raw, 'Input changed after archive capture: ' + name)
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        expected = {**payload, 'SNAPSHOT_MANIFEST.json': manifest_raw}
        require(len(members) == len(expected) and {m.name for m in members} == set(expected), 'Archive census differs')
        for member in members:
            require(member.isfile() and archive.extractfile(member).read() == expected[member.name], 'Archive member differs')
    compressed_raw = archive_path.read_bytes()
    receipt = {'schema': 'hepta-native-composition-archive-production:v1', 'passed': True,
               'archive': {'path': str(archive_path), 'bytes': len(compressed_raw), 'sha256': digest(compressed_raw)},
               'manifest': {'path': str(OUT / 'SNAPSHOT_MANIFEST.json'), 'bytes': len(manifest_raw), 'sha256': digest(manifest_raw)},
               'payload_files': len(payload), 'payload_bytes': sum(map(len, payload.values())),
               'regular_members': len(payload) + 1, 'inputs_unchanged_after': True,
               'archived_code_or_tests_executed': False, 'source_or_owner_content_modified': False,
               'whole_filesystem_zero_metadata_write_claim': False,
               'complete_inputs_rebuildable_without_external_repositories': False,
               'new_binaries_included': False, 'remote_git_publication_or_readback': False}
    (OUT / 'production-receipt.json').write_bytes(encoded(receipt))
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
