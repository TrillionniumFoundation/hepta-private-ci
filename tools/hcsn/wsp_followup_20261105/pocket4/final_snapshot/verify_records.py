#!/usr/bin/env python3
"""Check immutable public records; does not contact pocket4 or evaluate a model."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prior", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "MANIFEST.json").read_text())
    for item in manifest["files"]:
        path = root / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"]
        assert digest(path) == item["sha256"], item["path"]
    capture = json.loads((root / "capture_receipt.json").read_text())
    snapshot = json.loads((root / "public_snapshot.json").read_text())
    delta = json.loads((root / "delta.json").read_text())
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
    prior = args.prior or root / delta["prior_public_snapshot_relative"]
    prior_checked = prior.exists()
    if prior_checked:
        assert digest(prior) == delta["prior_public_snapshot_sha256"]
        old = json.loads(prior.read_text())
        assert old["trainer"]["job_counts"] == snapshot["trainer"]["job_counts"]
        assert old["candidate_binding"]["candidate_id"] == snapshot["candidate_binding"]["candidate_id"]
        assert old["sources"]["adapter"]["sha256"] == snapshot["sources"]["adapter"]["sha256"]
        service = "heptatrader-execution.service"
        before = int(old["services"][service]["properties"]["NRestarts"])
        after = int(snapshot["services"][service]["properties"]["NRestarts"])
        assert delta["execution_restart_delta"]["increase"] == after - before
    for name in ["public_snapshot.json", "capture_receipt.json", "delta.json"]:
        text = (root / name).read_text()
        for forbidden in ["/home/", "/Users/", '"steps"', "training_row_ids", "account_id", "order_id"]:
            assert forbidden not in text, (name, forbidden)
    print(json.dumps({"status": "PASS_RECORDS_ONLY", "files": len(manifest["files"]),
                      "prior_snapshot_checked": prior_checked, "new_remote_observation": False,
                      "new_model_efficacy_claim": False}, sort_keys=True))


if __name__ == "__main__":
    main()
