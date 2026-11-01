"""Merge restored evidence, accepting identical files and refusing conflicts."""

import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def merge(source, destination):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('Source and destination must be disjoint trees')
    files = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink source refused: '+str(path))
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        if not target.resolve().is_relative_to(destination):
            raise ValueError('Destination path escapes root')
        expected = digest(path)
        if target.exists() and (not target.is_file() or digest(target) != expected):
            raise FileExistsError('Different existing bytes: '+str(relative))
        files.append((path, target, expected))
    copied = existing = 0
    for path, target, expected in files:
        if target.exists():
            if digest(target) != expected:
                raise ValueError('Destination changed after preflight')
            existing += 1
            continue
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('Source changed after preflight')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        copied += 1
    return dict(files=len(files), copied=copied, existing_identical=existing,
                source=str(source), destination=str(destination))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(merge(args.source, args.destination), sort_keys=True))
