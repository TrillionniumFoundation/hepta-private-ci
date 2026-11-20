"""Lossless publication representations. No execution on import.

Every source stays intact locally. Oversized files and, recursively, their
descriptors are represented by exact byte slices; no JSON field is removed.
The publication file map is an external orchestration sidecar, not its own
member. This module does not publish Git objects or grant experiment status.
"""
from __future__ import annotations

import os
from pathlib import Path

from archive_common import ROOT, MAX_PART_BYTES, excluded_name, git_blob, json_bytes, metadata, safe_member, sha256


def put_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def read_publication_file(path: Path) -> bytes:
    """Read an exact local publication file; no generated-metadata size cap.

    Original-input size admission remains in archive_common.stable_read. This
    reader is used only for the named local publication representations, so a
    large generated manifest is split rather than rejected as an input body.
    """
    assert path.is_absolute() and path.is_relative_to(ROOT)
    assert excluded_name(path) is None
    before = metadata(path)
    assert before['regular'] and not before['symlink']
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        opened = os.fstat(fd)
        assert opened.st_ino == before['inode'] and opened.st_dev == before['device']
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read()
    finally:
        os.close(fd)
    assert metadata(path) == before and len(data) == before['bytes']
    return data


def identity(path: Path, repository_path: str, data: bytes) -> dict:
    assert safe_member(repository_path), repository_path
    return {
        'path': repository_path, 'local_path': str(path), 'bytes': len(data),
        'sha256': sha256(data), 'git_blob': git_blob(data), 'mode': '100644',
    }


class Publication:
    """Collect bounded files and verify literal restoration of every split."""

    def __init__(self, output: Path, repository_prefix: str):
        assert safe_member(repository_prefix)
        self.output = output
        self.prefix = repository_prefix
        self.files: dict[str, dict] = {}
        self.restorations: list[dict] = []

    def _admit(self, path: Path, repository_path: str, data: bytes) -> dict:
        assert repository_path.startswith(self.prefix + '/')
        assert len(data) <= MAX_PART_BYTES == 480000
        row = identity(path, repository_path, data)
        assert repository_path not in self.files, ('duplicate publication path', repository_path)
        self.files[repository_path] = row
        return row

    def stage(self, path: Path, repository_path: str) -> dict:
        data = read_publication_file(path)
        original = identity(path, repository_path, data)
        if len(data) <= MAX_PART_BYTES:
            return {'encoding': 'identity', 'file': self._admit(path, repository_path, data)}

        # Include the logical path in the name: equal bytes at different logical
        # locations remain two distinct, unambiguous publication representations.
        bundle = sha256(repository_path.encode()) + '-' + sha256(data)
        directory = self.output / 'metadata-parts' / bundle
        part_prefix = self.prefix + '/metadata-parts/' + bundle
        parts = []
        for ordinal, offset in enumerate(range(0, len(data), MAX_PART_BYTES)):
            chunk = data[offset:offset + MAX_PART_BYTES]
            name = f'part-{ordinal:05d}'
            local = directory / name
            put_new(local, chunk)
            row = self._admit(local, part_prefix + '/' + name, chunk)
            parts.append({
                'ordinal': ordinal, 'offset': offset,
                'file': row,
            })
        descriptor = {
            'schema': 'hepta.exact-byte-parts.v2',
            'original': {k: original[k] for k in ('path', 'bytes', 'sha256', 'git_blob', 'mode')},
            'max_part_bytes': MAX_PART_BYTES, 'parts': parts,
            'transformation': 'ordered original byte slices; no decoding or field removal',
        }
        descriptor_path = directory / 'REASSEMBLY.json'
        put_new(descriptor_path, json_bytes(descriptor))
        # A descriptor is metadata too. If large, apply the same rule instead
        # of weakening the limit or discarding rows.
        descriptor_representation = self.stage(descriptor_path, part_prefix + '/REASSEMBLY.json')
        representation = {
            'encoding': 'exact-byte-parts', 'original': original,
            'descriptor': descriptor_representation,
        }
        assert self.restore(representation) == data
        current = read_publication_file(path)
        assert current == data, ('original changed during splitting', str(path))
        self.restorations.append({
            'original': original, 'representation': representation,
            'byte_equal_to_original': True, 'removed_bytes_or_fields': 0,
        })
        return representation

    def _read_row(self, row: dict) -> bytes:
        assert self.files[row['path']] == row
        data = read_publication_file(Path(row['local_path']))
        assert len(data) == row['bytes'] <= MAX_PART_BYTES
        assert sha256(data) == row['sha256'] and git_blob(data) == row['git_blob']
        return data

    def restore(self, representation: dict) -> bytes:
        if representation['encoding'] == 'identity':
            return self._read_row(representation['file'])
        assert representation['encoding'] == 'exact-byte-parts'
        import json
        descriptor = json.loads(self.restore(representation['descriptor']))
        assert descriptor['schema'] == 'hepta.exact-byte-parts.v2'
        assert descriptor['max_part_bytes'] == MAX_PART_BYTES
        original = representation['original']
        assert descriptor['original'] == {
            k: original[k] for k in ('path', 'bytes', 'sha256', 'git_blob', 'mode')
        }
        chunks = []
        offset = 0
        paths = set()
        for ordinal, part in enumerate(descriptor['parts']):
            assert part['ordinal'] == ordinal and part['offset'] == offset
            claimed = part['file']
            assert safe_member(claimed['path']) and claimed['path'] not in paths
            paths.add(claimed['path'])
            row = self.files[claimed['path']]
            assert claimed == row
            chunk = self._read_row(row)
            assert 0 < len(chunk) <= MAX_PART_BYTES
            chunks.append(chunk)
            offset += len(chunk)
        rebuilt = b''.join(chunks)
        assert offset == len(rebuilt) == original['bytes']
        assert sha256(rebuilt) == original['sha256'] and git_blob(rebuilt) == original['git_blob']
        return rebuilt

    def verify_all(self) -> dict:
        for row in self.files.values():
            self._read_row(row)
        for check in self.restorations:
            data = read_publication_file(Path(check['original']['local_path']))
            assert self.restore(check['representation']) == data
        return {
            'scope': 'publication component bytes and exact metadata reconstruction only',
            'component_files_verified': len(self.files),
            'split_originals_verified': len(self.restorations),
            'all_component_files_at_most_bytes': MAX_PART_BYTES,
            'all_split_originals_byte_identical': True,
            'overall_result_not_claimed_by_this_component': True,
        }
