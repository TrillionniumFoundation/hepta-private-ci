"""Assemble a new fixed publication-evidence group using local closed originals only."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json

ROOT = Path(__file__).resolve().parents[1]
PREP = Path(__file__).resolve().parent
REPORT = ROOT / "hepta-cell/qualification/cell-unification-20261106"
OUT = REPORT / "native-evidence/source53-r30-publication-readback"
SOURCE_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
SOURCE_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
PREFIX = "qualification/cell-unification-20261106/"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    return pin(raw)


def safe(relative):
    path = PurePosixPath(relative)
    assert relative and not path.is_absolute() and ".." not in path.parts and "\\" not in relative, relative


def main():
    assert not OUT.exists(), "New group already exists; do not overwrite a frozen group."
    sources = {}
    def get(relative):
        safe(relative)
        path = ROOT / relative
        assert path.is_file() and not path.is_symlink(), relative
        raw = path.read_bytes()
        if relative in sources: assert sources[relative] == raw
        sources[relative] = raw
        return raw
    def obj(relative): return json.loads(get(relative))
    def ledger_diff(before, after, count):
        assert len(before["commits"]) == len(after["commits"]) == 53
        assert len(before["artifact_checkpoints"]) == len(after["artifact_checkpoints"]) == 6
        assert {k: v for k, v in before.items() if k != "created_blobs"} == {k: v for k, v in after.items() if k != "created_blobs"}
        assert all(after["created_blobs"][k] == v for k, v in before["created_blobs"].items())
        delta = {k: v for k, v in after["created_blobs"].items() if k not in before["created_blobs"]}
        assert len(delta) == count
        return delta

    base_path = "publication-recovery-prep/checkpoint6-actual-leaf-map.json"
    prior_path = "r29-publication-root-preparation/COMBINED-STAGED-OVERLAY.json"
    base, prior = obj(base_path), obj(prior_path)
    assert base["checkpoint_commit"] == "9896f63f1352906a6afec53b94d4d123143ba35e" and len(base["files"]) == 2370
    assert len(prior["files"]) == 243
    known = set(base["files"].values()) | set(prior["files"].values())
    selected = [(base_path, "references/checkpoint6-actual-leaf-map.json"),
                (prior_path, "references/prior-r29-publication-staged-overlay.json")]
    groups = []
    verified_attachments = []
    last_overlay = prior
    ledgers = {}
    for folder, label, count, creates, reuses, additions in [
        ("source53-formal-root-preparation", "source53-apply-publication", 238, 169, 69, 2),
        ("r30-formal-root-preparation", "r30-project-publication", 213, 126, 87, 10),
    ]:
        names = ["ROOT-UPLOAD-PLAN.json", "UPLOAD-CLOSED.json", "LEDGER-BEFORE-BINARY-REGISTRATION.json",
                 "LEDGER-AFTER-BINARY-REGISTRATION.json", "COMBINED-STAGED-OVERLAY.json"]
        data = {name: obj(folder + "/" + name) for name in names}
        selected += [(folder + "/" + name, label + "/" + name) for name in names]
        plan, closed, before, after, overlay = [data[name] for name in names]
        assert plan["count"] == closed["count"] == len(plan["files"]) == count
        assert plan["source_commit"] == SOURCE_COMMIT and plan["source_tree"] == SOURCE_TREE
        assert plan["diagnostic_only"] is True and plan["behavior_repair_claimed"] is False
        assert plan["science"] == "HOLD" and plan["authority"] == "DENY_ALL"
        assert after["current_source_commit"] == SOURCE_COMMIT and after["current_source_tree"] == SOURCE_TREE
        assert after["branch_created"] is after["pull_request_created"] is False
        delta = ledger_diff(before, after, additions)
        assert sorted(delta) == sorted(closed["new_binary_paths_registered"])
        for key, filename in [("ledger_before", names[2]), ("ledger_after", names[3]), ("combined_overlay", names[4])]:
            assert {k: closed[key][k] for k in ("bytes", "sha256", "git_blob")} == pin(sources[folder + "/" + filename])
        known.update(before["created_blobs"].values())
        rows = {r["repo_path"]: r for r in plan["files"]}
        assert len(rows) == count
        formal = Path(plan["formal_directory"])
        assert formal.is_relative_to(REPORT) and formal.is_dir()
        assert set(str(p.relative_to(formal)) for p in formal.rglob("*") if p.is_file()) == {r["path"] for r in rows.values()}
        for repo_path, row in rows.items():
            assert row["mode"] == "100644"
            assert Path(row["local_path"]) == formal / row["path"]
            assert repo_path == str(Path(row["local_path"]).relative_to(ROOT / "hepta-cell"))
            local = Path(row["local_path"])
            assert not local.is_symlink()
            raw = local.read_bytes()
            assert pin(raw) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
            verified_attachments.append({"path": str(local.relative_to(ROOT)), **pin(raw)})
            if repo_path in delta: assert delta[repo_path] == row["git_blob"] and row["binary"] is True
        batches = sorted((ROOT / folder / "upload-batches").glob("batch-*.json"))
        seen, actual_creates, actual_reuses = [], 0, 0
        for path in batches:
            relative = str(path.relative_to(ROOT))
            batch = obj(relative)
            selected.append((relative, label + "/upload-batches/" + path.name))
            assert batch["errors"] == [] and batch["total_paths"] == count
            for entry in batch["staged"]:
                repo_path = entry["repo_path"]
                assert repo_path in rows and repo_path not in seen
                assert entry["git_blob"] == rows[repo_path]["git_blob"] and entry["binary"] == rows[repo_path]["binary"]
                if entry["reused"]:
                    assert entry["git_blob"] in known, repo_path
                    actual_reuses += 1
                else:
                    response = entry["actual_response"]
                    assert not response.get("isError", False) and response["structuredContent"]["sha"] == entry["git_blob"]
                    known.add(entry["git_blob"])
                    actual_creates += 1
                seen.append(repo_path)
            assert batch["completed_paths"] == len(seen)
        assert seen == [r["repo_path"] for r in plan["files"]]
        assert actual_creates == creates == closed["actual_create_responses"]
        assert actual_reuses == reuses == closed["existing_actual_Git_object_reuses"]
        assert sum(r["bytes"] for r in rows.values()) == closed["bytes"] == plan["bytes"]
        expected_overlay = {**last_overlay["files"], **{p: r["git_blob"] for p, r in rows.items()}}
        expected_sizes = {**last_overlay["file_sizes"], **{p: r["bytes"] for p, r in rows.items()}}
        assert overlay["files"] == expected_overlay and overlay["file_sizes"] == expected_sizes
        assert overlay["not_yet_an_artifact_checkpoint"] is True
        groups.append({"name": label, "paths": count, "raw_bytes": plan["bytes"], "batches": len(batches),
                       "actual_create_responses": actual_creates, "known_object_reuses": actual_reuses,
                       "binary_paths_before": len(before["created_blobs"]), "binary_paths_after": len(after["created_blobs"]),
                       "added_binary_paths": delta, "combined_overlay_paths": len(overlay["files"]),
                       "all_original_attachment_raw_sha256_git_blob_mode_and_byte_counts_match": True,
                       "all_actual_responses_and_recorded_reuse_objects_match": True})
        ledgers[label] = (before, after)
        last_overlay = overlay

    archive_response_path = "native-validation-results/r30-archive-closed/ACTUAL-GIT-BLOB-RESPONSE.json"
    archive_response = obj(archive_response_path)
    archive_path = ROOT / "native-validation-results/r30-archive-closed/checkpoint-r30-closed.tar.gz"
    archive_pin = pin(archive_path.read_bytes())
    assert archive_pin == {"bytes": 1761785, "sha256": "14abba7cfb44b96d6a13c926335a38eb8be55c786a865c3887b3908b48f2ddce", "git_blob": "7bcac57e66f262e36a159e6530d7c178ccac51f7"}
    assert not archive_response.get("isError", False) and archive_response["structuredContent"]["sha"] == archive_pin["git_blob"]
    archive_before_path = "r30-archive-root-review/LEDGER-BEFORE-ARCHIVE-REGISTRATION.json"
    archive_after_path = "r30-archive-root-review/LEDGER-AFTER-ARCHIVE-REGISTRATION.json"
    archive_before, archive_after = obj(archive_before_path), obj(archive_after_path)
    archive_delta = ledger_diff(archive_before, archive_after, 1)
    assert archive_delta == {PREFIX + "native-evidence/r30-project-checkpoint/archive/checkpoint-r30-closed.tar.gz": archive_pin["git_blob"]}
    assert archive_before == ledgers["source53-apply-publication"][1] and archive_after == ledgers["r30-project-publication"][0]
    selected += [(archive_response_path, "r30-archive-registration/ACTUAL-GIT-BLOB-RESPONSE.json"),
                 (archive_before_path, "r30-archive-registration/LEDGER-BEFORE-ARCHIVE-REGISTRATION.json"),
                 (archive_after_path, "r30-archive-registration/LEDGER-AFTER-ARCHIVE-REGISTRATION.json")]
    note_path = "r30-formal-root-preparation/PREPARATION-ENCODING-NOTE.json"
    note = obj(note_path)
    assert note["source_formal_native_gate_or_result_changed"] is False
    selected.append((note_path, "r30-project-publication/PREPARATION-ENCODING-NOTE.json"))
    assert len({s for s, _ in selected}) == len(selected) == len({d for _, d in selected})
    assert len(ledgers["r30-project-publication"][1]["created_blobs"]) == 235

    # Only now create the new formal directory and exact copies/compressions.
    OUT.mkdir(parents=True, exist_ok=False)
    mapping, gzip_rows = [], []
    for source, destination in selected:
        raw = get(source)
        encoding = "identity"
        if len(raw) >= 16384:
            buffer = io.BytesIO()
            with gzip.GzipFile(fileobj=buffer, filename="", mode="wb", compresslevel=9, mtime=0) as stream:
                stream.write(raw)
            stored = buffer.getvalue()
            assert stored[4:8] == b"\0" * 4 and gzip.decompress(stored) == raw
            destination += ".gz"
            encoding = "gzip-mtime0"
        else:
            stored = raw
        write(OUT / destination, stored)
        row = {"source": {"path": source, **pin(raw)}, "destination": {"path": destination, **pin(stored)}, "encoding": encoding}
        mapping.append(row)
        if encoding != "identity": gzip_rows.append({**row, "full_decompression_equals_original_bytes": True})
    copy_script = Path(__file__).read_bytes()
    write(OUT / "reproduce/assemble.py", copy_script)
    independent = {"schema": "hepta.source53-r30-publication-independent-readback.v1",
                   "classification": "PUBLICATION_OBJECT_CUSTODY_ONLY_NOT_AN_ENGINEERING_GATE",
                   "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE,
                   "groups": groups, "source53_registration_count": 53,
                   "fixed_binary_registration_sequence": [222, 224, 225, 235],
                   "artifact_checkpoint_count_unchanged": 6,
                   "archive_actual_Git_response_matches_local_full_bytes": archive_pin,
                   "archive_payload_already_preserved_at": "../r30-project-checkpoint/archive/checkpoint-r30-closed.tar.gz",
                   "old_source_commits_other_ledger_fields_and_existing_binary_entries_unchanged": True,
                   "known_reuse_inputs": [{"path": p, **pin(sources[p])} for p in (base_path, prior_path)],
                   "same_bytes_duplicate_ledger_snapshots_preserved_separately": True,
                   "new_Git_API_requests_made": False, "remote_blobs_directly_re_read_this_time": False,
                   "new_artifact_checkpoint_branch_or_PR_created": False,
                   "R30_counts_are_existing_original_gate_not_upload_result": {"PASS": 1345, "FAIL": 0, "TIMEOUT": 0, "reported_skipped": 2},
                   "R31_results_not_in_this_group": True, "R31_result": None,
                   "diagnostic_only": True, "behavior_repair_claimed": False,
                   "science": "HOLD", "authority": "DENY_ALL", "native_execution": False}
    write(OUT / "INDEPENDENT-READBACK.json", encode(independent))
    write(OUT / "SOURCE-DESTINATION-MAPPING.json", encode({"schema": "hepta.exact-publication-original-copy-map.v1", "files": mapping}))
    write(OUT / "GZIP-ROUNDTRIP.json", encode({"schema": "hepta.publication-gzip-roundtrip.v1", "files": gzip_rows}))
    closure = {"schema": "hepta.source53-r30-publication-readback-closure.v1", "state": "FROZEN_PUBLICATION_EVIDENCE_SNAPSHOT",
               "source_commit": SOURCE_COMMIT, "source_tree": SOURCE_TREE,
               "original_publication_records": len(selected), "verified_formal_paths": 451,
               "source53_apply_group": {"paths": 238, "create": 169, "reuse": 69},
               "R30_group": {"paths": 213, "create": 126, "reuse": 87},
               "fixed_ledger_source_binary_artifact_counts": [53, 235, 6],
               "published_artifact_checkpoint_created_by_this_group": False,
               "upload_of_this_new_group": "PENDING_ROOT_UPLOAD_AND_REGISTRATION",
               "canonical_reports_INDEX_ledger_existing_formal_groups_modified": False,
               "R31_result_in_this_group": None, "diagnostic_only": True, "behavior_repair_claimed": False,
               "science": "HOLD", "authority": "DENY_ALL"}
    write(OUT / "CLOSURE.json", encode(closure))
    readme = """# Source53 / R30 发布记录补充

