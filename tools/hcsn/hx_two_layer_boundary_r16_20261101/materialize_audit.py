"""Restore the exact archived gzip bytes from bounded-size publication parts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(data):
    return hashlib.sha256(data).hexdigest()


def member(root, name):
    if not isinstance(name, str): raise ValueError('Part path must be text')
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(p in ('..', '.') for p in relative.parts):
        raise ValueError('Unsafe relative part path')
    path = (root/relative).resolve()
    if not path.is_relative_to(root): raise ValueError('Part escapes archive root')
    return path


def main(root, output):
    root = root.resolve(); output = output.resolve()
    manifest_path = root/'AUDIT_ARCHIVE.json'
    manifest_bytes = manifest_path.read_bytes(); manifest = json.loads(manifest_bytes)
    if manifest.get('schema') != 'hcsn.two-layer-audit-byte-parts.v1': raise ValueError('Wrong archive schema')
    parts = manifest['parts']
    if not parts or [p['index'] for p in parts] != list(range(len(parts))): raise ValueError('Wrong part order or count')
    paths = [member(root, p['path']) for p in parts]
    if len(paths) != len(set(paths)): raise ValueError('Duplicate part path')
    if output == manifest_path or output in paths or output.exists(): raise FileExistsError('Create-only output cannot replace an archive source')
    chunks = []
    for path, info in zip(paths, parts):
        raw = path.read_bytes()
        if type(info['bytes']) is not int or info['bytes'] <= 0 or len(raw) != info['bytes'] or sha(raw) != info['sha256']:
            raise ValueError('Part length or identity mismatch '+info['path'])
        chunks.append(raw)
    data = b''.join(chunks)
    if type(manifest['original_bytes']) is not int or len(data) != manifest['original_bytes'] or sha(data) != manifest['original_sha256']:
        raise ValueError('Reconstructed gzip length or identity mismatch')
    if manifest_path.read_bytes() != manifest_bytes: raise ValueError('Archive manifest changed while reading')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as target: target.write(data)
    print(json.dumps({'output': str(output), 'bytes': len(data), 'sha256': sha(data)}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--root', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); main(args.root, args.output)
