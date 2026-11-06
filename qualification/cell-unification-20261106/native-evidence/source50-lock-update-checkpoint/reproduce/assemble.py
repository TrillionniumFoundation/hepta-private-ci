#!/usr/bin/env python3
"""Create-only assembler for actual source50 closed lock evidence.

Standard-library offline reads and artifact writes only. No subprocess, network,
source change, Git API, toolchain, fix, fmt or Rust execution. Original bytes are
preserved; raw locks use verified lossless gzip with mtime=0.
"""
from pathlib import Path, PurePosixPath
import argparse
import gzip
import hashlib
import io
import json
import re
import stat
import tarfile

COMMIT = "1fdd647b0ecb235530e8b88bbea45b3d3762906f"
TREE = "ea48acf562499192a25e05ae28926a32632dee62"
SOURCE49_TREE = "be34ab1afe622ad3b8f030c8c5018f4f54fbc304"
ARCHIVE_PIN = {
    "bytes": 787385,
    "sha256": "7dbb64599c8986628e494536e0e0af4895e0d78f36ed8ea89153b94371fbb47c",
    "git_blob": "34e0677615f627ecbc79b87a35ecebfd6f7b9f58",
}
SOURCE_SHA = "ba7515c75980451e0b2514bce338b0ada8847daeef5ace5deacf45ca02e940c0"
TOOL_SHA = "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8"
TASK_SOURCE = "/home/alex/work/hepta-cell-unified-20261106-a/source"
LOCKS = {
    "MODULE.bazel.lock": (1761877, "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb", "b91bee756020f2b6b0e92b1a5c4477e6a180149e"),
    "codex-rs/Cargo.lock": (417315, "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c", "b7e710988d6a3377a7e0a1dc68aef49c68dda36e"),
}
PIN_KEYS = ("bytes", "sha256", "git_blob")
FILE_KEYS = ("path", "bytes", "sha256", "git_blob", "mode")


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def object_no_duplicates(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def parse(raw):
    def reject_constant(value):
        raise RuntimeError("non-finite JSON number: " + value)
    return json.loads(raw, object_pairs_hook=object_no_duplicates, parse_constant=reject_constant)


def safe(value):
    require(isinstance(value, str) and bool(value) and "\\" not in value and "\0" not in value, "unsafe empty/escaped path")
    path = PurePosixPath(value)
    require(not path.is_absolute() and value == path.as_posix() and all(part not in ("", ".", "..") for part in path.parts), "unsafe relative path: " + value)
    return path


def regular_read(path):
    path = Path(path)
    for part in (path, *path.parents):
        require(not part.is_symlink(), "symlink input: " + str(part))
    st = path.stat()
    require(stat.S_ISREG(st.st_mode), "not a regular input: " + str(path))
    raw = path.read_bytes()
    after = path.stat()
    require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) ==
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), "input changed while read")
    require(len(raw) == st.st_size, "short input read")
    return raw


def source_rows(rows):
    require(isinstance(rows, list) and len(rows) == 194, "source194 rows required")
    result = {}
    for row in rows:
        entry = {key: row[key] for key in FILE_KEYS}
        safe(entry["path"])
        require(entry["path"] not in result and entry["mode"] in ("100644", "100755"), "duplicate source/unsupported Git mode")
        result[entry["path"]] = entry
    return result


def terminal(value, job, exit_code):
    require(value["job_id"] == job and value["exit_code"] == exit_code, "outer job/return mismatch")
    require(value["state"] == ("succeeded" if exit_code == 0 else "failed"), "outer terminal state mismatch")
    for key in ("automatic_retry", "cancelled", "timed_out"):
        require(value[key] is False, "unexpected outer flag: " + key)
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(value[key] is True, "unclosed outer output: " + key)


