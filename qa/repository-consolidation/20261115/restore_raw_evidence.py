"""Restore exact historical evidence from individually compressed containers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zlib


INDEX = "qa/repository-consolidation/20261115/raw-evidence-storage.json"
EXTENSION_INDEX = (
    "qa/repository-consolidation/20261124/source53-log-gzip/raw-evidence-storage.json"
)
SOURCE84_INDEX = (
    "qa/repository-consolidation/20261124/source84-log-gzip/raw-evidence-storage.json"
)
SOURCE0A5_INDEX = (
    "qa/repository-consolidation/20261124/source0a5-log-gzip/raw-evidence-storage.json"
)
EVALUATED_READ_INDEX = "qa/repository-consolidation/20261124/evaluated-read-logs/raw-evidence-storage.json"
HOSTED_QUALIFICATION_INDEX = "qa/repository-consolidation/20261124/hosted-qualification-logs/raw-evidence-storage.json"
MEM8_INDEX = "qa/repository-consolidation/20261124/mem8-log-gzip/raw-evidence-storage.json"
HOSTED_1026_WINDOWS_INDEX = "qa/repository-consolidation/20261124/hosted-1026-windows-learn/raw-evidence-storage.json"
HISTORICAL_CARGO_DENY_INDEX = "qa/repository-consolidation/20261124/historical-cargo-deny-logs/raw-evidence-storage.json"
PAIRED_DIAGNOSTIC_INDEX = "qa/repository-consolidation/20261124/paired-diagnostic-logs/raw-evidence-storage.json"
VENDORED_PATCH_INDEX = "qa/repository-consolidation/20261124/vendored-patch-custody/raw-evidence-storage.json"
QUALIFIED_CONSOLE_INDEX = "qa/repository-consolidation/20261124/qualified-console-custody/raw-evidence-storage.json"
MEM8_BOUNDED_GNU_INDEX = "qa/repository-consolidation/20261125/mem8-bounded-gnu-logs/raw-evidence-storage.json"
RUNNER_CONSOLE_INDEX = "qa/repository-consolidation/20261125/qualified-runner-console/raw-evidence-storage.json"
HISTORICAL_PATCH_INDEX = "qa/repository-consolidation/20261125/review-only-source-diffs/raw-evidence-storage.json"
QUALIFICATION_TRANSFER_MANIFEST_INDEX = "qa/repository-consolidation/20261125/qualification-transfer-manifest/raw-evidence-storage.json"
VENDOR_MAINTENANCE_PATCH_INDEX = "qa/repository-consolidation/20261125/vendor-maintenance-patches/raw-evidence-storage.json"
HCSN_HOSTED_CONSOLE_INDEX = "qa/repository-consolidation/20261125/hcsn-hosted-console-custody/raw-evidence-storage.json"
CLOSED_RESULTS_INDEX = "qa/repository-consolidation/20261125/closed-public-results/raw-evidence-storage.json"
INDEX_SHA256 = {
    CLOSED_RESULTS_INDEX: "c776af0182349d8ea398fb3356491fe1140ac49d1f483eeadca0c12406367865",
    HCSN_HOSTED_CONSOLE_INDEX: "cd356ec2c924596980da39e9d55156c6be4d003df4b62d535168e2619095db54",
    VENDOR_MAINTENANCE_PATCH_INDEX: "61ac9fe9f6c92be15a21e276f574a37b223ef14653b78976e337e60a495cede9",
    QUALIFICATION_TRANSFER_MANIFEST_INDEX: "2b5ae403edfb29877d4766ac002e516b3593607d0e65092836fe28328759ea98",
    HISTORICAL_PATCH_INDEX: "cfdcb1368689f07a2de282e19fd40ee8d782993d7ea4f6eb2bebbf2a0f3d7b4d",
    RUNNER_CONSOLE_INDEX: "47e503499077278820266ee068ed8d638f5b0767d8bd94657cb1205d2de7307b",
    MEM8_BOUNDED_GNU_INDEX: "d249597de292b7c5e9bec309552d8e52d05a0cbe3261d1032f8b5bbb2958841e",
    QUALIFIED_CONSOLE_INDEX: "974ab4cc5a9a5066a3598ef64ba3eb990e6dff68ae3995956790835969f253b7",
    VENDORED_PATCH_INDEX: "17ba3a271e6a289faea295617649ad6dfc7cb90e42709c6b8c9e96ff2d352de9",
    PAIRED_DIAGNOSTIC_INDEX: "01d68c678f8f5fddb3ed685bdf6604da7639d740faddeda6a5fc723cf89ed7cf",
    HISTORICAL_CARGO_DENY_INDEX: "afd074a431b6cec896c4f4d8ce93a8edefd6b9641149a76bbf7c9b4d53aa30fd",
    HOSTED_1026_WINDOWS_INDEX: "528efff62065e0265093b041f0f1643f8170d3602b36b4feb3a244c9eb3636e5",
    MEM8_INDEX: "e9211b1fd070df8b4f8f622ef915171c5a7918279c07672ef8d637bbb41680c5",
    HOSTED_QUALIFICATION_INDEX: "eb8e44a4d72d6737a9deecf715fd38dcce94401d01925c1b6337771ec4aef434",
    EVALUATED_READ_INDEX: "b234ee9989eb6ed712905d6c9da748d35a1400d8b2c71ab197675520a5c8aa64",
    INDEX: "72103445cd088e31ee2e6d4887b9e24638d184389226b1577ff7342ebebc44c0",
    EXTENSION_INDEX: "9a4288af05724562b9aa4fde5782735531eeee048c3d4ce63a63f5f6b60e8b87",
    SOURCE84_INDEX: "a4b240eef423bab829e2150c63a603a5d0c3f001220ae5616b2f87eed7ec8184",
    SOURCE0A5_INDEX: "dde0cc0c597ed9d85d10aa68d0b4bbaaa32fd949efce445aeb1b346f08742f55",
}
MAX_BYTES = 8 * 1024 * 1024


def relative_path(name):
    if not isinstance(name, str) or "\\" in name or ":" in name or "\0" in name:
        raise ValueError("evidence path must use repository-relative syntax")
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("evidence path must remain relative to the repository")
    if path.as_posix() != name or not path.parts:
        raise ValueError("evidence path must be canonical")
    return path


def identity(value):
    return (
        value.st_dev,
        value.st_ino,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
        value.st_mode,
        value.st_nlink,
    )


def read_regular(repo, relative, limit):
    path = repo / relative_path(relative)
    if not 0 <= limit <= MAX_BYTES:
        raise ValueError("invalid evidence byte bound")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("evidence parent must not be a symbolic link")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError("evidence must be a regular single-link file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_BINARY", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(opened) != identity(before):
            raise ValueError("evidence changed before reading")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if (
        identity(after) != identity(before)
        or identity(path.lstat()) != identity(before)
        or len(data) > limit
    ):
        raise ValueError("evidence changed during reading or exceeds its bound")
    return data


def entries(repo):
    result = {}
    for index, expected in INDEX_SHA256.items():
        raw = read_regular(repo, index, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("registered evidence storage inventory changed")
        document = json.loads(raw)
        if document["schema"] != "hepta.raw-evidence.storage.v1":
            raise ValueError("unsupported raw evidence storage schema")
        for entry in document["files"]:
            name = relative_path(entry["original_path"]).as_posix()
            if name in result or entry["stored_path"] != name + ".evidence.gz":
                raise ValueError("duplicate or inconsistent stored evidence path")
            result[name] = entry
    return result


def read_verified(repo, relative, expected_bytes, expected_sha256):
    if type(expected_bytes) is not int or not 0 <= expected_bytes <= MAX_BYTES:
        raise ValueError("invalid original evidence byte bound")
    if not isinstance(expected_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", expected_sha256
    ):
        raise ValueError("invalid original evidence checksum")
    relative = relative_path(str(relative)).as_posix()
    path = repo / relative
    if path.exists() or path.is_symlink():
        data = read_regular(repo, relative, expected_bytes)
    else:
        entry = entries(repo)[relative]
        if (
            entry["original_bytes"] != expected_bytes
            or entry["original_sha256"] != expected_sha256
        ):
            raise ValueError("storage index differs from the original manifest")
        compressed = read_regular(repo, entry["stored_path"], entry["stored_bytes"])
        if (
            len(compressed) != entry["stored_bytes"]
            or hashlib.sha256(compressed).hexdigest() != entry["stored_sha256"]
        ):
            raise ValueError("stored evidence checksum mismatch")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        data = decoder.decompress(compressed, expected_bytes + 1)
        if (
            not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
            or len(data) != expected_bytes
        ):
            raise ValueError("truncated, oversized or concatenated gzip evidence")
    if (
        len(data) != expected_bytes
        or hashlib.sha256(data).hexdigest() != expected_sha256
    ):
        raise ValueError("original evidence length or checksum mismatch")
    return data


def restore(repo, destination):
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("destination must be a new directory")
    if not destination.parent.is_dir() or any(
        p.is_symlink() for p in destination.parents
    ):
        raise ValueError("destination parent must be an existing regular directory")
    if destination.is_relative_to(repo):
        raise ValueError("destination must be outside the repository")
    outputs = []
    for name, entry in entries(repo).items():
        data = read_verified(
            repo, name, entry["original_bytes"], entry["original_sha256"]
        )
        blob = hashlib.sha1(
            b"blob " + str(len(data)).encode() + b"\0" + data
        ).hexdigest()
        if blob != entry["original_git_blob"]:
            raise ValueError("original Git blob mismatch")
        outputs.append((name, data))
    destination.mkdir(mode=0o700)
    for name, data in outputs:
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(data)
    print(f"Restored {len(outputs)} exact historical evidence files")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parents[3], arguments.destination)
