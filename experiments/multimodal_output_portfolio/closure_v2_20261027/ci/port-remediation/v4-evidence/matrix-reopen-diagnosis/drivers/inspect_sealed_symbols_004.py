#!/usr/bin/env python3
"""Diagnose restored mode loss using the unchanged real CI executable in memory."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import stat
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone

ROOT = Path('/workspace/scratch/95988d8d3ab1')
REPO = ROOT / 'hepta-private-ci'
REMOTE = ROOT / 'ndu-port-remote-3a779a6'
OUT = Path(__file__).parent / 'symbols-004'
ZIP = REMOTE / 'raw/ndu-port-tests-matrix-40503203294-1.zip'
ZIP_SHA = 'ac5260d4cb487988c470b3cf4dfd4ac5817f84a424c64b26628be76e7074fbf5'
BIN_SHA = '12e53b85e42fbb8e42658a987523425bd1dc3ada4d545d1f1ac0ba3710859448'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    return {str(p.relative_to(root)): {'bytes': p.stat().st_size, 'sha256': sha(p)}
            for p in sorted(root.rglob('*')) if p.is_file()}


def now():
    return datetime.now(timezone.utc).isoformat()


OUT.mkdir(exist_ok=False)
record = {'schema': 'hepta.matrix-reopen.permission-diagnosis.v1', 'started_at': now(),
          'scope': 'Diagnostic reuse of the unchanged v2 CI executable. No new-source qualification, new build or policy change.',
          'driver_sha256': sha(Path(__file__)), 'commands': [], 'arms': []}
shutil.copyfile(__file__, OUT / 'executed-source.py')
assert sha(ZIP) == ZIP_SHA
record['original_zip'] = {'path': str(ZIP), 'sha256': ZIP_SHA, 'bytes': ZIP.stat().st_size}
old_record = json.loads((REMOTE / 'old-matrix-small/RESULT.json').read_text())
old_fixture = REMOTE / 'old-matrix-small/fixture'
assert tree(old_fixture) == old_record['fixture_files']
record['pristine_fixture'] = old_record['fixture_files']
meta = REMOTE / 'producer/metadata.json'
binaries = REMOTE / 'matrix-small/reopen_old_version_fixture-binaries.json'
for name, path in [('cargo-metadata.json', meta), ('binaries-metadata.json', binaries)]:
    shutil.copyfile(path, OUT / name)
    record[name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
listing = json.loads(binaries.read_text())
binary = listing['rust-binaries']['codex-hepta-matrix-sdk::store_version_migration']
relative_binary = Path(binary['binary-path']).relative_to(listing['rust-build-meta']['target-directory'])
target = OUT / 'relocated-target'
link = target / relative_binary
link.parent.mkdir(parents=True)
fd = os.memfd_create('hepta-unchanged-ci-matrix-019', os.MFD_ALLOW_SEALING)
try:
    digest = hashlib.sha256()
    size = 0
    with zipfile.ZipFile(ZIP) as archive:
        with archive.open('binaries/' + BIN_SHA) as source:
            for data in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(data)
                size += len(data)
                view = memoryview(data)
                while view:
                    view = view[os.write(fd, view):]
    assert digest.hexdigest() == BIN_SHA
    os.fchmod(fd, 0o555)
    # Linux UAPI values checked in /usr/include/linux/fcntl.h.
    seals = 0x0008 | 0x0004 | 0x0002 | 0x0001
    fcntl.fcntl(fd, 1033, seals)
    assert fcntl.fcntl(fd, 1034) == seals
    mempath = Path('/proc') / os.readlink('/proc/self') / 'fd' / str(fd)
    assert sha(mempath) == BIN_SHA
    link.symlink_to(mempath)
    record['actual_binary'] = {'sha256': BIN_SHA, 'bytes': size, 'memfd_seals': seals,
                               'relocated_path': str(link), 'stored_on_disk': False}
    selected = []
    with subprocess.Popen(['/usr/bin/nm', '--defined-only', '-C', str(mempath)], stdout=subprocess.PIPE, text=True) as names:
        for line in names.stdout:
            if any(term in line for term in ('codex_hepta_matrix_sdk::sdk::MatrixSdkClient::login_or_restore', 'codex_hepta_matrix_sdk::sdk::load_session', 'tokio::time::timeout::Timeout<T> as core::future::future::Future>::poll')):
                selected.append(line)
        assert names.wait() == 0
    (OUT / 'selected-symbols.txt').write_text(''.join(selected))
    record['selected_symbols_sha256'] = sha(OUT / 'selected-symbols.txt')
    record['selected_symbols_count'] = len(selected)
    record['status'] = 'symbols_inspected_no_test_executed'
    print(json.dumps({'status': record['status'], 'selected_symbols_count': len(selected)}), flush=True)
except Exception as error:
    record.update(status='diagnostic_failed_before_completion', error_type=type(error).__name__, error=str(error))
    print(json.dumps({'status': record['status'], 'error_type': type(error).__name__, 'error': str(error)}), flush=True)
    raise
finally:
    record.update(finished_at=now(), binary_dropped_after_diagnostic=True)
    os.close(fd)
    (OUT / 'RESULT.json').write_text(json.dumps(record, indent=2) + '\n')
