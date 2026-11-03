"""Package complete evidence after both monitored segments have stopped.

Publication transport is separate from measured maintenance. Original raw files
are preserved. Every published blob is at most 400000 bytes except this small
manifest and restore helper, which are also checked against the repository cap.
"""

import argparse
import hashlib
import json
import lzma
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time


ROOT = Path(__file__).resolve().parent
CAP = 400000


def identity(path):
    hasher, size = hashlib.sha256(), 0
    with path.open('rb') as source:
        while block := source.read(65536):
            hasher.update(block)
            size += len(block)
    return {'bytes': size, 'sha256': hasher.hexdigest()}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def pack(kind):
    began = time.monotonic_ns()
    roots = ('run-01', 'run-02-resume') if kind == 'chain' else ('run-03-clean',)
    result = json.loads((ROOT/roots[-1]/'RESULT.json').read_bytes())
    monitor = json.loads((ROOT/roots[-1]/'resource.json').read_bytes())
    if result['completed_cycles'] != 192 or monitor['exit_code'] != 0:
        raise ValueError('only the completed full horizon may be published')
    destination = ROOT/'evidence'/('longrun64x3' if kind == 'chain' else 'longrun64x3-clean')
    destination.mkdir(parents=True, exist_ok=False)
    files = sorted([p for name in roots for p in (ROOT/name).rglob('*') if p.is_file()])
    names = ('LONGRUN_PROTOCOL.json', 'LONGRUN_PROTOCOL.sha256', 'RESUME_PLAN.json', 'manager.py',
             'fit_worker.py', 'owner_read.py', 'resume.py', 'pack_evidence.py', 'restore_evidence.py',
             'INITIAL_TRAINING.json', 'SUMMARY.json' if kind == 'chain' else 'CLEAN_SUMMARY.json', 'README.md')
    files += [ROOT/name for name in names if (ROOT/name).exists()]
    entries = [{'path': str(path.relative_to(ROOT)), **identity(path)} for path in files]
    inventory, pending = [], bytearray()

    def inventory_chunk():
        if pending:
            path = destination/f'inventory.{len(inventory):04d}.jsonl'
            path.write_bytes(pending)
            inventory.append({'file': path.name, **identity(path)})
            pending.clear()

    for entry in entries:
        line = encoded(entry)+b'\n'
        if len(pending)+len(line) > CAP:
            inventory_chunk()
        pending.extend(line)
    inventory_chunk()
    parts, archive_hash, archive_bytes = [], hashlib.sha256(), 0
    with tempfile.TemporaryFile(dir=destination) as temporary:
        with lzma.LZMAFile(temporary, 'wb', preset=6) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|') as archive:
                for path, entry in zip(files, entries, strict=True):
                    member = tarfile.TarInfo(entry['path'])
                    member.size, member.mode, member.mtime = entry['bytes'], 0o644, 0
                    with path.open('rb') as source:
                        archive.addfile(member, source)
        temporary.seek(0)
        while block := temporary.read(CAP):
            path = destination/f'archive.{len(parts):04d}.part'
            path.write_bytes(block)
            parts.append({'file': path.name, **identity(path)})
            archive_hash.update(block)
            archive_bytes += len(block)
    shutil.copyfile(ROOT/'restore_evidence.py', destination/'restore.py')
    for name in roots:
        shutil.copyfile(ROOT/name/'FREEZE.json', destination/f'RAW_FREEZE-{name}.json')
    metadata = {'schema': 'hepta.memory.adapter-longrun-archive.v1', 'compression': 'tar+xz',
                'experiment': kind, 'raw_freezes': {name: identity(destination/f'RAW_FREEZE-{name}.json') for name in roots},
                'parts': parts, 'inventory': inventory, 'archive_sha256': archive_hash.hexdigest(),
                'archive_bytes': archive_bytes, 'member_count': len(entries), 'raw_bytes': sum(e['bytes'] for e in entries),
                'restore_helper': identity(destination/'restore.py'), 'all_model_parameters_preserved': True,
                'original_raw_files_preserved': True, 'dependency_sources': 'Frozen repository modules referenced by FREEZE.json; no dependency wheels or encoder weights copied'}
    (destination/'ARCHIVE.json').write_bytes(encoded(metadata)+b'\n')
    checked = subprocess.run([sys.executable, '-I', '-B', str(destination/'restore.py'), '--verify-only'],
                             capture_output=True, text=True, timeout=180)
    if checked.returncode:
        (destination/'VERIFICATION_FAILED.txt').write_text(checked.stdout+checked.stderr)
        raise RuntimeError('archive transport verification failed')
    verification = json.loads(checked.stdout)
    verification['publication_packaging_wall_ns'] = time.monotonic_ns()-began
    verification['part_limit_bytes'] = CAP
    verification['maximum_published_blob_bytes'] = max(p.stat().st_size for p in destination.iterdir() if p.is_file())
    if verification['maximum_published_blob_bytes'] >= 512000:
        raise ValueError('repository blob cap exceeded')
    (destination/'VERIFICATION.json').write_bytes(encoded(verification)+b'\n')
    print(json.dumps({'destination': str(destination), **verification, 'archive_bytes': archive_bytes}, sort_keys=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kind', choices=('chain', 'clean'), default='chain')
    pack(parser.parse_args().kind)
