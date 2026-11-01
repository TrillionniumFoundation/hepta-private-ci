"""Rebuild the historical V3 replay inputs from a complete repository checkout.

No network, credentials, model fitting, or fresh-data selection is performed.
Exact original source, part, archive and member hashes are mandatory. Newer
versions of a source file are rejected rather than silently substituted.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile


SPEC = Path(__file__).with_name("RECOVERY_SPEC.json")
REPO = Path(__file__).resolve().parents[3]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or not path.parts:
        raise ValueError("Unsafe recovery path: " + name)
    return Path(*path.parts)


def checked_file(root, name, expected_sha, expected_bytes=None):
    path = root / relative(name)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Recovery input escapes the checkout: " + name)
    data = path.read_bytes()
    if digest(data) != expected_sha or (expected_bytes is not None and len(data) != expected_bytes):
        raise ValueError("Original historical identity mismatch: " + name)
    return data


def preserve(root, name, data):
    path = root / relative(name)
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Recovery output escapes its destination: " + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError("Different existing recovery output: " + str(path))
        return
    with path.open("xb") as stream:
        stream.write(data)


def recover(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if source == output:
        raise ValueError("Source checkout and recovered output must differ")
    spec = json.loads(SPEC.read_text())
    source_records, archive_records = [], []
    for entry in spec["sources"]:
        data = checked_file(source, entry["path"], entry["sha256"], entry["bytes"])
        actual_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual_blob != entry["git_blob_sha1"]:
            raise ValueError("Original Git blob mismatch: " + entry["path"])
        preserve(output, entry["path"], data)
        source_records.append(dict(entry, matches=True))
    for archive in spec["archives"]:
        manifest_bytes = checked_file(source, archive["manifest"], archive["manifest_sha256"])
        manifest = json.loads(manifest_bytes)
        if manifest["archive_sha256"] != archive["archive_sha256"]:
            raise ValueError("Archive identity differs from the frozen recovery specification")
        base = relative(archive["manifest"]).parent
        parts = [checked_file(source, str(base / relative(part["path"])), part["sha256"], part["bytes"])
                 for part in manifest["parts"]]
        payload = b"".join(parts)
        if len(payload) != manifest["compressed_bytes"] or digest(payload) != archive["archive_sha256"]:
            raise ValueError("Reassembled historical archive identity differs")
        expected = {member["path"]: member for member in manifest["members"]}
        if len(expected) != len(manifest["members"]):
            raise ValueError("Duplicated declared archive member")
        seen, retained, retained_bytes = set(), 0, 0
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tar:
            for member in tar:
                path = relative(member.name)
                if not member.isfile() or member.name in seen or member.name not in expected:
                    raise ValueError("Unexpected historical archive member: " + member.name)
                seen.add(member.name)
                declared = expected[member.name]
                if member.size != declared["bytes"]:
                    raise ValueError("Historical archive member length mismatch")
                data = tar.extractfile(member).read()
                if digest(data) != declared["sha256"]:
                    raise ValueError("Historical archive member hash mismatch")
                if any(member.name.startswith(prefix) for prefix in archive["keep_member_prefixes"]):
                    preserve(output, str(relative(archive["destination"]) / path), data)
                    retained += 1
                    retained_bytes += len(data)
        if seen != set(expected):
            raise ValueError("Historical archive is incomplete")
        preserve(output, archive["manifest"], manifest_bytes)
        archive_records.append({"manifest": archive["manifest"],
            "archive_sha256": archive["archive_sha256"], "verified_parts": len(parts),
            "verified_members": len(seen), "retained_members": retained,
            "retained_bytes": retained_bytes})
    source_receipt = {"ref": spec["commit"], "files": source_records}
    archive_receipt = {"scope": spec["scope"], "records": archive_records}
    preserve(output, "SOURCE_VERIFICATION.json", (json.dumps(source_receipt, indent=2) + "\n").encode())
    preserve(output, "ARCHIVE_RECOVERY_RECEIPT.json", (json.dumps(archive_receipt, indent=2) + "\n").encode())
    return {"scope": spec["scope"], "sources_verified": len(source_records),
            "archives": archive_records, "output": str(output),
            "fresh_confirmation": False, "v6_restored": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=REPO)
    parser.add_argument("--output", type=Path, default=REPO / "recovered/v3")
    args = parser.parse_args()
    print(json.dumps(recover(args.source, args.output), indent=2))
