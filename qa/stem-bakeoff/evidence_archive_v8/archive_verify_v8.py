"""Independent bounded reader for the exact deterministic evidence tar/gzip stream."""

import hashlib
import os
from pathlib import Path
import tarfile
import zlib

from archive_plan_v8 import BLOCK, checked_open, digest, fingerprint, pin, require, validate_plan


class SingleGzipReader:
    """Reject truncation, extra gzip members and all uncommitted trailing bytes."""

    def __init__(self, raw):
        self.raw, self.pending = raw, raw.read(10)
        require(self.pending == b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff",
                "deterministic level-six gzip header, no filename and mtime zero required")
        self.hasher = hashlib.sha256(self.pending)
        self.compressed_bytes = len(self.pending)
        self.decoder = zlib.decompressobj(31)
        self.finished = False

    def read(self, size):
        require(0 < size <= BLOCK, "bounded decompression requests required")
        out = bytearray()
        while len(out) < size and not self.finished:
            if self.decoder.eof:
                require(not self.decoder.unused_data and not self.pending and self.raw.read(1) == b"",
                        "extra gzip member or trailing compressed bytes")
                self.finished = True
                break
            data, self.pending = self.pending, b""
            if not data:
                data = self.raw.read(BLOCK)
                require(data, "truncated gzip stream")
                self.hasher.update(data)
                self.compressed_bytes += len(data)
            try:
                out.extend(self.decoder.decompress(data, size - len(out)))
            except zlib.error as error:
                raise ValueError("invalid gzip checksum or compressed stream") from error
            self.pending = self.decoder.unconsumed_tail
        return bytes(out)


def exact(reader, expected):
    for start in range(0, len(expected), BLOCK):
        chunk = expected[start:start + BLOCK]
        require(reader.read(len(chunk)) == chunk, "tar metadata, manifest or padding differs")


def expected_header(name, size, mode, target=None):
    info = tarfile.TarInfo(name)
    info.uid = info.gid = info.mtime = 0
    info.uname = info.gname = ""
    info.mode = mode
    if target is None:
        info.type, info.size = tarfile.REGTYPE, size
    else:
        info.type, info.size, info.linkname = tarfile.LNKTYPE, 0, target
    return info.tobuf(tarfile.PAX_FORMAT, "utf-8", "strict")


def verify_archive(archive, manifest, manifest_sha256, archive_sha256=None):
    plan, manifest_bytes = validate_plan(manifest, manifest_sha256)
    raw, before = checked_open(Path(archive))
    with raw:
        reader = SingleGzipReader(raw)
        first = expected_header("MANIFEST.json", len(manifest_bytes), 0o644)
        exact(reader, first)
        exact(reader, manifest_bytes)
        padding = (-len(manifest_bytes)) % 512
        exact(reader, b"\0" * padding)
        position = len(first) + len(manifest_bytes) + padding
        verified, stored_bytes = {}, 0
        for row in plan["members"]:
            target = row["link_to"]
            header = expected_header(row["member"], row["bytes"], row["archive_mode"], target)
            exact(reader, header)
            position += len(header)
            if target is None:
                hasher, remaining = hashlib.sha256(), row["bytes"]
                while remaining:
                    chunk = reader.read(min(remaining, BLOCK))
                    require(chunk, "truncated regular tar member")
                    hasher.update(chunk)
                    remaining -= len(chunk)
                require(hasher.hexdigest() == row["sha256"], "complete archived member SHA256 differs: " + row["member"])
                padding = (-row["bytes"]) % 512
                exact(reader, b"\0" * padding)
                position += row["bytes"] + padding
                stored_bytes += row["bytes"]
            else:
                require(target in verified and verified[target] == (row["sha256"], row["bytes"], row["archive_mode"]),
                        "hardlink target has not been independently verified")
            verified[row["member"]] = row["sha256"], row["bytes"], row["archive_mode"]
        footer = ((position + 1024 + 10239) // 10240) * 10240 - position
        exact(reader, b"\0" * footer)
        require(reader.read(1) == b"" and reader.finished, "uncommitted tar contents after approved members")
        require(fingerprint(os.fstat(raw.fileno())) == before, "archive changed during verification")
        actual = reader.hasher.hexdigest()
        if archive_sha256 is not None:
            require(actual == pin(archive_sha256), "external compressed archive identity differs")
    require(stored_bytes == plan["stored_file_bytes"], "verified complete content total differs")
    return {"schema": "hepta.evidence-archive-verification.v8", "status": "PASS",
            "archive_sha256": actual, "archive_bytes": reader.compressed_bytes,
            "manifest_sha256": digest(manifest_bytes), "members": len(verified),
            "evidence_members": len(verified), "regular_evidence_members": len(verified) - plan["hardlinks"],
            "manifest_members": 1, "archive_logical_members": len(verified) + 1,
            "hardlinks": plan["hardlinks"], "logical_bytes": plan["logical_bytes"],
            "stored_file_bytes": stored_bytes, "all_regular_content_sha256_verified": True,
            "all_hardlinks_resolved_to_verified_regular_members": True,
            "source_directories_required": False, "extraction_performed": False,
            "source_stat_scope": "inode, times and modes detect concurrent input changes; they are not scientific identity or original-time restoration claims",
            "scientific_verdict_from_archive": False}
