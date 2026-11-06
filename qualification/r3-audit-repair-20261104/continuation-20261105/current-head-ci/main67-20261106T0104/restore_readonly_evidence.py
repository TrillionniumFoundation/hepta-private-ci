#!/usr/bin/env python3
"""Restore complete frozen evidence and execute its unchanged read-only verifier."""
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


def check(raw, declaration):
    assert identity(raw) == {k: declaration[k] for k in ("bytes", "sha256", "git_blob")}


def main(package):
    manifest = load(package / "member-manifest.json")
    transport = load(package / "archive-transport.json")
    spec = load(package / "replay-spec.json")
    pieces = []
    for part in transport["parts"]:
        assert Path(part["path"]).name == part["path"]
        raw = (package / part["path"]).read_bytes()
        check(raw, part)
        pieces.append(raw)
    encoded = b"".join(pieces)
    assert len(encoded) == transport["encoded_bytes"]
    archive = base64.b64decode(encoded, validate=True)
    check(archive, transport["archive"])
    if (package / "evidence.tar.gz").exists():
        assert (package / "evidence.tar.gz").read_bytes() == archive
    declarations = manifest["members"]
    assert len(declarations) == manifest["count"] == len({row["path"] for row in declarations})
    assert sum(row["bytes"] for row in declarations) == manifest["total_bytes"]
    originals = {}
    with tempfile.TemporaryDirectory(prefix="hepta-readonly-evidence-replay-") as temporary:
        destination = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(archive)), mode="r:") as tar:
            members = tar.getmembers()
            assert [entry.name for entry in members] == [row["path"] for row in declarations]
            for entry, row in zip(members, declarations):
                path = PurePosixPath(entry.name)
                assert entry.isfile() and not path.is_absolute() and ".." not in path.parts and path.parts[0] == "root"
                raw = tar.extractfile(entry).read()
                check(raw, row)
                originals[entry.name] = raw
                file = destination.joinpath(*path.parts)
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(raw)
                file.chmod(row["mode"])
                assert file.read_bytes() == raw
        root = destination / "root"
        verifier = root / spec["verifier"]
        args = [value.replace("{root}", str(root)) for value in spec["arguments"]]
        run = subprocess.run([sys.executable, str(verifier), *args], cwd=root,
                             env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                             capture_output=True, timeout=60)
        assert run.returncode == 0, (run.returncode, run.stderr.decode(errors="replace"))
        assert run.stderr == b"", run.stderr.decode(errors="replace")
        expected = originals["root/" + spec["frozen_stdout"]]
        assert run.stdout == expected
        for name, raw in originals.items():
            assert (destination / name).read_bytes() == raw
        after = {file.relative_to(destination).as_posix() for file in destination.rglob("*") if file.is_file()}
        assert after == set(originals)
        result = {"schema": "hepta-readonly-evidence-portable-replay-v1", "kind": spec["kind"],
                  "authority": spec["authority"], "status": "COMPLETE_BYTES_AND_FROZEN_STDOUT_EQUAL",
                  "member_count": len(originals), "member_bytes": manifest["total_bytes"],
                  "archive": identity(archive), "verifier": spec["verifier"],
                  "verifier_exit": run.returncode, "verifier_stderr_bytes": len(run.stderr),
                  "verifier_stdout": identity(run.stdout), "frozen_stdout": spec["frozen_stdout"],
                  "actual_stdout_equals_complete_frozen_stdout_bytes": True,
                  "every_original_member_compared_before_and_after_with_direct_bytes_equality": True,
                  "unexpected_files": [], "new_native_execution_or_capacity_query": False,
                  "product_compile_test_fmt": False, "network_or_ref_mutation": False,
                  "scope": spec["scope"]}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("package", nargs="?", type=Path, default=Path(__file__).resolve().parent)
    main(parser.parse_args().package.resolve())
