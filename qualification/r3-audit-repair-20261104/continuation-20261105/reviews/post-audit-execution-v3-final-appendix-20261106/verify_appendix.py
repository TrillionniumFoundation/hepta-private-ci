#!/usr/bin/env python3
"""Narrow custody and actual-publication checks; does not run audited code or CI."""
import hashlib
import json
from pathlib import Path
import sys

def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}

def check(data, row):
    assert all(row[k] == v for k, v in ident(data).items())

def load(path):
    return json.loads(path.read_bytes())

def tool_content(path):
    value = load(path)
    assert value.get("isError") is not True
    content = value["structuredContent"]["content"]
    assert isinstance(content, str)
    return content

def api(path):
    value = load(path)
    assert value.get("isError") is not True
    obj = value["structuredContent"]
    return json.loads(obj["content"]) if isinstance(obj.get("content"), str) else obj

def one(directory, *names):
    matches = [directory / name for name in names if (directory / name).is_file()]
    assert len(matches) == 1, ("ambiguous or missing actual record", names)
    return matches[0]

root = Path(sys.argv[1]).resolve()
freeze = load(root / "FREEZE.json")
assert len(freeze["files"]) == freeze["file_count"]
assert len({row["path"] for row in freeze["files"]}) == len(freeze["files"])
assert sum(row["bytes"] for row in freeze["files"]) == freeze["total_bytes"]
for row in freeze["files"]:
    check((root / row["path"]).read_bytes(), row)
assert not any(Path(row["path"]).name in {"POST_AUDIT_EXECUTION_UPDATE_V3.zh-CN.md", "post-audit-execution-v3.json", "evidence-index-v13-addendum.json"} for row in freeze["files"])

cut = root / "fourth-audit-current-cut"
metadata = load(cut / "METADATA-REVIEW.json")
assert metadata["new_full_repository_census"] is False
assert metadata["metadata_is_not_whole_PR_source_review"] is True
assert metadata["source_and_native_acceptance_not_transferred"] is True
assert len(metadata["records"]) == 10
assert sum(row["identity"]["bytes"] for row in metadata["records"]) == 2962768
for row in metadata["records"]:
    path = cut / row["file"]
    check(path.read_bytes(), row["identity"])
    value = api(path)
    if "pr" in row:
        assert value["number"] == row["pr"] and value["head"]["sha"] == row["head"] and value["base"]["sha"] == row["base"]
        assert value["draft"] == row["draft"] and value["state"] == row["state"]
        assert value["commits"] == row["commits"] and value["changed_files"] == row["changed_files"]
    elif "ref" in row:
        assert value["ref"] == row["ref"] and value["object"]["sha"] == row["head"]
    else:
        assert value["status"] == row["status"] == "ahead"
        assert value["ahead_by"] == row["ahead_by"] == 512 and value["behind_by"] == row["behind_by"] == 0
        assert value["merge_base_commit"]["sha"] == row["merge_base"] == "732e934ba496d90fbe042b8d41d479ef901643e5"
        assert len(value["files"]) == row["returned_file_records"] == 300
        assert row["full_source_diff_reviewed"] is False
compare = api(cut / "main-to-product.compare.original.json")
summary = load(cut / "main-to-product.summary.json")
assert compare["total_commits"] == summary["total_commits"] == 512
assert len(compare["commits"]) == summary["returned_commits"] == 1
assert summary["complete_source_diff_review"] is False

prroot = root / "pr4930-fa-increment-readonly-20261106"
prfreeze = load(prroot / "FREEZE.json")
assert ident((prroot / "FREEZE.json").read_bytes())["git_blob"] == "ce2ca32d5300b0a107e481c4209236d2cc3198b6"
assert len(prfreeze["files"]) == prfreeze["file_count"] == 82
for row in prfreeze["files"]:
    check((prroot / row["path"]).read_bytes(), row)
assert (prroot / "pr-4930.original.json").read_bytes() == (cut / "pr-4930.original.json").read_bytes()
prproof = load(prroot / "verification-01.stdout.json")
assert prproof["new_head"] == "fa1c0592e7d1dea60cd8d8459a4e2b18fdfbab61" and prproof["compare"]["paths"] == 60
assert prproof["all_19_execution_source_sha256_equal_actual_fa_bodies"] is True
assert prproof["campaign_statuses"] == {"VERIFIED": 1, "REJECTED": 8, "HOLD": 2}
assert prproof["authority"] == "DENY_ALL" and prproof["closure_transitions"] == []
check((prroot / "verification-01.stdout.json").read_bytes(), {"bytes": 26077, "git_blob": "f9e9c5d8108d7f80edc4e1d19adbaf6d5c36facd", "sha256": "eb9e5c89a950ca07451cc5eb781b80c50935ee5e376421878c72f0c7a08dd160"})
acceptance = tool_content(root / "pr4930-fa-increment-root-readback/ACCEPTANCE.actual.original.json").encode()
assert acceptance == (prroot / "postimage/ACCEPTANCE_20261106.md").read_bytes()
assert ident(acceptance)["git_blob"] == "ed8f418e6e1d8ae85260a9aae5a09829a81e70b5"

