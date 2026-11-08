"""Verify original archives and members without extracting or running them."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reconstruct-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    index = json.loads((root / "manifest.json").read_text())
    if args.reconstruct_dir is not None:
        args.reconstruct_dir.mkdir(parents=True, exist_ok=True)
    for entry in index["packets"]:
        manifest_bytes = (root / entry["manifest_path"]).read_bytes()
        assert sha256(manifest_bytes) == entry["manifest_sha256"], entry["packet_id"]
        packet = json.loads(manifest_bytes)
        original = bytearray()
        for sequence, chunk in enumerate(packet["publication_chunks"], 1):
            data = (root / chunk["path"]).read_bytes()
            assert chunk["sequence"] == sequence
            assert chunk["offset"] == len(original)
            assert len(data) == chunk["bytes"] <= index["max_chunk_bytes"]
            assert sha256(data) == chunk["sha256"], chunk["path"]
            original.extend(data)
        assert len(original) == packet["bytes"] == entry["archive_bytes"]
        assert sha256(original) == packet["sha256"] == entry["archive_sha256"]
        members = []
        with tarfile.open(fileobj=io.BytesIO(original)) as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                stream = archive.extractfile(member)
                assert stream is not None
                data = stream.read()
                members.append(
                    {"path": member.name, "bytes": len(data), "sha256": sha256(data)}
                )
        assert members == packet["file_members"], entry["packet_id"]
        if args.reconstruct_dir is not None:
            suffix = ".tar.xz" if packet["compression"] == "xz" else ".tar.gz"
            destination = args.reconstruct_dir / (entry["packet_id"] + suffix)
            with destination.open("xb") as output:
                output.write(original)
        print(f"{entry['packet_id']}: {len(members)} original file members verified")
    print("All selected packets verified. This does not imply full-history or stage qualification.")


if __name__ == "__main__":
    main()
