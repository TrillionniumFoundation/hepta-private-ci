"""Restore all non-data evidence of the original aborted cohort, with hashes."""

import argparse
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def restore(manifest_path, destination, shared_data_from=None):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest["schema"] != "hcsn-aborted-text-evidence.v1":
        raise ValueError("Unexpected archive schema")
    chunks = []
    for row in manifest["parts"]:
        if PurePosixPath(row["path"]).name != row["path"]:
            raise ValueError("Archive part must be adjacent to the manifest")
        encoded = (manifest_path.parent / row["path"]).read_bytes()
        if len(encoded) != row["bytes"] or hashlib.sha256(encoded).hexdigest() != row["sha256"]:
            raise ValueError("Encoded archive part changed")
        raw = base64.b64decode(encoded.strip(), validate=True)
        if len(raw) != row["decoded_bytes"] or hashlib.sha256(raw).hexdigest() != row["decoded_sha256"]:
            raise ValueError("Decoded archive part changed")
        chunks.append(raw)
    archive = b"".join(chunks)
    if len(archive) != manifest["compressed_bytes"] or hashlib.sha256(archive).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Whole archive changed")
    expected = {row["path"]: row for row in manifest["members"]}
    if len(expected) != len(manifest["members"]):
        raise ValueError("Duplicate archive member")
    destination = Path(destination).resolve()
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for item in tar:
            name = PurePosixPath(item.name)
            if (not item.isfile() or name.is_absolute() or ".." in name.parts
                    or "\\" in item.name or item.name not in expected or item.name in seen):
                raise ValueError("Unexpected or unsafe archive member")
            row = expected[item.name]
            data = tar.extractfile(item).read()
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Archive member identity mismatch")
            path = destination.joinpath(*name.parts)
            if path.is_symlink() or not path.resolve().is_relative_to(destination):
                raise ValueError("Destination escapes through a symlink")
            if path.exists():
                if not path.is_file() or path.read_bytes() != data:
                    raise FileExistsError("Refuse to replace different original evidence")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(data)
            seen.add(item.name)
    if seen != set(expected):
        raise ValueError("Missing archive member")
    data_count = 0
    if shared_data_from is not None:
        shared_data_from = Path(shared_data_from).resolve()
        for row in manifest["omitted_registered_data"]:
            name = PurePosixPath(row["path"])
            if name.is_absolute() or ".." in name.parts or "\\" in row["path"] or name.parts[0] != "data":
                raise ValueError("Unsafe shared-data member")
            source = shared_data_from.joinpath(*name.parts)
            if source.is_symlink() or not source.resolve().is_relative_to(shared_data_from):
                raise ValueError("Shared input escapes its source root")
            data = source.read_bytes()
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Shared registered input identity mismatch")
            path = destination.joinpath(*name.parts)
            if path.is_symlink() or not path.resolve().is_relative_to(destination):
                raise ValueError("Shared-data destination escapes its root")
            if path.exists():
                if not path.is_file() or path.read_bytes() != data:
                    raise FileExistsError("Refuse to replace different registered input")
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(data)
            data_count += 1
    return dict(restored_or_identical=len(seen), shared_registered_data_restored_or_identical=data_count,
                archive_sha256=manifest["archive_sha256"],
                registered_data_files_listed_separately=len(manifest["omitted_registered_data"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--shared-data-from", type=Path,
                        help="Restored comparison002_hosted root, whose22 shared inputs have identical declared hashes.")
    args = parser.parse_args()
    print(json.dumps(restore(Path(__file__).with_name("MANIFEST.json"), args.destination, args.shared_data_from)))