本组保全已完成的 Git blob 上传、对象复用与 ledger 追加原记录。它不是新的原生测试、artifact checkpoint、分支或 PR，也不把 source53 的诊断日志改称行为修复。

源53应用组 238 个路径对应169条真实 create response及69个已知对象复用；R30项目组213个路径对应126条create response及87个复用。全部451个原附件的raw SHA256、Git blob、字节数与mode记录重新核对，57批原响应完整保留。对象复用分别绑定checkpoint6原2370叶映射、先前243路径发布overlay、登记binary与早先真实create response；本次没有再请求Git API。

原 ledger 追加链为222→224（应用组2binary）→225（R30原archive）→235（R30其余10binary）。53个源码对象与6个artifact checkpoint始终未变；所有既有binary条目和其他ledger字段保持。每个before/after原文独立保留，即使字节相同也不改原语境。R30 archive完整1,761,785字节重新hash后匹配真实Git响应7bcac57e66f262e36a159e6530d7c178ccac51f7，archive自身沿用已封R30项目组，不再次复制。

大JSON仅用mtime=0、无文件名的gzip无损压缩；SOURCE-DESTINATION-MAPPING与GZIP-ROUNDTRIP分别记录原件和保存件pins，并完整解压逐字验证。原R30本地plan首版仅因gzip编码label被拒绝的纠正说明保留，它没有改变源码、原门、正式原件或结果。

