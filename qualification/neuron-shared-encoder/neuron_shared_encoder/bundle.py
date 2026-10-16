"""Closed-world, offline checkpoint identity for shadow-only model experiments.

The SHA-256 protects the entire staged local bundle, not merely tensor weights.
This is provenance, not a signature or permission to execute models.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

MAX_BUNDLE_FILES = 1024
MAX_BUNDLE_BYTES = 16 * 1024 * 1024 * 1024
_KINDS = {
    'laya-joint': frozenset({
        'model.safetensors', 'rl_agent_config.json',
        'encoder/config.json', 'tokenizer/tokenizer.json',
    }),
    'modernbert-joint': frozenset({
        'model.safetensors', 'config.json', 'tokenizer.json',
    }),
}


def checkpoint_bundle_sha256(root: str | Path, kind: str) -> str:
    """Digest every regular byte under a staged, symlink-free model directory.

    All files are included, sorted by relative POSIX path with length prefixes.
    Symlinks are refused so Hugging Face cache snapshots must be materialized
    into a private, read-only tree before qualification. File size is checked
    before and after hashing; higher-level owner must still protect against
    concurrent replacement between verification and use.
    """
    if kind not in _KINDS:
        raise ValueError('unsupported real checkpoint kind')
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('checkpoint root must be a real local directory')
    files = []
    total_bytes = 0
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ValueError('checkpoint symlinks are not qualified; materialize files')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('non-regular checkpoint artifact')
        relative = path.relative_to(root).as_posix()
        if not relative or len(relative.encode('utf-8')) > 1024:
            raise ValueError('invalid checkpoint member name')
        files.append((relative, path))
        if len(files) > MAX_BUNDLE_FILES:
            raise ValueError('checkpoint file count exceeds bound')
        size = path.stat().st_size
        if size < 0 or size > MAX_BUNDLE_BYTES - total_bytes:
            raise ValueError('checkpoint size exceeds bound')
        total_bytes += size
    found = {name for name, _ in files}
    if not _KINDS[kind].issubset(found):
        missing = ', '.join(sorted(_KINDS[kind] - found))
        raise ValueError(f'checkpoint missing required offline assets: {missing}')
    digest = hashlib.sha256()
    digest.update(b'hepta.neuron.checkpoint-bundle.v1\0')
    kind_bytes = kind.encode('ascii')
    digest.update(len(kind_bytes).to_bytes(4, 'big'))
    digest.update(kind_bytes)
    digest.update(len(files).to_bytes(4, 'big'))
    for name, path in sorted(files):
        name_bytes = name.encode('utf-8')
        stat_before = path.stat()
        subhash = hashlib.sha256()
        read_bytes = 0
        with path.open('rb') as reader:
            for chunk in iter(lambda: reader.read(1 << 20), b''):
                read_bytes += len(chunk)
                subhash.update(chunk)
        stat_after = path.stat()
        if (read_bytes != stat_before.st_size or
                stat_after.st_size != stat_before.st_size or
                stat_after.st_mtime_ns != stat_before.st_mtime_ns):
            raise ValueError(f'checkpoint mutated during read: {name}')
        digest.update(len(name_bytes).to_bytes(4, 'big'))
        digest.update(name_bytes)
        digest.update(read_bytes.to_bytes(8, 'big'))
        digest.update(subhash.digest())
    return digest.hexdigest()


def verify_checkpoint_bundle(root: str | Path, kind: str, expected_sha256: str) -> str:
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(
        c not in '0123456789abcdef' for c in expected_sha256
    ):
        raise ValueError('real model requires canonical checkpoint bundle SHA-256')
    actual = checkpoint_bundle_sha256(root, kind)
    if actual != expected_sha256:
        raise ValueError('checkpoint bundle SHA-256 mismatch')
    return actual
