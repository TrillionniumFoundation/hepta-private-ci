#!/usr/bin/env python3
"""Independently hash a received C4 archive, each original member, and local expansion."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def hash_file(path):
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
            size += len(block)
    return size, h.hexdigest()


def safe(name):
    p = PurePosixPath(name)
    assert not p.is_absolute() and all(v not in ("", ".", "..") for v in p.parts)
    assert str(p) == name and "\\" not in name
    return name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("expanded", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--expected-size", type=int, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    archive_size, archive_sha = hash_file(args.archive)
    assert (archive_size, archive_sha) == (args.expected_size, args.expected_sha256)
    with tarfile.open(args.archive, "r:xz") as tar:
        members = tar.getmembers()
        names = [safe(m.name) for m in members]
        assert len(names) == len(set(names))
        assert all(m.isfile() for m in members), "links, directories or devices are not original raw files"
        assert "export-index.json" in names
        raw_index = tar.extractfile("export-index.json").read()
    index = json.loads(raw_index, object_pairs_hook=pairs)
    expected = {safe(f["name"]): f for f in index["files"]}
    assert len(expected) == len(index["files"])
    assert set(names) == set(expected) | {"export-index.json"}
    assert index["commit"] == "8df4b21d893906570d48f5beafabb3b31e0aefbc"
    assert index["tree"] == "6f5aaa2af0432e27e24b6bd2ad18013ab4423d14"
    verified, empty, elf = [], [], []
    with tarfile.open(args.archive, "r|xz") as tar:
        for member in tar:
            stream = tar.extractfile(member)
            h = hashlib.sha256()
            size = 0
            magic = b""
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                if not magic:
                    magic = block[:4]
                h.update(block)
                size += len(block)
            digest = h.hexdigest()
            if member.name == "export-index.json":
                assert digest == hashlib.sha256(raw_index).hexdigest()
                assert (args.expanded / member.name).read_bytes() == raw_index
                continue
            record = expected[member.name]
            assert (size, digest) == (record["bytes"], record["sha256"])
            local = args.expanded / member.name
            assert local.is_file() and not local.is_symlink()
            assert hash_file(local) == (size, digest)
            verified.append({"path": member.name, "bytes": size, "sha256": digest})
            if size == 0:
                empty.append(member.name)
            if magic == b"\x7fELF":
                elf.append({"path": member.name, "bytes": size, "sha256": digest})
    assert len(verified) == len(expected)
    result = {"schema": "root-C4-raw-archive-independent-byte-review-v1", "commit": index["commit"], "tree": index["tree"], "archive": args.archive.name, "archive_bytes": archive_size, "archive_sha256": archive_sha, "export_index_sha256": hashlib.sha256(raw_index).hexdigest(), "original_file_count": len(verified), "original_raw_bytes": sum(f["bytes"] for f in verified), "empty_file_count": len(empty), "empty_files": empty, "actual_ELF_bytes_independently_hashed": elf, "all_archive_member_names_safe_unique_regular_files": True, "all_original_members_match_inventory": True, "all_expanded_files_independently_match": True, "native_samples_executed_by_review": 0, "verifier_replay_executed_by_review": False, "original_gate_credit_increased": False, "files": verified}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("files", "empty_files")}))


if __name__ == "__main__":
    main()
