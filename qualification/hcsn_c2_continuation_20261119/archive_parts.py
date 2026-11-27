"""Split or reassemble an exact archive; retain every byte and every part hash."""

import argparse
import hashlib
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_identity(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"bytes": size, "sha256": digest.hexdigest()}


def split(archive, receipt, directory):
    expected = json.loads(receipt.read_text())
    observed = file_identity(archive)
    require(observed == {key: expected[key] for key in ("bytes", "sha256")}, "complete original archive identity")
    directory.mkdir(parents=True, exist_ok=True)
    parts, offset = [], 0
    with archive.open("rb") as stream:
        while data := stream.read(4 * 1024**2):
            name = f"archive.part{len(parts):04d}"
            path = directory / name
            digest = hashlib.sha256(data).hexdigest()
            if path.exists():
                require(file_identity(path) == {"bytes": len(data), "sha256": digest}, "existing exact part")
            else:
                with path.open("xb") as target:
                    target.write(data)
            parts.append({"file": name, "offset": offset, "bytes": len(data), "sha256": digest,
                          "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()})
            offset += len(data)
    require(offset == observed["bytes"] and file_identity(archive) == observed, "archive unchanged during split")
    value = {"schema": "hcsn-c2-lossless-archive-parts-v1", "archive_name": archive.name,
             "archive": observed, "original_artifact_receipt_sha256": file_identity(receipt)["sha256"],
             "part_limit_bytes": 4 * 1024**2, "parts": parts,
             "scope": "All exact tar.xz bytes, split only for bounded transport; no checkpoint selection or transcoding."}
    contents = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
    manifest = directory / "PARTS.json"
    if manifest.exists():
        require(manifest.read_bytes() == contents, "existing exact part manifest")
    else:
        with manifest.open("xb") as target:
            target.write(contents)
    verify_parts(manifest)
    return {"parts_manifest": str(manifest), "parts": len(parts), "archive": observed,
            "all_parts_and_aggregate_verified": True, "model_forward_calls": 0, "optimizer_calls": 0}


def verify_parts(manifest, target=None):
    value = json.loads(manifest.read_text())
    digest, offset, names = hashlib.sha256(), 0, set()
    for part in value["parts"]:
        name = part["file"]
        require(Path(name).name == name and name not in names and part["offset"] == offset,
                "unique contiguous relative parts")
        names.add(name)
        path = manifest.parent / name
        require(path.is_file() and not path.is_symlink(), "regular part")
        data = path.read_bytes()
        require(len(data) == part["bytes"] and hashlib.sha256(data).hexdigest() == part["sha256"], "exact part " + name)
        require(hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == part["git_blob_sha"],
                "part Git object identity")
        digest.update(data)
        offset += len(data)
        if target is not None:
            target.write(data)
    actual = {"bytes": offset, "sha256": digest.hexdigest()}
    require(actual == value["archive"], "complete assembled archive identity")
    return actual


def assemble(manifest, output):
    expected = verify_parts(manifest)
    if output.exists():
        require(file_identity(output) == expected, "existing output must already be the exact complete archive")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("xb") as target:
            verify_parts(manifest, target)
        require(file_identity(output) == expected, "written complete archive identity")
    return {"archive": str(output), **expected, "all_parts_and_aggregate_verified": True,
            "model_forward_calls": 0, "optimizer_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    splitting = commands.add_parser("split")
    splitting.add_argument("--archive", type=Path, required=True)
    splitting.add_argument("--receipt", type=Path, required=True)
    splitting.add_argument("--directory", type=Path, required=True)
    assembling = commands.add_parser("assemble")
    assembling.add_argument("--parts", type=Path, required=True)
    assembling.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = (split(args.archive, args.receipt, args.directory) if args.command == "split"
              else assemble(args.parts, args.output))
    print(json.dumps(result, indent=2, sort_keys=True))
