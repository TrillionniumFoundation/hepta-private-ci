#!/usr/bin/env python3
"""Small synthetic byte-integrity and rejection checks; never opens study data."""

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import socket
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile


HERE = Path(__file__).absolute().parent
TOOL = HERE / "pack_results.py"
spec = importlib.util.spec_from_file_location("publication_pack_results", TOOL)
packaging = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packaging)


def execute(arguments, success=True):
    result = subprocess.run([sys.executable, "-B", str(TOOL), *arguments], capture_output=True, text=True)
    assert (result.returncode == 0) == success, (arguments, result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout) if success else result.stderr.strip()


def npy_bytes(values):
    header = f"{{'descr': '<i8', 'fortran_order': False, 'shape': ({len(values)},), }}"
    padding = (64 - (10 + len(header) + 1) % 64) % 64
    header = (header + " " * padding + "\n").encode("ascii")
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + struct.pack(f"<{len(values)}q", *values)


def test(output):
    checks = []

    def record(name, detail):
        checks.append({"name": name, "passed": True, "detail": detail})

    with tempfile.TemporaryDirectory(prefix="hcsn-publication-test-") as temporary:
        base = Path(temporary)
        source, development = base / "source", base / "development01"
        source.mkdir()
        development.mkdir()
        random_bytes = random.Random(713).randbytes(90_000)
        fixtures = {"source_snapshot/model.py": b"FROZEN_FIXTURE = True\n", "receipts/failure.json": b'{"status":"interrupted"}\n',
                    "checkpoints/selected.pt": random_bytes, "empty.bin": b"", "unicode/条件.txt": "finite grid\n".encode(),
                    "long/" + "a" * 140 + ".txt": b"long PAX name\n"}
        identities = npy_bytes(list(range(1000)))
        for index in range(3):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                for name, content in {"identities.npy": identities, "opaque_repeat.bin": random_bytes,
                                      "score.npy": npy_bytes([index])}.items():
                    archive.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), content)
            fixtures[f"raw/sample_{index}.npz"] = buffer.getvalue()
        for name, data in fixtures.items():
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (development / "diagnostic.json").write_bytes(b'{"split":"synthetic"}\n')
        for name in ["__pycache__/cached.pyc", "archives/prior.bin", "prior.tar.xz"]:
            target = source / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"must be excluded")
        server = socket.socket(socket.AF_UNIX)
        socket_note = None
        try:
            server.bind(str(source / "worker.socket"))
        except PermissionError as error:
            socket_note = f"AF_UNIX fixture creation denied by execution environment: {error}"
        roots = ["--root", f"study={source}", "--root", f"study/development/development01={development}"]
        bundle, restored = base / "bundle", base / "restored"
        packed = execute(["pack", *roots, "--output", str(bundle), "--dict-mib", "4"])
        manifest = json.loads((bundle / "manifest.json").read_text())
        assert len(manifest["parts"]) >= 2
        restored_receipt = execute(["restore", "--bundle", str(bundle), "--destination", str(restored),
                                    "--manifest-sha256", packed["manifest_sha256"]])
        expected = {"study/" + name: data for name, data in fixtures.items()}
        expected["study/development/development01/diagnostic.json"] = (development / "diagnostic.json").read_bytes()
        actual = {str(path.relative_to(restored)): path.read_bytes() for path in restored.rglob("*") if path.is_file()}
        assert actual == expected
        assert all(path.stat().st_mtime_ns == 0 for path in restored.rglob("*") if path.is_file())
        record("pack_restore_byte_equality", {"members": len(expected), "parts": len(manifest["parts"]),
                                               "input_bytes": packed["source_bytes"], "compressed_bytes": packed["archive_bytes"]})
        expected_reasons = {"excluded_directory", "existing_archive"}
        if socket_note is None:
            expected_reasons.add("socket")
        assert {entry["reason"] for entry in manifest["excluded"]} == expected_reasons
        record("cache_archive_exclusions", {"excluded": manifest["excluded"], "socket_fixture_limitation": socket_note})
        again = execute(["restore", "--bundle", str(bundle), "--destination", str(restored)])
        assert again["already_identical_members"] == len(expected)
        record("identical_existing_files_are_idempotent", again["already_identical_members"])
        for path in source.rglob("*"):
            if path.is_file():
                os.utime(path, (123456789, 123456789))
        bundle2 = base / "bundle2"
        execute(["pack", *roots, "--output", str(bundle2), "--dict-mib", "4"])
        assert {p.name: p.read_bytes() for p in bundle.iterdir()} == {p.name: p.read_bytes() for p in bundle2.iterdir()}
        record("reproducible_despite_source_mtime_change", {"all_manifest_and_shard_bytes_identical": True})
        victim = restored / "study/checkpoints/selected.pt"
        victim.write_bytes(b"different existing content")
        reason = execute(["restore", "--bundle", str(bundle), "--destination", str(restored)], success=False)
        assert victim.read_bytes() == b"different existing content" and "overwrite different" in reason
        record("different_existing_content_refused", reason)
        first_part = bundle / manifest["parts"][0]["path"]
        original_part = first_part.read_bytes()
        first_part.write_bytes(bytes([original_part[0] ^ 1]) + original_part[1:])
        corrupt_destination = base / "corrupt-destination"
        reason = execute(["restore", "--bundle", str(bundle), "--destination", str(corrupt_destination)], success=False)
        assert not corrupt_destination.exists() and "Part hash mismatch" in reason
        record("tampered_shard_refused_before_destination_creation", reason)
        first_part.write_bytes(original_part)
        linked_source = base / "linked-source"
        linked_source.mkdir()
        (linked_source / "escape").symlink_to(source)
        record("source_symlink_refused", execute(["pack", "--root", f"study={linked_source}", "--output", str(base / "bad")], success=False))
        malicious_destination = base / "symlink-destination"
        malicious_destination.mkdir()
        (malicious_destination / "study").symlink_to(development, target_is_directory=True)
        record("destination_ancestor_symlink_refused", execute(["restore", "--bundle", str(bundle), "--destination", str(malicious_destination)], success=False))
        for name in ["../escape", "/absolute", "normal/../../escape", "a\\escape", "C:/drive", "a//b", "a/./b"]:
            try:
                packaging.relative_path(name)
            except packaging.ArchiveError:
                continue
            raise AssertionError(name)
        record("unsafe_member_paths_refused", 7)
        for names in [["a", "a"], ["a", "a/b"]]:
            try:
                packaging.validate_names(names)
            except packaging.ArchiveError:
                continue
            raise AssertionError(names)
        record("manifest_duplicates_and_file_parent_collisions_refused", 2)
        safe_member = {"path": "safe", "bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()}
        for label, member_types in [("duplicate", [tarfile.REGTYPE, tarfile.REGTYPE]), ("symlink", [tarfile.SYMTYPE]),
                                    ("hardlink", [tarfile.LNKTYPE]), ("directory", [tarfile.DIRTYPE]), ("fifo", [tarfile.FIFOTYPE])]:
            malicious_tar, extraction = base / f"{label}.tar.xz", base / f"{label}-stage"
            extraction.mkdir()
            with tarfile.open(malicious_tar, "w:xz") as archive:
                for member_type in member_types:
                    info = tarfile.TarInfo("safe")
                    info.type, info.mode = member_type, 0o644
                    info.size = 1 if member_type == tarfile.REGTYPE else 0
                    info.linkname = "../outside" if member_type in [tarfile.SYMTYPE, tarfile.LNKTYPE] else ""
                    archive.addfile(info, io.BytesIO(b"x") if info.size else None)
            try:
                packaging.extract_verified(malicious_tar, {"members": [safe_member]}, extraction)
            except packaging.ArchiveError as error:
                record(f"tar_{label}_refused", str(error))
                continue
            raise AssertionError(label)
        server.close()
    result = {"scope": "synthetic publication mechanics only; no scientific or test-split data accessed",
              "passed": True, "checks": checks, "check_count": len(checks),
              "tool_sha256": hashlib.sha256(TOOL.read_bytes()).hexdigest(),
              "validation_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "fixture_pack_receipt": packed, "fixture_restore_receipt": restored_receipt}
    with output.open("x") as destination:
        json.dump(result, destination, indent=2, sort_keys=True)
        destination.write("\n")
    return {"passed": True, "checks": len(checks), "output": str(output), "tool_sha256": result["tool_sha256"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(test(parser.parse_args().output), sort_keys=True))
