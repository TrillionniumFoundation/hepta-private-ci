"""Recover only frozen V3 training inputs and prior source censuses into a new directory."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile


ARCHIVE_SHA256 = "4adb728e85274e34894918014ef5d8dd70d3303c3273cbe36cd3e20e38ad5e88"
SELECTED = {
    "raw/data/data_receipt.json", "raw/data/predictors.json", "raw/data/sources.json",
    "raw/data/train_labels.json", "raw/features/features.npz", "raw/features/plan.json",
    "raw/features/report.json", "raw/prior-v1/sources.json", "raw/prior-v2/sources.json",
    "raw/run/inputs/protocol.json",
}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def recover(evidence, output):
    evidence, output = Path(evidence), Path(output)
    manifest_path = evidence / "raw-evidence-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    if (manifest["archive_sha256"] != ARCHIVE_SHA256 or manifest["archive_bytes"] != 45289220
            or len(manifest["parts"]) != 87):
        raise ValueError("unexpected V3 evidence archive")
    expected = {row["path"]: row for row in manifest["files"] if row["path"] in SELECTED}
    if set(expected) != SELECTED:
        raise ValueError("registered V3 input missing from committed manifest")
    output.mkdir(parents=True, exist_ok=False)
    archive_path = output / "v3-input-source.tar.xz"
    with archive_path.open("xb") as stream:
        for index, part in enumerate(manifest["parts"]):
            relative = f"raw/part-{index:04d}.bin"
            if part["path"] != relative:
                raise ValueError("unexpected archive part order")
            path = evidence / relative
            if path.is_symlink() or not path.is_file() or path.stat().st_size != part["bytes"]:
                raise ValueError("invalid V3 evidence part")
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != part["sha256"]:
                raise ValueError("V3 evidence part hash differs")
            stream.write(payload)
    if archive_path.stat().st_size != 45289220 or digest(archive_path) != ARCHIVE_SHA256:
        raise ValueError("reassembled V3 archive hash differs")
    extracted = set()
    with tarfile.open(archive_path, "r|xz") as archive:
        for member in archive:
            if member.name not in SELECTED:
                continue
            identity = expected[member.name]
            if (member.name in extracted or not member.isfile() or member.size != identity["bytes"]
                    or member.size > 2 << 20):
                raise ValueError("duplicate or invalid selected archive member")
            payload = archive.extractfile(member).read()
            if hashlib.sha256(payload).hexdigest() != identity["sha256"]:
                raise ValueError("selected V3 input differs from manifest")
            target = output / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(payload)
            extracted.add(member.name)
    if extracted != SELECTED:
        raise ValueError("selected V3 inputs incomplete")
    receipt = {"archive_sha256": ARCHIVE_SHA256, "committed_manifest_sha256": digest(manifest_path),
               "recovered_files": [expected[k] for k in sorted(expected)],
               "withheld_files_extracted": False, "authority": "DENY_ALL"}
    with (output / "recovery_receipt.json").open("x") as stream:
        json.dump(receipt, stream, sort_keys=True)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--output", required=True)
    print(json.dumps(recover(**vars(parser.parse_args())), sort_keys=True))
