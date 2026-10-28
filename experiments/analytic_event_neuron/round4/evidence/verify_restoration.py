"""Actually restore selected archives, verify bytes and modes, then remove duplicates."""

import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import time

from ...round2.restore_evidence import materialize, restore, verify_members
from ..freeze import verify


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_collections(repo, run_dir, descriptors, output):
    started = time.perf_counter_ns()
    frozen_before = verify(run_dir)
    records = []
    for descriptor in descriptors:
        # Bound temporary storage to one logical archive. Earlier receipts
        # remain unchanged; every archive still receives an actual extraction.
        with tempfile.TemporaryDirectory(prefix="aen-r4-restoration-") as temporary:
            temporary = Path(temporary)
            destination = temporary / "restored"
            path = materialize(repo, descriptor, temporary)
            expected = verify_members(path, descriptor["member_manifest"])
            restore(path, destination, descriptor["member_manifest"], expected)
            modes, original_matches = 0, 0
            with tarfile.open(path, "r:gz") as archive:
                for member in archive:
                    if not member.isfile():
                        continue
                    restored = destination / member.name
                    if restored.stat().st_mode & 0o777 != member.mode & 0o777:
                        raise ValueError("Restored mode mismatch: " + member.name)
                    modes += 1
                    if member.name.startswith("run/"):
                        original = run_dir / member.name.removeprefix("run/")
                        if not original.is_file() or sha(original) != sha(restored):
                            raise ValueError("Restored bytes differ from retained original: " + member.name)
                        original_matches += 1
            records.append({"archive": descriptor["name"], "sha256": descriptor["sha256"],
                            "data_files": len(expected), "modes_verified": modes,
                            "retained_originals_byte_exact": original_matches,
                            "actual_disk_extraction": True})
    frozen_after = verify(run_dir)
    if frozen_before != frozen_after:
        raise ValueError("Frozen identities changed during restoration")
    report = {"schema": "hepta.analytic-event.round4.restoration.v1", "passed": True,
              "archives": records, "data_files": sum(r["data_files"] for r in records),
              "source_files_unchanged": len(frozen_after["sources_sha256"]),
              "prepared_artifacts_unchanged": len(frozen_after["artifacts_sha256"]),
              "scientific_data_regenerated": False,
              "maximum_simultaneously_restored_logical_archives": 1,
              "temporary_duplicates_removed_only_after_byte_verification": True,
              "wall_ns": time.perf_counter_ns() - started}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--descriptors", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    descriptors = []
    for path in args.descriptors:
        value = json.loads(path.read_text())
        descriptors.extend(value.get("archives", [value]) if isinstance(value, dict) else value)
    result = verify_collections(args.repo.resolve(), args.run_dir.resolve(), descriptors, args.output)
    print(json.dumps({"passed": result["passed"], "archives": len(result["archives"]),
                      "data_files": result["data_files"], "wall_ns": result["wall_ns"]}))
