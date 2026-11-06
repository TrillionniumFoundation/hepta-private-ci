import argparse
import hashlib
import json
from pathlib import Path


AC18 = "ac18b623c7a6cb953b4660979e9b620fe7176bb2"
AAF = "aaf86881da0b3a7651b4a6a56be49515b9aa9f2e"
FIRST = "875b774885c002bbe157fd2919fcb590ee1e0131"
FINAL = "840e8b5dbffca017753cdf87482ce325938f313c"
BASE = "63652be658ebed8d3052eb789b951793384fd5e4"
AC18_TREE = "c3e9ddc1799f470ac7c80e117ee953a7232847e0"
AAF_TREE = "66552bda88637403f4f1d72a5be8592e07a8a308"
FIRST_TREE = "c24f6910e0af5a3ebf809c29f1fb06dafbd94146"
FINAL_TREE = "b38cc55050c74f8765bdee397a24066c100a179a"
BRANCH = "integration/r3-repairs-and-locks-20261106"
ARG0 = "integration-arg0-fixture-publication/"
COMBINED = "integration-pty-supervisor-publication/"


def identity(data):
    return {"bytes": len(data),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
            "sha256": hashlib.sha256(data).hexdigest()}


def merkle(leaves):
    root = {}
    for name, row in sorted(leaves.items()):
        assert row["path"] == name and row["type"] == "blob"
        parts = name.split("/")
        assert all(part not in ("", ".", "..") for part in parts)
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        assert parts[-1] not in node
        node[parts[-1]] = (row["mode"], row["sha"])
    directories = []

    def visit(node, prefix):
        pieces = []
        for name, value in node.items():
            path = prefix + name
            if isinstance(value, dict):
                sha = visit(value, path + "/")
                mode = "40000"
                directories.append({"path": path, "mode": "040000", "type": "tree", "sha": sha})
                order = name.encode() + b"/"
            else:
                mode, sha = value
                order = name.encode()
            pieces.append((order, mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(sha)))
        payload = b"".join(piece for _, piece in sorted(pieces))
        return hashlib.sha1(b"tree " + str(len(payload)).encode() + b"\0" + payload).hexdigest()

    sha = visit(root, "")
    return {"sha": sha, "truncated": False,
            "tree": sorted([*leaves.values(), *directories], key=lambda row: row["path"])}


