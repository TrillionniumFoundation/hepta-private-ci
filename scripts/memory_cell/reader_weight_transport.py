"""Verify frozen Reader model transport at the research-only job boundary.

A SHA256SUMS file is a transport receipt, not a model file or a source of
trust. Eight *model* files are checked against the registered model inventory
identity. An explicit read-only compatibility mode accepts the historical
2026-10-16 artifact whose checksum manifest inadvertently included itself,
but does not accept an extra model file, lost bytes or a changed model identity.

No authority, promotion, installation or source access is granted here.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REGISTERED_READER_IDENTITY = (
    "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
)
MODEL_FILES = frozenset({
    "config.json", "generation_config.json", "merges.txt", "model.safetensors",
    "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
})
MAX_MODEL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 4096
LINE = re.compile(r"([0-9a-f]{64})  \./([A-Za-z0-9_.-]+)")


def _digest_inventory(inventory):
    raw = json.dumps(inventory, sort_keys=True, ensure_ascii=False,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def verify_reader_transport(directory, *, allow_legacy_self_entry=False,
                            expected_identity=REGISTERED_READER_IDENTITY):
    """Reject undeclared model bytes before they are made visible to Reader.

    expected_identity is only for deterministic synthetic tests. Hosted calls
    MUST omit it, keeping the actual registered Reader identity immutable.
    Return an explicit receipt; caller removes SHA256SUMS *after* this check.
    """
    root = Path(directory)
    if not root.is_dir() or root.is_symlink():
        raise ValueError("regular isolated reader transport directory required")
    if type(allow_legacy_self_entry) is not bool or not re.fullmatch(
        r"[0-9a-f]{64}", expected_identity
    ):
        raise ValueError("invalid manifest compatibility policy or model identity")
    expected_names = MODEL_FILES | {"SHA256SUMS"}
    entries = list(root.iterdir())
    if {entry.name for entry in entries} != expected_names or len(entries) != len(expected_names):
        raise ValueError("unexpected or missing reader transport files")
    if any(entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ValueError("reader transport symlink or nonregular file")
    manifest_path = root / "SHA256SUMS"
    if not 0 < manifest_path.stat().st_size <= MAX_MANIFEST_BYTES:
        raise ValueError("empty or oversized reader manifest")
    try:
        lines = manifest_path.read_bytes().decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("reader manifest must be ASCII") from exc
    checksums = {}
    legacy = False
    for line in lines:
        match = LINE.fullmatch(line)
        if not match:
            raise ValueError("invalid reader transport manifest entry")
        recorded_sha, name = match.groups()
        if name == "SHA256SUMS":
            if legacy or not allow_legacy_self_entry:
                raise ValueError("unexpected or duplicate self-referential manifest entry")
            legacy = True
            continue
        if name not in MODEL_FILES or name in checksums:
            raise ValueError("unrecognized or duplicate reader manifest file")
        checksums[name] = recorded_sha
    if set(checksums) != MODEL_FILES:
        raise ValueError("reader transport manifest does not cover every model file")
    inventory = {}
    for name in sorted(MODEL_FILES):
        path = root / name
        size = path.stat().st_size
        if not 0 < size <= MAX_MODEL_BYTES:
            raise ValueError("empty or oversized frozen Reader file")
        hasher = hashlib.sha256()
        with path.open("rb") as reader:
            for block in iter(lambda: reader.read(1024 * 1024), b""):
                hasher.update(block)
        observed = hasher.hexdigest()
        if observed != checksums[name]:
            raise ValueError("reader model file differs from transport manifest")
        inventory[name] = {"sha256": observed, "bytes": size}
    identity = _digest_inventory(inventory)
    if identity != expected_identity:
        raise ValueError("frozen Reader model identity differs from registered snapshot")
    return {
        "schema": "hepta.reader-weight-transport.research.v1",
        "registered_identity": identity,
        "verified_files": len(MODEL_FILES),
        "verified_bytes": sum(item["bytes"] for item in inventory.values()),
        "legacy_self_entry_not_model_data": legacy,
        "original_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "production_accepted": False,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--legacy-self-entry", action="store_true")
    args = parser.parse_args()
    receipt = verify_reader_transport(args.directory,
        allow_legacy_self_entry=args.legacy_self_entry)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
