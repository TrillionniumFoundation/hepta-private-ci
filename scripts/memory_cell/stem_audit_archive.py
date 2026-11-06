"""Read-only, externally pinned ZIP reader for stem experiment receipts.

No archive extraction, model loading, evaluation, or authority creation occurs.
Both transport bytes and the entire internal file census must match.
"""

import hashlib
import json
from pathlib import PurePosixPath
import re
import stat
import zipfile


class AuditError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise AuditError(reason)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def invalid_constant(value):
    raise AuditError("nonfinite JSON constant: " + value)


def parse_json(payload):
    return json.loads(
        payload, object_pairs_hook=unique_object, parse_constant=invalid_constant
    )


class PinnedArchive:
    def __init__(self, path, expected_sha256):
        require(
            re.fullmatch(r"[0-9a-f]{64}", expected_sha256), "external ZIP pin required"
        )
        require(
            not path.is_symlink()
            and path.is_file()
            and 0 < path.stat().st_size <= 128 * 1024 * 1024,
            "bounded regular ZIP required",
        )
        with path.open("rb") as stream:
            self.sha256 = hashlib.file_digest(stream, "sha256").hexdigest()
        require(self.sha256 == expected_sha256, "external ZIP digest mismatch")
        self.archive = zipfile.ZipFile(path)
        try:
            entries = self.archive.infolist()
            require(0 < len(entries) <= 4096, "archive member bound")
            require(
                sum(e.file_size for e in entries) <= 512 * 1024 * 1024, "ZIP size bound"
            )
            self.files, seen = set(), set()
            for entry in entries:
                name = entry.filename
                path_name = PurePosixPath(name)
                require(
                    name not in seen
                    and not path_name.is_absolute()
                    and ".." not in path_name.parts
                    and "\\" not in name
                    and ":" not in name
                    and "\x00" not in name
                    and str(path_name) == name.rstrip("/")
                    and stat.S_IFMT(entry.external_attr >> 16)
                    in (0, stat.S_IFREG, stat.S_IFDIR)
                    and not entry.flag_bits & 1,
                    "unsafe, duplicate, encrypted or nonregular ZIP member",
                )
                seen.add(name)
                if not entry.is_dir():
                    self.files.add(name)
            manifest = self.read("SHA256SUMS").decode("utf-8")
            pins = {}
            for line in manifest.splitlines():
                match = re.fullmatch(r"([0-9a-f]{64})  \./(.+)", line)
                require(match is not None, "noncanonical manifest line")
                value, name = match.groups()
                require(name not in pins, "duplicate manifest member")
                pins[name] = value
            require(
                set(pins) == self.files - {"SHA256SUMS"},
                "manifest file census mismatch",
            )
            for name, expected in pins.items():
                with self.archive.open(name) as stream:
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                require(actual == expected, "member digest mismatch: " + name)
            self.manifest_entries = len(pins)
        except BaseException:
            self.archive.close()
            raise

    def read(self, name):
        require(name in self.files, "missing artifact member: " + name)
        require(self.archive.getinfo(name).file_size <= 64 * 1024 * 1024, "read bound")
        return self.archive.read(name)

    def json(self, name):
        return parse_json(self.read(name))

    def jsonl(self, name):
        lines = self.read(name).splitlines()
        require(0 < len(lines) <= 20000, "JSONL census bound")
        require(all(line.strip() for line in lines), "blank JSONL record")
        return [parse_json(line) for line in lines]

    def close(self):
        self.archive.close()
