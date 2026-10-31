"""Verify a complete published archive; restore only an explicit member union.

The INDEX digest is supplied independently. One continuous XZ stream is read in
full; selective restoration saves output disk, not compressed-stream bandwidth.
No frozen archive or scientific source is modified.
"""

import argparse
import fnmatch
import hashlib
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import time

from experiments.hcsn_free_boundary_v1 import archive as frozen


BLOCK = 1 << 20
TAR_BUFFER = 10240


def sha(path):
    return frozen.sha256(path)


def safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or "\0" in name:
        raise ValueError("Invalid relative member name")
    value = PurePosixPath(name)
    if value.is_absolute() or ".." in value.parts or value.as_posix() != name or name == ".":
        raise ValueError("Noncanonical or escaping member name: " + name)
    return value


def no_symlink_path(path):
    path = Path(path).absolute()
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("Symlinked filesystem path is not accepted: " + str(path))
    return path


def bounded(root, name):
    path = root.joinpath(*safe_name(name).parts)
    no_symlink_path(path)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Filesystem path escaped its root")
    return path


def positive_size(value):
    if type(value) is not int or value < 0:
        raise ValueError("Byte sizes and counts must be nonnegative integers")
    return value


def valid_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected an exact SHA256")
    return value


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(path=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def load_manifest(index, expected_sha):
    if sha(index) != valid_sha(expected_sha):
        raise ValueError("Externally pinned INDEX SHA256 mismatch")
    descriptor = json.loads(index.read_bytes())
    if descriptor["schema"] != "hcsn-bounded-member-index.v1":
        raise ValueError("Unknown INDEX schema")
    members, shard_names = [], set()
    for row in descriptor["member_shards"]:
        name = safe_name(row["path"])
        if len(name.parts) != 1 or row["path"] in shard_names:
            raise ValueError("Member shards must be distinct adjacent files")
        shard_names.add(row["path"])
        path = bounded(index.parent, row["path"])
        if path.stat().st_size != positive_size(row["bytes"]) or sha(path) != valid_sha(row["sha256"]):
            raise ValueError("Member shard length/hash mismatch")
        content = json.loads(path.read_bytes())
        if not isinstance(content, list) or len(content) != positive_size(row["members"]):
            raise ValueError("Member shard count mismatch")
        members.extend(content)
    if len(members) != positive_size(descriptor["original_member_count"]):
        raise ValueError("Original member count mismatch")
    manifest = {key: value for key, value in descriptor.items()
                if key not in ("member_shards", "original_manifest_sha256", "original_member_count")}
    manifest.update(schema="hcsn-evidence-bundle.v1", members=members)
    canonical = (json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False)+"\n").encode()
    if hashlib.sha256(canonical).hexdigest() != valid_sha(descriptor["original_manifest_sha256"]):
        raise ValueError("Canonical original manifest SHA256 mismatch")
    expected = {}
    for row in members:
        safe_name(row["path"])
        positive_size(row["bytes"])
        valid_sha(row["sha256"])
        if row["path"] in expected:
            raise ValueError("Duplicate declared member")
        expected[row["path"]] = row
    if sum(row["bytes"] for row in members) != positive_size(manifest["uncompressed_file_bytes"]):
        raise ValueError("Uncompressed member byte total mismatch")
    parts = set()
    for row in manifest["parts"]:
        name = safe_name(row["path"])
        if len(name.parts) != 1 or row["path"] in parts or row["path"] in shard_names:
            raise ValueError("Archive parts must be distinct adjacent files")
        parts.add(row["path"])
        positive_size(row["bytes"])
        valid_sha(row["sha256"])
    if not parts or sum(row["bytes"] for row in manifest["parts"]) != positive_size(manifest["compressed_bytes"]):
        raise ValueError("Compressed part byte total mismatch")
    valid_sha(manifest["archive_sha256"])
    return manifest, expected, descriptor["original_manifest_sha256"]


def verify_parts(index, manifest, receipt):
    whole = hashlib.sha256()
    for row in manifest["parts"]:
        path = bounded(index.parent, row["path"])
        if not path.is_file() or path.stat().st_size != row["bytes"]:
            raise ValueError("Archive part length/type mismatch")
        value = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(BLOCK), b""):
                value.update(block)
                whole.update(block)
        if value.hexdigest() != row["sha256"]:
            raise ValueError("Archive part SHA256 mismatch")
        receipt["part_files_verified"] += 1
        receipt["compressed_bytes_verified"] += row["bytes"]
    if whole.hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Whole compressed archive SHA256 mismatch")
    receipt["verified_archive_sha256"] = whole.hexdigest()


