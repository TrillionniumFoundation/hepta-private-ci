"""Restore only pinned V6 source data/checkpoints, checking every selected file."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile


ARCHIVE_SHA256 = "ddbdf10b4397c8538183df8fa7c16f08c5fba226a304ff7cb55574ddb97e951e"


def restore(archive, destination):
    archive, destination = Path(archive), Path(destination)
    actual = hashlib.file_digest(archive.open("rb"), "sha256").hexdigest()
    if actual != ARCHIVE_SHA256:
        raise ValueError("Original V6 archive identity mismatch")
    destination.mkdir(parents=True, exist_ok=True)
    verified = []
    with tarfile.open(archive, "r:gz") as source:
        manifest_raw = source.extractfile("FULL002_MANIFEST.json").read()
        manifest = json.loads(manifest_raw)
        expected = {entry["path"]: entry for entry in manifest["files"]}
        for member in source:
            name = PurePosixPath(member.name)
            selected = (len(name.parts) == 2 and name.parts[0] == "ndu-data"
                        or len(name.parts) == 3 and name.parts[:2] == ("ndu-runs", "full-002"))
            if not selected:
                continue
            if (not member.isfile() or name.is_absolute() or ".." in name.parts
                    or member.name not in expected):
                raise ValueError("Unsafe or unregistered archive member")
            raw = source.extractfile(member).read()
            entry = expected[member.name]
            digest = hashlib.sha256(raw).hexdigest()
            if digest != entry["sha256"] or len(raw) != entry["bytes"]:
                raise ValueError(f"Corrupt archived member: {member.name}")
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != raw:
                raise ValueError(f"Refusing to replace a different restored asset: {target}")
            target.write_bytes(raw)
            verified.append({"path": member.name, "bytes": len(raw), "sha256": digest})
    receipt = {"schema": "hepta.ndu.repair-restoration.v1", "archive_sha256": actual,
               "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
               "selected_files": verified, "historical_full002_only": True,
               "oct25_26_four_modal_assets_restored": False}
    (destination / "RESTORATION.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("destination")
    args = parser.parse_args()
    receipt = restore(args.archive, args.destination)
    print(json.dumps({"files": len(receipt["selected_files"]),
                      "archive_sha256": receipt["archive_sha256"]}))
