"""Reconstruct the pinned Git tree from every archived path/mode/blob SHA.

This checks complete tree identity without fetching blob contents. Byte sizes
are inventory observations and are not authenticated by the Git tree hash.
"""

import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import time


HERE = Path(__file__).resolve().parent
EXPECTED_TREE = "ae6756959590c2281d5460d8f2bab1fb428d8e4b"
EXPECTED_FILES = 32151


def git_digest(kind, payload):
    header = kind.encode("ascii") + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


def reconstruct(rows):
    root, names = {}, set()
    for row in rows:
        path = PurePosixPath(row["path"])
        if (path.is_absolute() or ".." in path.parts or str(path) != row["path"]
                or row["path"] in names or row["type"] != "blob"
                or row["mode"] not in ("100644", "100755", "120000")):
            raise ValueError("Unexpected or duplicate inventory leaf")
        names.add(row["path"])
        sha = bytes.fromhex(row["sha"])
        if len(sha) != 20:
            raise ValueError("Invalid blob identifier")
        directory = root
        for part in path.parts[:-1]:
            directory = directory.setdefault(part, {})
            if not isinstance(directory, dict):
                raise ValueError("Conflicting file and directory")
        if path.name in directory:
            raise ValueError("Conflicting inventory entry")
        directory[path.name] = (row["mode"], row["sha"])

    def tree_hash(directory):
        entries = []
        for name, value in directory.items():
            mode, sha = ("40000", tree_hash(value)) if isinstance(value, dict) else value
            encoded = name.encode("utf-8")
            order = encoded + (b"/" if mode == "40000" else b"")
            entries.append((order, mode.encode("ascii") + b" " + encoded + b"\0" + bytes.fromhex(sha)))
        return git_digest("tree", b"".join(entry for _, entry in sorted(entries)))

    return tree_hash(root), len(root)


def main():
    started, cpu = time.monotonic(), time.process_time()
    compressed = (HERE / "integration-inventory.json.gz").read_bytes()
    original = gzip.decompress(compressed)
    rows = json.loads(original)
    tree, root_entries = reconstruct(rows)
    if tree != EXPECTED_TREE or len(rows) != EXPECTED_FILES:
        raise ValueError("Inventory does not reconstruct the pinned complete tree")
    missing = sum(row["bytes"] is None for row in rows)
    return {
        "status": "VERIFIED_COMPLETE_PATH_MODE_BLOB_TREE", "files": len(rows),
        "tree_sha": tree, "root_entries": root_entries,
        "compressed_bytes": len(compressed), "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "original_bytes": len(original), "original_sha256": hashlib.sha256(original).hexdigest(),
        "missing_blob_sizes": missing, "blob_contents_read": 0,
        "scope": "Complete paths/modes/blob identifiers; not complete blob-content or line-by-line review.",
        "byte_size_scope": "Saved observations only; sizes are not committed by tree hashes; missing sizes remain unknown.",
        "wall_seconds": time.monotonic() - started, "cpu_seconds": time.process_time() - cpu,
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
