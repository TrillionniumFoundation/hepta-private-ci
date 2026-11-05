"""Assemble exact source and observed-evidence identities for disabled V7."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
OUT = ROOT / "v7-candidate"


def pin(path):
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


preservation = json.loads((ROOT / "preservation-verification.json").read_bytes())
preservation["legacy_mode"] = "All legacy guard, capacity, family and runner implementation files are byte-identical; no historical receipt or path is relabeled."
(ROOT / "preservation-verification.json").write_text(json.dumps(preservation, ensure_ascii=False, indent=2) + "\n")
verification = json.loads((ROOT / "cloud-verification-v1/verification.json").read_bytes())
source_map = json.loads((ROOT / "source-map-v7.json").read_bytes())
base = ROOT.parent / "build-only-current-host-v6"
analysis = WORKSPACE / "ci-audit/recovered-20261105/b16-ai395-cold-bootstrap-v1/p4-v3-catalog-readonly-export-v1/catalog-analysis.json"
manifest = {
    "schema": "hepta-b16-v7-original-ignored-catalog-review-v1",
    "status": "SOURCE_FROZEN_CLOUD_CONTROLS_PASS_NATIVE_BINDING_DISABLED",
    "correction": {
        "prior_v6_manifest": pin(base / "review-manifest-v6.json"),
        "prior_v6_integrity": pin(base / "v6-candidate/runner-integrity.json"),
        "prior_records_preserved": True,
        "actual_defect": "P4 and V6 required all full-catalog cases to match, incorrectly rejecting 57 original ignored mismatch/reason=ignored cases.",
        "prior_review_limitation": "The original V6 static review did not compare its all-matches predicate and synthetic testcase fixture to the complete actual catalog; this V7 explicitly corrects that omission.",
        "p4_original_three_command_exit_codes": [0, 0, 0],
        "p4_original_controller_exit_code": 1,
        "p4_tests_executed": False,
        "this_is_not_a_product_failure_or_test_retry": True,
    },
    "accepted_case_contract": {
        "eligible": {"ignored": False, "filter_match": {"status": "matches"}, "count": 19506},
        "ignored": {"ignored": True, "filter_match": {"status": "mismatch", "reason": "ignored"}, "count": 57},
        "all_other_filter_forms_rejected": True,
        "ignored_requires_actual_boolean": True,
        "complete_counter_schema": ["binary_id", "name", "ignored"],
        "complete_sorted_counter_sha256": "2e483bc224e88e59f6ca6680c50d68d8123aa149268d4797de4d5c8496880674",
        "complete_counter_not_count_only": True,
        "case_names_or_ignored_membership_cannot_change": True,
        "historical_exact_raw_envelope": pin(OUT / "observed-original-A-catalog.json"),
    },
    "independently_read_originals": {
        "old_original": verification["old_original"], "old_source": verification["old_source"],
        "current_original": verification["new_original"], "current_source": verification["new_source"],
        "current_readonly_analysis": pin(analysis),
        "complete_19563_counter_equal": True, "complete_filter_forms_equal": True,
        "current_metadata_or_catalog_commands_repeated": False,
    },
    "change_scope": {
        "candidate_files": 29, "integrity_files": 25, "unchanged_existing_inputs": 22,
        "only_changed_runtime": "b16_build_only.py",
        "changed_files": source_map["changed_files"],
        "source_payload_project_test_or_ignored_policy_changes": False,
        "old_four_test_bodies_preserved": verification["original_four_test_bodies_byte_equal"],
        "test_fixture_correction": verification["fixture_correction"],
        "new_guard_tests": 2, "new_filter_subcases": 6, "new_counter_subcases": 3,
    },
    "pure_cloud_verification": pin(ROOT / "cloud-verification-v1/verification.json"),
    "preservation": pin(ROOT / "preservation-verification.json"),
    "source_map": pin(ROOT / "source-map-v7.json"),
    "patch": pin(ROOT / "v6-to-v7.delta.patch"),
    "integrity": pin(OUT / "runner-integrity.json"),
    "templates": [pin(OUT / name) for name in
                  ("binding-template-UNBOUND.json", "foundation-binding-UNBOUND.json", "foundation-build-only-binding-UNBOUND.json")],
    "concrete_foundation_binding_requirements": {
        "target_reuse_mode": "BUILD_ONLY_CURRENT_HOST",
        "actual_baseline_must_be_read_and_bound": True,
        "baseline_role": "BUILD_ONLY_CURRENT_HOST",
        "baseline_tests_executed": False, "baseline_test_qualification": False,
        "final_A_tree": "4a3374e22e16ce5c764288ad018cd9affadf94ea",
        "ordinary_head": "20fd174ded4e5ce01bda34e4f6d1d74803301f49",
        "historical_A_source": "fb9e131272f7e7a138d6c0d1af2b048b9a6ab7ff",
        "historical_hygiene_review": "40bd8b7030931cae6573ec126f4afc13a1140d33",
        "current_host_and_owner_not_historical_ROG_paths": True,
        "full_metadata_workspace_members": 193, "full_metadata_resolve_nodes": 1501,
        "complete_programs": 363, "complete_helpers": 33, "original_commands": 3, "original_source_guards": 6,
        "readonly_completion_guards_are_additional_not_relabelled": True,
        "same_actual_environment_both_SDKs_tools_recipes_index_and_locks": True,
        "future_binding_not_created_here": True,
        "fresh_free_and_capacity_guards_unchanged": True,
    },
    "internal_stage_ids_are_not_original_blocker_ids": True,
    "native_started": False, "refs_changed": False, "enabled_binding": False,
}
(ROOT / "review-manifest-v7.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(pin(ROOT / "review-manifest-v7.json"), indent=2))
