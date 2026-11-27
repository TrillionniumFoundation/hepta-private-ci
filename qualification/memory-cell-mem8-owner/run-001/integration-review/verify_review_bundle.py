#!/usr/bin/env python3
"""Verify an extracted MEM review bundle without network, native tests or source writes."""
import hashlib
import json
from pathlib import Path
import sys


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "MEMBER_MANIFEST.json").read_text())
    actual = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
    declared = {r["path"] for r in manifest["files"]}
    assert len(declared) == len(manifest["files"])
    assert actual == declared | {"MEMBER_MANIFEST.json"}
    for row in manifest["files"]:
        path = root / row["path"]
        assert not path.is_symlink() and root in path.resolve().parents
        assert not Path(row["path"]).is_absolute() and ".." not in Path(row["path"]).parts
        data = path.read_bytes()
        assert len(data) == row["bytes"] and sha(data) == row["sha256"], row["path"]
        assert git_blob(data) == row["git_blob_sha"], row["path"]
        assert "__pycache__" not in row["path"]
        assert not row["path"].endswith((".xz", ".gz", ".zip", ".tar", ".sqlite", ".db", ".pem", ".key", ".pyc"))
        assert not row["path"].endswith("/ROLLOUT_SAFE_OBSERVATIONS.json")
        assert not data.startswith((b"PK\x03\x04", b"\x1f\x8b", b"\xfd7zXZ\x00", b"SQLite format 3\0"))
        data.decode("utf-8")
    comp = root / "mem-final-composition-readonly"
    proof = json.loads((comp / "GIT_OBJECT_PROOF.json").read_text())
    plan = json.loads((comp / "GIT_TREE_PLAN.json").read_text())
    namespace = {"__name__": "review_import", "__file__": str(comp / "root_verify_trees.py")}
    exec(compile((comp / "root_verify_trees.py").read_text(), namespace["__file__"], "exec"), namespace)
    tree_sha, replay = namespace["tree_sha"], namespace["replay"]
    originals = proof["complete_tree_records"]
    original_count = 0
    for dirs in originals.values():
        for row in dirs.values():
            assert tree_sha(row["entries"]) == row["sha"]
            original_count += 1
    assert original_count == 73
    for branch, compared in proof["comparison"].items():
        assert compared["merge_base"] == plan["base_commit"] and compared["behind_by"] == 0
        changes = []
        for change in compared["files"]:
            parent, _, name = change["path"].rpartition("/")
            row = next(r for r in originals[branch][parent]["entries"] if r["path"] == name)
            assert row["sha"] == change["sha"]
            changes.append({"path": change["path"], "sha": row["sha"], "type": row["type"], "mode": row["mode"]})
        assert replay(originals["common"], changes) == compared["head_tree"]
    assert len(plan["tree_elements"]) == len({x["path"] for x in plan["tree_elements"]}) == 112
    assert replay(originals["common"], plan["tree_elements"]) == plan["expected_tree"]
    commit = json.loads((comp / "INTEGRATION_COMMIT.json").read_text())
    assert commit["tree"]["sha"] == plan["expected_tree"] == "12159640adcf073b51f3837e75575e11f5c20233"
    assert [x["sha"] for x in commit["parents"]] == plan["proposed_parents"]
    assert commit["sha"] == "2ae5215beaf8d7b7df111a090b82134beae2683d"
    publication = json.loads((comp / "PUBLICATION.json").read_text())
    assert publication["commit"] == commit["sha"] and publication["tree"] == plan["expected_tree"]
    capsule_paths = {}
    for name in ["WORKFLOW_SOURCE_CAPSULE.json", "CI_SUPPORTING_SOURCE_CAPSULE.json", "CI_WINDOWS_SCOPE_SOURCE.json", "CI_IGNORED_G_SOURCE.json"]:
        capsule = json.loads((comp / name).read_text())
        for row in capsule.get("files", [capsule]):
            data = row["content"].encode()
            assert len(data) == row["bytes"] and sha(data) == row["sha256"] and git_blob(data) == row["git_blob_sha"]
            assert (comp / "ci-source" / row["path"]).read_bytes() == data
            if row["path"] in capsule_paths:
                assert capsule_paths[row["path"]] == row["git_blob_sha"]
            capsule_paths[row["path"]] = row["git_blob_sha"]
    for row in json.loads((comp / "CI_MAIN_DISPATCH_SOURCES.json").read_text()).values():
        data = row["content"].encode()
        assert len(data) == row["bytes"] and sha(data) == row["sha256"] and git_blob(data) == row["git_blob_sha"]
    actual_ci_sources = {str(p.relative_to(comp / "ci-source")) for p in (comp / "ci-source").rglob("*") if p.is_file()}
    assert actual_ci_sources == set(capsule_paths) and len(capsule_paths) == 107
    frozen = json.loads((comp / "CI_REVIEW_FROZEN_FILES.json").read_text())
    assert len(frozen["files"]) == 121
    for row in frozen["files"]:
        data = (comp / row["path"]).read_bytes()
        assert len(data) == row["bytes"] and sha(data) == row["sha256"] and git_blob(data) == row["git_blob_sha"]
    matrix = json.loads((comp / "CI_REQUIRED_MATRIX.json").read_text())
    assert matrix["source"]["commit"] == commit["sha"] and matrix["source"]["tree"] == plan["expected_tree"]
    assert matrix["scope_select"]["result"]["full_repo"] is True
    assert matrix["branch_protection"]["common"]["protected"] is False
    assert matrix["branch_protection"]["main"]["required_contexts"] == ["CI required", "Architecture required"]
    review = json.loads((root / "mem8-owner-followup-v7/FINAL_BLOCKER_REVIEW_V2.json").read_text())
    assert review["recommended_open_blocker_count"] == 10 and review["newly_closed_original_blocker_ids"] == []
    assert len(review["blockers"]) == 10 and all(r["close_original_blocker"] is False for r in review["blockers"])
    assert review["scientific_acceptance"] == "HOLD" and review["adoption_action"] == "NoUpdate" and review["production_adoption"] is False
    for row in review["evidence"].values():
        assert not row["workspace_relative_path"].endswith("/ROLLOUT_SAFE_OBSERVATIONS.json")
        data = (root / row["workspace_relative_path"]).read_bytes()
        assert len(data) == row["bytes"] and sha(data) == row["sha256"]
    old = json.loads((root / review["base_ledger"]["workspace_relative_path"]).read_text())
    assert [r["id"] for r in review["blockers"]] == [r["id"] for r in old["open"]]
    assert review["counting_boundaries"]["new_scored_memory_actor_episodes"] == 0
    assert review["counting_boundaries"]["physical_provider_requests"] is None
    assert review["protocol_boundaries"]["W"]["minimum_source_groups"] == 20
    assert review["protocol_boundaries"]["W"]["minimum_groups_each_role"] == 4
    assert review["protocol_boundaries"]["E"]["numeric_source_minimum"] is None
    assert review["provider_evidence_correction"]["original_request_outcome"] == "UNKNOWN"
    redacted = json.loads((root / review["evidence"]["provider_rollout_redacted_v3"]["workspace_relative_path"]).read_text())
    assert redacted["derived_projection_not_original_bytes"] is True
    for row in redacted["rows"]:
        if row["record_type"] == "world_state":
            assert "state" not in row and set(row["omitted_fields"]["state"]) == {"type", "canonical_json_sha256", "canonical_json_bytes", "field_names"}
        if "state" in row:
            assert row["record_type"] == "event_msg" and row["payload_type"] == "turn_recovery_candidate" and row["state"] == "ready"
    return {"status": "PASS", "members": len(actual), "original_git_trees": original_count,
            "branch_root_reconstructions": 4, "overlay_files": 112, "published_commit": commit["sha"],
            "published_tree": commit["tree"]["sha"], "workflow_and_support_source_files": len(capsule_paths),
            "active_review_evidence_pins": len(review["evidence"]), "original_blockers_open": 10,
            "new_native_or_model_execution": False, "original_provider_outcome": "UNKNOWN"}


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
    print(json.dumps(verify(root), sort_keys=True, indent=2))
