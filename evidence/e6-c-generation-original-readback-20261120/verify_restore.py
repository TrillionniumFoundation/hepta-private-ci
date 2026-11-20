#!/usr/bin/env python3
"""Verify/restore finite saved evidence; no network, host, source or test execution."""

import argparse
from collections import defaultdict
from hashlib import sha1, sha256
import io
import json
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent


def digest(data):
    data = bytes(data)
    return {'bytes': len(data), 'sha256': sha256(data).hexdigest(),
            'git_blob': sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def matches(data, expected):
    actual = digest(data)
    for key in ('bytes', 'sha256', 'git_blob'):
        if key in expected:
            assert actual[key] == expected[key], (key, actual[key], expected[key])
    return data


def safe(name):
    path = PurePosixPath(name)
    assert name and not path.is_absolute() and '..' not in path.parts
    assert '\\' not in name and '\0' not in name
    return name


def load_metadata(name):
    storage = json.loads((HERE / 'METADATA_STORAGE.json').read_text())
    rows = [row for row in storage['files'] if row['name'] == name]
    assert len(rows) == 1
    row = rows[0]
    if row['kind'] == 'whole':
        data = (HERE / safe(name)).read_bytes()
    else:
        index = json.loads((HERE / safe(row['index'])).read_text())
        result = bytearray()
        for part in index['parts']:
            assert part['offset'] == len(result)
            result.extend(matches((HERE / safe(part['path'])).read_bytes(), part))
        data = bytes(result)
        matches(data, index)
    return json.loads(matches(data, row))


def read_tar_members(data, expected):
    result = {}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r|xz') as tar:
        for member in tar:
            safe(member.name)
            assert member.name not in seen and member.isfile(), member.name
            seen.add(member.name)
            if member.name in expected:
                result[member.name] = matches(tar.extractfile(member).read(), expected[member.name])
    assert set(result) == set(expected)
    return result, seen


def main():
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--repository', type=Path,
                        help='Checkout containing all referenced existing535 evidence paths')
    source.add_argument('--repository-files-manifest', type=Path,
                        help='Original frozen535 manifest with exact local_path body sources; cloud review only')
    parser.add_argument('--output', type=Path, help='New empty directory; omit to verify without restoring')
    parser.add_argument('--receipt', type=Path, help='New JSON readback receipt; never replace an existing file')
    args = parser.parse_args()
    inputs = load_metadata('INPUT_MANIFEST.json')
    dependencies = load_metadata('DEPENDENCIES.json')
    freeze = load_metadata('FREEZE.json')
    assert inputs['source'] == '1a9799686243c2be0ee393ba364e091029cfb944'
    assert inputs['tree'] == '931a344b1ea3e2ddf45e917ea4b3ae37c504ed05'
    # Bind publication metadata back to the original pre-pack freeze.
    for row in freeze['files']:
        metadata = json.dumps(load_metadata(row['path']), ensure_ascii=False, indent=2).encode() + b'\n'
        matches(metadata, row)
    repository_rows = None
    if args.repository_files_manifest:
        original = args.repository_files_manifest.read_bytes()
        matches(original, inputs['existing_535'])
        rows = json.loads(original)
        assert len(rows) == 535 and len({row['path'] for row in rows}) == 535
        repository_rows = {row['path']: row for row in rows}

    def repository_file(row):
        safe(row['path'])
        if repository_rows is not None:
            original = repository_rows[row['path']]
            assert all(original[key] == row[key] for key in ('bytes', 'sha256', 'git_blob'))
            path = Path(original['local_path'])
        else:
            path = args.repository / row['path']
        assert path.is_file() and not path.is_symlink()
        return matches(path.read_bytes(), row)

    index = json.loads((HERE / 'archive-parts.json').read_text())
    archive = bytearray()
    for part in index['parts']:
        assert part['offset'] == len(archive)
        archive.extend(matches((HERE / safe(part['path'])).read_bytes(), part))
    matches(archive, index)
    member_index = load_metadata('ARCHIVE_MEMBERS.json')
    expected = {row['path']: row for row in member_index['members']}
    assert len(expected) == member_index['member_count']
    new_members, all_new = read_tar_members(bytes(archive), expected)
    assert all_new == set(expected)
    assert matches(bytes(archive), member_index['archive'])

    requested = defaultdict(dict)
    for row in inputs['files']:
        storage = row['storage']
        if storage['kind'] == 'existing_archive_member':
            requested[storage['archive_id']][storage['member']] = row
    existing_members = {}
    for description in dependencies['archives']:
        if description['id'] not in requested:
            continue
        parts = bytearray()
        for part in description['parts']:
            data = repository_file(part['repository_file'])
            matches(data, part)
            parts.extend(data)
        matches(parts, description)
        members, _ = read_tar_members(bytes(parts), requested[description['id']])
        existing_members[description['id']] = members
    assert set(existing_members) == set(requested)

    if args.output:
        assert not args.output.exists(), 'restore only to a new directory'
        args.output.mkdir(parents=True)
    restored = []
    logical_seen = set()
    for row in inputs['files']:
        logical = safe(row['workspace_path'])
        assert logical not in logical_seen
        logical_seen.add(logical)
        storage = row['storage']
        if storage['kind'] == 'new_archive_object':
            data = new_members[storage['member']]
        elif storage['kind'] == 'existing_repository_file':
            data = repository_file(storage['repository_file'])
        elif storage['kind'] == 'existing_archive_member':
            data = existing_members[storage['archive_id']][storage['member']]
        else:
            raise ValueError('unknown storage kind')
        matches(data, row)
        if args.output:
            target = args.output / logical
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(data)
            matches(target.read_bytes(), row)
        restored.append({'workspace_path': logical, **digest(data), 'storage_kind': storage['kind']})
    assert len(restored) == inputs['logical_saved_files']
    mapping = load_metadata('SOURCE_REUSE_MAP.json')
    rows_by_path = {row['workspace_path']: row for row in inputs['files']}
    missing = 0
    for row in mapping['files']:
        if row.get('body') is None and 'body_workspace_path' not in row:
            assert row['readback_status'] == 'PRESERVED_PRIOR_MISSING_OBSERVATION'
            missing += 1
        else:
            body = rows_by_path[row['body_workspace_path']]
            assert row['bytes'] == body['bytes'] and row['sha256'] == body['sha256']
            assert row['storage'] == body['storage']
    assert len(mapping['files']) == 256 and missing == 6
    receipt = {
        'status': 'ALL_FINITE_LOGICAL_INPUTS_VERIFIED' if not args.output else 'ALL_FINITE_LOGICAL_INPUTS_RESTORED_AND_VERIFIED',
        'source': inputs['source'], 'archive_sha256': index['sha256'],
        'archive_members': len(all_new), 'logical_files': len(restored),
        'finite_host_paths': 256, 'explicit_missing_paths': 6,
        'files': restored, 'output': str(args.output) if args.output else None,
        'host_network_native_model_or_test_actions': 0,
        'new_physical_or_runtime_qualification': False,
    }
    if args.receipt:
        assert not args.receipt.exists()
        with args.receipt.open('x') as stream:
            json.dump(receipt, stream, indent=2)
            stream.write('\n')
    print(json.dumps({key: value for key, value in receipt.items() if key != 'files'}))


if __name__ == '__main__':
    main()
