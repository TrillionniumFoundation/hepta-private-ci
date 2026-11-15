"""POSIX publication: readers see a verified complete file or no final name.

The caller owns a private output directory. This is crash consistency, not a
defence against an adversary who can replace that directory or rewrite files.
An exception after link/replace can leave a published file: inspect it, never
silently repeat the write. Process-kill tests do not simulate storage power loss.
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile


def canonical_json(value):
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def identity(path):
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_publish(path, writer, validate=None, *, replace=False):
    """Serialize and validate before exclusive publication in the same directory.

    ``replace`` is reserved for reconstructible convenience views/aliases.
    A hard kill may leave a uniquely named .tmp file; it is never a receipt.
    Validation and write errors propagate. Existing final files are never
    overwritten by the default exclusive publication, even by a concurrent writer.
    """
    if os.name != "posix":
        raise OSError("HCSN persistence v1 requires POSIX file and directory fsync")
    path = Path(path)
    if not replace and os.path.lexists(path):
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w+b") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        before = identity(temporary)
        if before["bytes"] == 0 and not replace:
            raise ValueError("refuse an empty published artifact")
        if validate is not None:
            validate(temporary)
        if identity(temporary) != before:
            raise ValueError("validator changed serialized bytes")
        if replace:
            os.replace(temporary, path)
        else:
            # link is an atomic no-clobber namespace operation. rename/replace
            # would silently overwrite an existing immutable checkpoint.
            os.link(temporary, path)
        sync_directory(path.parent)
        return before
    finally:
        temporary.unlink(missing_ok=True)


def publish_json(path, value):
    raw = canonical_json(value)

    def validate(temporary):
        if canonical_json(json.loads(temporary.read_bytes())) != raw:
            raise ValueError("JSON round trip differs")

    return atomic_publish(path, lambda stream: stream.write(raw), validate)
