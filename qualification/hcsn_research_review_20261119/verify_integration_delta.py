"""Bind a complete captured tree and an additive delta to the observed new head.

No source blobs, historical scripts, models, or training are executed here.
"""

import gzip
import hashlib
import json
from pathlib import Path
import time

from verify_inventory import reconstruct


HERE = Path(__file__).resolve().parent


def main():
    wall, cpu = time.monotonic(), time.process_time()
    inventory = HERE / "integration-inventory.json.gz"
    delta_path = HERE / "INTEGRATION_DELTA.json"
    rows = json.loads(gzip.decompress(inventory.read_bytes()))
    delta = json.loads(delta_path.read_bytes())
    old_tree, old_root_count = reconstruct(rows)
    if old_tree != delta["from_tree"] or len(rows) != 32151:
        raise ValueError("Original complete inventory identity changed")
    names = {row["path"] for row in rows}
    changes = delta["changes"]
    if len(changes) != 35 or delta["api_comparison"]["merge_base"] != delta["from_commit"]:
        raise ValueError("Unexpected delta scope or ancestry")
    for change in changes:
        if (change["status"] != "added" or change["path"] in names
                or not change["path"].startswith("qa/stem-bakeoff/")):
            raise ValueError("Delta is not the observed additive Cell history")
        names.add(change["path"])
        rows.append({k: change[k] for k in ("path", "type", "mode", "sha", "bytes")})
    new_tree, root_count = reconstruct(rows)
    if (new_tree != delta["to_tree"] or len(rows) != 32186
            or root_count != delta["root_entries"] or root_count != old_root_count):
        raise ValueError("Advanced inventory does not reconstruct the observed root")
    return {
        "status": "VERIFIED_COMPLETE_ADVANCED_PATH_MODE_BLOB_TREE",
        "from_commit": delta["from_commit"], "from_tree": old_tree,
        "to_commit": delta["to_commit"], "to_tree": new_tree,
        "old_files": 32151, "added_files": len(changes), "new_files": len(rows),
        "root_entries": root_count,
        "missing_blob_sizes": sum(row["bytes"] is None for row in rows),
        "source_bindings": {
            p.name: {"bytes": p.stat().st_size,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in (inventory, delta_path, HERE / "verify_inventory.py", Path(__file__))
        },
        "blob_contents_read": 0, "model_calls": 0,
        "scope": "All paths, modes, and blob identities at both heads; not blob-content or line-by-line review.",
        "wall_seconds": time.monotonic() - wall,
        "cpu_seconds": time.process_time() - cpu,
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
