#!/usr/bin/env python3
"""Check frozen public records, not a new live audit or checkpoint replay."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def sha(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def main():
    assert sha("audit_live.py") == "76b5c2e7bd36e25c8fa2d371ed44648ba3e157c94d014a5a1456193dafae90d7"
    assert sha("attempt_1_source.py") == "b089087300db0f163abb9d68994cfc8e6f6d2dd2e969ac95d7242d4097c5d045"
    assert sha("attempt_1_failed.json") == "2cbbaf060261ebd8664f8c84aa16367ee168adb7ec2b9f3b7a7adb8643849971"
    assert sha("current_candidate_audit.json") == "9ee7af5299786e03cf69ef82787ea987c5ed53def4dee5ccb4cb62858a8ff15c"
    a = json.loads((ROOT / "current_candidate_audit.json").read_text())
    f = json.loads((ROOT / "attempt_1_failed.json").read_text())
    assert a["source_sha256"] == sha("audit_live.py")
    assert f["source_sha256"] == sha("attempt_1_source.py")
    assert f["status"] == "BLOCKED_OR_FAILED"
    assert f["error"]["message"] == "EFFECTIVE_SERVICE_CONFIG_MISMATCH"
    assert "adapter" not in f.get("sources", {})
    assert a["status"] == "PASS_BOUND_CURRENT_SMALL_ADAPTER_STATIC_AUDIT"
    assert a["public_projection"]["original_private_stdout_sha256"] == "1d13362c985910b3a9da55a32008a8f49b476e692aac672a4c14e566d466dab0"
    assert a["public_projection"]["original_private_stdout_bytes"] == 111818
    assert a["public_projection"]["sanitizer_sha256"] == sha("sanitize_export.py")
    assert not a["public_projection"]["raw_stdout_published"]
    assert a["effective_service_config_match"] and a["live_process_identity_stable"]
    assert a["sources"]["trainer_status_before"] == {
        **a["sources"]["trainer_status_after"],
        "observed_start_utc": a["sources"]["trainer_status_before"]["observed_start_utc"],
        "observed_end_utc": a["sources"]["trainer_status_before"]["observed_end_utc"],
    }
    assert a["sources"]["adapter"]["sha256"] == "94a8a2275e92fa6343b5c2b662c3a440c3cc870f067d73e86bb1c0069b880ee0"
    assert a["sources"]["adapter"]["bytes"] == 9988
    assert a["candidate_binding"]["manifest_adapter_hash_matches"]
    assert a["candidate_binding"]["same_candidate_and_job_at_end"]
    adapter = a["adapter"]
    assert adapter["all_finite"] and adapter["data_layout_nonoverlapping_and_complete"]
    assert adapter["tensor_count"] == len(adapter["tensors"]) == 6
    assert adapter["parameter_count"] == sum(t["parameters"] for t in adapter["tensors"]) == 2379
    assert all(t["dtype"] == "F32" and t["finite_parameters"] == t["parameters"] for t in adapter["tensors"])
    assert a["trainer"]["job_counts"] == {"ADMITTED": 0, "COMPLETED": 114, "FAILED": 2, "RUNNING": 0}
    assert a["trainer"]["pending_evaluations"] == 0
    assert a["training_lineage"]["optimizer_reset_each_job"]
    assert not a["training_lineage"]["completed_jobs_are_cumulative_updates"]
    assert a["candidate_reported_training"]["measurement"]["training_only"]
    for result in [a, f]:
        assert result["read_only"] and not result["model_forward_executed"]
        assert not result["training_started"] and not result["services_changed"]
        assert result["orders_sent"] == result["broker_queries_sent"] == 0
        assert not result["performance_qualified"] and not result["base_weight_content_refreshed"]
    text = (ROOT / "current_candidate_audit.json").read_text()
    assert all(term not in text for term in ["training_row_ids", "gradient_digest", '"steps"', "/home/", "/Users/", "account_id", "order_id"])
    e = json.loads((ROOT / "execution_restart_diagnostic.json").read_text())
    assert e["query"]["returned_records"] == e["query"]["maximum_records"] == 200
    assert e["observed_error"]["detailed_guard_branch_unknown"]
    assert not e["public_source"]["deployed_binary_bound_to_this_source_commit"]
    assert e["category_counts"]["error"] == 25
    assert len(e["sampled_last_restart_events"]) == 7
    assert all(30 < value < 32 for value in e["inter_restart_seconds"])
    assert not e["scope"]["root_cause_closed"]
    return {
        "schema": "hepta.wsp.pocket4_public_record_check.v1",
        "status": "PASS_FROZEN_PUBLIC_RECORD_VERIFICATION",
        "source_and_receipt_identities_verified": True,
        "preserved_first_attempt_failure": True,
        "private_raw_stdout_or_checkpoint_retrieved": False,
        "new_remote_observation_or_model_load_executed": False,
        "model_efficacy_or_live_root_cause_qualified": False,
        "verifier_sha256": sha("verify_records.py"),
    }


if __name__ == "__main__":
    print(json.dumps(main(), indent=2, sort_keys=True))