class StrictXZReader:
    """Bounded decompression of exactly one complete XZ stream, with a tail.

    The tail exposes bytes read ahead by tarfile, allowing strict end-marker and
    zero-padding checks even though tarfile normally stops at its first marker.
    """

    def __init__(self, source):
        self.source = source
        self.decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        self.finished, self.position, self.tail = False, 0, b""

    def read(self, size):
        if size < 0:
            raise ValueError("Only bounded archive reads are accepted")
        blocks, length = [], 0
        while length < size and not self.finished:
            if self.decoder.eof:
                if self.decoder.unused_data or self.source.read(1):
                    raise ValueError("Unexpected bytes after the single XZ stream")
                self.source.verify_end()
                self.finished = True
                break
            data = self.source.read(BLOCK) if self.decoder.needs_input else b""
            if self.decoder.needs_input and not data:
                raise EOFError("Truncated XZ stream")
            block = self.decoder.decompress(data, max_length=size-length)
            blocks.append(block)
            length += len(block)
        result = b"".join(blocks)
        self.position += len(result)
        self.tail = (self.tail+result)[-2*TAR_BUFFER:]
        return result

    def verify_tar_end(self, offset):
        start = self.position-len(self.tail)
        if not start <= offset <= self.position:
            raise ValueError("Tar read-ahead exceeded its bounded tail contract")
        padding = self.tail[offset-start:]
        count = len(padding)
        if any(padding):
            raise ValueError("Invalid tar end marker or nonzero trailing member data")
        for block in iter(lambda: self.read(BLOCK), b""):
            if any(block):
                raise ValueError("Nonzero bytes after tar end marker")
            count += len(block)
        if count < 1024 or self.position % 512 or not self.finished:
            raise ValueError("Truncated tar end markers or padding")
        return count


def select_members(expected, names, patterns):
    selected = set()
    if not names and not patterns:
        raise ValueError("At least one explicit path or pattern is required")
    for name in names:
        safe_name(name)
        if name not in expected:
            raise ValueError("Selected member does not exist: " + name)
        selected.add(name)
    for pattern in patterns:
        safe_name(pattern)
        matches = {name for name in expected if fnmatch.fnmatchcase(name, pattern)}
        if not matches:
            raise ValueError("Selection pattern has no match: " + pattern)
        selected.update(matches)
    return {name: dict(expected[name], disposition="not_committed") for name in sorted(selected)}


