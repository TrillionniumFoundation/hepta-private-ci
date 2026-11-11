#!/usr/bin/env python3
"""Append published V15/V16 evidence without changing an adoption requirement."""
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
BASE_HEAD = "fb533298874d85b6d6ec3d0d1352cd847e54ac4f"
EVIDENCE = "3a30ff5e95a74ee870799756b384ea9ac8c03b2e"
EVIDENCE_TREE = "68813fa680a583be6db6c57cf8047d6a80a78d34"
SOURCE = "c89540598693697577cda8cba31cb07f6ce65317"
SOURCE_TREE = "5a7c897a33e4eef48ea8f4bf52eaf48ea7c866ae"


def identity(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def evidence(path, local):
    return {"commit": EVIDENCE,
            "path": "qualification/memory-cell-mem8-ci-followup/" + path,
            **identity((WORK / local).read_bytes()), "full_remote_readback_verified": True}


base_raw = (HERE / "BASE_BLOCKERS.json").read_bytes()
assert identity(base_raw) == {
    "bytes": 124699,
    "sha256": "9e7598040fcedd533b14bcfdbcc28ad3cd44c465f699facd17814351d23d1800",
    "git_blob": "6030c1c917dbb0dcc6a6ff2ed5259e35a243a925",
}
before = json.loads(base_raw)
out = copy.deepcopy(before)
publication_raw = (WORK / "mem8-ci-followup-v16/ACTUAL_PUBLICATION.json").read_bytes()
publication = json.loads(publication_raw)
assert publication["after"]["head"] == publication["after"]["pr_head"] == EVIDENCE
assert publication["after"]["tree"] == EVIDENCE_TREE
assert publication["after"]["draft"] is True
assert publication["full_PR_body_equal_to_submitted"] is True
out["checkpoint_revision"] = 10
out["checkpoint_utc"] = datetime.now(timezone.utc).isoformat()
out["source_ci_followup_v6_v8"] = {
    "scope": "Actual source-only qualifications and published original evidence. No adoption gate closes.",
    "current_source": {
        "head": SOURCE, "tree": SOURCE_TREE,
        "parent": "1c063ba9e934f060181d4fc17d724361ba2a37fd",
        "pr": 5935, "draft": True,
        "actual_expected_head_update_and_full_raw_PR_readback_verified": True,
        "qualification_harness_commits_outside_pure_source_ancestry": True,
    },
    "source_only_operations": [
        {"version": 6, "run": 43032289667, "job": 130562136934,
         "python_pass": 18, "cumulative_reviewed_paths": 109, "rust_inventory": 6201,
         "actual_formatted_source": "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b",
         "evidence_commit": "3cfe2ba630123c8d29da92fe2292f33ce88c7d6d"},
        {"version": 7, "run": 43042186271, "job": 130596614396,
         "python_pass": 18, "cumulative_reviewed_paths": 114, "rust_inventory": 6204,
         "actual_gate_seconds": 156.902353,
         "actual_formatted_source": "c7c02cb425646adc6c85c763672cc6fa37e9c53d"},
        {"version": 8, "run": 43046107709, "job": 130610340916,
         "python_pass": 18, "cumulative_reviewed_paths": 116, "rust_inventory": 6204,
         "actual_gate_seconds": 212.521569, "actual_formatted_source": SOURCE},
    ],
    "source_only_limits": {
        "each_original_budget_seconds": 600,
        "full_caller_golden_equal_except_complete_tree_derived_file_count": True,
        "authorityGranted_remains_false": True, "both_lock_bytes_unchanged": True,
        "native_tests_executed_by_source_gates": 0, "model_requests": 0,
        "no_historical_native_pass_transferred_to_current_source": True,
    },
    "source_publication": evidence("v16/source-v8/SOURCE_PR_PUBLICATION.json", "mem8-source-v8-preparation/SOURCE_PR_PUBLICATION.json"),
    "source_gate_root_audit": evidence("v16/source-v8/ROOT_SOURCE_GATE_AUDIT.json", "mem8-source-v8-preparation/ROOT_SOURCE_GATE_AUDIT.json"),
    "original_b054": {
        "head": "b0547d2f874c0aeb54dabd3491caa2bee49fcb0b",
        "tree": "3f89ddeff13d0af85f4abe2690699107357f1038",
        "private": {"run": 43035589916, "distinct_selected_pass": 34,
                    "additional_unmutated_positive_executions": 2,
                    "mutant_executions": 4, "expected_mutant_failures": 2},
        "mem": {"run": 43035589682, "integrity_python_pass": 35,
                "synthetic_readers": 14, "synthetic_writers": 3,
                "cpu_tests_executed": 0, "native_tests_executed": 0, "model_calls": 0},
        "architecture": {"run": 43035589987,
                         "per_lane_qualification_receipted_python": 136,
                         "per_lane_additional_raw_only_preflight_python": 8,
                         "per_lane_total_python": 144,
                         "total_python_executions": 288, "distinct_python_cases": 144,
                         "native_tests_executed": 0,
                         "historical_136_case_receipt_scope_audit_preserved": True},
        "blocking": {"run": 43035589938, "terminal_jobs": 37,
                     "success": 23, "failure": 6, "cancelled": 4, "skipped": 4,
                     "full_blocking_logs_retained": 16,
                     "bazel_artifact_zip_bodies_retained": False},
        "windows_current": {"run": 43035590081, "job": 130573423888,
                            "conclusion": "cancelled", "declared_cases": 167,
                            "completed_cases": 124, "strict_pass": 122,
                            "leak": 1, "fail": 1, "unfinished": 43,
                            "scheduler_cancellation_reason": "UNKNOWN",
                            "final_source_after": "NOT_RECORDED"},
        "scoped_fix": {"run": 43038376307, "job": 130583219316,
                       "command_exits": [0, 0, 0], "strict_result": "FAILED",
                       "third_command_source_rewrites": 2,
                       "timeout_not_inferred_from_partial_collector": True},
    },
    "architecture_count_addendum": evidence("v16/architecture-count-addendum/ROOT_ARCH_PREFLIGHT_ADDENDUM_AUDIT.json", "mem8-ci-followup-v16/ROOT_ARCH_PREFLIGHT_ADDENDUM_AUDIT.json"),
    "current_native_original_admission": {
        "run": 43047914262, "job": 130616746852, "attempt": 1,
        "harness": "5529aeaace80458fb0b1ecae776f95de78c5f9c3",
        "source": SOURCE, "original_job_envelope_minutes": 65,
        "admitted_case_count": 5, "retries": 0,
        "scope": "Separate original Windows qualification; completed acceptance is not established by this checkpoint.",
        "preparation_replay": evidence("v16/native-five-preparation/ROOT_REMOTE_ARCHIVE_AUDIT.json", "mem8-ci-followup-v16/native-five-preparation/ROOT_REMOTE_ARCHIVE_AUDIT.json"),
    },
    "regular_current_source_runs": {"blocking": 43048568477, "private": 43048568252,
                                    "mem": 43048568457, "architecture": 43048568183,
                                    "windows_current": 43048569129},
    "current_source_required_CI_accepted": False,
    "published_evidence": {
        "commit": EVIDENCE, "tree": EVIDENCE_TREE, "pr": 5889, "draft": True,
        "actual_ref_and_full_raw_PR_body_verified": True,
        "checkpoint": evidence("CHECKPOINT_REPAIR_V16.md", "mem8-ci-followup-v16/CHECKPOINT_REPAIR_V16.md"),
        "relative_links_bound_to_full_remote_read_objects": 34,
        "publication_receipt": {"path_in_this_owner_commit": "qualification/memory-cell-mem8-owner/run-001/v10/V16_ACTUAL_PUBLICATION.json", **identity(publication_raw)},
    },
    "recovery_limits": {
        "complete_v8_evidence_reconstructed_and_original_verifier_replayed": True,
        "complete_native_preparation_reconstructed_and_original_verifier_replayed": True,
        "architecture_125MB_original_wrapper_verified_locally_but_not_duplicated_in_Git": True,
        "original_H_v3_process_and_H_v4_write_states": "UNKNOWN_UNCHANGED",
        "original_provider_terminal_and_physical_requests": "UNKNOWN_UNCHANGED",
        "archive_byte_custody_does_not_prove_owner_effect_cold_recovery": True,
    },
    "unresolved_product_limits": [
        "Original elevated outside-root delete assertions remain failed; ordinary-token controls do not qualify elevated behavior.",
        "Setup-handle and matched-recorder source changes require exact-source native results. The original leaked-writer owner remains unidentified.",
        "Fence inventory failure lacks its original unavailable-input subreason; DNS/apt prerequisite failures leave native scopes unexecuted.",
        "Mac assertion failures, timeouts, flakes, cached results and cancelled/unexecuted scopes retain their original identities.",
    ],
    "new_scored_actor_episodes": 0, "new_real_model_requests": 0,
    "adoption_gate_closed_by_source_checks_or_archives": False,
}
host = next(row for row in out["open"] if row["id"] == "HOSTED-CI")
host["status"] = "EXACT_C895_SOURCE_GATES_PASSED_ORIGINAL_NATIVE_FAILURES_RETAINED_CURRENT_CI_NOT_ACCEPTED"
host["finding"] = (
    "The V6, V7 and V8 original source-only checks passed their unchanged 600-second gates, "
    "with full caller/tree/lock checks and 18 Python regressions each. The exact V8 formatter "
    "postimages are published as pure c895/tree5a7 in draft PR5935, with qualification harnesses "
    "outside its ancestry. Published V16 evidence retains all b054 final scopes: Private34 selected "
    "passes; MEM35 integrity passes and zero CPU/native execution; Architecture144 Python cases "
    "per lane (136 receipted plus8 raw-only),288 executions/144 distinct; blocking37 terminal "
    "jobs with23 success/6 failure/4 cancelled/4 skipped; Windows-current122 strict PASS,1 LEAK, "
    "1 FAIL and43 unfinished of167, with no final source-after. Its original scoped-fix commands "
    "all exited0 but two source rewrites failed the strict clean gate. Original elevated delete, "
    "captured-pipe, Mac and prerequisite failures remain. The separately admitted c895 five-case "
    "Windows run43047914262 and regular c895 runs must be judged from their own actual outcomes. "
    "No older native pass, synthetic read, source gate or restored archive closes required CI, "
    "scientific benefit, original owner, provider settlement, deletion or independent trust gates."
)
intake = next(row for row in out["actionable_remaining_inputs"]["gates"] if row["gate_id"] == "HOSTED-CI")
intake["missing_inputs"] = [
    "Accepted required CI and actual dependent scopes on the final source composition; current pure source is c895/tree5a7, not an older head.",
    "Original terminal/source/case/raw/JUnit records for the admitted c895 jobs, including run43047914262; all failures, unexecuted scopes and unknowns remain explicit.",
]
intake["next_step"] = (
    "Adjudicate the already admitted c895 original jobs without replay or replacing their identities. "
    "Review concrete matcher-fixture, setup-handle, elevated-delete and Fence/prerequisite causes; "
    "qualify each changed source separately with the existing assertions, security checks, "
    "deadlines and retry limits. Do not transfer older source-only or native passes to a new head."
)
for version in (6, 7, 8):
    row = next(row for row in out["source_ci_followup_v6_v8"]["source_only_operations"] if row["version"] == version)
    out["closed_this_followup"].append({
        "id": f"MEM8-V{version}-SOURCE-GATES", "status": "CLOSED_SOURCE_ONLY",
        "original_run": row["run"], "original_job": row["job"],
        "scope": "Full original source-only gate and exact postimages verified. No native or adoption gate closes.",
        "evidence_commit": row.get("evidence_commit", EVIDENCE),
    })
out["v10_update_provenance"] = {
    "base_checkpoint_commit": BASE_HEAD, "base_blockers": identity(base_raw),
    "nine_non_CI_gate_objects_unchanged": True, "HOSTED_CI_closure_requirement_unchanged": True,
    "nine_non_CI_actionable_intake_objects_unchanged": True,
    "all_prior_closed_entries_unchanged": True,
    "scientific_results_and_acceptance_thresholds_unchanged": True,
    "original_provider_and_H_unknown_states_unchanged": True,
    "publication_activation": "Only successful expected-head CAS publishes this postimage; the resulting commit is recorded separately.",
    "new_real_model_requests": 0,
}
out["publication"] = {"scope": "Owner PR5897 V10 draft, based on immutable V9 and actually published V16 evidence.",
                      "activation": "ROOT_EXPECTED_HEAD_CAS_SUCCESS_ONLY",
                      "expected_previous_head": BASE_HEAD, "owner_pr": 5897, "draft": True,
                      "actual_new_head": "Recorded separately after successful publication; no ledger self-hash."}
assert len(out["open"]) == 10 and out["production_adoption"] is False
for old, new in zip(before["open"], out["open"]):
    assert old["id"] == new["id"]
    if old["id"] != "HOSTED-CI":
        assert old == new
    else:
        assert old["closure"] == new["closure"]
for old, new in zip(before["actionable_remaining_inputs"]["gates"], out["actionable_remaining_inputs"]["gates"]):
    assert old["gate_id"] == new["gate_id"]
    if old["gate_id"] != "HOSTED-CI":
        assert old == new
    else:
        assert {k: v for k, v in old.items() if k not in {"missing_inputs", "next_step"}} == {k: v for k, v in new.items() if k not in {"missing_inputs", "next_step"}}
assert out["closed_this_followup"][:-3] == before["closed_this_followup"]
changed = {"checkpoint_revision", "checkpoint_utc", "open", "closed_this_followup", "actionable_remaining_inputs", "publication"}
for key in before:
    if key not in changed:
        assert out[key] == before[key], key
raw = (json.dumps(out, indent=2, ensure_ascii=False) + "\n").encode()
(HERE / "BLOCKERS_FINAL.json").write_bytes(raw)
audit = {"schema": "mem8.owner-v10.final-invariant-audit.v1", "base": identity(base_raw),
         "postimage": identity(raw), "open_gates": 10,
         "nine_non_ci_gate_objects_unchanged": True, "nine_non_ci_intake_objects_unchanged": True,
         "HOSTED_CI_closure_requirement_unchanged": True, "prior_closed_entries_unchanged": True,
         "all_other_prior_top_level_fields_unchanged": True,
         "scientific_results_thresholds_original_provider_and_H_unknown_states_unchanged": True,
         "published_evidence": EVIDENCE, "source": SOURCE,
         "actual_owner_ref_update": "NOT_YET_PERFORMED", "new_real_model_requests": 0}
(HERE / "ROOT_FINAL_INVARIANT_AUDIT.json").write_text(json.dumps(audit, indent=2) + "\n")
print(json.dumps(audit, indent=2))
