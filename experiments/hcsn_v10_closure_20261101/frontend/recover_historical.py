"""Recover byte-verified v3 historical features/heads, never v6 or fresh media."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(data):
    return hashlib.sha256(data).hexdigest()


def recover(source, repository):
    spec_path = repository / "experiments/hcsn_v8_execution_20261101/frontend/RECOVERY_SPEC.json"
    spec = json.loads(spec_path.read_text())
    destination = repository / "recovered/v3"
    copied = []

    def install(relative, digest, size, blob=None, source_file=None):
        parts = PurePosixPath(relative)
        if parts.is_absolute() or ".." in parts.parts:
            raise ValueError("Unsafe historical member path")
        data = (source_file or (source / "recovered/v3" / relative)).read_bytes()
        if len(data) != size or sha(data) != digest:
            raise ValueError("Historical source bytes differ: " + relative)
        if blob and hashlib.sha1(b"blob " + str(size).encode() + b"\0" + data).hexdigest() != blob:
            raise ValueError("Historical Git blob differs: " + relative)
        target = destination / relative
        if target.exists() and target.read_bytes() != data:
            raise ValueError("Refusing to replace differing recovery bytes: " + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(data)
        copied.append({"path": relative, "bytes": size, "sha256": digest})

    for row in spec["sources"]:
        install(row["path"], row["sha256"], row["bytes"], row["git_blob_sha1"])
    archive_records = []
    for archive in spec["archives"]:
        raw = (source / archive["manifest"]).read_bytes()
        if sha(raw) != archive["manifest_sha256"]:
            raise ValueError("Historical transport manifest hash differs")
        manifest = json.loads(raw)
        if manifest["archive_sha256"] != archive["archive_sha256"]:
            raise ValueError("Historical archive identity differs")
        retained = 0
        for row in manifest["members"]:
            if any(row["path"].startswith(p) for p in archive["keep_member_prefixes"]):
                install(str(PurePosixPath(archive["destination"]) / row["path"]),
                        row["sha256"], row["bytes"])
                retained += 1
        archive_records.append({"manifest": archive["manifest"], "manifest_sha256": sha(raw),
                                "archive_sha256": manifest["archive_sha256"],
                                "retained_members_verified_from_existing_expansion": retained,
                                "transport_parts_replayed_in_this_recovery": False})
    # These three initializers are bound by the recovered v9 INPUTS source ledger.
    initializers = {
        "experiments/hcsn_causal_execution_v3/__init__.py": "4d77d70d4f664e21e538b23f5f0bf845f0c5efa02ac670d37ef13a699c37feaa",
        "experiments/hcsn_mechanism_content_v2/__init__.py": "9d7409cd830465f83202846e2d68976fb1cc33bf619e40115287555f38ead365",
        "experiments/hcsn_task_value_v1/__init__.py": "39d9c6a49be667f172380147c8b8ecf844c0f8d542c8acd72dfd5f6deafa39b6"}
    for name, digest in initializers.items():
        data = (source / name).read_bytes()
        install(name, digest, len(data), source_file=source / name)
    (destination / "SOURCE_VERIFICATION.json").write_text(json.dumps({
        "ref": spec["commit"], "spec_sha256": sha(spec_path.read_bytes()),
        "files": copied[:len(spec["sources"])], "scope": spec["scope"]}, indent=2) + "\n")
    (destination / "ARCHIVE_RECOVERY_RECEIPT.json").write_text(json.dumps({
        "scope": "Existing v3 expansion reverified against pinned member digests; no v6/fresh media",
        "records": archive_records}, indent=2) + "\n")
    return {"schema": "hcsn-v10-historical-recovery.v1", "source_checkout": str(source),
            "source_ref": spec["commit"], "destination": str(destination),
            "verified_and_installed_files": len(copied), "installed_bytes": sum(r["bytes"] for r in copied),
            "archives": archive_records,
            "files_digest": sha(json.dumps(copied, sort_keys=True).encode()),
            "v6_recovered": False, "new_recordings": False, "raw_media_recovered": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = recover(args.source, args.repository)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
