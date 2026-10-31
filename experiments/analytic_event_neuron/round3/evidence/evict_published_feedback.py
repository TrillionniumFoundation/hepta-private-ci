"""Reclaim large local feedback duplicates after publication and actual restoration."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evict(root, descriptors_path, remote_path, publication_path):
    root = Path(root).resolve()
    remote, publication = read(remote_path), read(publication_path)
    index = read(root / "FEEDBACK_INDEX.json")
    if not index["complete"] or not (root / "FEEDBACK_RUNTIME_ACCOUNTING.json").is_file():
        raise ValueError("Completed confirmation, review and accounting are required")
    review = read(root / "reviews/FEEDBACK_RUNTIME_INDEPENDENT_REVIEW.json")
    if not review["passed"]:
        raise ValueError("Independent review must have passed")
    by_seed = {item["seed"]: item for item in index["scopes"]}
    removed = []
    for item in read(descriptors_path)["archives"]:
        if not item["name"].startswith("FEEDBACK_CONFIRMATION_"):
            continue
        parts = item.get("parts", [item])
        if not all(p["path"] in remote["blobs"]
                   and remote["blobs"][p["path"]] == publication["blobs"].get(p["path"])
                   for p in parts):
            continue
        seed = int(item["name"].rsplit("_", 1)[1])
        receipt_path = root / "archival_reviews" / (item["name"] + "_RESTORE.json")
        receipt = read(receipt_path)
        hashes = by_seed[seed]["files_sha256"]
        if (not all(receipt[k] for k in ("passed", "restored", "member_hashes_verified",
                                         "file_bytes_and_modes_match_original"))
                or receipt["archive_sha256"] != item["sha256"]
                or receipt["restored_file_hashes"] != hashes):
            raise ValueError("Restoration does not bind the completed feedback scope")
        for relative, expected in hashes.items():
            path = (root / relative).resolve()
            if not path.is_relative_to(root / "feedback_confirmation" / f"seed_{seed}"):
                raise ValueError("Unexpected completed feedback path")
            if not path.is_file() or path.stat().st_size < 1_000_000:
                continue
            if sha(path) != expected:
                raise ValueError("Local original differs from the successfully restored file")
            row = {"recorded_utc": datetime.now(timezone.utc).isoformat(),
                   "path": str(path), "bytes": path.stat().st_size, "sha256": expected,
                   "archive": item["name"], "archive_sha256": item["sha256"],
                   "restore_receipt_sha256": sha(receipt_path),
                   "remote_head": remote["head"], "remote_tree": remote["tree"],
                   "published_parts": {p["path"]: remote["blobs"][p["path"]] for p in parts},
                   "only_local_duplicate_removed": True}
            with (root / "DURABLE_FEEDBACK_DUPLICATE_EVICTIONS.jsonl").open("a") as output:
                output.write(json.dumps(row, sort_keys=True) + "\n")
                output.flush()
                os.fsync(output.fileno())
            path.unlink()
            removed.append(row)
    stat = os.statvfs(root)
    return {"removed_files": len(removed), "logical_bytes": sum(x["bytes"] for x in removed),
            "current_free_bytes": stat.f_bfree * stat.f_frsize}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "descriptors", "remote-proof", "publication-state"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(evict(args.run_dir, args.descriptors, args.remote_proof, args.publication_state)))
