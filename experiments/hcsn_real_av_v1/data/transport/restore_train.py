"""Materialize the exact frozen training tensor from verified transport parts."""

import argparse
import hashlib
import json
from pathlib import Path
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def restore(destination=None):
    manifest_path = Path(__file__).with_name('TRAIN_MANIFEST.json')
    manifest = json.loads(manifest_path.read_bytes())
    root = Path(__file__).resolve().parents[4]
    target = Path(destination) if destination else root / manifest['logical_path']
    if target.exists():
        if target.stat().st_size == manifest['bytes'] and digest(target) == manifest['sha256']:
            return dict(status='already_exact', path=str(target), sha256=manifest['sha256'])
        raise FileExistsError('Destination exists with different bytes; no overwrite: ' + str(target))
    for part in manifest['parts']:
        path = root / part['path']
        if path.stat().st_size != part['bytes'] or digest(path) != part['sha256']:
            raise ValueError('Transport part identity mismatch: ' + str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name+'.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            for part in manifest['parts']:
                with (root / part['path']).open('rb') as source:
                    for block in iter(lambda: source.read(1 << 20), b''):
                        stream.write(block)
        if temporary.stat().st_size != manifest['bytes'] or digest(temporary) != manifest['sha256']:
            raise ValueError('Reconstructed file identity mismatch')
        if target.exists():
            raise FileExistsError('Destination appeared during reconstruction')
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return dict(status='restored_exact', path=str(target), bytes=manifest['bytes'], sha256=manifest['sha256'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(restore(args.destination), indent=2))
