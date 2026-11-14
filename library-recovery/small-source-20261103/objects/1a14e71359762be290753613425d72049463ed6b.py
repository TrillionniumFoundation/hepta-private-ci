"""Closed-world, digest-pinned offline Encoder snapshot qualification.

This is a **shadow-only integrity preflight**. It cannot authenticate the model
publisher, authorize data reuse, perform signed final-use, or guarantee an
atomic filesystem snapshot against a privileged concurrent writer. The caller
must pin the independently reviewed manifest digest outside the checkpoint.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

SCHEMA = 'hepta.neuron.encoder-snapshot.v1'
KINDS = ('laya-joint', 'modernbert-joint')
MAX_FILES = 2048
MAX_DIRECTORIES = 4096
MAX_FILE_BYTES = 16 * 1024 ** 3
MAX_TOTAL_BYTES = 32 * 1024 ** 3
SHA256_PATTERN = re.compile(r'^[0-9a-f]{64}$')
REVISION_PATTERN = re.compile(r'^[0-9a-f]{40}$')
REQUIRED = {
    'laya-joint': frozenset({'rl_agent_config.json', 'model.safetensors',
                             'tokenizer/tokenizer.json'}),
    'modernbert-joint': frozenset({'config.json', 'model.safetensors'}),
}


class CheckpointIntegrityError(ValueError):
    """Checkpoint identity, inventory or byte contents cannot be admitted."""


def _parse_unique_json(raw: bytes) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value = {}
        for name, item in pairs:
            if name in value:
                raise CheckpointIntegrityError(f'duplicate JSON key: {name}')
            value[name] = item
        return value
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise CheckpointIntegrityError('manifest is not valid UTF-8 JSON') from e
    if type(value) is not dict:
        raise CheckpointIntegrityError('manifest must be a JSON object')
    return value


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hex_digest(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_PATTERN.fullmatch(value) is None:
        raise CheckpointIntegrityError(f'{label}: expected lowercase SHA-256')
    return value


def _path(value: Any) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise CheckpointIntegrityError('invalid manifest relative path')
    path = PurePosixPath(value)
    if (path.is_absolute() or str(path) != value or
            any(segment in ('.', '..', '') for segment in value.split('/')) or
            '\\' in value or ':' in value or '\0' in value):
        raise CheckpointIntegrityError(f'unsafe or noncanonical manifest path: {value}')
    return value


def _no_symlink_parents(path: Path) -> None:
    if any(component.is_symlink() for component in (path, *path.parents)):
        raise CheckpointIntegrityError('checkpoint or manifest parent symlink denied')


def _root(directory: str | Path) -> Path:
    root = Path(directory).absolute()
    _no_symlink_parents(root)
    if not root.is_dir():
        raise CheckpointIntegrityError('checkpoint root must be a physical directory')
    return root


def _walk_files(root: Path) -> dict[str, Path]:
    """Enumerate without following directory or file symlinks/hardlinks."""
    files: dict[str, Path] = {}
    stack = [root]
    seen_directories = 0
    while stack:
        seen_directories += 1
        if seen_directories > MAX_DIRECTORIES:
            raise CheckpointIntegrityError('snapshot exceeds directory count limit')
        current = stack.pop()
        with os.scandir(current) as scan:
            entries = sorted(scan, key=lambda entry: entry.name)
        for entry in entries:
            # lstat and non-following tests reject both symlink files and dirs.
            metadata = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                stack.append(Path(entry.path))
            elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                relative = Path(entry.path).relative_to(root).as_posix()
                _path(relative)
                if len(files) >= MAX_FILES:
                    raise CheckpointIntegrityError('snapshot exceeds file count limit')
                files[relative] = Path(entry.path)
            else:
                raise CheckpointIntegrityError('checkpoint symlinks, hardlinks and special files denied')
    return files


def _digest_file(path: Path, declared_size: int | None = None) -> tuple[str, int]:
    # Explicit per-file size, checked before reading; detect in-place changes.
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise CheckpointIntegrityError('unsafe file type or hardlink')
    if before.st_size > MAX_FILE_BYTES or (declared_size is not None and before.st_size != declared_size):
        raise CheckpointIntegrityError('checkpoint file byte size mismatch or limit exceeded')
    hasher = hashlib.sha256()
    try:
        with path.open('rb') as stream:
            loaded = stream.fileno()
            opened = os.fstat(loaded)
            if (before.st_ino, before.st_dev, before.st_size) != (
                    opened.st_ino, opened.st_dev, opened.st_size):
                raise CheckpointIntegrityError('checkpoint file changed at open')
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(chunk)
            after_open = os.fstat(loaded)
    except OSError as e:
        raise CheckpointIntegrityError('checkpoint file unreadable') from e
    after = path.stat(follow_symlinks=False)
    stat_before = (before.st_ino, before.st_dev, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    for candidate in [after_open, after]:
        if stat_before != (candidate.st_ino, candidate.st_dev, candidate.st_size,
                           candidate.st_mtime_ns, candidate.st_ctime_ns):
            raise CheckpointIntegrityError('checkpoint file changed while hashing')
    return hasher.hexdigest(), before.st_size


def _requirements(kind: str, paths: set[str]) -> None:
    if kind not in KINDS:
        raise CheckpointIntegrityError('unsupported Encoder kind')
    missing = REQUIRED[kind] - paths
    if missing:
        raise CheckpointIntegrityError(f'missing required model files: {sorted(missing)}')
    if kind == 'modernbert-joint' and not (
        {'tokenizer.json', 'tokenizer/tokenizer.json'} & paths
    ):
        raise CheckpointIntegrityError('ModernBERT tokenizer.json absent')


def generate_inventory(checkpoint_dir: str | Path, kind: str, source_revision: str) -> dict[str, Any]:
    """Inventory bytes for review, NOT an independent signing/approval action."""
    if (kind not in KINDS or type(source_revision) is not str
            or REVISION_PATTERN.fullmatch(source_revision) is None):
        raise CheckpointIntegrityError('model kind and exact source revision are required')
    root = _root(checkpoint_dir)
    files = _walk_files(root)
    _requirements(kind, set(files))
    entries = []
    total = 0
    for name in sorted(files):
        digest, size = _digest_file(files[name])
        total += size
        if total > MAX_TOTAL_BYTES:
            raise CheckpointIntegrityError('snapshot exceeds total size limit')
        entries.append({'path': name, 'sha256': digest, 'bytes': size})
    return {'schema': SCHEMA, 'kind': kind, 'source_revision': source_revision, 'files': entries}


@dataclass(frozen=True)
class VerifiedCheckpoint:
    checkpoint_dir: Path
    kind: str
    source_revision: str
    manifest_sha256: str
    weight_sha256: str
    _inventory: tuple[tuple[str, str, int], ...]

    def verify_unchanged(self) -> None:
        root = _root(self.checkpoint_dir)
        actual = _walk_files(root)
        expected = {name for name, _, _ in self._inventory}
        if set(actual) != expected:
            raise CheckpointIntegrityError('checkpoint inventory drift (added/removed files)')
        total = 0
        for name, digest, size in self._inventory:
            actual_digest, actual_size = _digest_file(actual[name], size)
            total += actual_size
            if total > MAX_TOTAL_BYTES or actual_digest != digest:
                raise CheckpointIntegrityError(f'checkpoint digest mismatch: {name}')


def verify_checkpoint(
    checkpoint_dir: str | Path, kind: str,
    manifest_path: str | Path, expected_manifest_sha256: str,
    expected_weights_sha256: str,
) -> VerifiedCheckpoint:
    root = _root(checkpoint_dir)
    _hex_digest(expected_manifest_sha256, 'manifest digest')
    _hex_digest(expected_weights_sha256, 'model weights digest')
    manifest_path = Path(manifest_path).absolute()
    _no_symlink_parents(manifest_path)
    if manifest_path.is_relative_to(root):
        raise CheckpointIntegrityError('manifest must reside outside the model snapshot')
    try:
        manifest_stat = manifest_path.stat(follow_symlinks=False)
    except OSError as e:
        raise CheckpointIntegrityError('manifest unavailable') from e
    if (not stat.S_ISREG(manifest_stat.st_mode) or manifest_stat.st_nlink != 1
            or manifest_stat.st_size > 1024 * 1024):
        raise CheckpointIntegrityError('manifest file type or size invalid')
    manifest_digest, _ = _digest_file(manifest_path, manifest_stat.st_size)
    if manifest_digest != expected_manifest_sha256:
        raise CheckpointIntegrityError('checkpoint manifest SHA-256 mismatch')
    raw = manifest_path.read_bytes()
    if len(raw) != manifest_stat.st_size or _sha_bytes(raw) != expected_manifest_sha256:
        raise CheckpointIntegrityError('checkpoint manifest SHA-256 mismatch')
    body = _parse_unique_json(raw)
    if set(body) != {'schema', 'kind', 'source_revision', 'files'}:
        raise CheckpointIntegrityError('unsupported manifest fields')
    if body['schema'] != SCHEMA or body['kind'] != kind:
        raise CheckpointIntegrityError('manifest schema/model kind mismatch')
    if (type(body['source_revision']) is not str or
            REVISION_PATTERN.fullmatch(body['source_revision']) is None):
        raise CheckpointIntegrityError('source revision must be a pinned 40-hex commit')
    inventory = body['files']
    if type(inventory) is not list or not (1 <= len(inventory) <= MAX_FILES):
        raise CheckpointIntegrityError('manifest file list empty or oversized')
    entries = []
    for item in inventory:
        if type(item) is not dict or set(item) != {'path', 'sha256', 'bytes'}:
            raise CheckpointIntegrityError('invalid manifest inventory entry')
        name = _path(item['path'])
        digest = _hex_digest(item['sha256'], f'{name} digest')
        size = item['bytes']
        if type(size) is not int or not (0 <= size <= MAX_FILE_BYTES):
            raise CheckpointIntegrityError('invalid declared file length')
        entries.append((name, digest, size))
    if [name for name, _, _ in entries] != sorted(set(name for name, _, _ in entries)):
        raise CheckpointIntegrityError('manifest filenames must be unique and sorted')
    _requirements(kind, {name for name, _, _ in entries})
    weights = dict((name, digest) for name, digest, _ in entries)['model.safetensors']
    if weights != expected_weights_sha256:
        raise CheckpointIntegrityError('weight digest not bound to checkpoint manifest')
    result = VerifiedCheckpoint(root, kind, body['source_revision'], expected_manifest_sha256,
                                weights, tuple(entries))
    result.verify_unchanged()
    return result


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['inventory', 'verify'])
    p.add_argument('--checkpoint-dir', required=True)
    p.add_argument('--kind', required=True, choices=KINDS)
    p.add_argument('--manifest', required=True)
    p.add_argument('--source-revision', default='')
    p.add_argument('--manifest-sha256', default='')
    p.add_argument('--weights-sha256', default='')
    args = p.parse_args()
    if args.command == 'inventory':
        body = generate_inventory(args.checkpoint_dir, args.kind, args.source_revision)
        output = Path(args.manifest)
        if output.absolute().is_relative_to(_root(args.checkpoint_dir)):
            raise CheckpointIntegrityError('manifest output must be outside checkpoint')
        data = (json.dumps(body, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        with output.open('xb') as stream:
            stream.write(data)
        print(json.dumps({'manifest_sha256': _sha_bytes(data), 'weights_sha256': next(
            item['sha256'] for item in body['files'] if item['path'] == 'model.safetensors'),
            'files': len(body['files']), 'status': 'UNSIGNED_INVENTORY_ONLY'}))
    else:
        proof = verify_checkpoint(args.checkpoint_dir, args.kind, args.manifest,
                                  args.manifest_sha256, args.weights_sha256)
        print(json.dumps({'manifest_sha256': proof.manifest_sha256,
                          'model_kind': proof.kind, 'status': 'SHADOW_INTEGRITY_ONLY'}))


if __name__ == '__main__':
    main()
