"""Verify or restore the bounded transport of complete longrun raw artifacts."""

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
            block = self.current.read(len(buffer)-offset)
            if block:
                buffer[offset:offset+len(block)] = block
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
    if Path(name).name != name:
        raise ValueError('transport filenames must be basenames')
    raw = (root/name).read_bytes()
    if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('transport part integrity mismatch')
    return raw


def verify(archive_path, destination=None):
    metadata = json.loads(archive_path.read_bytes())
    root, inventory = archive_path.parent, {}
    for chunk in metadata['inventory']:
        for line in checked_file(root, chunk).splitlines():
            item = json.loads(line)
            name = item['path']
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or name in inventory:
                raise ValueError('unsafe or duplicate member name')
            inventory[name] = item
    combined, total = hashlib.sha256(), 0
    for part in metadata['parts']:
        raw = checked_file(root, part)
        combined.update(raw)
        total += len(raw)
    if combined.hexdigest() != metadata['archive_sha256'] or total != metadata['archive_bytes']:
        raise ValueError('combined archive integrity mismatch')
    if destination is not None:
        destination = destination.resolve()
        destination.mkdir(parents=True, exist_ok=False)
    seen, raw_bytes = set(), 0
    with Parts([root/p['file'] for p in metadata['parts']]) as parts:
        with lzma.LZMAFile(parts, 'rb') as decompressed, tarfile.open(fileobj=decompressed, mode='r|') as archive:
            for member in archive:
                if not member.isfile() or member.name not in inventory or member.name in seen:
                    raise ValueError('unexpected archive member or link')
                expected = inventory[member.name]
                if member.size != expected['bytes']:
                    raise ValueError('member length mismatch')
                stream, output = archive.extractfile(member), None
                if destination is not None:
                    path = destination.joinpath(*PurePosixPath(member.name).parts)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    output = path.open('xb')
                count, hasher = 0, hashlib.sha256()
                try:
                    while block := stream.read(65536):
                        count += len(block)
                        hasher.update(block)
                        if output is not None:
                            output.write(block)
                finally:
                    stream.close()
                    if output is not None:
                        output.close()
                if count != expected['bytes'] or hasher.hexdigest() != expected['sha256']:
                    raise ValueError('restored member integrity mismatch')
                seen.add(member.name)
                raw_bytes += count
    if seen != set(inventory) or len(seen) != metadata['member_count'] or raw_bytes != metadata['raw_bytes']:
        raise ValueError('restored inventory incomplete')
    return {'verified': True, 'members': len(seen), 'raw_bytes': raw_bytes,
            'archive_sha256': combined.hexdigest(), 'extracted': destination is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, default=Path(__file__).resolve().parent/'ARCHIVE.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if not args.verify_only and args.output is None:
        parser.error('--output or --verify-only is required')
    print(json.dumps(verify(args.archive, None if args.verify_only else args.output), sort_keys=True))
