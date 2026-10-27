"""Package existing AWS evidence and verify every member via actual disk restore."""

from pathlib import Path
import datetime
import gzip
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import time


ROOT = Path('/workspace/scratch/95988d8d3ab1')
WORK = ROOT / 'ndu-dependency-remediation/aws-login-port'
HERE = Path(__file__).resolve().parent
ARCHIVE = ROOT / 'hepta_aws_login_p256_candidate_20261027.tar.gz'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def record(path, name):
    return {'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)}


assert not ARCHIVE.exists(), 'Do not overwrite a frozen candidate archive.'
references = WORK / 'source-references'
references.mkdir(exist_ok=True)
repo = ROOT / 'hepta-private-ci'
for name in ['defs.bzl', 'workspace_root_test_launcher.sh.tpl', 'workspace_root_test_launcher.bat.tpl']:
    shutil.copyfile(repo / name, references / name)
registry = ROOT / 'ndu-dependency-remediation/yaml-migration/cargo-home/registry/src'
formatter = next(registry.glob('*/tracing-subscriber-0.3.22/src/fmt/fmt_layer.rs'))
shutil.copyfile(formatter, references / 'tracing-subscriber-0.3.22-fmt_layer.rs')

handoff = json.loads((WORK / 'CANDIDATE_HANDOFF.json').read_text())
for item in handoff['candidate_files']:
    assert sha(WORK / 'candidate-root' / item['path']) == item['sha256']
inputs = {}
for name in ['upstream-002', 'upstream-003', 'fixture-restoration-001', 'proposed', 'candidate-root', 'frozen-binaries', 'source-references']:
    directory = WORK / name
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(WORK)
        if path.is_file() and 'target' not in relative.parts and '__pycache__' not in relative.parts:
            inputs['aws-login-port/' + str(relative)] = path
for path in sorted(WORK.iterdir()):
    if path.is_file():
        inputs['aws-login-port/' + path.name] = path
for path in sorted(HERE.rglob('*')):
    if path.is_file() and '__pycache__' not in path.parts:
        inputs['repository-evidence/' + str(path.relative_to(HERE))] = path

rows = [record(path, name) for name, path in sorted(inputs.items())]
with ARCHIVE.open('xb') as raw:
    with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for item in rows:
                source = inputs[item['path']]
                assert sha(source) == item['sha256']
                info = tarfile.TarInfo(item['path'])
                info.size = item['bytes']
                info.mode = 0o555 if item['path'].startswith('aws-login-port/frozen-binaries/') else 0o644
                info.mtime = 0
                with source.open('rb') as stream:
                    tar.addfile(info, stream)
    raw.flush()
    os.fsync(raw.fileno())

index = {
    'archive': str(ARCHIVE), 'bytes': ARCHIVE.stat().st_size, 'sha256': sha(ARCHIVE),
    'files': rows, 'file_count': len(rows), 'payload_bytes': sum(row['bytes'] for row in rows),
    'production_candidate_handoff_sha256': sha(WORK / 'CANDIDATE_HANDOFF.json'),
    'scope': 'Complete vendored candidate, official source archives and extracted originals, all official fixtures, actual test executable, existing logs including failures, source/lock/peer reviews, and qualification plan. Build caches are excluded.',
}
index_path = Path(str(ARCHIVE) + '.index.json')
index_path.write_text(json.dumps(index, indent=2) + '\n')

start = time.monotonic()
restore_root = Path(tempfile.mkdtemp(prefix='aws-port-restore-', dir=ROOT))
expected = {row['path']: row for row in rows}
restored = 0
restored_bytes = 0
max_file = 0
with tarfile.open(ARCHIVE, 'r:gz') as tar:
    for member in tar:
        assert member.isfile() and member.name in expected
        item = expected.pop(member.name)
        assert member.size == item['bytes']
        # A unique path for each member avoids aliasing reused temporary paths.
        destination = restore_root / ('member-' + str(restored))
        with tar.extractfile(member) as source, destination.open('xb') as output:
            shutil.copyfileobj(source, output, length=1048576)
            output.flush()
            os.fsync(output.fileno())
        assert destination.stat().st_size == item['bytes']
        assert sha(destination) == item['sha256']
        restored += 1
        restored_bytes += item['bytes']
        max_file = max(max_file, item['bytes'])
        destination.unlink()
assert not expected
restore_root.rmdir()
assert sha(ARCHIVE) == index['sha256']
receipt = {
    'at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'archive': str(ARCHIVE), 'archive_sha256': index['sha256'], 'archive_bytes': index['bytes'],
    'index': str(index_path), 'index_sha256': sha(index_path),
    'passed': True, 'actual_disk_restored_members': restored,
    'actual_disk_restored_bytes': restored_bytes, 'maximum_single_restored_file_bytes': max_file,
    'procedure': 'Each member written to a unique path, flushed, fsynced, closed, reopened, SHA256 checked, then deleted; archive hash checked again.',
    'seconds': time.monotonic() - start,
    'full_upstream_and_workspace_gate_passed': False,
    'unchanged_remaining_failures': 2,
}
receipt_path = HERE / 'evidence/ARCHIVE_RESTORE_RECEIPT.json'
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt, indent=2))
