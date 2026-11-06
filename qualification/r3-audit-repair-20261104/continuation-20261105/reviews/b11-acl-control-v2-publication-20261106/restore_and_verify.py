#!/usr/bin/env python3
"""Restore an immutable source-publication archive and replay its offline verifier.

No network, repository ref, workflow dispatch, product compiler, formatter, or
native test action is performed. All verifier writes happen in a temporary copy.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
import tempfile


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def load(path):
    return json.loads(path.read_bytes())


def same(raw, expected):
    assert identity(raw) == {k: expected[k] for k in ("bytes", "sha256", "git_blob")}


def main(package):
    manifest = load(package / "member-manifest.json")
    transport = load(package / "archive-transport.json")
    spec = load(package / "replay-spec.json")
    pieces = []
    for part in transport["parts"]:
        assert Path(part["path"]).name == part["path"]
        raw = (package / part["path"]).read_bytes()
        same(raw, part)
        pieces.append(raw)
    encoded = b"".join(pieces)
    assert len(encoded) == transport["encoded_bytes"]
    archive = base64.b64decode(encoded, validate=True)
    same(archive, transport["archive"])
    if (package / "evidence.tar.gz").exists():
        assert (package / "evidence.tar.gz").read_bytes() == archive
    expected_stdout = (package / spec["expected_stdout_file"]).read_bytes()
    same(expected_stdout, spec["expected_stdout"])
    members = manifest["members"]
    assert manifest["count"] == len(members)
    assert manifest["total_bytes"] == sum(row["bytes"] for row in members)
    assert len({row["path"] for row in members}) == len(members)
    with tempfile.TemporaryDirectory(prefix="hepta-publication-replay-") as directory:
        destination = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
            actual = tar.getmembers()
            assert [entry.name for entry in actual] == [row["path"] for row in members]
            for entry, row in zip(actual, members):
                path = PurePosixPath(entry.name)
                assert entry.isfile() and not path.is_absolute() and ".." not in path.parts
                assert path.parts[0] == "root"
                raw = tar.extractfile(entry).read()
                same(raw, row)
                file = destination.joinpath(*path.parts)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(raw)
                file.chmod(row["mode"])
        restored_root = destination / "root"
        verifier = restored_root / spec["verifier"]
        arguments = [arg.replace("{root}", str(restored_root)) for arg in spec["arguments"]]
        run = subprocess.run([sys.executable, str(verifier), *arguments], cwd=restored_root,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             capture_output=True, timeout=60)
        assert run.returncode == 0, (run.returncode, run.stderr.decode(errors="replace"))
        assert run.stderr == b"", run.stderr.decode(errors="replace")
        assert run.stdout == expected_stdout, (run.stdout, expected_stdout)
        generated = []
        original_by_path = {row["path"]: row for row in members}
        for path in spec["verifier_written_frozen_files"]:
            actual_raw = (restored_root / path).read_bytes()
            frozen = original_by_path["root/" + path]
            same(actual_raw, frozen)
            generated.append({"path": path, **identity(actual_raw), "equals_complete_frozen_bytes": True})
        for row in members:
            same((destination / row["path"]).read_bytes(), row)
        restored_files = {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()}
        assert restored_files == set(original_by_path), sorted(restored_files - set(original_by_path))
        result = {"schema": "hepta-source-publication-portable-replay-v1",
                  "status": "LOSSLESS_ARCHIVE_AND_FROZEN_VERIFIER_OUTPUTS_REPRODUCED",
                  "package_kind": spec["kind"], "authority": spec["authority"],
                  "archive": identity(archive), "member_count": len(members),
                  "member_bytes": manifest["total_bytes"],
                  "all_archive_members_verified_before_and_after_replay": True,
                  "verifier": spec["verifier"], "verifier_exit_code": run.returncode,
                  "verifier_stderr_bytes": len(run.stderr), "verifier_stdout": identity(run.stdout),
                  "stdout_equals_expected_complete_bytes": True,
                  "expected_stdout_provenance": spec["expected_stdout_provenance"],
                  "regenerated_frozen_files": generated,
                  "unexpected_files_created": [], "writes_limited_to_disposable_restoration": True,
                  "native_or_product_compilation": False, "formatter": False,
                  "external_ref_mutation": False, "network": False,
                  "qualification": "SOURCE_PUBLICATION_CUSTODY_ONLY"}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    main(parser.parse_args().package.resolve())
