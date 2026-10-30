"""Exact file transport in content-addressed parts below the repository blob limit."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile

PART_BYTES = 368640
MAX_BYTES = 512000
REPO = Path(__file__).resolve().parents[2]


def safe_relative(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or '\\' in name:
        raise ValueError('Unsafe relative path: ' + name)
    return p


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def git_blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def create(paths, output, root=REPO):
    root, output = Path(root).resolve(), Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError('Preserve the existing transport index')
    rows = []
    unique = {}
    for name in sorted(set(paths)):
        relative = safe_relative(name)
        path = root.joinpath(*relative.parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Symlink/escaping source')
        size = path.stat().st_size
        if size <= MAX_BYTES:
            raise ValueError('Only oversized logical files need transport: ' + name)
        whole, whole_git = hashlib.sha256(), hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
        parts = []
        with path.open('rb') as source:
            for block in iter(lambda: source.read(PART_BYTES), b''):
                whole.update(block)
                whole_git.update(block)
                encoded = base64.b64encode(block) + b'\n'
                sha = hashlib.sha256(encoded).hexdigest()
                part = Path('experiments/hcsn_sixstage_v1/transport_objects') / sha[:2] / (sha + '.b64')
                target = root / part
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if target.read_bytes() != encoded:
                        raise ValueError('Content-address collision')
                else:
                    with target.open('xb') as f:
                        f.write(encoded)
                item = {'path': part.as_posix(), 'bytes': len(encoded), 'sha256': sha, 'git_blob_sha': git_blob(encoded), 'encoding': 'base64', 'decoded_bytes': len(block), 'decoded_sha256': hashlib.sha256(block).hexdigest()}
                parts.append(item)
                unique[item['path']] = item
        rows.append({'path': name, 'bytes': size, 'sha256': whole.hexdigest(), 'git_blob_sha': whole_git.hexdigest(), 'parts': parts})
        if digest(path) != whole.hexdigest():
            raise ValueError('Source changed during transport construction')
    result = {'schema': 'hcsn-bounded-exact-transport.v2', 'maximum_git_blob_bytes': MAX_BYTES, 'decoded_part_bytes': PART_BYTES, 'encoding': 'base64 ASCII with one newline', 'logical_files': rows, 'logical_bytes': sum(r['bytes'] for r in rows), 'unique_part_bytes': sum(r['bytes'] for r in unique.values()), 'unique_parts': len(unique), 'reason': 'Preserve exact evidence bytes while obeying the existing 512000-byte repository blob limit; no allowlist change.'}
    text = json.dumps(result, indent=2) + '\n'
    if len(text.encode()) > MAX_BYTES:
        raise ValueError('Transport index needs separate smaller cohorts')
    with output.open('x') as f:
        f.write(text)
    return result


def restore(index, object_root=REPO, destination=REPO):
    index = Path(index)
    object_root, destination = Path(object_root).resolve(), Path(destination).resolve()
    registry = json.loads(index.read_text())
    if registry.get('schema') not in ('hcsn-bounded-exact-transport.v1', 'hcsn-bounded-exact-transport.v2'):
        raise ValueError('Unknown transport contract')
    restored = unchanged = 0
    seen = set()
    for row in registry['logical_files']:
        relative = safe_relative(row['path'])
        if row['path'] in seen:
            raise ValueError('Duplicate logical file')
        seen.add(row['path'])
        target = destination.joinpath(*relative.parts)
        if not target.resolve().is_relative_to(destination) or target.is_symlink():
            raise ValueError('Destination escapes through a symlink')
        exists = target.exists()
        if exists and (not target.is_file() or target.stat().st_size != row['bytes'] or digest(target) != row['sha256']):
            raise FileExistsError('Refuse differing existing logical file: ' + row['path'])
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='hcsn_verified_', dir=target.parent)
        whole, total = hashlib.sha256(), 0
        try:
            with os.fdopen(fd, 'wb') as output:
                for item in row['parts']:
                    rel = safe_relative(item['path'])
                    source = object_root.joinpath(*rel.parts)
                    if source.is_symlink() or not source.resolve().is_relative_to(object_root):
                        raise ValueError('Part escapes through a symlink')
                    block = source.read_bytes()
                    if len(block) != item['bytes'] or len(block) > MAX_BYTES or hashlib.sha256(block).hexdigest() != item['sha256'] or git_blob(block) != item['git_blob_sha']:
                        raise ValueError('Corrupt transport part: ' + item['path'])
                    if item.get('encoding') == 'base64':
                        block = base64.b64decode(block.strip(), validate=True)
                        if len(block) != item['decoded_bytes'] or hashlib.sha256(block).hexdigest() != item['decoded_sha256']:
                            raise ValueError('Decoded transport part mismatch')
                    whole.update(block)
                    total += len(block)
                    output.write(block)
            if total != row['bytes'] or whole.hexdigest() != row['sha256']:
                raise ValueError('Logical file reconstruction failed')
            if exists:
                unchanged += 1
            else:
                os.link(temporary, target)
                restored += 1
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {'schema': 'hcsn-bounded-transport-verification.v1', 'index_sha256': digest(index), 'restored': restored, 'already_identical': unchanged, 'files': len(seen), 'logical_bytes': registry['logical_bytes']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--paths', type=Path, required=True)
    make.add_argument('--output', type=Path, required=True)
    unpack = commands.add_parser('restore')
    unpack.add_argument('--index', type=Path, required=True)
    unpack.add_argument('--destination', type=Path, default=REPO)
    args = parser.parse_args()
    if args.command == 'create':
        result = create(json.loads(args.paths.read_text()), args.output)
        print(json.dumps({k: v for k, v in result.items() if k != 'logical_files'}))
    else:
        print(json.dumps(restore(args.index, destination=args.destination)))


if __name__ == '__main__':
    main()
