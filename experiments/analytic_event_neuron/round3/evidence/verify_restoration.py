"""Actually restore selected published bundles in isolated disposable directories."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from ...round2.restore_evidence import materialize, restore, safe_child, verify_members
from .package_evidence import sha


def verify(manifest, repo, names, output):
    manifest, repo, output = Path(manifest), Path(repo), Path(output)
    selected = set(names)
    descriptors = json.loads(manifest.read_text())["archives"]
    if selected - {item["name"] for item in descriptors}:
        raise ValueError("Unknown archive selection")
    if output.exists():
        raise FileExistsError("Restore receipt is immutable")
    started, cpu, rows = time.perf_counter_ns(), time.process_time_ns(), []
    for item in descriptors:
        if selected and item["name"] not in selected:
            continue
        with tempfile.TemporaryDirectory(prefix="aen-r3-restore-isolated-") as temporary:
            temporary = Path(temporary)
            joined = temporary / "joined"
            joined.mkdir()
            archive = materialize(repo, item, joined)
            expected = verify_members(archive, item["member_manifest"])
            destination = safe_child(temporary / "restored", item["restore_root"])
            restore(archive, destination, item["member_manifest"], expected)
            rows.append({"archive": item["name"], "archive_sha256": item["sha256"],
                         "data_files_restored_and_sha256_verified": len(expected),
                         "restored_member_bytes": sum((destination / relative).stat().st_size for relative in expected),
                         "actual_disk_extraction_performed": True,
                         "temporary_restored_copy_removed_after_verification": True})
    receipt = {"schema": "hepta.analytic-event.round3.restore-verification.v1", "passed": True,
        "created_utc": datetime.now(timezone.utc).isoformat(), "archives": rows,
        "archives_verified": len(rows), "data_files_restored_and_verified": sum(x["data_files_restored_and_sha256_verified"] for x in rows),
        "manifest_sha256": sha(manifest), "review_script_sha256": sha(__file__),
        "scientific_data_regenerated": False, "training_or_native_inference_executed": False,
        "scope": "Physical parts, joined gzip archive, complete member set, safe extraction, actual restored bytes",
        "wall_ns": time.perf_counter_ns() - started, "parent_cpu_ns": time.process_time_ns() - cpu}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("manifest", "repo", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--archive", action="append", default=[])
    args = parser.parse_args()
    result = verify(args.manifest, args.repo, args.archive, args.output)
    print(json.dumps({key: result[key] for key in ("passed", "archives_verified", "data_files_restored_and_verified", "scientific_data_regenerated")}))
