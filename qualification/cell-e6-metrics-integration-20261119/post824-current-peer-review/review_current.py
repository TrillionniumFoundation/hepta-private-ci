#!/usr/bin/env python3
"""Compare frozen CURRENT records and existing evidence without executing it."""
import hashlib
import io
import json
import lzma
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
PUB = ROOT / "metrics_integration/post824-publication"
NEW = PUB / "qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json"
OLD = ROOT / "metrics_integration/followup-publication/qualification/cell-joint-20261118-2e9b/CURRENT_PROGRESS.json"
EVIDENCE = PUB / "qualification/cell-e6-metrics-integration-20261119"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def read(path, pin=None):
    raw = path.read_bytes()
    if pin:
        assert sha(raw) == pin, path
    return json.loads(raw), {"path": str(path.relative_to(ROOT)), "bytes": len(raw), "sha256": sha(raw)}


def leaves(value, path=()):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaves(child, path + (str(key),))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaves(child, path + (str(index),))
    else:
        yield path, value


def main():
    old, old_pin = read(OLD, "3cc021446a076f04c3654a5416964d29071ac1decf413cd3107abdd0f062e238")
    new, new_pin = read(NEW, "2700792bc2519f7bceec1ebd7ec5b9acce640bcbd35feb00f2594977a624217a")
    f, g = dict(leaves(old)), dict(leaves(new))
    missing = [path for path in f if path not in g]
    changes = [{"path": "/".join(path), "old": value, "new": g[path]} for path, value in f.items() if path in g and g[path] != value]
    added = ["/".join(path) for path in g if path not in f]
    permitted = {"observed_at_utc", "observed_at_user_timezone", "interpretation", "previous_evidence_commit", "checkpoint_scope/previous_current_sha256", "checkpoint_scope/previous_current_exact_bytes", "checkpoint_scope/new_source_change"}
    assert not missing and {row["path"] for row in changes} == permitted
    assert (len(f), len(g), len(changes), len(added)) == (7702, 8064, 7, 362)
    exact_domains = {}
    for key in ["E1", "E2", "E3", "E4", "Chain", "metrics_integration_6709", "qualification"]:
        assert old[key] == new[key]
        exact_domains[key] = {"unchanged": True, "canonical_sha256": sha(canonical(old[key]))}
    assert len(new["qualification"]) == 10 and all(value is False for value in new["qualification"].values())
    assert new["historical_freeze_rewritten"] is False
    compressed_old = PUB / "qualification/cell-joint-20261118-2e9b/checkpoint-824-successor/previous-current-824.json.xz"
    restored = lzma.decompress(compressed_old.read_bytes())
    assert restored == OLD.read_bytes()
    assert new["checkpoint_scope"]["previous_current_sha256"] == sha(restored)
    assert new["previous_evidence_commit"] == "8240292307116aa4063f7c63d8cdf48a0e8ef773"
    evidence_pins = []
    e5, pin = read(EVIDENCE / "e5-v2-complete-readback/MEASUREMENT_READOUT_3.json", "0108d4b9023626bc123c18527ea5a48c94788048220e1d622a0cca7e897e2aab")
    evidence_pins.append(pin)
    embedded_e5 = new["E5"]["latest_v2_complete_targets_and_original_gate"]
    for key, value in embedded_e5["complete_binding"].items():
        if key == "full_measurement_original_sha256":
            assert value == pin["sha256"]
        else:
            assert e5[key] == value, key
    assert len(e5["rows"]) == 16 and [row["ordinal"] for row in e5["rows"]] == list(range(16))
    assert sum(row["complete_encoding_and_token_bounds_fit"] for row in e5["rows"]) == 7
    assert sum(row["original_static_representation_admitted"] for row in e5["rows"]) == 0
    assert sum(row["training_execution_admitted"] for row in e5["rows"]) == 0
    assert all(value is False for value in e5["summary"]["original_static_prefix_1_4_16_admitted"].values())
    assert all(value is False for value in e5["summary"]["training_prefix_1_4_16"].values())
    assert e5["summary"]["complete_visible_target_roundtrips"] == 8
    assert e5["summary"]["target_scope_refusals"] == 7
    assert e5["rows"][2]["target_tokens"] == 622 > 384
    assert e5["summary"]["source_refusals"] == 1 and e5["rows"][13]["complete_encoding_and_token_bounds_fit"] is False
    assert e5["optimizer_unit_mapping"] is None and e5["training_compute_or_verifier_budget"] is None and e5["independent_B_C"] is None
    assert embedded_e5["real_users"] == embedded_e5["new_training_updates"] == embedded_e5["new_model_calls"] == embedded_e5["new_native_replays"] == 0
    e6, pin = read(EVIDENCE / "e6-8996-noupdate8-readback/SUMMARY.json", "a316f970778a5257a17b93f7365ffa0b4c7e2c4e5088900db7fc2ad3aa4f8e3c")
    evidence_pins.append(pin)
    embedded_e6 = new["E6"]["latest_8996_complete_ordinary_attempt"]
    assert embedded_e6["source"] == e6["source"] == "8996e4c5b6a8662c51f47d9e164b8c839635c796"
    assert embedded_e6["tree"] == e6["tree"]
    cases = [case for group in e6["new_actual_components"] for case in group["full_test_cases"]]
    assert len(cases) == sum(group["cases"] for group in e6["new_actual_components"]) == embedded_e6["actual_new_component_cases"] == 34
    assert all(case["failures"] == case["errors"] == case["skipped"] == 0 for case in cases)
    for group, current in zip(e6["new_actual_components"], embedded_e6["components"], strict=True):
        assert all(group[key] == value for key, value in current.items())
    raw_root = ROOT / "e6_owner_work/ack_order_evidence/expanded/raw"
    gate, pin = read(raw_root / "ack-marker-source-gate-3/RESULT.json", embedded_e6["full1159_result_sha256"])
    evidence_pins.append(pin)
    assert gate["successful"] is True and gate["full_caller_proof_exit"] == 0
    assert gate["classified_boundaries"] == 1159 and gate["current_source_full_caller_cli_executed"] is True
    assert gate["source_tests_executed_on_current_source"] == 0
    assert gate["retained_source_validation"]["source"] == "d0353abfbf9ac783f0fe842fe313977e9d49bff9"
    assert gate["retained_source_validation"]["executed_on_current_source"] is False
    assert gate["exact_marker_delta"]["extra_bytes"] == embedded_e6["exact_marker_framing_change_bytes"] == 2
    ordinary, pin = read(raw_root / "complete-noupdate-8/result.json", embedded_e6["ordinary_parent_result_sha256"])
    evidence_pins.append(pin)
    assert ordinary["source"] == embedded_e6["source"] and ordinary["successful"] is False
    assert ordinary["root-ack-lane-mechanism"]["command_exit_code"] == 0
    assert ordinary["root-ack-lane-mechanism"]["collection"]["status"] == "passed"
    assert ordinary["ordinary-post-a-no-update"]["command_exit_code"] == 100
    assert ordinary["ordinary-post-a-no-update"]["collection"]["failures"] == 1
    assert ordinary["ordinary-post-a-no-update"]["collection"]["junit_sha256"] == embedded_e6["ordinary_parent_JUnit_sha256"]
    assert embedded_e6["actual_Root_mechanism_parent_passed"] == e6["new_Root_mechanism_parent_passed"] is True
    assert embedded_e6["actual_Root_parent_terminal_branches"] == e6["new_Root_mechanism_terminal_branches"] == ["StalePrepare", "Revoked"]
    assert embedded_e6["actual_Root_parent_orders_each"] == e6["new_Root_mechanism_orders_each"] == ["SourceFirst", "CurrentFirst"]
    assert e6["last_accepted_historical_request"] == e6["historical_cap"] == embedded_e6["original_client_limit"] == 64
    assert e6["refused_historical_request"] == 65 and embedded_e6["request65_is_attempted_ID_refused_before_socket_exchange"] is True
    for current_key, raw_key in [("local_C_receipt_elapsed_micros", "C_receipt_returned_elapsed_micros"), ("local_C_publish_elapsed_micros", "C_Source_publish_returned_elapsed_micros"), ("local_C_RunStart_elapsed_micros", "C_final_run_start_returned_elapsed_micros"), ("ordinary_parent_command_seconds", "parent_command_seconds"), ("enclosing_pipeline_owner_seconds", "pipeline_owner_seconds")]:
        assert embedded_e6[current_key] == e6[raw_key]
    assert embedded_e6["ordinary_parent_passed"] is False and embedded_e6["ordinary_parent_executed"] is True
    assert embedded_e6["NextUse_executed"] is False and embedded_e6["terminal_Accept_executed"] is False
    assert embedded_e6["cold_D_executed"] is False and embedded_e6["Adopt_executed"] is False and embedded_e6["FinalUse_and_settlement_qualified"] is False
    projected = embedded_e6["independent_source_projection_only"]
    assert projected == {"unmodified_full_path": 70, "actual_observed_through_attempt": 65, "66_through70_not_executed": True, "proposed_same_operation_savings": 6, "proposed_full_path": 64, "candidate_implemented_or_executed_at_snapshot": False}
    tail_root = EVIDENCE / "e6-tail65-independent-review"
    tail_manifest, pin = read(tail_root / "MANIFEST.json")
    evidence_pins.append(pin)
    tail_raw = b"".join((tail_root / row["path"]).read_bytes() for row in tail_manifest["parts"])
    assert sha(tail_raw) == tail_manifest["archive_sha256"]
    tail_entries = {row["path"]: row for row in tail_manifest["members"]}
    with tarfile.open(fileobj=io.BytesIO(tail_raw), mode="r:xz") as archive:
        tail_md = archive.extractfile("READOUT.md").read()
        assert len(tail_md) == tail_entries["READOUT.md"]["bytes"] and sha(tail_md) == tail_entries["READOUT.md"]["sha256"]
        assert b"70 sequence entries" in tail_md and b"save six entries" in tail_md
        assert b"not an implemented or executed qualification" in tail_md
    ci, pin = read(EVIDENCE / "ci-824-complete/READOUT.json", "6afac2aa16b096f527e65ff1b1ce1a4aa94c048100375757b23c8ca05c96a8bd")
    evidence_pins.append(pin)
    mac, pin = read(EVIDENCE / "macintel-lease-fixture-review/READOUT.json", "7bf9bff2f30d9583006e61de39eb79ad349c519828ca2711b557bd653c0a288a")
    evidence_pins.append(pin)
    latest_ci = new["CI"]["latest_824_terminal_workflow_observation"]
    for key in ["actual_selected_job_checkout", "run_id", "run_status", "run_conclusion", "run_updated_at", "job_counts"]:
        assert latest_ci[key] == ci[key]
    all_jobs = {row["id"]: row for row in ci["all_jobs"]}
    for row in latest_ci["selected_jobs"]:
        assert row == all_jobs[row["id"]]
    assert latest_ci["mac_intel"] == mac["mac_intel"]
    assert latest_ci["mac_intel_causal_observation"] == mac["causal_observation"]
    assert latest_ci["mac_arm_executed"] is False and latest_ci["mac_arm_cancellation_cause"] is None
    assert latest_ci["cargo_deny_cause"] is None and latest_ci["cargo_deny_retrieval_error_retained"] == "Transport closed"
    assert latest_ci["whole_mac_or_joint_CI_passed"] is False
    assert latest_ci["gnu_musl_independent_physical_execution_or_summed_cost_claimed"] is False
    workflow = PUB / ".github/workflows/codespell.yml"
    workflow_raw = workflow.read_bytes()
    accepted = ROOT / "metrics_gate_work/codespell-binary-classification-review-1/publication/codespell.proposed.yml"
    assert workflow_raw == accepted.read_bytes()
    assert sha(workflow_raw) == "d19ff4e23b7ed3b413be94626f52e3ead5ec1318b058d0040266c5bb12e4f366"
    scope = []
    for path in sorted(PUB.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            scope.append({"path": str(path.relative_to(PUB)), "bytes": len(data), "sha256": sha(data)})
    non_evidence = [row for row in scope if not row["path"].startswith("qualification/")]
    assert [row["path"] for row in non_evidence] == [".github/workflows/codespell.yml"]
    assert not any(row["path"].startswith("codex-rs/") for row in scope)
    md = NEW.with_suffix(".md").read_bytes()
    for required in [b"All ten joint qualification flags remain false", b"Seven complete encodings", b"zero pass the original static gate", b"This is only a projection", b"not an overall Mac PASS", b"runner_id0", b"cause unknown"]:
        assert required in md, required
    report = {
        "schema": "hepta.post824-current-independent-review.v1",
        "status": "PASS",
        "scope": "exact frozen CURRENT JSON/MD, existing evidence, and current publication source scope; no final candidate gate or CI execution claimed",
        "old_current": old_pin,
        "new_current": new_pin,
        "new_current_markdown": {"bytes": len(md), "sha256": sha(md)},
        "old_leaf_count": len(f),
        "new_leaf_count": len(g),
        "missing_old_leaves": [],
        "changed_old_leaf_count": len(changes),
        "changed_old_leaves": changes,
        "new_leaf_count_added": len(added),
        "new_leaf_paths": added,
        "unchanged_complete_domains": exact_domains,
        "all_original_budget_and_history_leaves_preserved_except_explicit_checkpoint_metadata": True,
        "previous_824_json_xz_restores_exact_old_bytes": True,
        "joint_qualification": new["qualification"],
        "e5": {"length_fit_count": 7, "original_static_admitted_count": 0, "training_admitted_count": 0, "target_roundtrips": 8, "target_scope_refusals": 7, "rich_target_tokens": 622, "jsonschema_retained_ordinal": 13, "all_static_training_prefixes_false": True, "missing_external_mappings_remain_null": True, "complete_binding_matches_retained_measurement": True},
        "e6": {"source": embedded_e6["source"], "fresh_full_caller_classifications": 1159, "old_433_907_398_remain_d035": True, "fresh_native_component_cases": 34, "component_failure_error_skip": 0, "actual_root_parent_passed": True, "ordinary_parent_executed": True, "ordinary_parent_passed": False, "observed_attempt_refused_before_transport": 65, "original_limit": 64, "static_unexecuted_full_path": 70, "proposed_unimplemented_full_path": 64, "proposal_is_not_new_native_evidence": True, "local_C_not_complete_C_or_learning": True, "whole_parent_cold_D_Adopt_FinalUse_settlement_remain_unqualified": True},
        "ci": {"head": ci["head_sha"], "actual_checkout": ci["actual_selected_job_checkout"], "run": ci["run_id"], "overall": "failure", "all_selected_job_fields_equal_retained_final_API": True, "mac_intel_unit_pass_cognitive_failure_kept_separate": True, "mac_arm_no_runner_cancelled_no_execution": True, "cargo_deny_cause_unknown": True, "gnu_musl_not_double_counted": True},
        "workflow": {"path": ".github/workflows/codespell.yml", "bytes": len(workflow_raw), "sha256": sha(workflow_raw), "equals_exact_accepted_candidate": True, "only_non_evidence_path_in_reviewed_publication": True, "runtime_paths_present": 0, "integrated_new_workflow_CI_executed_by_review": False},
        "evidence_pins": evidence_pins,
        "reviewed_publication_file_count": len(scope),
        "reviewed_publication_scope_sha256": sha(canonical(scope)),
        "material_findings": [],
        "limitations": ["Current source-scope statement applies to the reviewed publication; the later complete candidate manifest/tree still needs its original exact-head gate", "Archive-wide274/612/41/41 member verification is root's separately retained readback; this review independently compared selected summaries, relevant native result/source-gate originals, and tail source-review bytes", "1159 is the fresh source caller-classification CLI coverage, not1159 freshly rerun mutation tests; those historical433/907/398 records remain d035", "The proposed70-to64 reduction remains an unimplemented source projection in this frozen snapshot"],
        "new_executions": {"host_jobs": 0, "native_runs": 0, "cargo_runs": 0, "model_calls": 0, "training_updates": 0, "gate_runs": 0, "network_calls": 0, "ref_updates": 0}
    }
    for name, value in [("READOUT.json", report), ("REVIEWED_PUBLICATION_SCOPE.json", scope)]:
        path = OUT / name
        assert not path.exists()
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "readout_sha256": sha((OUT / "READOUT.json").read_bytes()), "scope_files": len(scope), "new_current_sha256": new_pin["sha256"]}, indent=2))


if __name__ == "__main__":
    main()
