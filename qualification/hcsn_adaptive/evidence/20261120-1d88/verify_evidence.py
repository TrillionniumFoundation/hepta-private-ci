"""Assemble and verify frozen evidence without executing any experiment."""
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / 'ARTIFACTS.json').read_text())


def check(path, record):
    if path.stat().st_size != record['bytes']:
        raise ValueError('Size mismatch: ' + str(path))
    if hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('SHA256 mismatch: ' + str(path))


def verify_archive(record):
    path = ROOT / record['file']
    check(path, record)
    with tarfile.open(path, 'r:gz') as archive:
        rows = json.load(archive.extractfile(record['member_manifest']))
        expected = {row['path'] for row in rows} | {record['member_manifest']}
        if len(rows) != record['members'] or set(archive.getnames()) != expected:
            raise ValueError('Archive membership mismatch: ' + str(path))
        for row in rows:
            data = archive.extractfile(row['path']).read()
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Member integrity failure: ' + row['path'])
    return {'archive': record['file'], 'verified_members': len(rows), 'sha256': record['sha256']}


def assemble(record):
    for part in record.get('parts', []):
        check(ROOT / part['name'], part)
    assembled = ROOT / record['file']
    if not assembled.exists() and record.get('parts'):
        temporary = assembled.with_suffix(assembled.suffix + '.assembling')
        with temporary.open('xb') as output:
            for part in record['parts']:
                output.write((ROOT / part['name']).read_bytes())
        check(temporary, record)
        temporary.rename(assembled)


archives = [MANIFEST['runtime'], MANIFEST['audit']]
if 'ci_followup' in MANIFEST:
    archives.append(MANIFEST['ci_followup'])
for archive in archives:
    assemble(archive)
print(json.dumps([verify_archive(archive) for archive in archives], indent=2))
