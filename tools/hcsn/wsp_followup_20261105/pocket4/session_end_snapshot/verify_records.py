#!/usr/bin/env python3
"""Check session-end records and prior immutability; never contact the host."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = read(root / "MANIFEST.json")
    assert len(manifest["files"]) == 6
    for item in manifest["files"]:
        path = root / item["path"]
        assert path.is_file() and not path.is_symlink()
        assert path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]
    capture = read(root / "capture_receipt.json")
    snapshot = read(root / "public_snapshot.json")
    delta = read(root / "delta.json")
    assert capture["status"] == "PASS_FINAL_BOUND_READONLY_SNAPSHOT"
    assert capture["public_snapshot_sha256"] == digest(root / "public_snapshot.json")
    assert capture["driver_sha256"] == digest(root / "capture_final.py")
    assert capture["private_stdout_sha256"] == snapshot["public_projection"]["original_private_stdout_sha256"]
    assert snapshot["public_projection"]["sanitizer_sha256"] == capture["sanitizer_source_sha256"]
    assert snapshot["source_sha256"] == capture["audit_source_sha256"]
    assert snapshot["live_process_identity_stable"] and snapshot["effective_service_config_match"]
    assert snapshot["candidate_binding"]["same_candidate_and_job_at_end"]
    assert snapshot["candidate_binding"]["manifest_adapter_hash_matches"]
    assert snapshot["adapter"]["all_finite"] and snapshot["adapter"]["data_layout_nonoverlapping_and_complete"]
    assert all(delta["checks"].values())
    assert delta["final_public_snapshot_sha256"] == digest(root / "public_snapshot.json")
    assert not snapshot["model_forward_executed"] and not snapshot["training_started"]
    assert snapshot["broker_queries_sent"] == snapshot["orders_sent"] == 0
    prior = args.prior or root / delta["prior_public_snapshot_relative"]
    assert prior.exists(), "The prior snapshot is required for this delta check"
    assert digest(prior) == delta["prior_public_snapshot_sha256"]
    old = read(prior)
    assert old["trainer"]["job_counts"] == snapshot["trainer"]["job_counts"] == delta["counts"]
    for key in ("candidate_id", "job_id"):
        assert old["candidate_binding"][key] == snapshot["candidate_binding"][key]
    for key in ("adapter", "candidate_manifest", "bound_job_configuration", "guardian_config", "original_config"):
        assert old["sources"][key]["sha256"] == snapshot["sources"][key]["sha256"]
    assert old["trainer"]["current_blockers"] == snapshot["trainer"]["current_blockers"] == delta["current_blockers"]
    service = "heptatrader-execution.service"
    before = int(old["services"][service]["properties"]["NRestarts"])
    after = int(snapshot["services"][service]["properties"]["NRestarts"])
    assert delta["execution_restart_delta"]["increase"] == after - before
    assert not delta["execution_restart_delta"]["new_journal_errors_queried"]
    for key, difference in delta["memory_kib_changes"].items():
        assert snapshot["resources"]["memory_kib"][key] - old["resources"]["memory_kib"][key] == difference
    assert len(delta["prior_final_snapshot_files"]) == 7
    for name, identity in delta["prior_final_snapshot_files"].items():
        path = prior.parent / name
        assert path.stat().st_size == identity["bytes"] and digest(path) == identity["sha256"]
    parent = prior.parent.parent
    parent_sources_checked = (parent / "audit_live.py").exists() and (parent / "sanitize_export.py").exists()
    if parent_sources_checked:
        assert digest(parent / "audit_live.py") == capture["audit_source_sha256"]
        assert digest(parent / "sanitize_export.py") == capture["sanitizer_source_sha256"]
    for name in ("public_snapshot.json", "capture_receipt.json", "delta.json"):
        text = (root / name).read_text()
        for forbidden in ("/home/", "/Users/", '"steps"', "training_row_ids", "account_id", "order_id"):
            assert forbidden not in text, (name, forbidden)
    print(json.dumps({"status": "PASS_RECORDS_ONLY", "files_including_manifest": 7,
        "prior_snapshot_checked": True, "prior_seven_files_unchanged": True,
        "parent_sources_checked": parent_sources_checked, "new_remote_observation": False,
        "new_model_efficacy_claim": False}, sort_keys=True))


if __name__ == "__main__":
    main()
