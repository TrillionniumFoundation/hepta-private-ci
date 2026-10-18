"""Bounded physical source checks for the Linux fixed CPU encoder."""

import hashlib
import json
import os
from pathlib import Path
import stat
import struct


def protected_path(path, directory=False):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError("noncanonical source")
    for ancestor in path.parents:
        info = ancestor.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError("writable source ancestor")
    info = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("unprotected source")
    if not directory and info.st_nlink != 1:
        raise ValueError("source has aliases")
    return path


def source_bytes(source, maximum):
    if set(source) != {"path", "sha256", "size"}:
        raise ValueError("source fields")
    path = protected_path(source["path"])
    with open(path, "rb", buffering=0) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != source["size"] or not 0 <= before.st_size <= maximum:
            raise ValueError("source budget")
        payload = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
    stable = lambda info: (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
                           info.st_mode, info.st_nlink, info.st_size,
                           info.st_mtime_ns, info.st_ctime_ns)
    if stable(before) != stable(after) or stable(path.stat()) != stable(before):
        raise ValueError("source changed during read")
    if hashlib.sha256(payload).hexdigest() != source["sha256"]:
        raise ValueError("source digest")
    return payload


def verify_large_source(source, maximum):
    if set(source) != {"path", "sha256", "size"}:
        raise ValueError("source fields")
    path = protected_path(source["path"])
    digest = hashlib.sha256()
    with open(path, "rb", buffering=0) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != source["size"] or not 0 <= before.st_size <= maximum:
            raise ValueError("large source budget")
        while block := stream.read(1024 * 1024):
            digest.update(block)
        after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("large source changed")
    if digest.hexdigest() != source["sha256"]:
        raise ValueError("large source digest")


def unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


def decode_json(payload):
    return json.loads(payload, object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def tokenizer_digest(stream):
    """Hash original tokenizer entries in file order, as the training pin did."""
    captured = bytearray()
    consumed = 0

    def read(size, record=False):
        nonlocal consumed
        consumed += size
        if size < 0 or consumed > 8 * 1024 * 1024:
            raise ValueError("GGUF metadata budget")
        data = stream.read(size)
        if len(data) != size:
            raise ValueError("truncated GGUF")
        if record:
            captured.extend(data)
        return data

    def number(kind, record=False):
        return struct.unpack("<" + kind, read(struct.calcsize("<" + kind), record))[0]

    def string(record=False):
        size = number("Q", record)
        if size > 1024 * 1024:
            raise ValueError("GGUF string budget")
        return read(size, record)

    scalar = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i",
              6: "f", 7: "B", 10: "Q", 11: "q", 12: "d"}

    def value(kind, record, array=False):
        if kind in scalar:
            number(scalar[kind], record)
        elif kind == 8:
            string(record)
        elif kind == 9 and not array:
            element = number("I", record)
            count = number("Q", record)
            if count > 65536 or element not in (*scalar, 8):
                raise ValueError("GGUF array budget/type")
            for _ in range(count):
                value(element, record, True)
        else:
            raise ValueError("GGUF metadata type")

    if read(4) != b"GGUF" or number("I") != 3:
        raise ValueError("GGUF version")
    tensors, count = number("Q"), number("Q")
    if tensors > 4096 or not 1 <= count <= 256:
        raise ValueError("GGUF header budget")
    seen = set()
    for _ in range(count):
        key = string()
        if key in seen:
            raise ValueError("duplicate GGUF metadata")
        seen.add(key)
        record = key.startswith(b"tokenizer.")
        if record:
            captured.extend(struct.pack("<Q", len(key)) + key)
        value(number("I", record), record)
    if not captured:
        raise ValueError("missing tokenizer metadata")
    return hashlib.sha256(captured).hexdigest()


def verify_inventory(root, sources):
    root = protected_path(root, directory=True)
    paths = sorted(str(path) for path in root.rglob("*") if not path.is_dir())
    expected = sorted(item["path"] for item in sources)
    if not 1 <= len(paths) <= 4096 or paths != expected:
        raise ValueError("runtime inventory changed")
    for item in sources:
        verify_large_source(item, 32 * 1024 * 1024)


def root_role():
    fields = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.split()
    if fields.get("Uid") != ["0"] * 4 or fields.get("Gid") != ["0"] * 4:
        raise ValueError("fixed Root role")
    if fields.get("Groups") or fields.get("NoNewPrivs") != ["1"]:
        raise ValueError("Root process boundary")
    if any(int(fields[name][0], 16) for name in ("CapEff", "CapPrm", "CapAmb")):
        raise ValueError("Root encoder capabilities")