def verify(packet):
    manifest = json.loads((packet / "ORIGINALS-MANIFEST.json").read_bytes())
    assert manifest["file_count"] == len(manifest["files"]) == 74
    assert len({row["path"] for row in manifest["files"]}) == 74
    for row in manifest["files"]:
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        assert identity((packet / path).read_bytes()) == {key: row[key] for key in ("bytes", "git_blob", "sha256")}
    assert sum(row["bytes"] for row in manifest["files"]) == 12875033
    root = packet / "root"

    def load(name):
        return json.loads((root / name).read_bytes())

    def actual_text(name):
        response = load(name)
        assert response["isError"] is False
        return response["structuredContent"]["content"]

    def actual(name):
        return json.loads(actual_text(name))

    def check_commit(name, sha, tree, parents):
        commit = actual(name)
        assert commit["sha"] == sha and commit["tree"]["sha"] == tree
        assert [row["sha"] for row in commit["parents"]] == parents
        return {"sha": sha, "tree": tree, "parents": parents,
                "original_API": name, "signature_verification_reexecuted": False}

    commits = [
        check_commit(ARG0 + "commit.actual.original.json", AAF, AAF_TREE, [AC18]),
        check_commit(ARG0 + "merge.actual.original.json", "8ca7a5b30bf6abfaf3ad7bb538d00f505d0847f8", AAF_TREE, [BASE, AAF]),
        check_commit(COMBINED + "first.commit.actual.original.json", FIRST, FIRST_TREE, [AAF]),
        check_commit(COMBINED + "final.commit.actual.original.json", FINAL, FINAL_TREE, [FIRST]),
        check_commit(COMBINED + "merge.actual.original.json", "e0993cb056c30ae4b694f5c0a187759f0edeefe1", FINAL_TREE, [BASE, FINAL]),
    ]
    for prefix, before, after in [(ARG0, AC18, AAF), (COMBINED, AAF, FINAL)]:
        for name, expected in [("ref.before.original.json", before), ("ref.prelease.original.json", before), ("ref.after.original.json", after)]:
            ref = actual(prefix + name)
            assert ref["ref"] == "refs/heads/" + BRANCH
            assert ref["object"]["type"] == "commit" and ref["object"]["sha"] == expected

    pr_summary = []
    for prefix, path, head, merge, original_key in [
        (ARG0, "pr.final.original.json", AAF, "8ca7a5b30bf6abfaf3ad7bb538d00f505d0847f8", "previous_body"),
        (COMBINED, "pr.after.original.json", FINAL, "e0993cb056c30ae4b694f5c0a187759f0edeefe1", "original_body"),
    ]:
        pr = actual(prefix + path)
        plan = load(prefix + "pr-body.plan.json")
        assert pr["number"] == 4936 and pr["head"]["sha"] == head and pr["base"]["sha"] == BASE
        assert pr["head"]["ref"] == BRANCH
        assert pr["merge_commit_sha"] == merge and pr["draft"] is True and pr["state"] == "open"
        assert pr["body"] == plan["body"] and pr["body"].endswith(plan[original_key])
        assert actual(prefix + "pr.before.original.json")["body"] == plan[original_key]
        pr_summary.append({"head": head, "merge": merge, "body_chars": len(pr["body"]),
                           "prior_body_exact_suffix_preserved": True, "base": BASE,
                           "changed_files_against_target_base": pr["changed_files"], "commits_against_target_base": pr["commits"]})

    def full_tree(name, pin):
        data = load(name)
        assert data["sha"] == pin and data["truncated"] is False
        normalized = [{key: row[key] for key in ("path", "mode", "type", "sha")} for row in data["tree"]]
        assert len({row["path"] for row in normalized}) == len(normalized)
        leaves = {row["path"]: row for row in normalized if row["type"] != "tree"}
        rebuilt = merkle(leaves)
        assert rebuilt["sha"] == pin and rebuilt["tree"] == sorted(normalized, key=lambda row: row["path"])
        return leaves, rebuilt

    aaf, aaf_full = full_tree("b21-writer-observation-candidate/authority/base-full-tree.json", AAF_TREE)
    first, first_full = full_tree("b21-writer-observation-candidate/verification-01/intended-full-tree.json", FIRST_TREE)
    final, final_full = full_tree(COMBINED + "intended-full-tree.json", FINAL_TREE)
    assert len(aaf) == len(first) == 10802 and len(final) == 10804

    arg0_verified = load(ARG0 + "publication-verified.json")
    ac18 = dict(aaf)
    arg0_changes = []
    for row, api in zip(arg0_verified["changed_paths"], ["workflow", "dependencies", "tests"], strict=True):
        path = row["path"]
        body = actual_text(ARG0 + api + ".source.actual.original.json").encode()
        assert identity(body) == row["postimage"] and aaf[path]["sha"] == row["postimage"]["git_blob"]
        ac18[path] = {"path": path, "mode": row["mode"], "type": "blob", "sha": row["preimage"]["git_blob"]}
        arg0_changes.append(path)
    assert len(arg0_changes) == 3 and merkle(ac18)["sha"] == AC18_TREE
    assert sum(ac18[path] == aaf[path] for path in ac18) == 10799

    plan = load(COMBINED + "publication-plan.json")
    first_changes = sorted(path for path in aaf if aaf[path] != first[path])
    second_changes = sorted(path for path in set(first) | set(final) if first.get(path) != final.get(path))
    all_changes = sorted(path for path in set(aaf) | set(final) if aaf.get(path) != final.get(path))
    assert first_changes == plan["first_paths"] and len(first_changes) == 3
    assert second_changes == plan["second_paths"] and len(second_changes) == 3
    assert not set(first_changes) & set(second_changes)
    assert all_changes == plan["changed_paths_against_aaf"] and len(all_changes) == 6
    assembled = dict(first)
    for row, api in zip(plan["second_tree_elements"], ["unix", "connect", "tests"], strict=True):
        body = actual_text(COMBINED + "supervisor." + api + ".actual.original.json").encode()
        assert identity(body)["git_blob"] == row["sha"] and row["mode"] == "100644" and row["type"] == "blob"
        assert first.get(row["path"]) == ac18.get(row["path"])
        assembled[row["path"]] = row
    assert assembled == final and merkle(assembled)["sha"] == FINAL_TREE
    assert sum(final.get(path) == row for path, row in aaf.items()) == 10798
    assert final["codex-rs/hepta-supervisor/tests/paired_process_product.rs"]["sha"] == "c03bdba974ea48281cd839b9161eb0ccdc38b892"
    for name, full in [(ARG0 + "tree.actual.original.json", aaf_full),
                       (COMBINED + "combined.tree.actual.original.json", final_full)]:
        api = actual(name)
        assert api["sha"] == full["sha"] and api["truncated"] is False
        roots = sorted([{key: row[key] for key in ("path", "mode", "type", "sha")} for row in api["tree"]], key=lambda row: row["path"])
        assert roots == [row for row in full["tree"] if "/" not in row["path"]]
        assert len(roots) == 53

    for name, pin in [(ARG0 + "independent.review.actual.original.json", "cd7ed2f2a033882671a24258e1d360863039e5d0"),
                      (COMBINED + "b21.review.actual.original.json", "4f14ab769aa1d95a4e46249f345323beaeeaf68c"),
                      (COMBINED + "supervisor.review.actual.original.json", "35b07140231fa056026ca00088930873a4812b55")]:
        assert identity(actual_text(name).encode())["git_blob"] == pin

    receipts_prefix = "arg0-fixture-prebuild-candidate-20261106/delivery/"
    registry_body = (root / (receipts_prefix + "registry.actual.json")).read_bytes()
    assert identity(registry_body)["git_blob"] == "08e8e7ea26909d95392a0eddc157f75e308e2e9c"
    registry = json.loads(registry_body)
    original_rows = {row["source_file"]: row for row in registry["files"]}
    assert len(original_rows) == 30
    self_receipt = load(receipts_prefix + "registry.self.actual.json")
    assert self_receipt["actual_full_GET"]["structuredContent"]["content"].encode() == registry_body
    observed = set()
    batch_rows = []
    for index in range(4):
        name = receipts_prefix + f"registration-originals/batch-{index:02}.original.json"
        raw = load(name)
        assert raw["create"]["isError"] is False and raw["tree_full_get"]["isError"] is False
        tree = json.loads(raw["tree_full_get"]["structuredContent"]["content"])
        assert tree["sha"] == raw["create"]["structuredContent"]["sha"] and tree["truncated"] is False
        leaves = {row["path"]: row for row in tree["tree"] if row["type"] == "blob"}
        current = set()
        payload_bytes = 0
        for item in raw["full_gets"]:
            key = item["source_file"]
            assert key not in observed and key not in current
            current.add(key)
            response = item["raw"]
            assert response["isError"] is False
            body = response["structuredContent"]["content"].encode()
            row = original_rows[key]
            assert item["sha"] == row["git_blob"] and identity(body) == {field: row[field] for field in ("bytes", "git_blob", "sha256")}
            assert row["actual_create_tree"] == tree["sha"]
            assert leaves[row["path"]]["sha"] == row["git_blob"] and leaves[row["path"]]["mode"] == "100644"
            payload_bytes += len(body)
        assert len(leaves) == len(current)
        observed |= current
        batch_rows.append({"path": name, **identity((root / name).read_bytes()), "full_GET_payloads": len(current), "payload_bytes": payload_bytes,
                           "actual_create_tree": tree["sha"], "complete_original_tool_return_preserved": True})
    assert observed == set(original_rows) and sum(row["payload_bytes"] for row in batch_rows) == 4716332

    assert identity((root / "prepare_third_post_audit_delta.py").read_bytes())["git_blob"] == "170ed6f6b22184a9e8fe759342c2942e1e6690eb"
    assert identity((root / "prepare_pty_supervisor_publication.py").read_bytes())["git_blob"] == "fa6a0bdfd894518e2870251596167d9d90075eeb"
    assert load(COMBINED + "composition-01.exec.original.json")["exit_code"] == 1
    assert "full Merkle mismatch" in load(COMBINED + "composition-01.exec.original.json")["output"]
    assert load(COMBINED + "composition-02.exec.original.json")["exit_code"] == 0
    preparer_records = []
    for path in sorted((root / "third-post-audit-inputs").glob("*.exec.original.json")):
        data = json.loads(path.read_bytes())
        preparer_records.append({"path": path.name, "observed_exit": data["exit_code"], **identity(path.read_bytes()),
                                 "reexecuted_by_this_packet": False})
    assert len(preparer_records) == 5
    ready = []
    for number in [1, 2]:
        data = load(f"third-post-audit-inputs/components.ready-{number:02}.json")
        ready.append({"snapshot": number, "parent_commit": data["parent_commit"], "base_tree": data["base_tree"], "component_count": len(data["components"]),
                      "final_C4_status": "NOT_FINAL; frozen preparation snapshot only"})
    return {
        "schema": "hepta-integration-successor-publication-offline-verification-v1",
        "result": "PASS_ORIGINAL_CUSTODY_AND_PUBLICATION_IDENTITIES_ONLY",
        "original_members": 74, "original_bytes": 12875033,
        "originals_manifest": identity((packet / "ORIGINALS-MANIFEST.json").read_bytes()),
        "actual_commit_and_merge_API_relations": commits,
        "actual_PR_and_body_binding": pr_summary,
        "tree_reconstruction": {"arg0_before": AC18_TREE, "arg0_after": AAF_TREE, "PTY_intermediate": FIRST_TREE, "final": FINAL_TREE,
                                "arg0_changed_paths": arg0_changes, "final_changed_paths_against_aaf": all_changes,
                                "aaf_leaves": len(aaf), "final_leaves": len(final), "unchanged_aaf_leaves": 10798,
                                "all_53_actual_root_entries_equal": True, "original_paired_test_unchanged": True},
        "original_arg0_registration_receipts": {"registry_actual": "08e8e7ea26909d95392a0eddc157f75e308e2e9c", "batch_count": 4,
                                                "complete_GET_payloads": 30, "GET_payload_bytes": 4716332, "batches": batch_rows,
                                                "retention": "Complete original serialized JSON files, not a partial projection or synthesized replacement."},
        "preparation_history": {"composition_first_failure_and_next_success_retained": True,
                                "third_preparer_frozen_snapshot": "170ed6f6b22184a9e8fe759342c2942e1e6690eb",
                                "component_snapshots": ready, "original_exec_records": preparer_records},
        "scope": {"external_author_or_independent_verifiers_reexecuted": False, "full_C4_builder_executed": False,
                  "all_external_preparer_inputs_reexecuted": False, "native_or_CI_executed": False,
                  "new_ref_or_PR_mutations": False, "final_C4_documents_included": False,
                  "new_native_qualification": False, "all_blockers_closed": False,
                  "original_23_exit_conditions_modified": False, "blocker_counts": {"CLOSED_SCOPED": 16, "OPEN": 6, "SCIENTIFIC_HOLD": 1}},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.packet.resolve()), ensure_ascii=False, indent=2))
