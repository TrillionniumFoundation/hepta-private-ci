"""Stream an exact, non-extracting CI evidence transport. No authority is granted."""

import hashlib
import io
import json
import lzma
import math
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile


MAX_JSON = 64 * 1024 * 1024
MAX_ARCHIVE = 8 * 1024**3
MAX_EXPANDED = 32 * 1024**3
MAX_CHUNK = 512_000
MAX_PAX_HEADER = 1024 * 1024
NATIVE_PREFIX = "memory-v9-ci-output/"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field: " + key)
            result[key] = value
        return result
    def number(text):
        value = float(text)
        require(math.isfinite(value), "nonfinite JSON number")
        return value
    return json.loads(raw, object_pairs_hook=unique, parse_float=number,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def safe_name(name):
    require(isinstance(name, str) and name and "\\" not in name and "\0" not in name,
            "invalid relative evidence path")
    path = PurePosixPath(name)
    require(path.parts and not path.is_absolute() and all(part not in (".", "..") for part in path.parts)
            and path.as_posix() == name, "noncanonical or escaping evidence path: " + name)
    return name


def plain_file(path):
    path = Path(path).absolute()
    require(not any(item.is_symlink() for item in (path, *path.parents)), "symlinked evidence input")
    require(stat.S_ISREG(path.stat().st_mode), "regular evidence input required")
    return path


def load(path, maximum=MAX_JSON):
    path = plain_file(path)
    require(path.stat().st_size <= maximum, "oversized JSON input")
    raw = path.read_bytes()
    require(len(raw) <= maximum, "JSON input grew beyond bound")
    return raw, decode(raw)


def pin(value, *, path=False, nonempty=False, maximum=MAX_EXPANDED):
    expected = {"bytes", "sha256", "path"} if path else {"bytes", "sha256"}
    require(isinstance(value, dict) and set(value) == expected, "invalid identity fields")
    require(type(value["bytes"]) is int and (1 if nonempty else 0) <= value["bytes"] <= maximum,
            "invalid identity length")
    require(isinstance(value["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
            "invalid SHA-256 identity")
    if path:
        safe_name(value["path"])
    return {key: value[key] for key in ("bytes", "sha256")}


def file_pin(path):
    path = plain_file(path)
    with path.open("rb") as source:
        sha = hashlib.file_digest(source, "sha256").hexdigest()
    return {"bytes": path.stat().st_size, "sha256": sha}


class ChunkStream(io.RawIOBase):
    """Validate each bounded chunk before exposing its bytes to decompression."""

    def __init__(self, directory, chunks, archive):
        super().__init__()
        require(isinstance(chunks, list) and 1 <= len(chunks) <= 100_000, "invalid chunk inventory")
        self.directory, self.chunks, self.archive = directory, chunks, pin(archive, path=True, nonempty=True,
                                                                         maximum=MAX_ARCHIVE)
        offset, names = 0, set()
        for chunk in chunks:
            require(isinstance(chunk, dict) and set(chunk) == {"path", "offset", "bytes", "sha256"},
                    "invalid chunk descriptor")
            require(type(chunk["offset"]) is int and chunk["offset"] == offset, "chunk offset gap or overlap")
            pin({key: chunk[key] for key in ("path", "bytes", "sha256")}, path=True,
                nonempty=True, maximum=MAX_CHUNK)
            require(chunk["path"] not in names, "duplicate chunk path")
            names.add(chunk["path"])
            offset += chunk["bytes"]
        require(offset == self.archive["bytes"], "chunk lengths differ from archive length")
        self.index, self.buffer, self.position = 0, b"", 0
        self.sha, self.bytes_read = hashlib.sha256(), 0

    def readable(self):
        return True

    def readinto(self, target):
        if not target:
            return 0
        if self.position == len(self.buffer):
            if self.index == len(self.chunks):
                require({"bytes": self.bytes_read, "sha256": self.sha.hexdigest()} == self.archive,
                        "archive digest differs from concatenated chunks")
                return 0
            item = self.chunks[self.index]
            path = plain_file(self.directory / item["path"])
            require(path.stat().st_size == item["bytes"], "chunk length mismatch")
            with path.open("rb") as handle:
                self.buffer = handle.read(MAX_CHUNK + 1)
            require(identity(self.buffer) == {key: item[key] for key in ("bytes", "sha256")},
                    "chunk digest mismatch")
            self.position = 0
            self.index += 1
        count = min(len(target), len(self.buffer) - self.position)
        data = self.buffer[self.position:self.position + count]
        target[:count] = data
        self.position += count
        self.bytes_read += count
        self.sha.update(data)
        return count


class XzStream(io.RawIOBase):
    """One bounded XZ stream; reject truncation, concatenation and trailing data."""

    def __init__(self, compressed):
        super().__init__()
        self.compressed = compressed
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=256 * 1024**2)
        self.expanded = 0

    def readable(self):
        return True

    def readinto(self, target):
        if not target:
            return 0
        while True:
            if self.decoder.eof:
                require(not self.decoder.unused_data and not self.compressed.read(1), "trailing compressed data")
                return 0
            data = self.compressed.read(65536) if self.decoder.needs_input else b""
            require(data or not self.decoder.needs_input, "truncated XZ stream")
            output = self.decoder.decompress(data, max_length=len(target))
            self.expanded += len(output)
            require(self.expanded <= MAX_EXPANDED, "expanded archive exceeds bound")
            if output:
                target[:len(output)] = output
                return len(output)


class BoundedTarInfo(tarfile.TarInfo):
    """Constrain metadata before tarfile reads or recursively processes it."""

    def _proc_member(self, archive):
        # The frozen packer emits regular files with optional local PAX headers.
        # GNU longname/global/sparse forms are outside this transport profile.
        require(self.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.XHDTYPE),
                "nonregular or unsupported TAR header")
        require(0 <= self.size <= MAX_EXPANDED, "TAR header length exceeds bound")
        if self.type != tarfile.XHDTYPE:
            return super()._proc_member(archive)
        require(self.size <= MAX_PAX_HEADER, "PAX metadata length exceeds bound")
        require(not getattr(archive, "_completion_reading_pax", False), "nested PAX metadata is unsupported")
        archive._completion_reading_pax = True
        try:
            return super()._proc_member(archive)
        finally:
            archive._completion_reading_pax = False

    def _proc_gnusparse_00(self, *arguments):
        raise ValueError("sparse PAX metadata is unsupported")

    _proc_gnusparse_01 = _proc_gnusparse_00
    _proc_gnusparse_10 = _proc_gnusparse_00


def verify_transport(manifest_path):
    raw, manifest = load(manifest_path)
    require(isinstance(manifest, dict) and set(manifest) == {
        "schema", "source", "archive", "index", "receipt", "chunks"}
        and manifest["schema"] == "hepta.memory.completion.transport.v1", "unsupported transport manifest")
    source = manifest["source"]
    require(isinstance(source, dict) and set(source) == {"commit", "tree", "run_id", "job_id"},
            "invalid transport source binding")
    for name in ("commit", "tree"):
        require(isinstance(source[name], str) and re.fullmatch(r"[0-9a-f]{40}", source[name]), "invalid Git identity")
    for name in ("run_id", "job_id"):
        require(type(source[name]) is int and source[name] > 0, "invalid CI run/job identity")
    directory = Path(manifest_path).absolute().parent
    documents = {}
    for name in ("index", "receipt"):
        expected = pin(manifest[name], path=True, nonempty=True, maximum=MAX_JSON)
        contents, value = load(directory / manifest[name]["path"])
        require(identity(contents) == expected, name + " file digest mismatch")
        documents[name] = (contents, value)
    require(manifest["index"]["path"] != manifest["receipt"]["path"], "aliased transport documents")
    index, receipt = documents["index"][1], documents["receipt"][1]
    require(isinstance(index, dict) and set(index) == {"schema", "files", "nonregular_entries", "archive",
            "original_file_names_preserved", "symlinks_followed", "model_or_measurement_bytes_changed"}
            and index["schema"] == "hepta.memory.v9.portable-evidence.v1"
            and index["original_file_names_preserved"] is True and index["symlinks_followed"] is False
            and index["model_or_measurement_bytes_changed"] is False, "invalid portable INDEX contract")
    require(index["archive"] == manifest["archive"], "INDEX archive identity mismatch")
    inventory = index["files"]
    require(isinstance(inventory, dict) and 1 <= len(inventory) <= 200_000, "invalid archive inventory")
    for name, value in inventory.items():
        safe_name(name)
        require(name.startswith(NATIVE_PREFIX) or (name.startswith("preparation/")
                and "/" not in name[len("preparation/"):] and name.endswith("PREPARATION.json")),
                "unexpected archive root")
        pin(value)
    special = index["nonregular_entries"]
    require(isinstance(special, dict), "invalid nonregular inventory")
    for name, value in special.items():
        safe_name(name)
        require(name.startswith(NATIVE_PREFIX) and name not in inventory and isinstance(value, dict)
                and value.get("contents_followed") is False, "nonregular entry conflicts with retained evidence")
    require(isinstance(receipt, dict) and isinstance(receipt.get("files"), dict), "missing raw receipt inventory")
    raw_files = receipt["files"]
    for name, value in raw_files.items():
        safe_name(name)
        pin(value)
        require(name != "receipt.json", "CI receipt must not claim its own pre-write inventory")
        require(inventory.get(NATIVE_PREFIX + name) == value, "raw receipt inventory differs from portable INDEX")
    expected_native = {NATIVE_PREFIX + name for name in raw_files} | {NATIVE_PREFIX + "receipt.json"}
    require({name for name in inventory if name.startswith(NATIVE_PREFIX)} == expected_native,
            "unlisted or missing native archive file")
    require(inventory[NATIVE_PREFIX + "receipt.json"] == identity(documents["receipt"][0]),
            "archived receipt differs from external receipt")
    seen = set()
    with io.BufferedReader(ChunkStream(directory, manifest["chunks"], manifest["archive"])) as compressed:
        with XzStream(compressed) as expanded:
            # A 512-byte read buffer leaves no unexamined nonzero TAR tail.
            with tarfile.open(fileobj=expanded, mode="r|", bufsize=512, tarinfo=BoundedTarInfo) as archive:
                for member in archive:
                    name = safe_name(member.name)
                    require(name not in seen, "duplicate TAR member")
                    require(member.isreg() and not member.issparse(), "nonregular or sparse TAR member")
                    require(name in inventory and member.size == inventory[name]["bytes"], "unexpected TAR member or length")
                    seen.add(name)
                    hasher, count = hashlib.sha256(), 0
                    handle = archive.extractfile(member)
                    require(handle is not None, "unreadable TAR member")
                    with handle:
                        while data := handle.read(65536):
                            count += len(data)
                            hasher.update(data)
                    require({"bytes": count, "sha256": hasher.hexdigest()} == inventory[name], "TAR member digest mismatch")
            while data := expanded.read(65536):
                require(not any(data), "nonzero data after TAR end marker")
    require(seen == set(inventory), "archive is missing indexed files")
    return manifest, receipt, {"manifest": identity(raw), "index": identity(documents["index"][0]),
        "receipt": identity(documents["receipt"][0]), "archive": manifest["archive"],
        "verified_regular_files": len(seen), "nonregular_metadata_only": len(special),
        "expanded_bytes": expanded.expanded, "extracted_files": 0}
