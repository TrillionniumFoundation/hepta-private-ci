"""Read closed finalization data only. No project code, Git, Cargo or formatter execution."""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import re
from pathlib import Path

from source_compare import check_patch, pin, read_tar, require

TESTED_COMMIT = "f74be175de66a4b351cd239d39d98cd34fe9cc1b"
TESTED_TREE = "440d4a8e09af4009e4d9ea067388826308da8803"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
JOB = "1a1b2a75955-fc05-7f27"
CARGO_LOCK = "4165307bb6c41d08e6c1c362060f2a958c8200ea43fdab2b8b1e6220ad82b55c"
BAZEL_LOCK = "e80ef06b6f824a19cdcedd6010738b316ccca96b83ad8730fafb52153a2634fb"


def dump(path, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with path.open("xb") as output:
        output.write(raw)
    return {"path": path.name, **pin(raw)}


def match_pin(raw, expected, where):
    observed = pin(raw)
    for key in ("bytes", "sha256", "git_blob"):
        if key in expected:
            require(observed[key] == expected[key], where + ": " + key)
    return observed


def source_map(manifest):
    rows = manifest["changed_files"]
    require(len(rows) == 197 and len({x["path"] for x in rows}) == 197, "source manifest count")
    return {x["path"]: x for x in rows}


def check_identity(obj, prefix="source"):
    require(obj[prefix + "_tree"] == TESTED_TREE and obj[prefix + "_commit"] == TESTED_COMMIT,
            "tested identity mismatch")


def check_selection(selection, expected):
    require(selection["native_head"] == HEAD and selection["default_base"] == "HEAD", "formatter HEAD/base")
    require(selection["all_flag"] is False and selection["base_override"] is None, "formatter flags")
    require(selection["other_formatter_groups_selected"] is False, "other format group")
    require(selection["selection_algorithm_bound_to_original_format_py"] is True, "formatter algorithm")
    for key in ("changed_paths", "rust_paths", "python_paths"):
        require(selection[key] == expected[key], "formatter selection " + key)


def binding_body_readback(template, executed):
    """Reverse only None literal bindings and FROZEN, then compare complete source text."""
    def assignments(raw):
        text = raw.decode()
        tree = ast.parse(text)
        starts = [0]
        for line in text.splitlines(keepends=True): starts.append(starts[-1] + len(line))
        result = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                v = node.value
                start = starts[v.lineno-1] + v.col_offset
                end = starts[v.end_lineno-1] + v.end_col_offset
                result[node.targets[0].id] = (v, start, end, text[start:end])
        return text, result
    original_text, original = assignments(template)
    actual_text, actual = assignments(executed)
    replacements, names = [], []
    for name, (value, _, _, source) in original.items():
        if isinstance(value, ast.Constant) and (value.value is None or name == "FROZEN"):
            require(name in actual, "missing executed constant " + name)
            a, start, end, text = actual[name]
            if name == "FROZEN": require(ast.literal_eval(a) is True, "not executed FROZEN")
            else: require(ast.literal_eval(a) is not None, "unbound executed constant")
            replacements.append((start, end, source)); names.append(name)
    for start, end, source in sorted(replacements, reverse=True):
        actual_text = actual_text[:start] + source + actual_text[end:]
    require(actual_text == original_text, "executed script body differs beyond exact literal bindings")
    require(len(names) == 36 and "FROZEN" in names, "expected 35 bindings plus FROZEN")
    return {"template": pin(template), "executed": pin(executed), "actual_literal_bindings": 35,
            "frozen_only_boolean_change": True, "full_body_inverse_exact": True, "names": names}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path.cwd())
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    root, out = args.workspace.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    used = {}
    def read(path):
        p = path if path.is_absolute() else root / path
        raw = p.read_bytes()
        try: relative = str(p.relative_to(root))
        except ValueError: relative = str(p)
        used[relative] = {"path": relative, **pin(raw)}
        return raw
    def obj(path): return json.loads(read(path))
    closed = Path("native-validation-results/source53-finalization-closed")
    evidence = closed / "evidence"
    complete = obj(evidence / "complete.json")
    preconditions = obj(evidence / "preconditions.json")
    check_identity(complete, "tested_source")
    check_identity(preconditions, "tested_source")
    require(complete["final_formatted_commit"] is None, "do not rewrite original publication state")
    require(complete["native_HEAD"] == preconditions["native_head"] == HEAD, "native HEAD")
    require(complete["post_fix_or_format_tests_executed"] is False
            and complete["qualification_transferred_to_mutated_tree"] is False, "postformat qualification boundary")
    require(complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False, "diagnostic boundary")
    require(complete["original_r29_failure_relabelled_as_pass"] is False, "historical failed gate boundary")
    require(complete["cargo_lock_sha256"] == preconditions["cargo_lock_sha256"] == CARGO_LOCK, "cargo lock")
    require(complete["bazel_lock_sha256"] == preconditions["bazel_lock_sha256"] == BAZEL_LOCK, "bazel lock")
    scope_dir = Path("source53-final-scope-preparation")
    selection = obj(scope_dir / "EXPECTED-SELECTION.json")
    packages = obj(scope_dir / "PACKAGE-ARGS.json")
    scope = preconditions["fresh_metadata_scope"]
    check_identity(scope)
    for k in ("rust_paths", "python_paths", "owners"):
        require(scope[k] == selection[k], "scope input " + k)
    require(len(scope["source_paths"]) == 197 and scope["source_paths"] == selection["changed_paths"], "scope197")
    require(scope["rust_count"] == len(scope["rust_paths"]) == 183, "scope Rust183")
    require(scope["python_count"] == len(scope["python_paths"]) == 2, "scope Python2")
    require(len(scope["owners"]) == 26 and selection["ci_selector_count"] == 27, "owner/CI counts")
    require(scope["fix_command"] == packages["command"] == ["just", "fix", "--locked", *packages["package_args"]], "original fix command")
    require(scope["format_command"] == ["just", "fmt"], "original format command")
    require(packages["package_args"] == [v for owner in scope["owners"] for v in ("-p", owner)], "original26 packages")
    require(not {"--all", "--allow-staged"} & set(scope["fix_command"] + scope["format_command"]), "extra flag")
    check_selection(preconditions["default_formatter_selection"], selection)
    for record in scope["scope_input_pins"]:
        match_pin(read(scope_dir / Path(record["path"]).name), record, "original scope input")
    require(scope["primary_source_pins"] == json.loads(read(scope_dir / "PRIMARY-SOURCE-PINS.json")), "34 primary pins")
    require(len(scope["primary_source_pins"]) == 34, "primary count")
    authorization = obj(closed / "input/ROOT-EXECUTION-AUTHORIZATION.json")
    executed = read(closed / "input/executed.py")
    match_pin(executed, authorization["script"], "root authorized script")
    require(authorization["authorized"] is True, "actual root authorization")
    require(authorization["scope"]["fix_owner_packages"] == scope["owners"], "authorized fix owner scope")
    script_binding = binding_body_readback(read(Path("source53-finalize-preparation/native-finalize-source53-template.py")), executed)

    archive_root = Path("native-validation-results/source53-finalization-archives")
    snapshots, sources, member_rows = {}, {}, {}
    for label, key in (("tested-pre-fix-source", "tested"), ("post-fix-source", "after_fix"),
                       ("final-post-format-source", "after_format")):
        archive_path = archive_root / label / (label + ".tar.gz")
        raw = read(archive_path)
        match_pin(raw, complete[key]["archive"], label + " archive")
        contents, members = read_tar(raw)
        require(len(members) == 198, "snapshot members")
        external = read(evidence / (label + "-manifest.json"))
        require(contents["source-manifest.json"] == external, "archive embedded manifest differs")
        match_pin(external, complete[key]["manifest"], label + " manifest")
        manifest = json.loads(external)
        require(manifest["label"] == label and manifest["source_tree"] == complete[key]["tree"], "snapshot identity")
        check_identity(manifest, "tested_source")
        require(manifest["native_head"] == manifest["original_framework_base"] == HEAD, "snapshot HEAD")
        require(manifest["cargo_lock_sha256"] == CARGO_LOCK and manifest["bazel_lock_sha256"] == BAZEL_LOCK, "snapshot locks")
        require(manifest["post_fix_or_format_tests_executed"] is False
                and manifest["qualification_transferred_to_mutated_tree"] is False, "snapshot no qualification transfer")
        check_selection(manifest["default_formatter_selection"], selection)
        rows = source_map(manifest)
        require(set(contents) == {"source-manifest.json", *("source/"+x for x in rows)}, "snapshot exact path set")
        require(set(rows) == set(scope["source_paths"]), "snapshot scope differs")
        modes = {x["path"]: x["mode"] for x in members}
        for path, row in rows.items():
            require(row["mode"] in ("100644", "100755"), "Git regular mode")
            match_pin(contents["source/"+path], row, label + ":" + path)
            require(int(modes["source/"+path], 8) == int(row["mode"][-3:], 8), "Git mode vs tar permissions")
        sources[label] = {path: contents["source/"+path] for path in rows}
        snapshots[label] = {"archive": {"path": str(archive_path), **pin(raw)},
                            "manifest": pin(external), "source_tree": manifest["source_tree"],
                            "source_commit": manifest["source_commit"], "source_paths": len(rows),
                            "all_raw_sha256_git_blob_modes_match": True, "files": rows}
        member_rows[label] = members
    tested = sources["tested-pre-fix-source"]
    fixed = sources["post-fix-source"]
    final = sources["final-post-format-source"]
    require(tested == fixed, "fix changed actual raw source")
    require(snapshots["tested-pre-fix-source"]["source_tree"] == snapshots["post-fix-source"]["source_tree"] == TESTED_TREE,
            "fix tree identity changed")
    r31_path = Path("native-validation-results/r31-archive-closed/checkpoint-r31-closed.tar.gz")
    r31_raw = read(r31_path)
    require(pin(r31_raw)["sha256"] == "87afd6c49a3c753b90c8e53b3b70988f2964352fcf2daf0ed85c536ac6f77563", "R31 original archive")
    r31, _ = read_tar(r31_raw)
    require({k[7:]: v for k, v in r31.items() if k.startswith("source/")} == tested,
            "tested snapshot does not equal full 197 R31 original source bytes")
    original_lock_sources = []
    for path, raw in r31.items():
        if path.endswith("/Cargo.lock") or path.endswith("/MODULE.bazel.lock"):
            expected = CARGO_LOCK if path.endswith("/Cargo.lock") else BAZEL_LOCK
            require(pin(raw)["sha256"] == expected, "original archive lock bytes")
            original_lock_sources.append({"member": path, **pin(raw)})
    require({x["sha256"] for x in original_lock_sources} == {CARGO_LOCK, BAZEL_LOCK}, "both original lock bytes")
    patch_results = {}
    for name, before, after in (("fix-only.patch", tested, fixed), ("format-only.patch", fixed, final),
                                ("tested-to-final.patch", tested, final)):
        raw = read(evidence / name)
        rows = check_patch(raw, before, after)
        patch_results[name] = {**pin(raw), "changed_paths": len(rows), "files": rows,
                              "entire_forward_and_reverse_bytes_exact": True}
    require(read(evidence / "fix-only.patch") == b"", "actual fix empty patch")
    require(read(evidence / "format-only.patch") == read(evidence / "tested-to-final.patch"), "two final patches differ")
    changed = sorted(path for path in tested if tested[path] != final[path])
    require(set(changed) <= set(scope["rust_paths"]) | set(scope["python_paths"]), "format outside allowed paths")
    for path in tested:
        require(snapshots["tested-pre-fix-source"]["files"][path]["mode"] == snapshots["final-post-format-source"]["files"][path]["mode"], "source mode changed")

    phases = {}
    for phase, before, after, before_files, after_files, allowed in (
        ("fix", TESTED_TREE, TESTED_TREE, tested, fixed, scope["rust_paths"]),
        ("format", TESTED_TREE, complete["final_formatted_tree"], fixed, final, sorted(set(scope["rust_paths"]) | set(scope["python_paths"]))),
    ):
        raw_record = obj(evidence / (phase + "-raw-process-result.json"))
        receipt_raw = read(evidence / (phase + "-receipt.json")); receipt = json.loads(receipt_raw)
        stage_pre = obj(evidence / (phase + "-preconditions.json"))
        guard = obj(evidence / (phase + "-post-command-guard.json"))
        for key in ("command", "cwd", "before_tree", "tested_source_tree", "tested_source_commit", "start_unix", "end_unix", "elapsed_seconds", "exit_code"):
            require(receipt[key] == raw_record[key], phase + " receipt/raw field " + key)
        require(raw_record["exit_code"] == receipt["effective_exit_code"] == 0 and raw_record["wait_exception"] is None,
                phase + " raw/effective failure")
        require(receipt["before_tree"] == before and receipt["after_tree"] == after, phase + " tree chain")
        require(receipt["phase_pass"] is True and receipt["issues"] == [], phase + " receipt issues")
        require(abs(raw_record["end_unix"] - raw_record["start_unix"] - raw_record["elapsed_seconds"]) < 1e-8, "wall time arithmetic")
        require(raw_record["command"] == (packages["command"] if phase == "fix" else ["just", "fmt"]), "actual original command")
        require(raw_record["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs", "actual cwd")
        require(stage_pre["command"] == raw_record["command"] and set(stage_pre["allowed_paths"]) == set(allowed), "phase preconditions scope")
        check_selection(stage_pre["default_formatter_selection"], selection)
        require(guard["pass"] is True and guard["issues"] == [] and guard["untracked_paths"] == [], "post command guard")
        require(guard["native_head"] == HEAD and guard["observed_index_tree"] == before, "prestage index/HEAD")
        require(set(guard["allowed_paths"]) == set(allowed), "guard allowed paths")
        differences = sorted(path for path in before_files if before_files[path] != after_files[path])
        require(guard["tracked_changed_paths"] == differences, "guard exact actual changed paths")
        require(guard["working_source_files"] == list(snapshots["post-fix-source" if phase == "fix" else "final-post-format-source"]["files"].values()), "guard exact source list")
        require(guard["cargo_lock_sha256"] == CARGO_LOCK and guard["bazel_lock_sha256"] == BAZEL_LOCK, "post command locks")
        check_selection(guard["default_formatter_selection"], selection)
        for field in ("raw_process_result", "log", "resources", "phase_only_patch", "source_postguard"):
            match_pin(read(evidence / Path(receipt[field]["path"]).name), receipt[field], phase + " receipt pin " + field)
        match_pin(receipt_raw, complete[phase + "_receipt"], phase + " complete receipt")
        resources = read(evidence / (phase + "-resources.txt"))
        require(re.findall(rb"^\s*Exit status: (\d+)\s*$", resources, re.M) == [b"0"], "time resource raw exit")
        command_line = re.findall(rb'^\s*Command being timed: "(.*)"$', resources, re.M)
        require(command_line == [" ".join(raw_record["command"]).encode()], "time resource command")
        staged = None
        if differences:
            stage_raw = obj(evidence / (phase + "-stage-raw-process-result.json"))
            stage_receipt = obj(evidence / (phase + "-stage-receipt.json"))
            require(stage_raw["command"] == stage_receipt["command"] == ["git", "add", "--", *differences], "exact staging argv")
            require(stage_raw["exit_code"] == stage_receipt["exit_code"] == 0, "original stage result")
            require(stage_receipt["native_head_changed"] is False, "stage HEAD mutation")
            for field in ("raw_process_result", "stdout", "stderr"):
                match_pin(read(evidence / Path(stage_receipt[field]["path"]).name), stage_receipt[field], "stage pin")
            match_pin(read(evidence / (phase + "-stage-raw-process-result.json")), receipt["exact_stage_raw_result"], "phase stage pin")
            staged = {"exit_code": stage_raw["exit_code"], "changed_path_count": len(differences)}
        else:
            require(receipt["exact_stage_raw_result"] is None, "empty phase stage must be null")
            require(not any((root/evidence).glob(phase + "-stage-*")), "unexpected empty-phase stage files")
        phases[phase] = {"raw_exit": raw_record["exit_code"], "effective_exit": receipt["effective_exit_code"],
                         "wall_seconds": raw_record["elapsed_seconds"], "command": raw_record["command"],
                         "before_tree": before, "after_tree": after, "changed_paths": differences,
                         "raw_receipt_resources_guards_and_outputs_exact": True, "stage": staged,
                         "max_rss_kib": int(re.findall(rb"Maximum resident set size \(kbytes\): (\d+)", resources)[0]),
                         "free_bytes_after_original_sample": receipt["free_bytes_after"]}

    ctrl = closed / "controller"
    launch_args = obj(ctrl / "launch-args.json")
    launch = obj(ctrl / "launch-original.json")
    terminal = obj(ctrl / "terminal-process-status-original.json")
    require(terminal["job_id"] == launch["job"]["id"] == JOB, "controller job")
    require(terminal["state"] == "succeeded" and terminal["exit_code"] == 0
            and terminal["output_complete"] is True and terminal["output_durable"] is True, "natural outer0 durable")
    for field in ("automatic_retry", "cancelled", "timed_out"):
        require(terminal[field] is False, "outer exception flag " + field)
    for field in ("executable", "args", "cwd", "idempotency_key"):
        require(launch_args[field] == launch["job"][field] == authorization[field], "controller authorization " + field)
    require(launch_args["timeout_seconds"] == authorization["outer_timeout_seconds"] == 9600, "original outer deadline")
    accumulated = {"stdout": b"", "stderr": b""}; ranges=[]
    for name in ("read-0-original.json", "read-final-original.json"):
        record = obj(ctrl / name)
        require(record["job_id"] == JOB, "read job")
        for stream in accumulated:
            value = record[stream]; raw = bytes.fromhex(value["bytes_hex"])
            require(value["offset"] == len(accumulated[stream]), "controller offset continuity")
            require(value["next_offset"]-value["offset"] == len(raw) and value["size"] >= value["next_offset"], "controller chunk size semantic")
            if "text" in value: require(value["text"].encode() == raw, "controller text/hex")
            accumulated[stream] += raw
            ranges.append({"file":name,"stream":stream,"offset":value["offset"],"next_offset":value["next_offset"],"observed_size":value["size"],"bytes":len(raw)})
    for stream, raw in accumulated.items():
        require(read(ctrl / ("original-"+stream+".log")) == raw, "complete controller stream")
        require(terminal["log_bytes"][stream] == {"seen": len(raw), "stored": len(raw)}, "terminal observed/stored lengths")
        require(terminal["log_synced"][stream] is True and terminal["log_truncated"][stream] is False and terminal["log_errors"][stream] is None, "controller durability")
    events = [json.loads(line) for line in accumulated["stdout"].splitlines()]
    require(len(events) == 7, "actual expected event count")
    for phase in ("fix", "format"):
        raw = obj(evidence / (phase + "-raw-process-result.json"))
        require([e for e in events if e.get("event") == "finalization-raw-process-return" and e.get("phase") == phase]
                == [{**raw, "event":"finalization-raw-process-return"}], "controller raw event")
        receipt = obj(evidence / (phase + "-receipt.json"))
        require([e for e in events if e.get("schema") == receipt["schema"] and e.get("phase") == phase] == [receipt], "controller receipt event")
    require(events[-1]["phase"] == "finalization-complete" and events[-1]["formatted_tree"] == complete["final_formatted_tree"], "final controller event")

    log = read(evidence / "fix.log"); lines = log.splitlines(keepends=True)
    warning_blocks=[]; offset=0
    for i,line in enumerate(lines):
        if line.startswith(b"warning:"):
            j=i+1
            while j<len(lines) and not lines[j].startswith((b"warning:", b"    Checking ", b"   Compiling ", b"    Finished ")): j+=1
            raw=b"".join(lines[i:j]);summary=line.startswith(b"warning: `")
            warning_blocks.append({"line":i+1,"byte_start":offset,"byte_end":offset+len(raw),**pin(raw),"summary":summary,"text":raw.decode()})
        offset += len(line)
    require(len(warning_blocks)==6 and sum(not x["summary"] for x in warning_blocks)==3, "actual warning count")
    require(read(evidence / "format.log") == b"", "actual format output changed")

    artifacts={}
    artifacts["snapshots"] = dump(out / "SNAPSHOT-MEMBERS.json",member_rows)
    artifacts["sources"] = dump(out / "SNAPSHOT-SOURCE-INVENTORIES.json",snapshots)
    artifacts["patches"] = dump(out / "PATCH-ROUNDTRIP-READBACK.json",patch_results)
    artifacts["warnings"] = dump(out / "WARNING-READBACK.json",warning_blocks)
    artifacts["inputs"] = dump(out / "INPUT-PINS.json",list(used.values()))
    report={
        "schema":"hepta.source53-finalization-independent-mechanical-readback.v1",
        "status":"ACTUAL_PHASE_ARCHIVE_AND_PATCH_MECHANICAL_READBACK_PASS_SEMANTIC_REVIEW_SEPARATE",
        "reader_did_not_execute_native_rust_metadata_tests_fix_format_or_git":True,
        "source53_tested_commit":TESTED_COMMIT,"source53_tested_tree":TESTED_TREE,
        "after_fix_tree":TESTED_TREE,"final_formatted_tree_observed_in_originals":complete["final_formatted_tree"],
        "final_commit_in_original_complete":None,"native_head":HEAD,
        "snapshots":{label:{k:v for k,v in row.items() if k!="files"} for label,row in snapshots.items()},
        "all_197_tested_source_bytes_equal_original_R31_archive":True,
        "fix_changed_files":0,"format_changed_files":len(changed),
        "format_changed_rust":sum(x.endswith('.rs') for x in changed),"format_changed_python":sum(x.endswith('.py') for x in changed),
        "format_changed_paths":changed,"allowed_rust_paths":183,"allowed_python_paths":2,"fix_owners":scope["owners"],
        "default_formatter_command":["just","fmt"],"default_base":"HEAD","all_flag":False,"extra_allow_staged":False,
        "phases":phases,"script_binding":script_binding,
        "outer":{"job_id":JOB,"exit_code":0,"natural_and_durable":True,"stdout_bytes":len(accumulated['stdout']),"stderr_bytes":len(accumulated['stderr']),"ranges":ranges,"events":len(events)},
        "actual_warnings":{"distinct_diagnostics":3,"summary_lines":3,"agentd_lib_test_is_duplicate_of_lib":True,"strict_lint_all_clear_claimed":False},
        "lock_evidence":{"original_R31_raw_lock_members":original_lock_sources,"all_original_pre_post_snapshot_hash_guards_match":True,"post_final_raw_lock_files_not_in_197_member_source_snapshot":True},
        "git_tree_scope":"All exported 197 raw blobs and Git regular-file modes independently recomputed. Whole repository root tree is the original native observed value; this report does not independently rebuild untouched repository directories.",
        "source_guard_scope":"Full raw exported paths and patches independently checked; unchanged non-exported dependency inputs rely on pinned original native pre/post hash guards.",
        "post_fix_or_format_tests_executed":False,"tested_R31_results_remain_on_440_tree":True,
        "qualification_transferred_to_mutated_tree":False,"science":"HOLD","authority":"DENY_ALL",
        "diagnostic_only":True,"behavior_repair_claimed":False,"historical_R29_failure_relabelled":False,
        "space_measurement_boundary":"Original free-space samples are shared filesystem observations, not exclusive task costs.",
        "artifacts":artifacts,
    }
    result=dump(out/"MECHANICAL-READBACK.json",report)
    print(json.dumps({"status":report['status'],"report":result,"snapshots":3,"source_files_each":197,"format_changed":len(changed),"phases":[0,0],"outer":0}))


if __name__ == "__main__":
    main()
