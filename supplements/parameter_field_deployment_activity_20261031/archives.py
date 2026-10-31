"""Stream and reconstruct bounded literal ZIP bytes without scientific decoding."""

import hashlib
import os
from pathlib import Path
import stat
import zipfile

from . import portable_common as c

LOCKS = {
    ".ops-controller.lock",
    ".ops-phase.lock",
    ".ops-write.lock",
    ".ops-slot-0.lock",
    ".ops-slot-1.lock",
}


def logical(value):
    path = c.relative(value)
    parts = path.parts
    if any(part.startswith(".") for part in parts):
        before = parts[:-1]
        c.need(
            parts[-1] in LOCKS
            and before in (("raw",), ("execution07", "raw"), ("payload", "raw")),
            "Undeclared hidden ZIP member",
        )
    return path


class Archive:
    def __init__(self, item, *, maximum_bytes=4 * c.GIB, maximum_files=100000):
        self.item, self.path = item, c.checked(item)
        self.before = c.fingerprint(self.path)
        self.zip = zipfile.ZipFile(self.path)
        try:
            info = self.zip.infolist()
            c.need(
                len(info) <= maximum_files
                and len({row.filename for row in info}) == len(info),
                "Duplicate or excessive ZIP member population",
            )
            self.files = {}
            for row in info:
                logical(row.filename.rstrip("/"))
                kind = stat.S_IFMT(row.external_attr >> 16)
                c.need(
                    kind in (0, stat.S_IFREG, stat.S_IFDIR) and not row.flag_bits & 1,
                    "Linked, special or encrypted ZIP member",
                )
                c.need(
                    kind != stat.S_IFDIR or row.is_dir(),
                    "A directory mode cannot conceal a file member",
                )
                if not row.is_dir():
                    self.files[row.filename] = row
            c.need(
                sum(row.file_size for row in self.files.values()) <= maximum_bytes,
                "Uncompressed ZIP bytes exceed the replay bound",
            )
        except BaseException:
            self.zip.close()
            raise
        self.verified = {}

    def member(self, name, expected=None, destination=None):
        c.need(name in self.files, "Required ZIP member is missing")
        row = self.files[name]
        if expected is not None:
            c.need(
                set(expected) >= {"bytes", "sha256"}
                and type(expected["bytes"]) is int
                and row.file_size == expected["bytes"],
                "ZIP member byte count differs",
            )
        target = None
        if destination is not None:
            destination = Path(destination)
            c.need(
                destination.is_absolute() and destination.resolve() == destination,
                "Noncanonical reconstruction destination",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            target = destination.open("xb")
        digest, count = hashlib.sha256(), 0
        try:
            with self.zip.open(name) as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    count += len(block)
                    c.need(
                        count <= row.file_size,
                        "ZIP member expanded beyond declared length",
                    )
                    digest.update(block)
                    if target is not None:
                        c.need(
                            target.write(block) == len(block),
                            "Partial reconstruction write",
                        )
            actual = {"bytes": count, "sha256": digest.hexdigest()}
            c.need(
                count == row.file_size
                and (
                    expected is None or actual == {key: expected[key] for key in actual}
                ),
                "ZIP member identity differs",
            )
            if target is not None:
                target.flush()
                os.fsync(target.fileno())
            self.verified[name] = actual
            return actual
        finally:
            if target is not None:
                target.close()

    def json(self, name, expected=None):
        actual = self.member(name, expected)
        c.need(actual["bytes"] <= 32 * 1024**2, "Archive metadata exceeds bound")
        raw = self.zip.read(name)
        c.need(
            hashlib.sha256(raw).hexdigest() == actual["sha256"],
            "Archive metadata changed",
        )
        return c.strict_json(raw)

    def stable(self):
        c.need(
            c.fingerprint(self.path) == self.before,
            "Downloaded archive changed during verification",
        )

    def close(self):
        try:
            self.stable()
        finally:
            self.zip.close()


def reconstruct(final_scientific, final_operations):
    """Preserve original absolute metadata paths; extract only into a fresh RUN."""
    c.need(not c.RUN.exists(), "Portable replay requires a fresh canonical run root")
    c.RUN.mkdir(parents=True, exist_ok=False)
    coverage = {}
    for artifact, role in (
        (final_scientific, "scientific"),
        (final_operations, "operations"),
    ):
        archive = Archive(artifact, maximum_bytes=4 * c.GIB)
        try:
            total = sum(row.file_size for row in archive.files.values())
            space = os.statvfs(c.RUN)
            c.need(
                space.f_bavail * space.f_frsize >= total + 256 * 1024**2,
                "Insufficient reconstruction disk reserve",
            )
            for name in sorted(archive.files):
                path = logical(name)
                if role == "scientific":
                    c.need(
                        path.parts[0] in ("raw", "raw_cas"),
                        "Scientific delivery has unrelated paths",
                    )
                    target = c.RUN / str(path)
                else:
                    c.need(
                        path.parts[0]
                        in ("execution07", "preparation", "qualification"),
                        "Operational delivery has unrelated paths",
                    )
                    if path.parts[0] != "execution07":
                        archive.member(name)
                        continue
                    relative = Path(*path.parts[1:])
                    c.need(
                        relative.parts and relative.parts[0] not in ("raw", "raw_cas"),
                        "Operational delivery cannot replace scientific RAW",
                    )
                    target = c.RUN / relative
                c.need(
                    str(target) not in coverage,
                    "Delivery overlaps another reconstructed member",
                )
                actual = archive.member(name, destination=target)
                coverage[str(target)] = {"artifact": artifact, "member": name, **actual}
        finally:
            archive.close()
    for name in ("raw", "raw_cas"):
        (c.RUN / name).mkdir(exist_ok=True)
    return coverage
