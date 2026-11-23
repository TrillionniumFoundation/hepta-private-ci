"""Read a hosted MemoryCell startup build ZIP without extracting or executing binaries."""

import argparse
import hashlib
import json
import struct
import tarfile
from pathlib import Path
from zipfile import ZipFile
import zstandard

FILES = {
    "source.txt", "SHA256SUMS", "codex", "hepta-joint-propose", "agentd-lib.tar.zst",
    "source-list.json", "nextest-version.txt",
}


def elf(stream):
    header = stream.read(64)
    if header[:7] != b"\x7fELF\x02\x01\x01" or struct.unpack_from("<H", header, 18)[0] != 62:
        raise ValueError("expected 64-bit little-endian x86-64 ELF")
    digest = hashlib.sha256(header)
    size = len(header)
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(block)
        size += len(block)
    return {"machine": "x86-64", "bytes": size, "sha256": digest.hexdigest()}


def read(archive, source, digest):
    with archive.open("rb") as f:
        if hashlib.file_digest(f, "sha256").hexdigest() != digest:
            raise ValueError("ZIP digest differs from hosted artifact")
    with ZipFile(archive) as z:
        if len(z.infolist()) != len(FILES) or set(z.namelist()) != FILES:
            raise ValueError("build archive roster differs")
        if z.read("source.txt").decode().strip() != source:
            raise ValueError("compiler source differs")
        checks = dict((name, h) for h, name in (line.split() for line in z.read("SHA256SUMS").decode().splitlines()))
        if set(checks) != FILES - {"source.txt", "SHA256SUMS"}:
            raise ValueError("incomplete build manifest")
        children = {}
        for name, expected in checks.items():
            with z.open(name) as f:
                if name in ("codex", "hepta-joint-propose"):
                    children[name] = elf(f)
                    actual = children[name]["sha256"]
                else:
                    actual = hashlib.file_digest(f, "sha256").hexdigest()
            if actual != expected:
                raise ValueError(f"build member differs {name}")
        candidate = None
        seen = set()
        with z.open("agentd-lib.tar.zst") as f, zstandard.ZstdDecompressor().stream_reader(f) as decoded:
            with tarfile.open(fileobj=decoded, mode="r|") as tar:
                for member in tar:
                    if member.name in seen:
                        raise ValueError(f"duplicate tar member {member.name}")
                    seen.add(member.name)
                    if member.name.startswith("target/debug/deps/codex_hepta_agentd-"):
                        if candidate or not member.isfile() or not member.mode & 0o111:
                            raise ValueError("test binary is ambiguous or non-executable")
                        item = elf(tar.extractfile(member))
                        if item["bytes"] != member.size:
                            raise ValueError("test binary size differs")
                        candidate = {member.name: item}
        if not candidate or not {"target/nextest/cargo-metadata.json", "target/nextest/binaries-metadata.json"} <= seen:
            raise ValueError("incomplete nextest archive")
        suites = json.loads(z.read("source-list.json"))["rust-suites"]
        if list(suites) != ["codex-hepta-agentd"]:
            raise ValueError("unexpected suite")
        suite = suites["codex-hepta-agentd"]
        if (suite["status"], suite["kind"]) != ("listed", "lib"):
            raise ValueError("unexpected test binary kind")
        cases = suite["testcases"]
        selected = sum(not row["ignored"] and row["filter-match"]["status"] == "matches" for row in cases.values())
        return {
            "archive_sha256": digest, "archive_bytes": archive.stat().st_size,
            "source": source, "manifest": checks, "child_processes": children, "native_test_binary": candidate,
            "archive_member_count": len(seen), "roster_size": len(cases), "selected": selected,
            "ignored": sum(row["ignored"] for row in cases.values()), "native_tool": z.read("nextest-version.txt").decode().splitlines()[0],
        }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("archive", type=Path)
    ap.add_argument("--digest", required=True)
    ap.add_argument("--source", required=True)
    args = ap.parse_args()
    print(json.dumps(read(args.archive, args.source, args.digest), sort_keys=True, indent=2))
