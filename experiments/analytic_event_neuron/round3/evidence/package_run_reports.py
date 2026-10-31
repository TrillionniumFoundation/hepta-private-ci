"""Snapshot completed reports and prove ordinary-file restoration, without rerunning science."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time

from ...round2.restore_evidence import materialize, restore, verify_members
from .. import freeze
from .package_evidence import package, sha


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def collect(root, repo, output):
    root, repo, output = Path(root).resolve(), Path(repo).resolve(), Path(output)
    frozen = freeze.verify(root)
    if output.exists():
        raise FileExistsError("A report snapshot must not replace a previously bound archive")
    excluded = {"RUN_REPORTS_RESTORE.json"}
    selected = [str(p.relative_to(root)) for p in sorted(root.iterdir())
                if p.is_file() and p.suffix in (".json", ".jsonl", ".log") and p.name not in excluded]
    for relative in ("main/reports", "reviews", "independent_main_review", "report_qa",
                     "archival_reviews", "operational_logs", "operational_sources", "publication_records"):
        if (root / relative).is_dir():
            selected.append(relative)
    # Window JSONs are already in their calibration bundles. These two global
    # files are required to bind the full phase and reproduce its final report.
    selected.extend(("calibration_confirmation/RESULTS.json", "calibration_confirmation/INDEX.json"))
    started = time.perf_counter_ns()
    descriptor = package(root, selected, repo,
        repo / "experiments/analytic_event_neuron/round3/evidence/confirmation", "RUN_REPORTS")
    package_ns = time.perf_counter_ns() - started
    started = time.perf_counter_ns()
    with tempfile.TemporaryDirectory(prefix="aen-r3-run-reports-") as temporary:
        temporary = Path(temporary)
        archive = materialize(repo, descriptor, temporary)
        expected = verify_members(archive, descriptor["member_manifest"])
        destination = temporary / "restored"
        restore(archive, destination, descriptor["member_manifest"], expected)
        for relative, digest in expected.items():
            original, restored = root / relative, destination / relative
            if (sha(original) != digest or sha(restored) != digest
                    or (original.stat().st_mode & 0o777) != (restored.stat().st_mode & 0o777)):
                raise ValueError("Restored report differs from the snapshot: " + relative)
    restoration_ns = time.perf_counter_ns() - started
    freeze.verify(root)
    write(output, [descriptor])
    result = {
        "schema": "hepta.analytic-event.round3.report-restoration.v1",
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": frozen["source_commit"], "passed": True,
        "archive": descriptor["name"], "archive_sha256": descriptor["sha256"],
        "compressed_bytes": descriptor["bytes"], "data_members": len(expected),
        "restored": True, "file_bytes_and_modes_match_original": True,
        "ordinary_files_actually_extracted": True,
        "temporary_restore_directory_removed": True,
        "scientific_data_regenerated": False, "model_fitting_performed": False,
        "frozen_sources_verified_before_and_after": len(frozen["sources_sha256"]),
        "prepared_artifacts_verified_before_and_after": len(frozen["artifacts_sha256"]),
        "member_sha256": expected, "package_ns": package_ns,
        "restore_and_verification_ns": restoration_ns,
        "snapshot_excludes_its_own_restore_receipt_and_later_manifest_qa_publication_receipts": True,
        "later_receipts_published_as_standalone_files": True,
    }
    target = root / "archival_reviews/RUN_REPORTS_RESTORE.json"
    write(target, result)
    return {"archive": descriptor["name"], "bytes": descriptor["bytes"],
            "data_members": len(expected), "passed": True, "receipt": str(target)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("run-dir", "repo", "output"):
        parser.add_argument("--" + key, required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(collect(args.run_dir, args.repo, args.output)))
