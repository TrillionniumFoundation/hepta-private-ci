"""Restore a lossless evidence archive without executing its contents."""
from pathlib import Path, PurePosixPath
import argparse
import base64
import hashlib
import io
import json
import tarfile


def identity(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(
        b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.resolve()
    assert not destination.exists(), "destination must be a new owned directory"
    manifest = json.loads((args.bundle / "BUNDLE_MANIFEST.json").read_bytes())
    parts = []
    for entry in manifest["parts"]:
        name = PurePosixPath(entry["path"])
        assert len(name.parts) == 1 and not name.is_absolute()
        data = (args.bundle / entry["path"]).read_bytes()
        assert identity(data) == {key: entry[key] for key in ("bytes", "git_blob", "sha256")}
        parts.append(data)
    archive_bytes = base64.b64decode(b"".join(parts), validate=True)
    assert identity(archive_bytes) == manifest["compressed_archive_computed_identity"]
    expected = {entry["path"]: entry for entry in manifest["members"]}
    assert len(expected) == len(manifest["members"])
    extracted = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for entry in archive:
            name = PurePosixPath(entry.name)
            assert entry.isfile() and not name.is_absolute() and ".." not in name.parts
            assert name.parts[0] == "packet" and "\\" not in entry.name
            assert entry.name in expected and entry.name not in extracted
            data = archive.extractfile(entry).read()
            assert identity(data) == {key: expected[entry.name][key] for key in ("bytes", "git_blob", "sha256")}
            extracted[entry.name] = data
    assert set(extracted) == set(expected)
    destination.mkdir(parents=True)
    for name, data in extracted.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(json.dumps({"complete_archive_verified": True, "members_restored": len(extracted),
                      "parts_verified": len(parts), "product_code_executed": False}, indent=2))


if __name__ == "__main__":
    main()