def restore_selected(index, index_sha256, publication_root, destination, audit_output,
                     names=(), patterns=(), reserve_bytes=64*1024**2):
    index, publication_root = no_symlink_path(index), no_symlink_path(publication_root)
    destination, audit_output = no_symlink_path(destination), no_symlink_path(audit_output)
    index.relative_to(publication_root)
    if (destination.is_relative_to(publication_root) or publication_root.is_relative_to(destination)
            or audit_output.is_relative_to(publication_root) or audit_output.is_relative_to(destination)):
        raise ValueError("Destination and audit must be outside the immutable publication; audit also outside destination")
    if not publication_root.is_dir() or (destination.exists() and not destination.is_dir()):
        raise ValueError("Expected publication/destination directories")
    if audit_output.exists() or list(audit_output.parent.glob(audit_output.stem+"_selection_*.json")):
        raise FileExistsError("Audit output already exists; use a new attempt")
    positive_size(reserve_bytes)
    start, cpu = time.perf_counter(), time.process_time()
    selected = {}
    receipt = dict(schema="hcsn-selective-archive-restore.v1", passed=False,
        scope="Complete archive/member verification with explicit selective restoration; not a full extraction",
        index=str(index), expected_index_sha256=index_sha256, publication_root=str(publication_root),
        destination=str(destination), selectors=dict(paths=list(names), patterns=list(patterns),
            semantics="Union; fnmatchcase matches entire relative POSIX paths and * can match slash"),
        part_files_verified=0, compressed_bytes_verified=0, member_files_verified=0,
        member_bytes_verified=0, all_members_verified=False, selected_bytes_verified=0,
        staged_payload_bytes=0, restored_files=0, restored_bytes=0, existing_identical_files=0,
        existing_identical_bytes=0, full_restoration_claim=False)
    try:
        manifest, expected, original_sha = load_manifest(index, index_sha256)
        receipt.update(canonical_manifest_sha256=original_sha, declared_member_files=len(expected),
                       declared_member_bytes=manifest["uncompressed_file_bytes"])
        selected = select_members(expected, names, patterns)
        receipt.update(selected_files=len(selected), selected_declared_bytes=sum(r["bytes"] for r in selected.values()),
                       all_members_selected=len(selected)==len(expected))
        needed = set()
        for name, row in selected.items():
            target = bounded(destination, name)
            if target.exists():
                if not target.is_file() or sha(target) != row["sha256"]:
                    raise FileExistsError("Refusing differing existing member: " + name)
            else:
                needed.add(name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        needed_bytes = sum(selected[name]["bytes"] for name in needed)
        if shutil.disk_usage(destination.parent).free < needed_bytes+reserve_bytes:
            raise OSError("Insufficient disk for selected staged payload plus declared reserve")
        verify_parts(index, manifest, receipt)
        with tempfile.TemporaryDirectory(prefix="selective_restore_", dir=destination.parent) as temporary:
            staging = Path(temporary)
            seen = set()
            with frozen._PartReader(index.parent, manifest["parts"], manifest["archive_sha256"]) as compressed:
                decoded = StrictXZReader(compressed)
                with tarfile.open(fileobj=decoded, mode="r|", bufsize=TAR_BUFFER) as archive:
                    for member in archive:
                        safe_name(member.name)
                        if not member.isfile() or member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE):
                            raise ValueError("Nonregular archive member")
                        if member.name not in expected or member.name in seen:
                            raise ValueError("Unexpected or duplicate archive member")
                        row = expected[member.name]
                        if member.size != row["bytes"]:
                            raise ValueError("Archive member size mismatch")
                        output = None
                        if member.name in needed:
                            target = bounded(staging, member.name)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            output = target.open("xb")
                        value, count = hashlib.sha256(), 0
                        try:
                            source = archive.extractfile(member)
                            with source:
                                for block in iter(lambda: source.read(BLOCK), b""):
                                    value.update(block)
                                    count += len(block)
                                    if output is not None:
                                        output.write(block)
                                        receipt["staged_payload_bytes"] += len(block)
                        finally:
                            if output is not None:
                                output.close()
                        if count != row["bytes"] or value.hexdigest() != row["sha256"]:
                            raise ValueError("Archive member payload hash/length mismatch: " + member.name)
                        seen.add(member.name)
                        receipt["member_files_verified"] += 1
                        receipt["member_bytes_verified"] += count
                        if member.name in selected:
                            receipt["selected_bytes_verified"] += count
                    end = archive.offset
                receipt["tar_zero_padding_bytes"] = decoded.verify_tar_end(end)
                receipt["xz_complete"] = decoded.finished
            if seen != set(expected):
                raise ValueError("Missing or truncated declared archive members")
            receipt["all_members_verified"] = True
            destination.mkdir(parents=True, exist_ok=True)
            for name, row in selected.items():
                target = bounded(destination, name)
                if target.exists():
                    if not target.is_file() or sha(target) != row["sha256"]:
                        raise FileExistsError("Existing selected member changed before commit")
                    row["disposition"] = "existing_identical_reused"
                    receipt["existing_identical_files"] += 1
                    receipt["existing_identical_bytes"] += row["bytes"]
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    bounded(destination, name)
                    os.link(staging/name, target, follow_symlinks=False)
                    row["disposition"] = "restored_after_complete_verification"
                    receipt["restored_files"] += 1
                    receipt["restored_bytes"] += row["bytes"]
            receipt["passed"] = True
    except Exception as error:
        receipt["error"] = dict(type=type(error).__name__, message=str(error))
    receipt["selection_shards"] = []
    entries = list(selected.values())
    for offset in range(0, len(entries), 600):
        path = audit_output.with_name(audit_output.stem+f"_selection_{offset//600:04d}.json")
        receipt["selection_shards"].append(dict(write_new(path, entries[offset:offset+600]),
                                                members=len(entries[offset:offset+600])))
    receipt.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-start,
        source_sha256={"selective_restore.py":sha(Path(__file__)), "frozen_archive.py":sha(Path(frozen.__file__))},
        cost_scope="Internal recovery clocks after imports; includes archive verification and selected writes, before final receipt serialization")
    write_new(audit_output, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--index-sha256", required=True)
    parser.add_argument("--publication-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--audit-output", type=Path, required=True)
    parser.add_argument("--select", action="append", default=[])
    parser.add_argument("--pattern", action="append", default=[])
    parser.add_argument("--reserve-bytes", type=int, default=64*1024**2)
    args = parser.parse_args()
    result = restore_selected(args.index, args.index_sha256, args.publication_root, args.destination,
                              args.audit_output, args.select, args.pattern, args.reserve_bytes)
    print(json.dumps({key:result.get(key) for key in ("passed", "all_members_verified", "member_files_verified",
          "selected_files", "restored_bytes", "existing_identical_bytes", "error")}, sort_keys=True))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