history = root / "third-post-audit-inputs"
failed = load(history / "components.validation-05.exec.original.json")
assert failed["exit_code"] == 1 and "registry identity differs" in failed["output"]
passed = load(history / "components.validation-06.exec.original.json")
validation = load(history / "components.validation-06.json")
assert passed["exit_code"] == 0 and json.loads(passed["output"]) == validation
assert validation["paths"] == 248 and validation["unique_blobs"] == 234 and len(validation["groups"]) == 11
assert validation["input_files_rehashed"] == 303 and validation["native_CI_ref_operations"] is False
check((history / "prepare_third_post_audit_delta.at_components_validation_06.py").read_bytes(), validation["builder"])
assert validation["builder"]["git_blob"] == "35b9f129e6a2b582e41c83f5db62b49ae688bb66"
seventh = load(history / "components.validation-07.json")
seventh_exec = load(history / "components.validation-07.exec.original.json")
assert seventh_exec["exit_code"] == 0 and json.loads(seventh_exec["output"]) == seventh
assert seventh["paths"] == 288 and seventh["unique_blobs"] == 273 and len(seventh["groups"]) == 12
assert seventh["input_files_rehashed"] == 346 and seventh["builder"] == validation["builder"]
assert seventh["native_CI_ref_operations"] is False
preread = load(root / "v3-report-preread-windows-env-20261106/PREREAD.json")
check((root / "third-post-audit-review-inputs/ROOT-DRAFT-01.md").read_bytes(), preread["reviewed_report"])
assert preread["reviewed_report"]["git_blob"] == "7f35c93e68cf53943578ab0807b24262777710c8"
assert preread["edits_to_author_report"] is False and preread["new_native_execution"] is False and preread["new_CI_query_in_this_review"] is False

expected = freeze["expected_publication"]
pub = root / "integration-840-format-publication"
confirmed = load(pub / "publication-verified.json")
assert confirmed["head"] == expected["head"] and confirmed["tree"] == expected["tree"]
commit = api(pub / "commit.actual.original.json")
merge = api(pub / "merge.actual.original.json")
tree = api(pub / "tree.actual.original.json")
ref = api(pub / "ref.after.original.json")
pr = api(pub / "pr.after.original.json")
prior_pr = api(pub / "pr.before.original.json")
assert commit["sha"] == expected["head"] and commit["tree"]["sha"] == expected["tree"]
assert [p["sha"] for p in commit["parents"]] == [expected["parent"]]
assert tree["sha"] == expected["tree"] and tree.get("truncated") is not True
assert ref["ref"] == "refs/heads/integration/r3-repairs-and-locks-20261106" and ref["object"]["sha"] == expected["head"]
assert merge["sha"] == pr["merge_commit_sha"] and merge["tree"]["sha"] == expected["tree"]
assert [p["sha"] for p in merge["parents"]] == [expected["base"], expected["head"]]
assert pr["number"] == 4936 and pr["head"]["sha"] == expected["head"] and pr["base"]["sha"] == expected["base"]
assert pr["draft"] is True and pr["merged"] is False and pr["state"] == "open"
bodyplan = load(one(pub, "pr-body-update.plan.json", "pr-body.plan.json"))
planned = bodyplan["new_body"] if "new_body" in bodyplan else bodyplan["body"]
assert pr["body"] == planned and pr["body"].endswith(prior_pr["body"])
if "old_body" in bodyplan:
    assert bodyplan["old_body"] == prior_pr["body"]
if "original_body" in bodyplan:
    assert bodyplan["original_body"] == prior_pr["body"]
assert confirmed["native_qualification"] == "PENDING_OWN_ORIGINAL_CI"
assert confirmed["manual_CI_operations"] == [] and confirmed["all_blockers_closed"] is False
assert confirmed["blocker_counts"] == {"CLOSED_SCOPED": 16, "OPEN": 6, "SCIENTIFIC_HOLD": 1}
print(json.dumps({
    "schema": "hepta-fourth-audit-final-appendix-narrow-verification-v1",
    "frozen_files": freeze["file_count"], "frozen_bytes": freeze["total_bytes"],
    "metadata_cut": {"actual_original_API_records": 10, "original_API_bytes": 2962768, "main_to_product_ahead": 512, "behind": 0, "returned_file_records": 300, "returned_commit_records": 1, "full_source_diff_reviewed": False},
    "pr4930_increment": {"head": prproof["new_head"], "changed_paths": 60, "frozen_members": 82, "actual_root_ACCEPTANCE_GET_equals_reviewed_bytes": True, "authority": "DENY_ALL", "B16_B18_acceptance": False},
    "historical_preparer_validation": {"failure05_retained": True, "success06_retained": True, "paths06": 248, "unique_blobs06": 234, "inputs_rehashed06": 303, "success07_retained": True, "paths07": 288, "unique_blobs07": 273, "inputs_rehashed07": 346, "snapshot": validation["builder"], "large_preparer_reexecuted": False},
    "historical_report_preread": {"reviewed_draft": preread["reviewed_report"], "final_report_not_included": True},
    "actual_format_successor_publication": {"head": commit["sha"], "tree": commit["tree"]["sha"], "parents": [p["sha"] for p in commit["parents"]], "ref": ref["object"]["sha"], "merge": merge["sha"], "merge_tree": merge["tree"]["sha"], "merge_parents": [p["sha"] for p in merge["parents"]], "PR": 4936, "draft": True, "full_PR_body_readback_equal": True, "old_body_exact_suffix": True},
    "limits": ["No full main-to-product diff audit.", "PR4930 source/receipts retain their prior component-only execution scope.", "No formatter-native result or other platform acceptance transferred to the successor.", "Does not rerun qualification code, large preparer or native CI.", "Final C4 report/index/config/plan excluded to prevent circular dependencies."],
    "ledger_transitions": [], "native_CI_ref_PR_operations": False
}, ensure_ascii=False, indent=2))
