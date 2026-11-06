#!/usr/bin/env python3
"""Assemble only closed local evidence. No subprocess, network or native calls."""
import argparse
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TESTED_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TESTED_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
PREFIX = "native-source53-finalization/"
SCOPE_SHA256 = {
    "EXPECTED-SELECTION.json": "9fdc8321c241b7f852bb055db9d23caa471f70349c269fa7746bd819dc80dfeb",
    "PACKAGE-ARGS.json": "ba044ba7576a3e20bfc483d9ab9009733ebd3d46a2c52d0305cb0ad15f0ab886",
    "RUST-FILE-COMMANDS.json": "19a78abce6965f0da7df8a67d8f06b499185daac983fe78a1e5bedc943d026d0",
    "PRIMARY-SOURCE-PINS.json": "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def safe(value):
    p = PurePosixPath(value)
    require(isinstance(value, str) and value and not p.is_absolute() and ".." not in p.parts
            and str(p) == value and "\\" not in value, "unsafe relative path: " + str(value))
    return value


def load_pin(record):
    require(isinstance(record, dict) and {"path", "bytes", "sha256", "git_blob"} <= set(record), "unbound complete file pin")
    path = ROOT / safe(record["path"])
    require(path.is_file() and not path.is_symlink(), "missing/nonregular pinned input " + str(path))
    data = path.read_bytes()
    require(pin(data) == {key: record[key] for key in ("bytes", "sha256", "git_blob")}, "input pin mismatch " + str(path))
    return data


def encode(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def warning_observations(raw):
    """Keep compiler warning headers at original offsets; never call exit0 warning-free."""
    rows, offset, lines = [], 0, raw.splitlines(keepends=True)
    for number, line in enumerate(lines, 1):
        if re.match(rb"^\s*warning(?:\[[^\]]+\])?:", line):
            rows.append({"line": number, "byte_offset": offset,
                         "text": line.rstrip(b"\r\n").decode("utf-8", errors="strict"),
                         "package_summary": bool(re.match(rb"^\s*warning: `[^`]+` .* generated [0-9]+ warning", line))})
        offset += len(line)
    diagnostics = []
    for item in rows:
        if item["package_summary"]:
            continue
        end_line = item["line"]
        while end_line < len(lines) and not re.match(rb"^\s*(?:warning(?:\[[^\]]+\])?:|Checking |Compiling |Finished )", lines[end_line]):
            end_line += 1
        block = b"".join(lines[item["line"] - 1:end_line])
        locations = re.findall(rb"^\s*-->\s+([^\r\n]+)$", block, re.M)
        diagnostics.append({**item, "byte_end": item["byte_offset"] + len(block),
                            "block_sha256": hashlib.sha256(block).hexdigest(), "block_text": block.decode("utf-8"),
                            "source_locations": [value.decode("utf-8") for value in locations]})
    return {"warning_headers": rows, "warning_header_occurrences": len(rows),
            "diagnostic_warning_count": len(diagnostics), "diagnostic_warnings": diagnostics,
            "package_summary_count": sum(item["package_summary"] for item in rows),
            "large_enum_variant_mentioned": b"clippy::large_enum_variant" in raw,
            "full_original_log_retained": True, "warning_free_claimed": False,
            "fix_is_original_scoped_command_not_new_strict_D_warnings_gate": True}


def verify_snapshot(raws, reference, label):
    def pointed(record):
        require(record["path"].startswith(PREFIX), "snapshot pointer outside finalization")
        name = safe(record["path"][len(PREFIX):])
        data = raws[name]
        require(pin(data) == {key: record[key] for key in ("bytes", "sha256", "git_blob")}, "snapshot pointer pin mismatch")
        return data
    manifest_raw = pointed(reference["manifest"])
    manifest = json.loads(manifest_raw)
    require(manifest["schema"] == "hepta.source53-finalization-source-snapshot.v1" and manifest["label"] == label,
            "snapshot schema/label mismatch")
    require(manifest["source_tree"] == reference["tree"] and manifest["tested_source_tree"] == TESTED_TREE
            and manifest["tested_source_commit"] == TESTED_COMMIT and manifest["native_head"] == HEAD,
            "snapshot identity mismatch")
    for key in ("qualification_transferred_to_mutated_tree", "post_fix_or_format_tests_executed", "behavior_repair_claimed"):
        require(manifest[key] is False and (key not in reference or reference[key] is False), "snapshot qualification boundary changed")
    require(manifest["source_snapshot_complete"] is True and manifest["diagnostic_only"] is True, "snapshot is incomplete")
    rows = {row["path"]: row for row in manifest["changed_files"]}
    require(len(rows) == len(manifest["changed_files"]) == reference["source_paths"] == 197, "snapshot source set count mismatch")
    expected = {"source/" + safe(name) for name in rows} | {"source-manifest.json"}
    seen = set()
    with tarfile.open(fileobj=io.BytesIO(pointed(reference["archive"])), mode="r:gz") as archive:
        for member in archive.getmembers():
            safe(member.name)
            require(member.isfile() and not member.issym() and not member.islnk() and member.name not in seen,
                    "unsafe/duplicate/nonregular snapshot member")
            seen.add(member.name)
            data = archive.extractfile(member).read()
            require(len(data) == member.size, "short snapshot member")
            if member.name == "source-manifest.json":
                require(data == manifest_raw and member.mode == 0o644, "embedded manifest mismatch")
            else:
                require(member.name.startswith("source/"), "unexpected snapshot member")
                row = rows[member.name[len("source/"):]]
                require(pin(data) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "source member pin mismatch")
                require(member.mode == int(row["mode"][-3:], 8), "source mode mismatch")
    require(seen == expected, "snapshot member coverage mismatch")
    return manifest, rows


def validate_closed(raws, terminal, scope):
    result = {"success": False, "raw_output_count": len(raws), "actual_files": sorted(raws),
              "tested_source_commit": TESTED_COMMIT, "tested_source_tree": TESTED_TREE,
              "final_formatted_commit": None, "final_formatted_tree": None,
              "fix": None, "format": None, "post_fix_or_format_tests_executed": False,
              "qualification_transferred_to_mutated_tree": False, "diagnostic_only": True,
              "behavior_repair_claimed": False}
    if "complete.json" not in raws:
        require("incomplete.json" in raws or "orchestration-failure.json" in raws,
                "closed failed output lacks its real failure record")
        result["state"] = "ACTUAL_FINALIZATION_INCOMPLETE_RETAINED"
        result["outer_exit_code"] = terminal["exit_code"]
        result["failure_records"] = {name: json.loads(raws[name]) for name in ("incomplete.json", "orchestration-failure.json") if name in raws}
        result["observed_raw_phase_results"] = {name: json.loads(data) for name, data in raws.items() if name.endswith("-raw-process-result.json")}
        return result
    require("incomplete.json" not in raws and "orchestration-failure.json" not in raws, "success and failure records coexist")
    require(terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "success file is not a natural successful outer")
    require(not terminal["cancelled"] and not terminal["timed_out"] and not terminal["automatic_retry"], "outer was cancelled/timed out/retried")
    complete = json.loads(raws["complete.json"])
    require(complete["schema"] == "hepta.source53-finalization-complete.v1"
            and complete["tested_source_commit"] == TESTED_COMMIT and complete["tested_source_tree"] == TESTED_TREE,
            "complete identity/schema mismatch")
    require(complete["native_HEAD"] == HEAD and complete["final_formatted_commit"] is None,
            "original complete commit/HEAD modified")
    for key in ("post_fix_or_format_tests_executed", "qualification_transferred_to_mutated_tree", "remote_refs_changed", "behavior_repair_claimed", "original_r29_failure_relabelled_as_pass"):
        require(complete[key] is False, "finalization boundary changed: " + key)
    require(complete["diagnostic_only"] is True and complete["original_gate_source_retained_separately_from_final_tree"] is True,
            "tested/final identity boundary missing")
    pre = json.loads(raws["preconditions.json"])
    require(pre["schema"] == "hepta.source53-finalization-preconditions.v1" and pre["tested_source_tree"] == TESTED_TREE
            and pre["tested_source_commit"] == TESTED_COMMIT and pre["source_paths"] == 197,
            "preconditions identity mismatch")
    references = [complete["tested"], complete["after_fix"], complete["after_format"]]
    labels = ["tested-pre-fix-source", "post-fix-source", "final-post-format-source"]
    snapshots = [verify_snapshot(raws, reference, label) for reference, label in zip(references, labels)]
    require(references[0]["tree"] == TESTED_TREE and references[2]["tree"] == complete["final_formatted_tree"], "snapshot chain mismatch")
    require(all(set(rows) == set(snapshots[0][1]) for _, rows in snapshots), "source snapshot paths changed")
    require(all(sum(name.endswith(".rs") for name in rows) == 183 for _, rows in snapshots), "Rust scope changed")

    def pointer(record):
        require(record["path"].startswith(PREFIX), "phase pointer outside finalization")
        data = raws[safe(record["path"][len(PREFIX):])]
        require(pin(data) == {key: record[key] for key in ("bytes", "sha256", "git_blob")}, "phase pointer pin mismatch")
        return data

    phase_deltas = {}
    previous_end = None
    for idx, phase in enumerate(("fix", "format")):
        receipt = json.loads(pointer(complete[phase + "_receipt"]))
        raw = json.loads(pointer(receipt["raw_process_result"]))
        guard = json.loads(pointer(receipt["source_postguard"]))
        require(receipt["schema"] == "hepta.source53-finalization-phase-receipt.v1" and receipt["phase"] == phase,
                "phase receipt schema mismatch")
        command = scope["fix_command"] if phase == "fix" else ["just", "fmt"]
        require(receipt["command"] == raw["command"] == command, "original phase command changed")
        require(raw["exit_code"] == receipt["exit_code"] == receipt["effective_exit_code"] == 0
                and receipt["phase_pass"] is True and receipt["post_source_tree_bound"] is True
                and receipt["issues"] == [] and raw["wait_exception"] is None, "phase not successful")
        require(receipt["before_tree"] == raw["before_tree"] == references[idx]["tree"]
                and receipt["after_tree"] == references[idx + 1]["tree"], "phase tree chain mismatch")
        require(guard["pass"] is True and guard["issues"] == [] and guard["native_head"] == HEAD
                and guard["untracked_paths"] == [] and guard["observed_index_tree"] == references[idx]["tree"],
                "phase postguard failed")
        allowed = set(scope["rust_paths"]) | (set(scope["python_paths"]) if phase == "format" else set())
        actual_delta = sorted(name for name in snapshots[idx][1] if snapshots[idx][1][name] != snapshots[idx + 1][1][name])
        require(set(actual_delta) <= allowed and sorted(guard["tracked_changed_paths"]) == actual_delta,
                "phase changed paths disagree with source snapshots/scope")
        require({row["path"]: row for row in guard["working_source_files"]} == snapshots[idx + 1][1], "guard source rows differ from snapshot")
        for name in snapshots[idx][1]:
            require(snapshots[idx][1][name]["mode"] == snapshots[idx + 1][1][name]["mode"], "phase mode changed")
        for key in ("cargo_lock_sha256", "bazel_lock_sha256"):
            require(guard[key] == complete[key] == snapshots[idx][0][key] == snapshots[idx + 1][0][key], "dual locks changed")
        log_raw, resources_raw, patch_raw = pointer(receipt["log"]), pointer(receipt["resources"]), pointer(receipt["phase_only_patch"])
        require(re.findall(rb"^\s*Exit status: ([0-9]+)\s*$", resources_raw, re.M) == [b"0"], "resource exit mismatch")
        if actual_delta:
            staged = json.loads(pointer(receipt["exact_stage_raw_result"]))
            require(staged["exit_code"] == 0 and staged["command"] == ["git", "add", "--", *actual_delta], "exact stage mismatch")
            stage_receipt = json.loads(raws[phase + "-stage-receipt.json"])
            require(stage_receipt["exit_code"] == 0 and stage_receipt["raw_process_result"] == receipt["exact_stage_raw_result"], "stage receipt mismatch")
            pointer(stage_receipt["stdout"]); pointer(stage_receipt["stderr"])
        else:
            require(receipt["exact_stage_raw_result"] is None, "empty delta must not invent stage")
            require(not any(name.startswith(phase + "-stage-") for name in raws), "empty delta has unexpected stage output")
        require(receipt["start_unix"] == raw["start_unix"] and receipt["end_unix"] == raw["end_unix"], "phase raw/receipt times mismatch")
        require(previous_end is None or receipt["start_unix"] >= previous_end, "phase order mismatch")
        previous_end = receipt["end_unix"]
        phase_deltas[phase] = actual_delta
        result[phase] = {"exit_code": 0, "effective_exit_code": 0, "command": command,
                         "elapsed_seconds": receipt["elapsed_seconds"], "changed_path_count": len(actual_delta),
                         "changed_paths": actual_delta, "before_tree": receipt["before_tree"], "after_tree": receipt["after_tree"],
                         "log": receipt["log"], "resources": receipt["resources"], "receipt": complete[phase + "_receipt"],
                         "raw_process_result": receipt["raw_process_result"], "phase_only_patch": receipt["phase_only_patch"],
                         "warnings": warning_observations(log_raw), "original_log_bytes": len(log_raw)}
    require(terminal["at_unix_ms"] / 1000 >= previous_end, "outer precedes completed formatting")
    pointer(complete["tested_to_final_patch"])
    result.update(success=True, state="ACTUAL_FIX_FORMAT_CLOSED_SUCCESS", outer_exit_code=0,
                  final_formatted_tree=complete["final_formatted_tree"], snapshot_references={label: ref for label, ref in zip(labels, references)},
                  source_snapshot_count=3, source_path_count_each=197, snapshot_members_each=198,
                  complete=complete, phase_delta_paths=phase_deltas,
                  combined_delta_paths=sorted(name for name in snapshots[0][1] if snapshots[0][1][name] != snapshots[2][1][name]))
    result["readback_scope"] = {
        "all_three_archives_raw_sha_git_blob_member_mode_and_manifest_verified": True,
        "raw_phase_receipts_resources_guards_and_controller_verified": True,
        "complete_git_tree_reconstruction_performed_by_this_reader": False,
        "patch_application_performed_by_this_reader": False,
        "separate_root_and_peer_deep_readbacks_retained_as_support": True,
    }
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bindings", required=True)
    args = parser.parse_args()
    config_path = ROOT / args.bindings
    config_raw = config_path.read_bytes()
    config = json.loads(config_raw)
    require(config["schema"] == "hepta.source53-finalization-assembly-bindings.v1" and config["frozen"] is True,
            "unbound preparation; no formal directory will be created")
    source = ROOT / safe(config["native_complete_directory"])
    listed = config["native_complete_directory_file_pins"]
    require(isinstance(listed, list) and listed, "actual closed output list is missing")
    expected = {safe(row["path"]): row for row in listed}
    require(len(expected) == len(listed), "duplicate output pins")
    observed = {str(p.relative_to(source)) for p in source.rglob("*") if p.is_file()}
    require(observed == set(expected) and not any(p.is_symlink() for p in source.rglob("*")), "actual output set mismatch or symlink")
    origins = {name: str((source / name).relative_to(ROOT)) for name in expected}
    raws = {name: load_pin({**row, "path": origins[name]}) for name, row in expected.items()}
    archives = config["archive_files"]
    require(isinstance(archives, list) and len(archives) == 3, "three actually downloaded archive pins are required")
    for row in archives:
        name = safe(row["output_name"])
        require(name not in raws and name.endswith(".tar.gz"), "duplicate or invalid archive output name")
        raws[name] = load_pin(row)
        origins[name] = row["path"]
    launch_raw = load_pin(config["controller_launch"])
    launch = json.loads(launch_raw)
    require(launch["job"]["id"] == config["native_job_id"] and launch["launch"]["ok"] is True
            and launch["reused"] is False and launch["job"]["executable"] == "/usr/bin/python3"
            and launch["job"]["args"] == ["/home/alex/work/hepta-cell-unified-20261106-a/native-finalize-source53.py"]
            and launch["job"]["idempotency_key"] == "cell-source53-finalize-20261106-v1",
            "finalizer launch identity or direct-file command mismatch")
    terminal_raw = load_pin(config["terminal"])
    terminal = json.loads(terminal_raw)
    require(terminal["job_id"] == config["native_job_id"] and terminal["state"] in ("succeeded", "failed", "timed_out"), "not actual terminal")
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        require(terminal[key] is True, "terminal record not fully closed")
    stdout_raw, stderr_raw = load_pin(config["controller_stdout"]), load_pin(config["controller_stderr"])
    for channel, data in (("stdout", stdout_raw), ("stderr", stderr_raw)):
        require(terminal["log_bytes"][channel]["stored"] == terminal["log_bytes"][channel]["seen"] == len(data)
                and terminal["log_synced"][channel] is True and terminal["log_truncated"][channel] is False,
                "outer output custody mismatch")
    scope_dir = ROOT / "source53-final-scope-preparation"
    for name, digest in SCOPE_SHA256.items():
        require(hashlib.sha256((scope_dir / name).read_bytes()).hexdigest() == digest,
                "frozen actual fresh-scope bytes changed: " + name)
    selection = json.loads((scope_dir / "EXPECTED-SELECTION.json").read_bytes())
    packages = json.loads((scope_dir / "PACKAGE-ARGS.json").read_bytes())
    scope = {"fix_command": packages["command"], "rust_paths": selection["rust_paths"],
             "python_paths": [str(PurePosixPath(path)) for path in selection["python_paths"]]}
    require(len(scope["rust_paths"]) == 183 and len(scope["python_paths"]) == 2 and len(packages["owners"]) == 26, "fixed scope mismatch")
    require(selection["source_commit"] == packages["source_commit"] == TESTED_COMMIT
            and selection["source_tree"] == packages["source_tree"] == TESTED_TREE
            and selection["native_HEAD"] == HEAD and selection["default_formatter_command"] == ["just", "fmt"]
            and selection["all_flag_used"] is False and selection["fresh_source53_r31_metadata_verified"] is True,
            "frozen scope source or default formatter contract mismatch")
    report = validate_closed(raws, terminal, scope)
    report["formatter_selection_path_representation"] = {
        "original_python_paths": selection["python_paths"],
        "equivalent_git_relative_python_paths": scope["python_paths"],
        "reason": "Original formatter selection retains ./ prefix; Git manifests use canonical repository-relative paths.",
        "original_scope_file_modified": False,
    }
    registration = config["root_code_registration"]
    require(isinstance(registration, dict) and registration["stage"] == 54,
            "actual root post-format code registration is not yet bound")
    commit_api = json.loads(load_pin(registration["commit_api"]))
    for key in registration["commit_api_json_pointer"].strip("/").split("/") if registration["commit_api_json_pointer"] else []:
        commit_api = commit_api[key.replace("~1", "/").replace("~0", "~")]
    if isinstance(commit_api, str):
        commit_api = json.loads(commit_api)
    require(commit_api["sha"] == registration["commit"]
            and commit_api["tree"]["sha"] == registration["tree"] == report["final_formatted_tree"]
            and [row["sha"] for row in commit_api["parents"]] == [TESTED_COMMIT],
            "actual code registration commit/tree/parent mismatch")
    load_pin(registration["root_readback"])
    registration_ledger = json.loads(load_pin(registration["ledger_snapshot"]))
    require(registration_ledger["current_source_commit"] == registration["commit"]
            and registration_ledger["current_source_tree"] == registration["tree"],
            "actual root fixed ledger does not bind final code")
    collections = config["collections"]
    require(isinstance(collections, list) and collections, "support copy map is not frozen")
    copies = []
    for name, data in raws.items():
        copies.append(("original/finalization/" + name, origins[name], data))
    for group in collections:
        destination = safe(group["destination"])
        for row in group["files"]:
            data = load_pin(row)
            copies.append((destination + "/" + safe(row["relative_destination"]), row["path"], data))
    for name, record, data in (("launch.json", config["controller_launch"], launch_raw),
                               ("terminal-process-status.json", config["terminal"], terminal_raw),
                               ("stdout.log", config["controller_stdout"], stdout_raw),
                               ("stderr.log", config["controller_stderr"], stderr_raw)):
        copies.append(("original/controller/" + name, record["path"], data))
    copies.append(("support/assembly/ACTUAL-BINDINGS.json", str(config_path.relative_to(ROOT)), config_raw))
    for name in ("assemble_finalization.py", "prepare_actual_bindings.py", "OUTPUT-CONTRACT.json", "README.md",
                 "assembly-history/assemble_finalization-attempt1.py", "assembly-history/ATTEMPT-1-EXECUTION.json",
                 "assembly-history/PATH-REPRESENTATION-CORRECTION.json"):
        path = Path(__file__).resolve().parent / name
        copies.append(("support/assembly/" + name, str(path.relative_to(ROOT)), path.read_bytes()))
    require(len({name for name, _, _ in copies}) == len(copies), "duplicate formal destination")
    target = ROOT / safe(config["formal_directory"])
    require(not target.exists(), "formal destination already exists")
    target.mkdir(parents=True)
    mappings = []
    def put(name, data):
        path = target / safe(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
        return {"path": name, **pin(data)}
    for name, origin, data in copies:
        put(name, data)
        mappings.append({"source_path": origin, "destination_path": name, "transform": "exact_bytes", **pin(data)})
    put("SOURCE-DESTINATION-MAPPING.json", encode({"schema": "hepta.finalization-original-copy-map.v1", "files": mappings}))
    put("INDEPENDENT-READBACK.json", encode(report))
    put("COMPILER-WARNING-READBACK.json", encode({"schema": "hepta.finalization-warning-closure.v1",
        "fix": report["fix"]["warnings"] if report["fix"] else None,
        "format": report["format"]["warnings"] if report["format"] else None,
        "original_scoped_fix_is_not_new_strict_D_warnings_gate": True,
        "warnings_silenced_or_tests_repeated_by_reader": False}))
    closure = {"schema": "hepta.source53-finalization-formal-closure.v1", "state": report["state"],
               "success": report["success"], "tested_source_commit": TESTED_COMMIT, "tested_source_tree": TESTED_TREE,
               "final_formatted_tree": report["final_formatted_tree"], "root_registered_final_commit": registration["commit"],
               "root_code_registration": registration,
               "original_outer_exit_code": terminal["exit_code"], "native_job_id": terminal["job_id"],
               "fix": report["fix"], "format": report["format"],
               "originals": {"directory": "original/finalization", "file_count": len(raws)},
               "complete": {"path": "original/finalization/complete.json", **pin(raws["complete.json"])} if "complete.json" in raws else None,
               "original_terminal": {"path": "original/controller/terminal-process-status.json", **pin(terminal_raw)},
               "source_snapshot_count": report.get("source_snapshot_count"), "combined_delta_paths": report.get("combined_delta_paths"),
               "post_fix_or_format_tests_executed": False, "qualification_transferred_to_mutated_tree": False,
               "diagnostic_only": True, "behavior_repair_claimed": False, "science": "HOLD", "authority": "DENY_ALL",
               "root_code_registration_is_separate_from_original_complete": True,
               "original_complete_final_formatted_commit_remains_null": True}
    put("CLOSURE.json", encode(closure))
    put("README.md", ("# source53 finalization 原件\n\n本组封存实际终态、原命令与源码快照。测试资格仍绑定 `f74be175de66a4b351cd239d39d98cd34fe9cc1b` / `440d4a8e09af4009e4d9ea067388826308da8803`；格式化后没有重跑测试。最终 Git commit 由 root 单独登记，并以 publication-support/source54 保留真实回执；原 complete 中的 null 保持不变。R31 附件的上传/ledger登记独立放在 publication-support/R31，不是新门或 artifact checkpoint。诊断-only、HOLD、DENY_ALL 与旧失败均未改变。原 fix 日志的三条诊断警告和三条汇总原文保留；fix 退出0不等于新 `-D warnings` 严格门通过。实际状态见 CLOSURE.json，不能从附件存在推断执行成功。\n").encode())
    files = [{"path": str(path.relative_to(target)), **pin(path.read_bytes())} for path in sorted(target.rglob("*")) if path.is_file()]
    put("ATTACHMENT-MANIFEST.json", encode({"schema": "hepta.finalization-attachment-manifest.v1", "files": files,
                                         "file_count_excluding_manifest": len(files), "byte_count_excluding_manifest": sum(row["bytes"] for row in files)}))
    binary = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            binary.append({"path": str(path.relative_to(ROOT)), **pin(data), "uploaded_by_this_script": False})
    plan_path = Path(__file__).resolve().parent / "BINARY-PLAN.json"
    with plan_path.open("xb") as stream:
        stream.write(encode({"schema": "hepta.finalization-binary-plan.v1", "files": binary, "ledger_modified": False}))
    print(json.dumps({"formal_directory": str(target.relative_to(ROOT)), "state": report["state"],
                      "files": len(files) + 1, "manifest": pin((target / "ATTACHMENT-MANIFEST.json").read_bytes()),
                      "binary_paths": len(binary)}, indent=2))


if __name__ == "__main__":
    main()
