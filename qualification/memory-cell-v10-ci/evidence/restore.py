"""Verify a retained original Actions ZIP and optionally restore its regular files.

Examples, when running from this evidence directory:
  python restore.py --attempt native-attempt-01 --verify-only
  python restore.py --attempt native-attempt-04 --output /tmp/v10-native-restored

The evidence directory contains either artifact.zip or ZIP_PARTS.json plus
canonical base64 chunks. Both representations must reproduce the GitHub ZIP
digest. Nonregular entries were recorded by the CI packer, never followed.
"""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import tempfile
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_zip(attempt):
    origin = json.loads((attempt / "GITHUB_ORIGIN.json").read_text())
    expected = {"bytes": origin["artifact"]["size_in_bytes"],
                "sha256": origin["artifact"]["digest"].removeprefix("sha256:")}
    require(0 < expected["bytes"] <= 512 * 1024**2, "ZIP size is outside the retained profile")
    direct = attempt / "artifact.zip"
    if direct.is_file():
        raw = direct.read_bytes()
    else:
        transport = json.loads((attempt / "ZIP_PARTS.json").read_text())
        require(transport["schema"] == "hepta.memory.v10.retained-zip-parts.v1", "unknown part schema")
        require(transport["zip"] == expected, "part transport and GitHub identity differ")
        parts, total = [], 0
        for number, part in enumerate(transport["parts"]):
            require(part["path"] == f"zip-parts/part-{number:04d}.b64", "part order or path differs")
            path = attempt / part["path"]
            require(path.is_file() and not path.is_symlink(), "part is not a regular file")
            encoded = path.read_bytes()
            require(identity(encoded) == part["encoded"], "encoded part identity differs")
            decoded = base64.b64decode(encoded.removesuffix(b"\n"), validate=True)
            require(identity(decoded) == part["decoded"] and len(decoded) <= 400_000,
                    "decoded part identity differs")
            total += len(decoded)
            require(total <= expected["bytes"], "parts exceed ZIP size")
            parts.append(decoded)
        require(parts, "empty ZIP transport")
        raw = b"".join(parts)
    require(identity(raw) == expected, "ZIP differs from GitHub's recorded size or digest")
    return raw, origin


def verify(attempt, output):
    raw, origin = read_zip(attempt)
    expected_names = {"INDEX.json", "receipt.json", "memory-v10-evidence.tar.xz"}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(len(archive.infolist()) == 3 and set(archive.namelist()) == expected_names,
                "unexpected ZIP inventory")
        contents = {}
        for member in archive.infolist():
            require(not member.is_dir() and not member.flag_bits & 1
                    and 0 < member.file_size <= 512 * 1024**2, "unsafe ZIP entry")
            contents[member.filename] = archive.read(member)
    index = json.loads(contents["INDEX.json"])
    require(index["schema"] == "hepta.memory.v10.ci-transport.v1", "unexpected CI index schema")
    require(identity(contents["memory-v10-evidence.tar.xz"]) == {
        key: index["archive"][key] for key in ("bytes", "sha256")}, "tar archive digest differs")
    receipt = json.loads(contents["receipt.json"])
    require(receipt["source_commit"] == origin["run"]["head_sha"], "receipt source and run differ")
    found, total = set(), 0
    with tempfile.TemporaryDirectory(prefix="hepta-v10-restore-") as temporary:
        staging = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(contents["memory-v10-evidence.tar.xz"]), mode="r:xz") as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                require(member.isfile() and path.parts and path.parts[0] == "memory-v10-ci-output"
                        and ".." not in path.parts and not path.is_absolute() and member.name not in found,
                        "unsafe or duplicate tar entry")
                require(member.size <= 512 * 1024**2 and len(found) < 100_000,
                        "tar entry exceeds the retained profile")
                total += member.size
                require(total <= 2 * 1024**3, "expanded tar exceeds bound")
                data = archive.extractfile(member).read()
                require(identity(data) == index["files"].get(member.name), "tar member identity differs")
                if member.name == "memory-v10-ci-output/receipt.json":
                    require(data == contents["receipt.json"], "inner and outer receipts differ")
                if output is not None:
                    target = staging.joinpath(*path.parts[1:])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                found.add(member.name)
        require(found == set(index["files"]) and "memory-v10-ci-output/receipt.json" in found,
                "tar/index inventory differs or its receipt is absent")
        if output is not None:
            require(not output.exists(), "output must not already exist")
            import shutil
            shutil.copytree(staging, output)
    return {"schema": "hepta.memory.v10.retained-evidence-verification.v1",
            "run_id": origin["run"]["id"], "zip": identity(raw), "archive": index["archive"],
            "verified_regular_files": len(found), "expanded_bytes": total,
            "receipt_passed": receipt.get("passed"), "source_commit": receipt["source_commit"],
            "output": str(output) if output is not None else None,
            "nonregular_entries_restored": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--verify-only", action="store_true")
    mode.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.attempt.absolute(), args.output), indent=2))