R30既有1345PASS／0FAIL／0TIMEOUT／2reportedskip仍属于其原完整项目门；本组不新增工程资格。R31、工具盘点、fix/fmt、最终SHA CI或后续发布结果不纳入这个定点snapshot。科学HOLD、权限DENY_ALL、诊断限定均不变。
"""
    write(OUT / "README.md", readme.encode())
    entries = [{"path": str(p.relative_to(OUT)), "mode": "100644", **pin(p.read_bytes())} for p in sorted(OUT.rglob("*")) if p.is_file()]
    manifest = {"schema": "hepta.frozen-publication-attachment-manifest.v1", "files": entries,
                "file_count_excluding_this_manifest": len(entries), "bytes_excluding_this_manifest": sum(r["bytes"] for r in entries),
                "original_record_count": len(mapping), "native_qualification_not_granted": True}
    manifest_pin = write(OUT / "ATTACHMENT-MANIFEST.json", encode(manifest))
    for row in mapping:
        raw = (ROOT / row["source"]["path"]).read_bytes()
        assert pin(raw) == {k: row["source"][k] for k in ("bytes", "sha256", "git_blob")}
        stored = (OUT / row["destination"]["path"]).read_bytes()
        assert (gzip.decompress(stored) if row["encoding"] == "gzip-mtime0" else stored) == raw
    for row in verified_attachments:
        assert pin((ROOT / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}
    final_files = entries + [{"path": "ATTACHMENT-MANIFEST.json", "mode": "100644", **manifest_pin}]
    final_ledger = ledgers["r30-project-publication"][1]
    binaries = [{**row, "repo_path": str((OUT / row["path"]).relative_to(ROOT / "hepta-cell")),
                 "existing_ledger_paths_for_same_blob": sorted(k for k, v in final_ledger["created_blobs"].items() if v == row["git_blob"])} for row in final_files if row["path"].endswith(".gz")]
    write(PREP / "INPUT-PINS.json", encode({"schema": "hepta.publication-copy-input-pins.v1", "files": [{"path": p, **pin(b)} for p, b in sources.items()]}))
    binary_pin = write(PREP / "BINARY-PLAN.json", encode({"schema": "hepta.publication-readback-binary-plan.v1", "state": "NOT_UPLOADED_BY_ASSEMBLER", "files": binaries}))
    receipt = {"schema": "hepta.local-publication-group-assembly-receipt.v1", "formal_directory": str(OUT.relative_to(ROOT)),
               "files": len(final_files), "bytes": sum(r["bytes"] for r in final_files), "manifest": manifest_pin,
               "binary_plan": binary_pin, "binary_count": len(binaries), "originals_copied": len(mapping),
               "verified_formal_original_paths": len(verified_attachments), "readonly_Git_API_or_native_commands_executed": False}
    receipt_pin = write(PREP / "ASSEMBLY-READBACK.json", encode(receipt))
    prep_files = [{"path": p.name, **pin(p.read_bytes())} for p in sorted(PREP.iterdir()) if p.is_file()]
    handoff_pin = write(PREP / "HANDOFF-MANIFEST.json", encode({"schema": "hepta.publication-readback-handoff.v1", "files": prep_files,
        "formal_directory": str(OUT.relative_to(ROOT)), "formal_manifest": manifest_pin, "frozen_formal_file_count": len(final_files),
        "root_upload_required": True, "native_or_scientific_qualification_granted": False}))
    print(json.dumps({"formal": receipt, "assembly_receipt": receipt_pin, "handoff": handoff_pin}, ensure_ascii=False))


if __name__ == "__main__":
    main()
