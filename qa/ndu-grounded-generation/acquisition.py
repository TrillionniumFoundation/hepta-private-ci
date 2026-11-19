"""Acquire pinned Florence files and one official COCO ZIP member, without Hub caches."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from urllib.request import Request, urlopen
import zlib


REPOSITORY = "florence-community/Florence-2-base"
REVISION = "00921df66db728a9ceb750f5eca43e5c203a2051"
FILES = {
    "added_tokens.json": (22430, "1d75deda84dfa81fb6c09301f3fed00f9695059568bbb1403a6bf299cd84fc37"),
    "config.json": (2387, "2a4dfe9885d183da121f239ada734bd700ee6908b650a7a25ab32eb104fe1d7a"),
    "generation_config.json": (292, "0251459c49cc358ac033b5d4b8569e61ac22bde5d76be404b97a44cfb33fb12e"),
    "merges.txt": (456318, "1ce1664773c50f3e0cc8842619a93edc4624525b728b188a9e0be33b7726adc5"),
    "model.safetensors": (463178864, "62f3e696da74f8869a68ddb529a9b3e14eb25b21c592cb3dea6179bf944df6a0"),
    "preprocessor_config.json": (603, "1396ec5a0a7adfe1c04fb777b09e8ba753be6dbb5868212ab3c3ef39d91fe031"),
    "processor_config.json": (2264, "cd0e3bf41a39b1276503fbd273bc03b9afc70d7a15ea681a92a1b4b77f858ee6"),
    "special_tokens_map.json": (146627, "72ff172dc769bc1551b1b4211628ce3271643bc60379e4da45d85a9be9332c39"),
    "tokenizer.json": (3748144, "3ad7001f773409abe6bba33eac92662611a73d72f459bda2f00d2a221dd31ce4"),
    "tokenizer_config.json": (197922, "cb5f80bd9afa767bb1bb798ee5f0a79eae45239b8e72506166b4218175a16723"),
    "vocab.json": (798293, "ed19656ea1707df69134c4af35c8ceda2cc9860bf2c3495026153a133670ab5e"),
}
ARCHIVE_URL = "https://s3.amazonaws.com/images.cocodataset.org/annotations/annotations_trainval2017.zip"
ARCHIVE_BYTES, LOCAL_OFFSET = 252907541, 152757923
MEMBER = "annotations/instances_val2017.json"
COMPRESSED_BYTES, ANNOTATION_BYTES, CRC32 = 6529031, 19987840, 781945669
ANNOTATION_SHA256 = "e8c7f7908f1d7278341fae127d0da654f102f11bd7b21d8aeefa635b8c810b6f"


def verified(path, size, digest):
    if path.is_symlink():
        raise ValueError(f"refusing symlink destination: {path}")
    if not path.exists():
        return False
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if path.stat().st_size != size or actual != digest:
        raise ValueError(f"existing file differs from fixed pin: {path}")
    return True


@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name("." + path.name + ".acquisition.lock")
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        lock.unlink(missing_ok=True)


def atomic_write(path, chunks, size, digest):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".partial", dir=path.parent)
    temporary, actual, count = Path(name), hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as stream:
            for chunk in chunks:
                count += len(chunk)
                if count > size:
                    raise ValueError("download exceeded pinned byte limit")
                stream.write(chunk)
                actual.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if count != size or actual.hexdigest() != digest:
            raise ValueError("acquisition length or SHA256 mismatch")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def manifest(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    atomic_write(path, [raw], len(raw), hashlib.sha256(raw).hexdigest())


def acquire_model(directory):
    directory.mkdir(parents=True, exist_ok=True)
    started, inventory = time.perf_counter(), []
    missing = sum(size for name, (size, _) in FILES.items() if not (directory / name).exists())
    if shutil.disk_usage(directory).free < missing + 32_000_000:
        raise OSError("insufficient disk for one checkpoint plus annotation working reserve")
    for name, (size, digest) in FILES.items():
        path = directory / name
        if not verified(path, size, digest):
            request = Request(f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}",
                              headers={"User-Agent": "Hepta-NDU-acquisition/1"})
            with urlopen(request, timeout=90) as response:
                atomic_write(path, iter(lambda: response.read(1024 * 1024), b""), size, digest)
        inventory.append({"path": name, "bytes": size, "sha256": digest})
    value = {"schema": "hepta.ndu-generative-checkpoint-acquisition.v1", "repository": REPOSITORY,
             "revision": REVISION, "license": "MIT", "files": inventory,
             "total_bytes": sum(row["bytes"] for row in inventory), "remote_code_executed": False,
             "inventory_sha256": hashlib.sha256(json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
             "wall_seconds": time.perf_counter() - started}
    manifest(directory.with_name(directory.name + ".acquisition.json"), value)
    return value


def range_bytes(start, length):
    end = start + length - 1
    request = Request(ARCHIVE_URL, headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"})
    with urlopen(request, timeout=45) as response:
        if response.status != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{ARCHIVE_BYTES}":
            raise ValueError("official ZIP server did not honor the exact bounded Range")
        raw = response.read(length + 1)
    if len(raw) != length:
        raise ValueError("ZIP Range length mismatch")
    return raw


def acquire_annotations(path):
    if not verified(path, ANNOTATION_BYTES, ANNOTATION_SHA256):
        header = struct.unpack("<4s5H3I2H", range_bytes(LOCAL_OFFSET, 30))
        if header[0] != b"PK\x03\x04" or header[2] != 0 or header[3] != 8 or header[6:9] != (CRC32, COMPRESSED_BYTES, ANNOTATION_BYTES):
            raise ValueError("fixed official ZIP local-header identity mismatch")
        if range_bytes(LOCAL_OFFSET + 30, header[9]).decode() != MEMBER:
            raise ValueError("wrong ZIP member name")
        compressed = range_bytes(LOCAL_OFFSET + 30 + header[9] + header[10], COMPRESSED_BYTES)
        decoder = zlib.decompressobj(wbits=-15)
        raw = decoder.decompress(compressed, ANNOTATION_BYTES + 1)
        if not decoder.eof or decoder.unused_data or len(raw) != ANNOTATION_BYTES or zlib.crc32(raw) != CRC32:
            raise ValueError("ZIP member decompression or CRC32 mismatch")
        atomic_write(path, [raw], ANNOTATION_BYTES, ANNOTATION_SHA256)
    value = {"schema": "hepta.ndu-coco-member-acquisition.v1", "archive_url": ARCHIVE_URL,
             "archive_bytes": ARCHIVE_BYTES, "whole_archive_verified": False,
             "member": MEMBER, "local_header_offset": LOCAL_OFFSET,
             "compressed_bytes": COMPRESSED_BYTES, "bytes": ANNOTATION_BYTES,
             "crc32": CRC32, "sha256": ANNOTATION_SHA256}
    manifest(path.with_name(path.name + ".acquisition.json"), value)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--annotations-output", required=True, type=Path)
    args = parser.parse_args()
    with exclusive(args.model_dir), exclusive(args.annotations_output):
        model = acquire_model(args.model_dir)
        annotations = acquire_annotations(args.annotations_output)
    print(json.dumps({"model_inventory_sha256": model["inventory_sha256"], "annotations_sha256": annotations["sha256"]}))
