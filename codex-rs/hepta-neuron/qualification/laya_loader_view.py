"""Isolate Laya's tokenizer compatibility rewrite from an immutable snapshot.

This is a byte-integrity boundary, not an OS sandbox or upstream attestation.
The caller verifies the source against upstream before constructing this view.
Only the explicitly versioned tokenizer normalization below is permitted.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path

MAX_FILES = 256
MAX_TOTAL_BYTES = 4 * 1024**3
TOKENIZER_CONFIG = "tokenizer/tokenizer_config.json"


def _json(data: bytes) -> dict:
    def unique(pairs):
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("duplicate tokenizer field")
        return result
    def reject(value):
        raise ValueError("non-finite tokenizer value: " + value)
    value = json.loads(data, object_pairs_hook=unique, parse_constant=reject)
    if not isinstance(value, dict):
        raise ValueError("tokenizer configuration is not an object")
    return value


def _inventory(root: Path) -> list[dict]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("snapshot root must be a real directory")
    result = []
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if ".cache" in relative.parts:
            continue
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("snapshot contains a link or non-regular entry")
        if len(result) >= MAX_FILES or info.st_size > MAX_TOTAL_BYTES - total:
            raise ValueError("snapshot capacity exceeded")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        digest = hashlib.sha256()
        consumed = 0
        with os.fdopen(os.open(path, flags), "rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                raise ValueError("snapshot changed before open")
            while chunk := stream.read(1024 * 1024):
                consumed += len(chunk)
                if consumed > info.st_size:
                    raise ValueError("snapshot grew during read")
                digest.update(chunk)
            after = os.fstat(stream.fileno())
        if consumed != info.st_size or after.st_mtime_ns != opened.st_mtime_ns:
            raise ValueError("snapshot changed during read")
        result.append({"path": str(relative), "bytes": consumed, "sha256": digest.hexdigest()})
        total += consumed
    if not result:
        raise ValueError("snapshot is empty")
    return result


def _digest(files: list[dict]) -> str:
    raw = (json.dumps(files, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()


class LayaLoaderView:
    """Own a private regular-file copy and report source/effective identities."""

    def __init__(self, source: Path, *, expected_snapshot_digest: str):
        self.source = Path(source)
        self.source_files = _inventory(self.source)
        if _digest(self.source_files) != expected_snapshot_digest:
            raise ValueError("snapshot differs from the admitted upstream inventory")
        self._temporary = tempfile.TemporaryDirectory(prefix="hepta-laya-loader-")
        self.path = Path(self._temporary.name)
        try:
            for row in self.source_files:
                destination = self.path / row["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Never use hardlinks/symlinks: upstream Agent rewrites this file.
                shutil.copyfile(self.source / row["path"], destination)
            if _inventory(self.path) != self.source_files:
                raise ValueError("snapshot changed during private copy")
            config_path = self.path / TOKENIZER_CONFIG
            before = config_path.read_bytes()
            if len(before) > 1024 * 1024:
                raise ValueError("tokenizer configuration exceeds capacity")
            config = _json(before)
            changed = False
            if config.get("tokenizer_class") in (None, "TokenizersBackend"):
                config["tokenizer_class"] = "PreTrainedTokenizerFast"
                config.pop("backend", None)
                config.pop("is_local", None)
                changed = True
            extra = config.get("extra_special_tokens")
            if isinstance(extra, list):
                if any(not isinstance(token, str) for token in extra):
                    raise ValueError("invalid extra special token")
                config["extra_special_tokens"] = {f"extra_{i}": token for i, token in enumerate(extra)}
                changed = True
            if changed:
                config_path.write_text(json.dumps(config, indent=2, allow_nan=False))
            self.effective_files = _inventory(self.path)
            original = {row["path"]: row for row in self.source_files}
            changes = [row["path"] for row in self.effective_files if row != original[row["path"]]]
            if set(changes) - {TOKENIZER_CONFIG}:
                raise ValueError("unregistered loader transformation")
            self.identity = {
                "schema": "hepta.laya-loader-view.v1",
                "transform": "laya-tokenizer-compatibility-v1",
                "source_snapshot_digest": _digest(self.source_files),
                "effective_snapshot_digest": _digest(self.effective_files),
                "changed_paths": changes,
                "tokenizer_before_sha256": hashlib.sha256(before).hexdigest(),
                "tokenizer_after_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
                "loader_adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "upstream_attestation": False,
            }
            for row in self.effective_files:
                (self.path / row["path"]).chmod(0o400)
            self.verify()
        except BaseException:
            self._temporary.cleanup()
            raise

    def verify(self) -> None:
        if _inventory(self.source) != self.source_files:
            raise ValueError("original snapshot changed during loader use")
        if _inventory(self.path) != self.effective_files:
            raise ValueError("effective loader inputs changed after preparation")

    def close(self) -> None:
        self._temporary.cleanup()
