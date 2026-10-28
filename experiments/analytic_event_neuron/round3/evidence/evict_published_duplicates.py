"""Reclaim only byte-verified archive duplicates already present in a read-back Git tree."""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def git_sha(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def evict(repo, root, proof_path, main_descriptors, retain):
    repo, root = Path(repo).resolve(), Path(root).resolve()
    proof = read(proof_path)
    blobs = proof["blobs"]
    receipt = root / "DURABLE_ARCHIVE_DUPLICATE_EVICTIONS.jsonl"
    removed = []

    def remove(path, verification):
        row = {"recorded_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "path": str(path), "bytes": path.stat().st_size,
               "remote_head": proof["head"], "remote_tree": proof["tree"],
               "verification": verification, "only_local_duplicate_removed": True}
        # Write the verified intent before unlinking; a failed unlink is harmless.
        with receipt.open("a") as stream:
            stream.write(json.dumps(row, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        path.unlink()
        removed.append(row)

    for relative, expected in blobs.items():
        path = (repo / relative).resolve()
        if (not path.is_relative_to(repo / "experiments/analytic_event_neuron/round3/evidence")
                or ".tar.gz" not in path.name):
            raise ValueError("Unexpected remote proof archive path")
        if path.is_file():
            data = path.read_bytes()
            if git_sha(data) != expected:
                raise ValueError("Local duplicate differs from durable blob: " + relative)
            remove(path, {"git_blob_sha1": expected, "sha256": hashlib.sha256(data).hexdigest()})

    index = read(root / "main/RUN_INDEX.json")
    if not index["complete"] or not (root / "MAIN_EXECUTION_COSTS.json").is_file():
        raise ValueError("Completed review and cost extraction must precede main archive eviction")
    by_scope = {item["scope"]: item for item in index["scopes"]}
    for item in read(main_descriptors):
        scope = item["name"].removeprefix("MAIN_")
        if scope in retain:
            continue
        entry = by_scope[scope]
        path = root / entry["archive"]
        parts = item.get("parts", [item])
        if not path.is_file() or not all(part["path"] in blobs for part in parts):
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != item["sha256"] or digest != entry["archive_receipt"]["sha256"]:
            raise ValueError("Completed main archive identity changed")
        offset = 0
        for part in parts:
            segment = data[offset:offset + part["bytes"]]
            if (len(segment) != part["bytes"] or hashlib.sha256(segment).hexdigest() != part["sha256"]
                    or git_sha(segment) != blobs[part["path"]]):
                raise ValueError("Original archive does not reconstruct published parts")
            offset += part["bytes"]
        if offset != len(data):
            raise ValueError("Published partition does not cover the original archive")
        remove(path, {"sha256": digest, "all_published_parts_exact": True,
                      "parts": [part["path"] for part in parts],
                      "independent_review_sha256": item["independent_review_sha256"]})
    stat = os.statvfs(root)
    return {"removed_files": len(removed), "logical_bytes": sum(x["bytes"] for x in removed),
            "current_free_bytes": stat.f_bfree * stat.f_frsize, "receipt": str(receipt)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--remote-proof", type=Path, required=True)
    parser.add_argument("--main-descriptors", type=Path, required=True)
    parser.add_argument("--retain-main", action="append", default=[])
    args = parser.parse_args()
    print(json.dumps(evict(args.repo, args.run_dir, args.remote_proof,
                           args.main_descriptors, args.retain_main)))
