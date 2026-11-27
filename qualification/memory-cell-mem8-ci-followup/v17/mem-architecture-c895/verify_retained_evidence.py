"""Replay retained original evidence only; no test, build, model or network call."""
import contextlib
import io
import json
from pathlib import Path

import audit_completed_records as audit
import audit_mem_arch_originals as final_audit
from audit_arch_candidate_preflight import audit_raw
from tree_identity import listing, tree_hash

HERE = Path(__file__).resolve().parent

def verify():
    manifest = audit.load(HERE / "FILE_MANIFEST.json")
    actual_files = {p.relative_to(HERE).as_posix() for p in HERE.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert actual_files == {r["path"] for r in manifest["files"]} | {"FILE_MANIFEST.json"}
    for row in manifest["files"]:
        assert audit.identity((HERE / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    originals = [audit.verify_artifact(aid) for aid in (13868481966, 13868718108, 13867409972, 13867373162)]
    large = HERE / "artifacts/13867509444"
    large_manifest = audit.load(large / "MANIFEST.json")
    retained_members = []
    for row in large_manifest["members"]:
        if row["name"] == "source-input.tar.gz":
            continue
        data = (large / "files" / row["name"]).read_bytes()
        assert len(data) == row["bytes"] and audit.identity(data)["sha256"] == row["sha256"]
        retained_members.append(row["name"])
    assert len(retained_members) == 9
    before = (HERE / "MEM_ARCH_ORIGINAL_FINAL_AUDIT.json").read_bytes()
    with contextlib.redirect_stdout(io.StringIO()):
        final_audit.main()
    assert (HERE / "MEM_ARCH_ORIGINAL_FINAL_AUDIT.json").read_bytes() == before
    final = json.loads(before)
    expected = listing((HERE / "references/CANDIDATE_TREE.ls-tree").read_bytes())
    index = audit.load(HERE / "SOURCE_ARCHIVE_FULL_INDEX.json")
    measured = {r["path"]: {"mode": r["mode"], "type": "blob", "git_blob": r["git_blob"]} for r in index["files"]}
    assert len(measured) == len(index["files"]) == len(expected) == 14053
    assert measured == expected and tree_hash(measured) == audit.TREE
    commit = audit.load(HERE / "SOURCE_COMMIT.json")
    assert commit["sha"] == audit.HEAD and commit["tree"]["sha"] == audit.TREE
    for path in (HERE / "source").rglob("*"):
        if path.is_file():
            assert expected[path.relative_to(HERE / "source").as_posix()]["git_blob"] == audit.identity(path.read_bytes())["git_blob"]
    addendum = audit.load(HERE / "ARCH_CANDIDATE_RAW_ONLY_COUNT_ADDENDUM.json")
    old = audit.load(HERE / "reference-b054/AUDIT.json")
    for row in addendum["jobs"]:
        is_current = row["source_commit"] == audit.HEAD
        if is_current:
            groups = [r for r in final["groups"] if r["lane"] == row["lane"] and r["artifact_id"] in (13867509444, 13867373162)]
            raw = HERE / f"original/job-{row['job_id']}.log"
        else:
            groups = [r for r in old["groups"] if r["lane"] == row["lane"] and r["artifact_id"] in (13862859146, 13862932588)]
            raw = HERE / f"reference-b054/job-{row['job_id']}.log"
        ids = {name for group in groups for name in group["case_ids"]}
        replayed = audit_raw(raw, row["source_commit"], row["source_tree"], row["tested_commit"], row["lane"], row["job_id"], ids)
        assert replayed["all_python_execution_case_ids"] == addendum["all_144_case_ids"]
        replayed.pop("raw_file")
        replayed.pop("all_python_execution_case_ids")
        expected_row = {key: value for key, value in row.items() if key not in ("raw_file", "all_python_case_ids_canonical_json_sha256")}
        assert replayed == expected_row
    for row in manifest["files"]:
        assert audit.identity((HERE / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    return {"status": "PASS_RETAINED_EVIDENCE_SCOPE", "files": len(actual_files), "source_commit": audit.HEAD,
            "source_tree": audit.TREE, "complete_original_ZIPs_replayed": originals,
            "large_Architecture_ZIP_small_members_replayed": retained_members,
            "source_index_entries_bound_to_complete_Git_tree": 14053,
            "large_original_ZIP_and_source_tar_present_in_this_package": False,
            "wrapper_boundary": "The original 125 MB ZIP and source tar were fully read locally. This packet retains the byte identities, complete source index, exact Git tree, and small diagnostics; it does not contain that compressed wrapper.",
            "MEM_integrity_python_passed": 35, "MEM_CPU_contract_tests_executed": 0, "MEM_native_tests_executed": 0,
            "Architecture_python_executions": 288, "Architecture_unique_python_case_ids": 144,
            "Architecture_native_tests_executed": 0, "Architecture_required_conclusion": "failure",
            "synthetic_readers": 14, "synthetic_writers": 3, "both_original_workflows_failed": True,
            "tests_builds_models_or_network_operations_executed_by_this_verifier": 0}

if __name__ == "__main__":
    print(json.dumps(verify(), indent=2, sort_keys=True))
