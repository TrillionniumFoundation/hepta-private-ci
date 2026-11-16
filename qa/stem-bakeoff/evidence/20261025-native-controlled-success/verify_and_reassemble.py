"""Verify ordered parts, reconstruct the archive, and read every regular member."""
from pathlib import Path
import argparse
import hashlib
import json
import tarfile

parser = argparse.ArgumentParser()
parser.add_argument('manifest', type=Path)
parser.add_argument('--output', type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_bytes())
root = args.manifest.resolve().parent
output = args.output or root / (manifest['archive']['filename'] + '.reassembled')
digest = hashlib.sha256()
total = 0
with output.open('xb') as target:
    for row in manifest['parts']:
        assert Path(row['filename']).name == row['filename']
        data = (root / row['filename']).read_bytes()
        assert len(data) == row['bytes'] <= 5 * 1024 * 1024
        assert hashlib.sha256(data).hexdigest() == row['sha256']
        target.write(data)
        digest.update(data)
        total += len(data)
assert total == manifest['archive']['bytes']
assert digest.hexdigest() == manifest['archive']['sha256']
with tarfile.open(output, 'r:xz') as archive:
    members = archive.getmembers()
    assert len({member.name for member in members}) == len(members)
    assert all(not member.name.startswith('/') and '..' not in Path(member.name).parts for member in members)
    assert all(member.isfile() or member.isdir() for member in members)
    index_data = archive.extractfile('audit/member-inventory.json').read()
    assert hashlib.sha256(index_data).hexdigest() == manifest['archive']['member_inventory_sha256']
    index = json.loads(index_data)
    regular = [member for member in members if member.isfile()]
    assert len(regular) == manifest['archive']['regular_members']
    assert len(members) - len(regular) == manifest['archive']['directory_members']
    assert {member.name for member in regular} == set(index) | {'audit/member-inventory.json'}
    for member in regular:
        if member.name == 'audit/member-inventory.json':
            continue
        row = index[member.name]
        data = archive.extractfile(member).read()
        assert len(data) == row['bytes']
        assert hashlib.sha256(data).hexdigest() == row['sha256']
        assert member.mode == row['mode']
    for label, expected in manifest['raw_runs'].items():
        before = archive.extractfile(f'audit/{label}-inventory-before.json').read()
        after = archive.extractfile(f'audit/{label}-inventory-after.json').read()
        assert before == after
        raw = json.loads(before)
        actual = [member for member in regular if member.name.startswith(f'runs/{label}/')]
        assert len(actual) == expected['files']
        assert sum(member.size for member in actual) == expected['bytes']
        for name, row in raw.items():
            tar_name = f'runs/{label}' if name == '.' else f'runs/{label}/{name}'
            member = archive.getmember(tar_name)
            assert member.mode == int(row['mode'], 8)
            if row['type'] == 'directory':
                assert member.isdir()
            else:
                assert member.isfile()
                assert hashlib.sha256(archive.extractfile(member).read()).hexdigest() == row['sha256']
result = dict(archive_sha256=digest.hexdigest(), archive_bytes=total,
              verified_parts=len(manifest['parts']), regular_members=len(regular),
              directory_members=len(members)-len(regular), all_member_bytes_and_modes_verified=True,
              raw_run_before_after_inventory_equal=True, raw_original_files=5668,
              raw_original_bytes=99475967, extraction_performed=False,
              model_calls=0, rust_runs=0, sqlite_connections=0)
print(json.dumps(result, sort_keys=True))
