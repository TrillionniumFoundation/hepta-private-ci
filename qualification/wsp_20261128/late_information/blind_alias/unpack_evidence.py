"""Verify all chunk/member hashes and extract into a new directory only."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    manifest = json.loads((source/"EVIDENCE_MANIFEST.json").read_text())
    chunks = []
    for item in manifest["chunks"]:
        raw = (source/item["path"]).read_bytes()
        assert len(raw) == item["bytes"]
        assert hashlib.sha256(raw).hexdigest() == item["sha256"]
        chunks.append(raw)
    raw = b"".join(chunks)
    assert len(raw) == manifest["archive_bytes"]
    assert hashlib.sha256(raw).hexdigest() == manifest["archive_sha256"]
    uncompressed = gzip.decompress(raw)
    assert len(uncompressed) == manifest["uncompressed_tar_bytes"]
    assert hashlib.sha256(uncompressed).hexdigest() == manifest["uncompressed_tar_sha256"]
    expected = {x["path"]: x for x in manifest["files"]}
    with tarfile.open(fileobj=io.BytesIO(uncompressed)) as archive:
        assert len(archive.getmembers()) == len(expected)
        for member in archive.getmembers():
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and ".." not in path.parts
            data = archive.extractfile(member).read()
            row = expected[member.name]
            assert len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"]
        args.destination.mkdir(parents=True, exist_ok=False)
        archive.extractall(args.destination, filter="data")
    print(json.dumps({"status": "PASS", "verified_files": len(expected), "destination": str(args.destination.resolve())}))


if __name__ == "__main__":
    main()
