"""Stdlib-only, fixed-version byte materializer. Does not execute capsule code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

# Import only this package's frozen, generated scalar layout, never capsule code.
sys.path.insert(0, str(Path(__file__).absolute().parent))
from capsule_spec import (CAPSULES, EXPECTED_FILES, EXPECTED_RECORDS,
                          MANIFEST_BYTES, MANIFEST_SHA256, STORAGE_BYTES,
                          STORAGE_FILES, CONTENT_PATH)

LIMIT = 511999
RECEIPT = 'MATERIALIZATION_RECEIPT.json'
PENDING = '.materialization-receipt.pending'
H = lambda value: hashlib.sha256(value).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('ascii')


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def parse(raw):
    return json.loads(raw, object_pairs_hook=unique_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def keys(value, expected, label):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError(label + ' schema')


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(label + ' integer bound')


def digest(value):
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('digest syntax')


def relative(value):
    if type(value) is not str or not value or '\\' in value or '\x00' in value:
        raise ValueError('unsafe relative path')
    if value.startswith('/') or any(x in ('', '.', '..') for x in value.split('/')):
        raise ValueError('unsafe relative path')
    if len(value) > 240:
        raise ValueError('relative path bound')
    return value


def checked_path(value, *, new=False):
    """No symlink in any existing ancestor; trusted, non-concurrent local parent."""
    raw = os.fspath(value)
    if not raw or '\x00' in raw or any(p == '..' for p in Path(raw).parts):
        raise ValueError('unsafe filesystem path')
    path = Path(os.path.abspath(raw))
    current = Path(path.anchor)
    for index, part in enumerate(path.parts[1:]):
        current /= part
        final = index == len(path.parts) - 2
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if new and final:
                return path
            raise
        if stat.S_ISLNK(mode):
            raise ValueError('filesystem symlink')
        if not final and not stat.S_ISDIR(mode):
            raise ValueError('unsafe filesystem ancestor')
        if final and new:
            raise FileExistsError(str(path))
    if new:
        raise FileExistsError(str(path))
    return path


def read_regular(path, size):
    path = checked_path(path)
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise ValueError('stored file size/type')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(size + 1)
        if len(raw) != size:
            raise ValueError('stored read size')
        return raw
    finally:
        os.close(fd)


def tree_paths(root):
    found = set()
    for folder, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(folder) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                raise ValueError('storage tree symlink')
            if name in files:
                if not stat.S_ISREG(mode):
                    raise ValueError('storage tree nonregular')
                found.add(str(path.relative_to(root)))
    return found


def verified(root):
    """Validate exact schema, layout, every stored object and reconstructed identity."""
    root = checked_path(root)
    if not root.is_dir():
        raise ValueError('package root type')
    manifest_path = checked_path(root / 'capsule-manifest.json')
    manifest_size = manifest_path.stat().st_size
    if not 0 < manifest_size <= MANIFEST_BYTES:
        raise ValueError('manifest byte bound')
    raw_manifest = read_regular(manifest_path, manifest_size)
    m = parse(raw_manifest)
    keys(m, ('schema', 'capsules', 'files', 'storage_files', 'storage_bytes'), 'manifest')
    if m['schema'] != 'joint-product-six-capsules-v1':
        raise ValueError('manifest version')
    integer(m['storage_files'], 1, STORAGE_FILES, 'storage count')
    integer(m['storage_bytes'], 1, STORAGE_BYTES, 'storage bytes')
    if m['storage_files'] != STORAGE_FILES or m['storage_bytes'] != STORAGE_BYTES:
        raise ValueError('storage totals')
    if type(m['capsules']) is not dict or set(m['capsules']) != set(CAPSULES):
        raise ValueError('capsule allowlist')
    for name, value in m['capsules'].items():
        keys(value, ('source_files', 'input_files', 'expanded_bytes', 'expanded_files'), 'capsule')
        for field in ('source_files', 'input_files'):
            if type(value[field]) is not list or not all(type(x) is str for x in value[field]):
                raise ValueError('capsule paths type')
            if len(set(value[field])) != len(value[field]):
                raise ValueError('duplicate capsule destination')
            for item in value[field]: relative(item)
        integer(value['expanded_bytes'], 1, 3000000, 'expanded bytes')
        integer(value['expanded_files'], 1, 64, 'expanded files')
        if value != CAPSULES[name]:
            raise ValueError('capsule fixed mapping')
    if type(m['files']) is not list or len(m['files']) != len(EXPECTED_FILES):
        raise ValueError('file count')
    seen = set()
    storage = set()
    result = {}
    sources = {}
    for entry in m['files']:
        keys(entry, ('path', 'bytes', 'sha256', 'storage'), 'file')
        path = relative(entry['path'])
        if path in seen:
            raise ValueError('duplicate destination')
        seen.add(path)
        if path not in EXPECTED_FILES:
            raise ValueError('unexpected destination')
        integer(entry['bytes'], 0, 1560407, 'file bytes')
        digest(entry['sha256'])
        if (entry['bytes'], entry['sha256']) != tuple(EXPECTED_FILES[path]):
            raise ValueError('original identity drift')
        st = entry['storage']
        if path == CONTENT_PATH:
            keys(st, ('kind', 'records'), 'records')
            if st['kind'] != 'raw-zip-records' or type(st['records']) is not list or len(st['records']) != 79:
                raise ValueError('record kind/count')
            offset = 0
            pieces = []
            for index, record in enumerate(st['records']):
                keys(record, ('index', 'offset', 'bytes', 'sha256'), 'record')
                integer(record['index'], 0, 78, 'record index')
                integer(record['offset'], 0, 1560407, 'record offset')
                integer(record['bytes'], 1, 401600, 'record bytes')
                digest(record['sha256'])
                if record['index'] != index or record['offset'] != offset:
                    raise ValueError('record order/coverage')
                if record != EXPECTED_RECORDS[index]:
                    raise ValueError('record identity drift')
                stored = 'objects/' + record['sha256'] + '.bin'
                storage.add(stored)
                pieces.append((stored, record['bytes'], record['sha256']))
                offset += record['bytes']
            if offset != entry['bytes'] or st['records'][-1]['bytes'] != 4960:
                raise ValueError('whole archive coverage')
            sources[path] = pieces
        else:
            keys(st, ('kind', 'path'), 'whole storage')
            if st['kind'] != 'whole-file' or st['path'] != 'files/' + path:
                raise ValueError('whole storage path')
            if entry['bytes'] > LIMIT:
                raise ValueError('blob size bound')
            sources[path] = [(st['path'], entry['bytes'], entry['sha256'])]
            storage.add(st['path'])
    if seen != set(EXPECTED_FILES):
        raise ValueError('exact destination set')
    if len(storage) != STORAGE_FILES:
        raise ValueError('unique storage count')
    if H(raw_manifest) != MANIFEST_SHA256:
        raise ValueError('immutable manifest identity')
    for folder in ('files', 'objects'):
        checked_path(root / folder)
        actual = {folder + '/' + p for p in tree_paths(root / folder)}
        if actual != {p for p in storage if p.startswith(folder + '/')}:
            raise ValueError('exact stored path set')
    for path, parts in sources.items():
        pieces = []
        for stored, size, pin in parts:
            value = read_regular(root / stored, size)
            if H(value) != pin:
                raise ValueError('stored content digest')
            pieces.append(value)
        value = b''.join(pieces)
        size, pin = EXPECTED_FILES[path]
        if len(value) != size or H(value) != pin:
            raise ValueError('original content digest')
        result[path] = value
    return result


def receipt_for(capsule):
    c = CAPSULES[capsule]
    paths = sorted(c['source_files'] + c['input_files'])
    return canonical({'schema': 'joint-capsule-materialization-v1',
                      'status': 'MATERIALIZED_BYTES_VERIFIED_NOT_QUALIFIED',
                      'capsule': capsule, 'manifest_sha256': MANIFEST_SHA256,
                      'files': {p: {'bytes': EXPECTED_FILES[p][0], 'sha256': EXPECTED_FILES[p][1]} for p in paths},
                      'runner_executed': False, 'shared_lock_created': False})


def _write_file(path, raw):
    with path.open('xb') as stream:
        if stream.write(raw) != len(raw):
            raise OSError('short output write')
        stream.flush()


def materialize(root, capsule, output):
    if type(capsule) is not str or capsule not in CAPSULES:
        raise ValueError('unknown capsule')
    output = checked_path(output, new=True)
    values = verified(root)  # All bytes retained; never reread unchecked package bytes.
    cfg = CAPSULES[capsule]
    paths = sorted(cfg['source_files'] + cfg['input_files'])
    if len(paths) != len(set(paths)) or any(p.startswith(capsule + '/RUN_ONCE/') for p in paths):
        raise ValueError('target output collision')
    if sum(len(values[p]) for p in paths) != cfg['expanded_bytes']:
        raise ValueError('expanded total')
    receipt = receipt_for(capsule)
    # Fresh root only. No atomic-directory or hostile-concurrency claim.
    output.mkdir(exist_ok=False)
    for path in paths:
        target = output / path
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_file(target, values[path])
    if tree_paths(output) != set(paths) or (output / capsule / 'RUN_ONCE').exists():
        raise ValueError('written path set')
    for path in paths:
        if read_regular(output / path, len(values[path])) != values[path]:
            raise ValueError('written byte identity')
    # Complete receipt is renamed into place last, after verification. A failed
    # pre-rename write leaves only an explicitly incomplete pending file.
    _write_file(output / PENDING, receipt)
    if read_regular(output / PENDING, len(receipt)) != receipt:
        raise ValueError('pending receipt identity')
    os.rename(output / PENDING, output / RECEIPT)
    return {'capsule': capsule, 'data_files': len(paths), 'data_bytes': cfg['expanded_bytes'],
            'receipt_bytes': len(receipt), 'status': 'MATERIALIZED_BYTES_VERIFIED_NOT_QUALIFIED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).absolute().parent)
    parser.add_argument('--capsule', choices=sorted(CAPSULES), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(materialize(args.root, args.capsule, args.output), sort_keys=True))


if __name__ == '__main__':
    main()