def load_archive(path):
    raw = regular_read(path)
    require(pin(raw) == ARCHIVE_PIN, "closed archive identity mismatch")
    members, modes = {}, {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        infos = archive.getmembers()
        require(len(infos) == 29, "expected29 archive members")
        for info in infos:
            safe(info.name)
            require(info.isfile() and not info.issym() and not info.islnk(), "nonregular tar member")
            require(info.name not in members and info.mode == 0o600, "duplicate tar member or unexpected transport mode")
            data = archive.extractfile(info).read()
            require(len(data) == info.size, "tar member size mismatch")
            members[info.name], modes[info.name] = data, info.mode
    index = parse(members["INDEX.json"])
    require(index["schema"] == "hepta.source50-lock-closed-index.v1", "unknown archive INDEX schema")
    require(index["source_tree"] == TREE and index["source_count"] == 194 and index["root_source_commit_later_frozen"] == COMMIT, "INDEX source binding mismatch")
    require(index["classification"] == "original_bazel_lock_prerequisite_not_rust_gate", "INDEX qualification scope mismatch")
    rows = index["files"]
    require(isinstance(rows, list) and len(rows) == 28, "expected28 INDEX rows")
    paths = []
    for row in rows:
        safe(row["path"])
        require(set(row) == {"path", "bytes", "sha256", "git_blob", "mode"}, "unexpected INDEX row schema")
        require(type(row["mode"]) is int and 0 <= row["mode"] <= 0o7777, "invalid original permission bits")
        require(pin(members[row["path"]]) == {key: row[key] for key in PIN_KEYS}, "archive raw pin mismatch: " + row["path"])
        paths.append(row["path"])
    require(len(set(paths)) == 28 and set(paths) == set(members) - {"INDEX.json"}, "INDEX/member-set mismatch")
    return raw, members, index, modes


def lock_readback(members):
    def obj(name):
        return parse(members["evidence/" + name])
    raw = obj("lock-update-raw-process-result.json")
    receipt = obj("lock-update-receipt.json")
    post = obj("postguard.json")
    complete = obj("complete.json")
    require(raw["schema"] == "hepta.original-command-raw-result.v1" and all(receipt[key] == value for key, value in raw.items()), "raw/receipt mismatch")
    require(raw["command"] == ["just", "bazel-lock-update"] and raw["cwd"] == TASK_SOURCE and raw["source_tree_before_command"] == TREE and raw["exit_code"] == 0, "original lock command did not pass on expected tree")
    require(raw["ended_unix"] >= raw["started_unix"] and abs(raw["elapsed_seconds"] - (raw["ended_unix"] - raw["started_unix"])) < 1e-6, "lock timing mismatch")
    for key, name in (("log", "lock-update.log"), ("resources", "lock-update.resources.txt")):
        require(receipt[key] == pin(members["evidence/" + name]), "receipt output mismatch")
    require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", members["evidence/lock-update.resources.txt"], re.M) == [b"0"], "resource exit mismatch")
    require(post["schema"] == "hepta.source50-lock-postguard.v1" and post["guard_pass"] is True, "postguard failed")
    require(post["source_tree_index_before_lock_stage"] == post["generated_source_tree"] == TREE and post["actual_changed_file_count"] == 194 and post["working_tree_changed_paths"] == [], "postguard source scope mismatch")
    require(post["rust_tests_started"] is False and post["fix_fmt_executed"] is False, "lock vs Rust phase confusion")
    lock_records = {}
    for name, expected in LOCKS.items():
        before, after = (members["locks/" + phase + "/" + name] for phase in ("before", "after"))
        expected_pin = dict(zip(PIN_KEYS, expected))
        require(before == after and pin(before) == expected_pin, "raw lock changed/unbound: " + name)
        require(post["locks"][name] == {"before": expected_pin, "after": expected_pin}, "lock postguard record mismatch")
        lock_records[name] = {**expected_pin, "before_after_byte_identical": True}
    require(members["evidence/generated-lock.patch"] == b"", "nonempty actual lock delta")
    require(complete["receipt"] == receipt and complete["postguard"] == post and complete["status"] == "LOCK_UPDATE_PASSED_SOURCE_FREEZE_PENDING", "original historical completion mismatch")
    require(complete["rust_tests_started"] is False and complete["fix_fmt_executed"] is False, "completion phase confusion")
    outer = obj("terminal-process-status.json")
    terminal(outer, "1a1b16cb87c-fc05-7898", 0)
    require(outer["at_unix_ms"] / 1000 >= raw["ended_unix"], "outer before original command completion")
    generated, applied = obj("generated-source.json"), obj("applied-source.json")
    require(generated["source_commit"] is None and generated["root_source_identity_freeze_pending"] is True and generated["source_tree"] == TREE, "historical generated-source fields were rewritten")
    require(applied["source_commit"] is None and applied["source_tree"] == TREE and applied["before_tree"] == SOURCE49_TREE, "historical apply identity mismatch")
    require(source_rows(applied["changed_files"]) == source_rows(generated["changed_files"]), "applied/generated194 rows differ")
    require(generated["cargo_lock_sha256"] == LOCKS["codex-rs/Cargo.lock"][1] and generated["bazel_lock_sha256"] == LOCKS["MODULE.bazel.lock"][1], "generated source lock binding mismatch")
    export = obj("export-source-verification-v2.json")
    require(export["source_tree"] == TREE and export["source_count"] == 194 and export["source_manifest_sha256"] == pin(members["evidence/generated-source.json"])["sha256"], "export source binding mismatch")
    require(all(export[key] is True for key in ("all_raw_sha_gitblob_mode_match", "no_unstaged_or_untracked", "source_not_modified_by_export")) and export["rust_test_qualification"] is False, "export evidence status mismatch")
    export_v1 = parse(members["export-attempt-v1/terminal-process-status.json"])
    terminal(export_v1, "1a1b173c81a-fc05-78d7", 1)
    require(b"AssertionError" in members["export-attempt-v1/stderr.txt"], "export-v1 failure original absent")
    warnings = [line for line in members["evidence/lock-update.log"].decode().splitlines() if line.startswith("WARNING:")]
    require(len(warnings) == 6, "original Bazel warning inventory changed")
    return {
        "original_command": raw, "outer_terminal": outer,
        "dual_locks": lock_records, "generated_lock_patch_empty": True,
        "raw_generated_source_commit_null_preserved": True,
        "raw_complete_status_preserved": complete["status"],
        "source_rows_compared": 194, "warnings_preserved": warnings,
        "original_export_v1": {"exit_code": 1, "job_id": export_v1["job_id"], "stderr": pin(members["export-attempt-v1/stderr.txt"]), "command_not_stdout_preserved": True},
        "rust_qualification_granted": False,
        "independent_full_source_tree_reconstruction_performed_here": False,
    }, generated


def load_extras(root, manifest_path):
    raw = regular_read(manifest_path)
    manifest = parse(raw)
    require(manifest["schema"] == "hepta.source50-lock-formal-inputs.v1", "unknown formal input schema")
    result, roles = {}, {}
    for row in manifest["files"]:
        source, destination = str(safe(row["source"])), str(safe(row["destination"]))
        require(destination not in result, "duplicate attachment destination")
        value = regular_read(root / source)
        require(pin(value) == {key: row[key] for key in PIN_KEYS}, "extra input pin mismatch: " + source)
        require(len(value) < 2 * 1024 * 1024, "unexpected large attachment; no executable/chunk binaries allowed")
        require(Path(source).suffix in (".json", ".txt", ".py", ".patch", ".sha256", ".md", ".log"), "unapproved binary attachment")
        result[destination] = (value, row)
        if row.get("role"):
            require(row["role"] not in roles, "duplicate semantic attachment role")
            roles[row["role"]] = value
    for role in ("actual_source_manifest", "actual_git_commit", "tool_v1_observation", "tool_v2", "tool_v3", "tool_v4", "tool_canonical", "tool_version_probe", "tool_v4_terminal"):
        require(role in roles, "required original missing: " + role)
    require(isinstance(manifest["missing_originals"], list), "missing originals must be explicit")
    return raw, manifest, result, roles


def extra_readback(roles, generated, members):
    source_raw = roles["actual_source_manifest"]
    require(len(source_raw) == 53832 and pin(source_raw)["sha256"] == SOURCE_SHA, "actual source50 manifest pin mismatch")
    source = parse(source_raw)
    require(source["schema"] == "hepta.root-bound-source50.v1" and source["source_commit"] == COMMIT and source["source_tree"] == TREE, "actual root source identity mismatch")
    require(source_rows(source["changed_files"]) == source_rows(generated["changed_files"]), "actual194 rows differ from original generated snapshot")
    commit = parse(roles["actual_git_commit"])
    if "structuredContent" in commit:
        commit = commit["structuredContent"]
    require(commit["sha"] == COMMIT and commit["tree"]["sha"] == TREE, "actual Git commit/tree response mismatch")
    require(commit["parents"][0]["sha"] == "50dd4bedefcd1b8e2e8cd5cf5023c60a86d38d0a" and len(commit["parents"]) == 1, "source50 parent mismatch")
    v4 = parse(roles["tool_v4"])
    require(roles["tool_canonical"] == roles["tool_v4"] == members["input/bazel-tool-preparation.json"], "canonical tool receipt differs from successful v4/input")
    require(v4["attempt"] == 4 and v4["exit_code"] == 0 and v4["official_checksum"] == TOOL_SHA, "canonical tool qualification mismatch")
    require(v4["binary"]["bytes"] == 77023347 and v4["binary"]["sha256"] == TOOL_SHA, "official binary pin mismatch")
    require(v4["version_probe"] == parse(roles["tool_version_probe"]) and v4["version_probe"]["exit_code"] == 0 and v4["version_probe"]["stdout"] == "bazel 9.3.0\n", "version probe original mismatch")
    require(v4["rust_tests_started"] is False, "tool preparation vs Rust phase confusion")
    for phase in ("source_before", "source_after"):
        require(v4[phase]["tree"] == SOURCE49_TREE and v4[phase]["guard_pass"] is True, "tool preparation did not preserve original source49")
    tool_terminal = parse(roles["tool_v4_terminal"])
    terminal(tool_terminal, "1a1b169e3ee-fc05-787e", 0)
    cursor = v4["prefix_bytes"]
    require(cursor == 70098250, "unexpected actual v4 prefix")
    for segment in v4["segments"]:
        size = segment["end"] - segment["start"] + 1
        response = segment["http_response"]
        require(segment["start"] == cursor and segment["expected_bytes"] == segment["actual_bytes"] == size and segment["exit_code"] == 0, "successful Range coverage mismatch")
        require(response["status"] == 206 and response["content_range"] == f"bytes {cursor}-{segment['end']}/77023347" and int(response["content_length"]) == size, "actual Range response mismatch")
        cursor = segment["end"] + 1
    require(cursor == 77023347 and len(v4["segments"]) == 4, "Range coverage incomplete")
    v2, v3 = parse(roles["tool_v2"]), parse(roles["tool_v3"])
    for attempt, receipt in ((3, v3), (4, v4)):
        for number, segment in enumerate(receipt["segments"]):
            role = f"tool_v{attempt}_chunk_{number}"
            require(role in roles and parse(roles[role]) == segment, "standalone chunk receipt differs: " + role)
    require("tool_official_checksum" in roles and roles["tool_official_checksum"].decode().split()[0] == TOOL_SHA,
            "original official checksum text mismatch")
    require(v2["exit_code"] == v3["exit_code"] == 1 and v2["prior_terminal_exit_code"] == 124, "original tool failure history changed")
    require(v2["error"]["type"] == "TimeoutError" and v3["segments"][3]["exit_code"] == 1, "original failed download boundary missing")
    original_v1 = parse(roles["tool_v1_observation"])
    require(original_v1["original_job_id"] == "1a1b13d4104-fc05-772d" and original_v1["source_tree"] == SOURCE49_TREE, "v1 post-timeout observation mismatch")
    extra = {
        "actual_git_commit": COMMIT, "actual_git_tree": TREE, "actual_native_manifest194_equals_generated194": True,
        "raw_commit_response": pin(roles["actual_git_commit"]), "native_manifest": pin(source_raw),
        "tool_history": {"attempt1": "outer124 recorded by original v2; post-timeout observation preserved",
                         "attempt2": {"exit_code": 1, "error": v2["error"]},
                         "attempt3": {"exit_code": 1, "segment_exits": [s["exit_code"] for s in v3["segments"]]},
                         "attempt4": {"exit_code": 0, "outer_exit_code": tool_terminal["exit_code"], "binary": v4["binary"], "version_probe": v4["version_probe"]}},
        "tool_binary_and_chunks_included": False,
        "tool_binary_bytes_rehashed_by_this_reader": False,
        "official_full_hash_and_range_receipts_cross_checked": True,
    }
    if "lock_export_v2_terminal" in roles:
        export = parse(roles["lock_export_v2_terminal"])
        require(export["state"] == "succeeded" and export["exit_code"] == 0 and export["output_complete"] is True and export["output_durable"] is True and export["terminal_publication_confirmed"] is True, "export-v2 outer incomplete")
        require(all(export[k] is False for k in ("timed_out", "cancelled", "automatic_retry")), "export-v2 outer flags invalid")
        extra["export_v2_terminal"] = {"job_id": export["job_id"], "exit_code": export["exit_code"], **pin(roles["lock_export_v2_terminal"])}
    else:
        extra["export_v2_terminal"] = None
    return extra


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "create-only formal output already exists")
    require(args.output.name == "source50-lock-update-checkpoint", "only new authorized formal group is allowed")
    archive, members, index, modes = load_archive(args.archive)
    input_raw, inputs, extras, roles = load_extras(args.workspace, args.inputs)
    lock_result, generated = lock_readback(members)
    extra_result = extra_readback(roles, generated, members)
    payload, mapping = {}, []
    def add(destination, raw, origin, encoded=False):
        safe(destination)
        require(destination not in payload, "duplicate output path")
        out = gzip.compress(raw, compresslevel=9, mtime=0) if encoded else raw
        if encoded:
            require(gzip.decompress(out) == raw, "lossless gzip verification failed")
        payload[destination] = out
        mapping.append({"destination": destination, "origin": origin, "encoding": "gzip-mtime0" if encoded else "identity", "original": pin(raw), "stored": pin(out)})
    add("checkpoint-source50-lock-update-v2.tar.gz", archive, {"archive": str(args.archive)})
    for name, raw in sorted(members.items()):
        encoded = name.startswith("locks/")
        destination = "original/" + name + (".gz" if encoded else "")
        add(destination, raw, {"archive_member": name, "tar_transport_mode": modes[name],
                               "original_input_permission_mode": next((r["mode"] for r in index["files"] if r["path"] == name), None)}, encoded)
    for destination, (raw, row) in sorted(extras.items()):
        add(destination, raw, {"local_original": row["source"], "role": row.get("role")})
    add("reproduce/INPUTS.json", input_raw, {"preparation_inputs": str(args.inputs)})
    add("reproduce/assemble.py", regular_read(Path(__file__)), {"assembler": str(Path(__file__))})
    readback = {
        "schema": "hepta.source50-lock-formal-independent-readback.v1",
        "classification": "CLOSED_LOCK_PREREQUISITE_AND_HISTORY_NOT_RUST_QUALIFICATION",
        "archive": pin(archive), "regular_members": 29, "index_rows": 28,
        "all_archive_raw_size_sha256_gitblob_and_member_sets_verified": True,
        "transport_permission_bits": 0o600,
        "index_modes_are_original_permission_bits_not_git_modes": True,
        "original_index": pin(members["INDEX.json"]),
        "lock": lock_result, "source_and_tool": extra_result,
        "missing_originals": inputs["missing_originals"],
        "prior_provisional_group": "../source50-provisional-repair/",
        "prior_provisional_snapshot_mutated": False,
        "historical_pending_flags_preserved_verbatim": True,
        "current_r24_result_not_derived_from_this_lock_group": True,
        "r25_or_workspace_qualification_granted": False,
        "source_mutated": False, "rust_or_bazel_executed_by_assembler": False,
    }
    payload["INDEPENDENT-READBACK.json"] = json_bytes(readback)
    payload["CLOSURE-MAPPING.json"] = json_bytes({"schema": "hepta.exact-original-attachment-closure.v1", "classification": readback["classification"], "entries": mapping, "missing_originals": inputs["missing_originals"]})
    payload["README.md"] = (
        "# source50：原生锁更新闭合证据\n\n"
        "本组保留实际 just bazel-lock-update 返回0、原始资源/日志/外层终态，以及两份锁更新前后完整字节相同的证据。"
        "实际 source50 commit 为 " + COMMIT + "，tree 为 " + TREE + "；原生成快照的 source_commit:null 和当时待冻结标记均原样保留。\n\n"
        "Bazel 工具下载的早期失败、成功第4次准备、六条原始 Bazel warning、锁归档导出第1次失败均保留。"
        "77 MB 工具及分块二进制不进入本组；本次只复核原始工具回执，不冒称重新读取工具本体。"
        "完整锁归档包含29件，28行 INDEX；INDEX 是原文件权限，tar 运输权限独立记录。四份 raw lock 以 mtime=0 gzip 无损保存。\n\n"
        "INDEPENDENT-READBACK.json、CLOSURE-MAPPING.json 和 ATTACHMENT-MANIFEST.json 定义完整范围及缺件。"
        "该锁前置条件通过不表示 Rust、r24、r25 或科学资格通过。"
        "旧 source50-provisional-repair 是历史准备快照，未被改写。\n"
    ).encode()
    binary_rows = []
    for name, raw in sorted(payload.items()):
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            binary_rows.append({"path": name, **pin(raw), "git_mode": "100644", "upload_performed_by_assembler": False})
    payload["BINARY-PLAN.json"] = json_bytes({"schema": "hepta.binary-upload-preparation.v1", "entries": binary_rows, "all_files_are_git_mode_100644": True, "no_upload_performed": True})
    payload["ATTACHMENT-MANIFEST.json"] = json_bytes({
        "schema": "hepta.source50-lock-formal-attachment-manifest.v1",
        "classification": readback["classification"], "source_commit": COMMIT, "source_tree": TREE,
        "files": [{"path": name, **pin(raw), "mode": "100644"} for name, raw in sorted(payload.items())],
        "manifest_self_excluded": True, "missing_originals": inputs["missing_originals"],
    })
    args.output.mkdir(parents=True, exist_ok=False)
    for name, raw in sorted(payload.items()):
        path = args.output / safe(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(raw)
        path.chmod(0o644)
        require(regular_read(path) == raw, "formal attachment readback mismatch")
    print(json.dumps({"status": "FORMAL_LOCK_EVIDENCE_CREATED", "files": len(payload),
                      "bytes": sum(map(len, payload.values())), "output": str(args.output),
                      "readback": pin(payload["INDEPENDENT-READBACK.json"]),
                      "manifest": pin(payload["ATTACHMENT-MANIFEST.json"]),
                      "binary_plan": pin(payload["BINARY-PLAN.json"]),
                      "rust_qualification_granted": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
