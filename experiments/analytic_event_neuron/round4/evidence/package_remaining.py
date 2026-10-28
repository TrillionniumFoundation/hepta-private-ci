"""Archive the remaining immutable run files and prove snapshot coverage.

Already archived paths must still have their original bytes. This helper does
not regenerate data, silently supersede evidence, or include its active wrapper.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile

from ...round2.restore_evidence import materialize
from ..freeze import verify
from .package import pack


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def descriptors(paths):
    result = []
    for path in paths:
        value = json.loads(path.read_text())
        result.extend(value if isinstance(value, list) else value.get("archives", [value]))
    return result


def run(repo, root, descriptor_paths, active_label, descriptor_output):
    if descriptor_output.resolve().is_relative_to(root.resolve()):
        raise ValueError("The archive descriptor output must be outside the snapshotted run")
    frozen = verify(root)
    if not (root / "RUNTIME_RESULTS.json").exists() or not (root / "reviews/RUNTIME_FINAL_REVIEW.json").exists():
        raise ValueError("Final scientific results and independent review are required")
    archived = {}
    archives = descriptors(descriptor_paths)
    with tempfile.TemporaryDirectory(prefix="aen-r4-snapshot-inventory-") as temporary:
        for row in archives:
            joined = materialize(repo, row, Path(temporary))
            with tarfile.open(joined, "r:gz") as archive:
                members = json.load(archive.extractfile(row["member_manifest"]))
            for name, expected in members.items():
                if not name.startswith("run/"):
                    raise ValueError("Unexpected archive member root: " + name)
                relative = name[4:]
                if relative in archived and archived[relative] != expected:
                    raise ValueError("Existing archives conflict: " + relative)
                archived[relative] = expected
            if "parts" in row:
                joined.unlink()
    for relative, expected in archived.items():
        path = root / relative
        if not path.is_file() or sha(path) != expected:
            raise ValueError("An already archived original changed or is missing: " + relative)
    omitted = {"execution/" + active_label + suffix for suffix in ("_STARTED.json", "_COMPLETED.json", ".log")}
    files = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root))
        if relative in omitted:
            continue
        if path.is_symlink():
            raise ValueError("Run evidence must be a regular file: " + relative)
        files[relative] = {"sha256": sha(path), "bytes": path.stat().st_size}
    remaining = sorted(set(files) - set(archived))
    receipt_path = root / "FINAL_RUN_SNAPSHOT_INVENTORY.json"
    if receipt_path.exists():
        raise FileExistsError(receipt_path)
    receipt = {
        "schema": "hepta.round4.run-snapshot-inventory.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": frozen["source_commit"], "freeze_sha256": sha(root / "FREEZE.json"),
        "existing_logical_archives": len(archives), "unique_already_archived_paths": len(archived),
        "run_files_in_snapshot": len(files), "remaining_files_before_this_receipt": len(remaining),
        "run_file_bytes_in_snapshot": sum(row["bytes"] for row in files.values()),
        "all_previous_archive_paths_still_exact": True,
        "snapshot_file_hashes": files,
        "current_wrapper_paths_excluded_to_avoid_mutable_or_recursive_hashes": sorted(omitted),
        "later_delivery_scope": "This inventory itself is included in RUN_REPORTS. The active archive wrapper completion, final restoration/report QA and Git readback are published separately after the snapshot.",
        "scientific_data_regenerated": False,
    }
    with receipt_path.open("x") as stream:
        json.dump(receipt, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    remaining.append(receipt_path.name)
    value = pack(root, remaining, "RUN_REPORTS", "operational")
    # No selected input, including logs, may have changed during compression.
    for relative, expected in files.items():
        if sha(root / relative) != expected["sha256"]:
            raise ValueError("A run file changed during final snapshot: " + relative)
    after_paths = {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}
    after_paths -= omitted | {receipt_path.name}
    if after_paths != set(files):
        raise ValueError("The run file set changed during final snapshot")
    verify(root)
    with descriptor_output.open("x") as stream:
        json.dump([value], stream, sort_keys=True, indent=2)
        stream.write("\n")
    return {"archive": value, "snapshot_files": len(files), "additional_inventory_file": 1,
            "previous_paths_exact": True, "remaining_paths_packaged": len(remaining)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, action="append", required=True)
    parser.add_argument("--active-label", required=True)
    parser.add_argument("--descriptor-output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.repo.resolve(), args.run_dir.resolve(), args.descriptor,
                         args.active_label, args.descriptor_output), sort_keys=True))
