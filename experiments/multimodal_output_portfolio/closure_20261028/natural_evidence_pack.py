"""Stream and verify immutable evidence parts without modifying any source file."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def sha(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def pack(plan_path, part):
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    if not 1 <= part <= len(plan['parts']):
        raise ValueError('Unknown immutable evidence part')
    prefix = plan['archive_prefix']
    if not prefix or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in prefix):
        raise ValueError('Invalid archive prefix')
    records = plan['parts'][part - 1]
    names = [record['archive_name'] for record in records]
    if len(set(names)) != len(names) or 'PART_MANIFEST.json' in names:
        raise ValueError('Repeated member names')
    for name in names:
        member = PurePosixPath(name)
        if member.is_absolute() or '..' in member.parts:
            raise ValueError('Archive members must be relative paths')
    path = plan_path.parent / f'{prefix}-part{part:02d}.tar.gz'
    receipt_path = path.with_suffix('.receipt.json')
    if path.exists() or receipt_path.exists():
        raise FileExistsError('Preserve any existing archive or verification receipt')
    plan_sha = hashlib.sha256(plan_bytes).hexdigest()
    manifest = json.dumps({'schema': plan['schema'], 'plan_sha256': plan_sha,
                           'part': part, 'files': records}, indent=2, sort_keys=True).encode()
    with path.open('xb') as destination:
        with tarfile.open(fileobj=destination, mode='w:gz', compresslevel=1) as archive:
            header = tarfile.TarInfo('PART_MANIFEST.json')
            header.size = len(manifest)
            archive.addfile(header, io.BytesIO(manifest))
            for record in records:
                source = Path(record['path'])
                if source.is_symlink() or not source.is_file():
                    raise ValueError('Archive only regular immutable files')
                if source.stat().st_size != record['bytes'] or sha(source) != record['sha256']:
                    raise ValueError('A frozen source changed before packing')
                archive.add(source, arcname=record['archive_name'], recursive=False)
    with tarfile.open(path, 'r:gz') as archive:
        if archive.getnames() != ['PART_MANIFEST.json'] + names:
            raise ValueError('Unexpected archive member set or order')
        if archive.extractfile('PART_MANIFEST.json').read() != manifest:
            raise ValueError('Internal manifest differs from the expected part')
        for record in records:
            hasher, count = hashlib.sha256(), 0
            with archive.extractfile(record['archive_name']) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(block)
                    count += len(block)
            if count != record['bytes'] or hasher.hexdigest() != record['sha256']:
                raise ValueError('Archived member differs from the frozen source manifest')
    result = {'schema': 'hepta.closure.verified-local-evidence-archive.v1', 'part': part,
              'archive_path': str(path), 'archive_bytes': path.stat().st_size,
              'archive_sha256': sha(path), 'member_files_verified': len(records),
              'plan_sha256': plan_sha, 'durable_save_confirmed': False,
              'raw_files_removed': False}
    with receipt_path.open('x') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--part', required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(pack(args.plan, args.part)))
