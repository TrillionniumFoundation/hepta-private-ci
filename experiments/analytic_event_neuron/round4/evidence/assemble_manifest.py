"""Assemble complete archive identities without changing any scientific result."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from ...round2.restore_evidence import verify_file
from ..freeze import verify


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assemble(run_dir, repo, descriptor_paths, result_paths, output):
    frozen = verify(run_dir)
    archives = []
    for path in descriptor_paths:
        value = json.loads(path.read_text())
        if isinstance(value, dict):
            archives.extend(value["archives"] if "archives" in value else [value])
        else:
            archives.extend(value)
    if len({row["name"] for row in archives}) != len(archives):
        raise ValueError("Duplicate logical archive names")
    physical = []
    for row in archives:
        combined = hashlib.sha256()
        size = 0
        for part in row.get("parts", [row]):
            path = repo / part["path"]
            verify_file(path, part)
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    combined.update(block)
                    size += len(block)
            physical.append(part["path"])
        if size != row["bytes"] or combined.hexdigest() != row["sha256"]:
            raise ValueError("Logical archive partitions differ: " + row["name"])
    if len(physical) != len(set(physical)):
        raise ValueError("A physical archive is listed more than once")
    results = {}
    for path in result_paths:
        path = path.resolve()
        if not path.is_relative_to(repo):
            raise ValueError("Result outside repository")
        results[str(path.relative_to(repo))] = {"sha256": sha(path), "bytes": path.stat().st_size}
    document = {
        "schema": "hepta.analytic-event.round4.evidence-manifest.v1",
        "assembled_utc": datetime.now(timezone.utc).isoformat(),
        "repository": "TrillionniumFoundation/hepta-private-ci",
        "branch": "research/analytic-event-neuron-20261027",
        "base_commit": frozen["base_commit"], "source_commit": frozen["source_commit"],
        "freeze_sha256": sha(run_dir / "FREEZE.json"),
        "sources_sha256": frozen["sources_sha256"],
        "prepared_artifacts_sha256": frozen["artifacts_sha256"],
        "archives": archives,
        "totals": {"logical_archives": len(archives), "physical_blobs": len(physical),
                   "compressed_bytes": sum(row["bytes"] for row in archives),
                   "outer_data_members": sum(row["data_files"] for row in archives),
                   "outer_manifest_members": len(archives)},
        "results": results,
        "nested_zip_member_counts_are_not_added_to_outer_counts": True,
        "overlapping_archive_paths_are_not_independent_samples": True,
        "restorer": "experiments/analytic_event_neuron/round2/restore_evidence.py",
        "restoration_requires_no_training_or_confirmation_generation": True,
        "source_and_prepared_artifacts_still_exact": True,
        "post_snapshot_receipts": "Final report QA and Git readback receipts are published separately to avoid recursive hashes.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(document, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return document


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, action="append", required=True)
    parser.add_argument("--result", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = assemble(args.run_dir.resolve(), args.repo.resolve(), args.descriptor, args.result, args.output)
    print(json.dumps(result["totals"]))
