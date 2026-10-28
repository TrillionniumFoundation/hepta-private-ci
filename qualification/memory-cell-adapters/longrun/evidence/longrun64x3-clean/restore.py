"""Verify/restore the original CI tar bytes from bounded transport parts.

This helper is outside the frozen experiment runtime. It handles the original
GitHub tar's directory entries without rewriting or recompressing that tar.
"""

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import tarfile


class Parts(io.RawIOBase):
    def __init__(self, paths):
        super().__init__()
        self.paths, self.current = iter(paths), None

    def readable(self):
        return True

    def readinto(self, buffer):
        offset = 0
        while offset < len(buffer):
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    break
                self.current = path.open('rb')
            block = self.current.read(len(buffer) - offset)
            if block:
                buffer[offset:offset + len(block)] = block
                offset += len(block)
            else:
                self.current.close()
                self.current = None
        return offset

    def close(self):
        if self.current is not None:
            self.current.close()
        super().close()


def checked_file(root, entry):
    name = entry['file']
    path = root / name
    if Path(name).name != name or path.is_symlink() or not path.is_file():
        raise ValueError('transport members must be regular basenames')
    if path.stat().st_size > 400000:
        raise ValueError('transport member exceeds the publication bound')
    raw = path.read_bytes()
    if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('transport member integrity mismatch')
    return raw


def member_path(name, expected_root):
    path = PurePosixPath(name)
    if (not path.parts or path.is_absolute() or '..' in path.parts
            or '\\' in name or '\x00' in name or str(path) != name
            or path.parts[0] != expected_root):
        raise ValueError('unsafe or noncanonical archive name')
    return path


def verify(archive_path, destination=None):
    metadata = json.loads(archive_path.read_bytes())
    if metadata['schema'] != 'hepta.memory.adapter-ci-longrun-archive.v1':
        raise ValueError('unexpected transport schema')
    root, inventory = archive_path.parent, {}
    expected_root = metadata['archive_root']
    if Path(expected_root).name != expected_root:
        raise ValueError('one archive root basename is required')
    for chunk in metadata['inventory']:
        for line in checked_file(root, chunk).splitlines():
            item = json.loads(line)
            name = item['path']
            member_path(name, expected_root)
            if name in inventory or item['kind'] not in ('file', 'directory'):
                raise ValueError('duplicate or unsupported inventory entry')
            if item['bytes'] < 0 or (item['kind'] == 'directory' and item['bytes']):
                raise ValueError('invalid inventory size')
            inventory[name] = item
    raw_budget = sum(item['bytes'] for item in inventory.values())
    if len(inventory) > 10000 or raw_budget > 128 * 1024 * 1024:
        raise ValueError('restore inventory exceeds the declared safety budget')
    file_names = {PurePosixPath(name) for name, item in inventory.items() if item['kind'] == 'file'}
    if any(parent in file_names for item in inventory for parent in PurePosixPath(item).parents):
        raise ValueError('file inventory member is used as an ancestor')
    combined, total = hashlib.sha256(), 0
    part_names = [part['file'] for part in metadata['parts']]
    if len(set(part_names)) != len(part_names):
        raise ValueError('duplicate transport part')
    for part in metadata['parts']:
        raw = checked_file(root, part)
        combined.update(raw)
        total += len(raw)
    if combined.hexdigest() != metadata['archive_sha256'] or total != metadata['archive_bytes']:
        raise ValueError('combined original tar integrity mismatch')
    if destination is not None:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=False)
    seen, raw_bytes, files, directories = set(), 0, 0, 0
    with Parts([root / name for name in part_names]) as parts:
        with lzma.LZMAFile(parts, 'rb') as decompressed, tarfile.open(fileobj=decompressed, mode='r|') as archive:
            for member in archive:
                path = member_path(member.name.rstrip('/'), expected_root)
                name = str(path)
                if name not in inventory or name in seen:
                    raise ValueError('unexpected or duplicate tar member')
                expected = inventory[name]
                if member.size != expected['bytes'] or member.sparse is not None:
                    raise ValueError('unexpected size or sparse tar member')
                target = destination.joinpath(*path.parts) if destination is not None else None
                if expected['kind'] == 'directory':
                    if not member.isdir():
                        raise ValueError('expected a directory tar member')
                    if target is not None:
                        target.mkdir(parents=True, exist_ok=True)
                    directories += 1
                else:
                    if not member.isfile():
                        raise ValueError('links and special tar entries are refused')
                    stream, output = archive.extractfile(member), None
                    if target is not None:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if not target.resolve().is_relative_to(destination):
                            raise ValueError('restored path escapes destination')
                        output = target.open('xb')
                    count, hasher = 0, hashlib.sha256()
                    try:
                        while block := stream.read(65536):
                            count += len(block)
                            if count > expected['bytes']:
                                raise ValueError('tar member expansion exceeds its inventory')
                            hasher.update(block)
                            if output is not None:
                                output.write(block)
                    finally:
                        stream.close()
                        if output is not None:
                            output.close()
                    if count != expected['bytes'] or hasher.hexdigest() != expected['sha256']:
                        raise ValueError('restored member integrity mismatch')
                    raw_bytes += count
                    files += 1
                seen.add(name)
    if (seen != set(inventory) or len(seen) != metadata['member_count']
            or files != metadata['regular_file_count'] or directories != metadata['directory_count']
            or raw_bytes != metadata['raw_bytes']):
        raise ValueError('restored inventory incomplete')
    return {'verified': True, 'members': len(seen), 'regular_files': files,
            'directories': directories, 'raw_bytes': raw_bytes,
            'archive_sha256': combined.hexdigest(), 'archive_bytes': total,
            'extracted': destination is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parent / 'ARCHIVE.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if not args.verify_only and args.output is None:
        parser.error('--output or --verify-only is required')
    print(json.dumps(verify(args.archive, None if args.verify_only else args.output), sort_keys=True))
