import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
V1 = ROOT.parent / "execution-candidate-v1"
ARCH = Path("architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3").resolve()


def identity(path):
    body = path.read_bytes()
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def item(path, role=None):
    return {"local_file": str(path), "role": role or path.name, **identity(path)}


mapping = json.loads((ROOT / "source-map.json").read_text())
combined = json.loads((ROOT / "combined-source-map.json").read_text())
manifest = copy.deepcopy(json.loads((V1 / "manifest.json").read_text()))
manifest.update(schema="hepta.static_proposal.read_acl_readiness_execution.v2",
                frozen_at_utc=datetime.now(timezone.utc).isoformat(),
                status="FROZEN_V3_CONSUMER_STATIC_ONLY_PENDING_INDEPENDENT_EXECUTION_REVIEW_AND_WINDOWS")
manifest["files"] = mapping["files"]
manifest["patch"] = item(ROOT / "execution.patch")
manifest["preserved_V1"] = {"manifest": item(V1 / "manifest.json"), "actual_publication_map": item(V1 / "publication-map.json"),
                            "all_16_original_objects_actual_create_GET_equal": True,
                            "scope": "0f with 25def counterfactual; source, documents and receipts not rewritten."}
manifest["counterfactual_dependency"] = {
    "path": ".github/scripts/run_b11_acl_identity_counterfactual.py", **mapping["required_control_postimage"],
    "required_V3_patch": item(ARCH / "full.patch"), "V3_manifest": item(ARCH / "manifest-DISABLED.json"),
    "V3_actual_publication_map": item(ARCH / "github-readback-map.json"),
    "independent_review_actual_blob": "c4ff565c7d003890d6ad42420ec18e802053f467",
    "explicit_consumer_pin_delta": item(ROOT / "v1-to-v2-consumer-pin.delta.patch"),
    "all_nine_non_main_functions_and_terminal_restore_interface_unchanged": True,
    "new_positive_scopes_field_not_used_as_a_substitute_for_valid_restored_terminal": True}
manifest["static_verification"] = item(ROOT / "static-composition-verification.json")
manifest["V1_static_checks_preserved"] = item(V1 / "static-verification.json")
manifest["fixed_source_evidence"] += [item(path) for path in sorted((ROOT / "originals").glob("*.json"))]
manifest["combined_delivery"] = {
    "patch": item(ROOT / "combined-seven-paths.patch"), "source_map": item(ROOT / "combined-source-map.json"),
    "files": combined["files"], "path_count": 7, "added_lines": 400, "deleted_lines": 99,
    "independent_cohorts": ["readiness Rust 3 paths: 96+/92-", "execution 3 paths: 244+/0-", "counterfactual V3 1 path: 60+/7-"],
    "real_isolated_sequential_and_full_patch_application_produced_all_7_identical_postimages": True,
    "source_refs_and_original_lockfiles_untouched": True,
    "not_a_published_commit_or_an_executed_source": True}
manifest["helper_runtime_requirements"]["build_cache_is_not_disabled_or_counted_as_a_test_pass"] = True
manifest["helper_runtime_requirements"]["source_anchors_are_10_old_and_1_previously_prepared_readiness_control"] = True
manifest["no_new_native_or_parser_tests_added_for_this_wiring"] = True
manifest["required_independent_review"] = "CI agent reviews final execution V2 and exact composition; no launch/ref action by this author."
(ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

new_paths = [ROOT / "candidate/.github/scripts/run_b11_read_acl_readiness.py"]
new_paths += [ROOT / name for name in ("execution.patch", "v1-to-v2-consumer-pin.delta.patch", "combined-seven-paths.patch",
             "source-map.json", "combined-source-map.json", "assemble_verify.py", "freeze_manifest.py",
             "static-composition-verification.json", "README.zh-CN.md", "manifest.json")]
new_paths += sorted((ROOT / "originals").glob("*.json"))
plan = [item(path, path.relative_to(ROOT).as_posix()) for path in new_paths]
assert all(row["bytes"] < 512000 for row in plan)
(ROOT / "upload-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
existing = []
for row in combined["files"]:
    if row["path"] == ".github/scripts/run_b11_read_acl_readiness.py":
        continue
    if row["cohort"] == "execution-v2":
        proof = V1 / "publication-map.json"
    elif row["cohort"] == "readiness-rust-0a80":
        proof = ROOT.parent / "publication-map.json"
    else:
        proof = ARCH / "github-readback-map.json"
    existing.append({"path": row["path"], "local_file": row["local_postimage"], **row["postimage"],
                     "already_published_and_GET_verified_source": item(proof)})
(ROOT / "existing-object-references.json").write_text(json.dumps(existing, indent=2) + "\n")
plan.append(item(ROOT / "existing-object-references.json", "existing-object-references.json"))
(ROOT / "upload-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
print(json.dumps({"manifest": identity(ROOT / "manifest.json"), "new_objects": len(plan),
                  "already_actual_postimages": len(existing), "bytes": sum(row["bytes"] for row in plan)}))
