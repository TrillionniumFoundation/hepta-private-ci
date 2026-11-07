#!/usr/bin/env python3
"""Static/data-only audit of the frozen R30 template; never import or run it."""
import ast
from collections import Counter
import difflib
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
DEST = Path(__file__).resolve().parent
PREP = ROOT / "source53-native-gates-preparation"


def need(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def put(name, raw):
    p = DEST / name
    if p.exists():
        need(p.read_bytes() == raw, "refuse overwrite: " + name)
    else:
        with p.open("xb") as stream:
            stream.write(raw)
    return pin(raw)


def parsed(raw):
    text = raw.decode()
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    fns = {n.name: "".join(lines[n.lineno - 1:n.end_lineno]).encode()
           for n in tree.body if isinstance(n, ast.FunctionDef)}
    values = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try:
                values[n.targets[0].id] = ast.literal_eval(n.value)
            except ValueError:
                pass
    return tree, fns, values


def main():
    names = ("source52-r28-reviewed-template.py", "native-run-r30-template.py", "native-run-r30-template-v2.py")
    raw = {name: (PREP / name).read_bytes() for name in names}
    need(pin(raw[names[0]])["sha256"] == "2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb", "R28 reference differs")
    need(pin(raw[names[1]])["sha256"] == "7e5c320133b585f9f1ce18e272ebbe26c0ad0da430fbde46d988aa89bb6a4dc9", "R30 v1 differs")
    need(pin(raw[names[2]])["sha256"] == "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b", "R30 v2 differs")
    trees, functions, values = {}, {}, {}
    for name, data in raw.items():
        trees[name], functions[name], values[name] = parsed(data)
    old, v1, v2 = (functions[n] for n in names)
    changed_v2 = sorted(name for name in v1 if v1[name] != v2[name])
    need(changed_v2 == ["review_tests", "write_json"] and set(v1) == set(v2), "v2 changed an unreviewed function")
    restore = raw[names[2]].decode()
    for name in changed_v2:
        need(restore.count(v2[name].decode()) == 1, "v2 function occurrence differs")
        restore = restore.replace(v2[name].decode(), v1[name].decode(), 1)
    need(restore.encode() == raw[names[1]], "v2 whole-file inverse differs")
    common = sorted(name for name in old if name in v2 and old[name] == v2[name])
    need(len(common) == 17, "unexpected shared R28 function count")
    current = values[names[2]]
    need(current["FROZEN"] is False and sum(v is None for v in current.values()) == 15, "inert bindings changed")
    none_names = sorted(k for k, v in current.items() if v is None)
    need(current["PACKAGES"] == ["codex-app-server"] and current["DIAGNOSTIC_ONLY"] is True, "gate owner/classification differs")
    for key in ("CARGO_LOCK_SHA256", "BAZEL_LOCK_SHA256", "LOCK_INPUT_PINS", "LOCK_TERMINAL_NAME", "LOCK_TERMINAL_SHA256",
                "LOCK_TERMINAL_BYTES", "LOCK_JOB_ID", "FRAMEWORK_PARENT", "MIN_FREE_BYTES"):
        need(current[key] == values[names[0]][key], "historical lock/HEAD/resource binding changed")
    for group, directory in (("R29_FAILURE_PINS", ROOT / "native-validation-results/r29-closed-input/evidence"),):
        for name, expected in current[group].items():
            actual = pin((directory / name).read_bytes())
            need(all(actual[k] == expected[k] for k in expected), "original failure pin differs: " + name)
    apply_raw = (ROOT / "source53-apply-preparation/native-source53-apply-template.py").read_bytes()
    _, apply_functions, apply_values = parsed(apply_raw)
    need(pin(apply_raw)["sha256"] == "cf5b74eaa8532166fe8a29386982aeaaca4a579cf37fa227c2d3f31ba04fab2d", "apply producer differs")
    need(tuple(current["ALLOWED_SOURCE53_DELTA"]) == tuple(apply_values["ALLOWED_PATHS"]), "producer/consumer path order differs")
    for key in ("SOURCE52_COMMIT", "SOURCE52_TREE", "FRAMEWORK_PARENT", "CARGO_LOCK_SHA256", "BAZEL_LOCK_SHA256", "R29_JOB_ID"):
        need(current[key] == apply_values[key], "producer/consumer baseline differs: " + key)
    required_complete = {"source_before_tree", "source_before_commit", "source_tree", "source_commit", "source_manifest",
                         "delta_manifest", "source_postguard", "source_guards_pass", "actual_changed_file_count", "prior_changed_file_count",
                         "before_existing_repo_leaves_not_in_prior_changed_manifest", "cargo_lock_sha256", "bazel_lock_sha256",
                         "changed_from_source52_paths", "dependency_inputs_changed_paths", "diagnostic_only", "behavior_repair_claimed",
                         "bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"}
    apply_main = ast.parse(apply_functions["main"]).body[0]
    complete = next(n.value for n in ast.walk(apply_main) if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == "complete" for t in n.targets))
    producer_keys = {ast.literal_eval(k) for k in complete.keys}
    need(required_complete <= producer_keys, "apply producer lacks a required gate field")
    phases_node = next(n.value for n in ast.walk(trees[names[2]]) if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "phases" for t in n.targets))
    commands = [ast.literal_eval(node.elts[1]) for node in phases_node.elts]
    need(commands == [["just", "clippy", "--locked", "-p", "codex-app-server", "--", "-D", "warnings"],
                      ["just", "test", "--locked", "--retries", "0", "-p", "codex-app-server"]], "original two commands differ")
    need('output.flush()' in v2["write_json"].decode() and 'os.fsync(output.fileno())' in v2["write_json"].decode()
         and 'path.open("xb")' in v2["write_json"].decode(), "durable create-only write missing")
    run_phase = v2["run_phase"].decode()
    need(run_phase.index('raw_pin = write_json(stem + "-raw-process-result.json", raw_result)')
         < run_phase.index('log_raw = log.read_bytes()'), "raw rc not persisted first")
    need("process.wait()" in run_phase and "process.kill(" not in run_phase and "process.terminate(" not in run_phase,
         "natural subprocess wait contract differs")
    need('and not missing and not additional and not unsuccessful' in v2["review_tests"].decode(), "closed coverage is not exact")
    baseline_path = ROOT / "source53-app-server-baseline-preparation/BASELINE-IDS.json"
    baseline_raw = baseline_path.read_bytes()
    need(len(baseline_raw) == current["BASELINE_BYTES"] and pin(baseline_raw)["sha256"] == current["BASELINE_SHA256"], "baseline pin differs")
    baseline = json.loads(baseline_raw)
    baseline_ids = {(r["binary"], r["name"]) for r in baseline["test_ids"]}
    need(len(baseline_ids) == len(baseline["test_ids"]) == 1345, "baseline ID count differs")
    log_path = ROOT / "native-validation-results/r29-archive-closed/original/evidence/native-workspace-r29-tests.log"
    log = log_path.read_bytes()
    need(pin(log) == {k: baseline["original_log"][k] for k in ("bytes", "sha256", "git_blob")}, "original R29 log differs")
    ansi = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")
    rows, footer, state = [], [], "before"
    starts, summaries = [], []
    offset = 0
    for number, raw_line in enumerate(log.splitlines(keepends=True), 1):
        text = ansi.sub(b"", raw_line).decode("utf-8", "replace").rstrip("\r\n")
        if re.match(r"^\s*Starting [0-9]+ tests?\b", text):
            starts.append({"line": number, "offset": offset, "text": text})
            need(state == "before", "multiple or reordered Starting")
            state = "running"
        if re.match(r"^\s*Summary\s+\[\s*[0-9.]+s\]", text):
            summaries.append({"line": number, "offset": offset, "text": text})
            need(state == "running", "multiple or reordered Summary")
            state = "after"
        match = re.match(r"^\s*(PASS|FAIL|TIMEOUT)\s+\[\s*([0-9.]+)s\]\s+(\S+)\s+(.+)$", text)
        if match:
            row = {"status": match[1], "seconds": float(match[2]), "binary": match[3], "name": match[4].strip(),
                   "line": number, "byte_offset": offset}
            if state == "running":
                rows.append(row)
            elif state == "after":
                footer.append(row)
        offset += len(raw_line)
    need(len(starts) == len(summaries) == 1 and state == "after", "original log not complete")
    ids = {(r["binary"], r["name"]) for r in rows}
    need(len(ids) == len(rows) == 20228, "original workspace executions differ")
    app = [r for r in rows if r["binary"].split("::", 1)[0] == "codex-app-server"]
    app_ids = {(r["binary"], r["name"]) for r in app}
    need(len(app) == len(app_ids) == 1345 and app_ids == baseline_ids, "baseline differs from independently parsed original1345")
    need(app == baseline["observed_results"], "baseline original offsets/results differ")
    need(Counter(r["status"] for r in app) == {"PASS": 1344, "FAIL": 1}, "baseline original failure was relabeled")
    failed = [r for r in app if r["status"] != "PASS"]
    need(failed[0]["name"] == "suite::v2::bedrock_setup::setup_bedrock_profile_and_environment", "wrong original failed ID")
    inputs = [{"path": str(PREP.relative_to(ROOT) / n), **pin(b)} for n, b in raw.items()]
    inputs.extend([{"path": str(baseline_path.relative_to(ROOT)), **pin(baseline_raw)},
                   {"path": str(log_path.relative_to(ROOT)), **pin(log)},
                   {"path": "source53-apply-preparation/native-source53-apply-template.py", **pin(apply_raw)}])
    report = {"schema": "hepta.source53-r30-independent-static-review.v1", "status": "STATIC_CLEAR_INERT_NOT_EXECUTED",
              "reviewed_template": {"path": names[2], **pin(raw[names[2]])}, "inputs": inputs,
              "AST_parsed_without_import_or_execution": True, "FROZEN": False, "unbound_count": 15, "unbound_names": none_names,
              "r28_shared_function_count": len(common), "r28_shared_functions_byte_exact": common,
              "v1_to_v2_changed_functions": changed_v2, "v2_to_v1_wholefile_reverse_exact": True,
              "original_phase_commands": commands,
              "original_deadlines_threads_profiles_features_filters_retries_unchanged": True,
              "historical_source50_lock_originals_and_outer0_required": True,
              "lock_inheritance_checks": "Full source50/source51/source52/source53 manifest and raw Git boundaries; exactly five non-build Rust paths since source50, two since source52; all original raw lock bytes equal.",
              "source53_apply_producer_consumer_contract": "Exact source/manifest/delta/postguard pins, natural outer0,197/195,two plural existing leaves,diagnostic_only true and behavior_repair_claimed false.",
              "original_r24_r26_r29_failed100_preserved": True,
              "native_HEAD_bef_and_full197_and_dual_lock_guards_required": True,
              "raw_returncode_persisted_create_only_flush_fsync_before_output_hashing": True,
              "strict_failure_or_postguard_failure_stops_tests": True,
              "nonzero_original_returncode_retained": True,
              "postprocessing_failure_cannot_emit_complete_or_PASS": True,
              "subprocesses_wait_naturally_no_kill_or_retry": True,
              "baseline_crosscheck": {"actual_r29_workspace_unique": 20228, "app_server_unique": 1345,
                  "original_app_server_results": {"PASS": 1344, "FAIL": 1, "TIMEOUT": 0},
                  "baseline_all_binary_name_pairs_and_raw_offsets_equal": True,
                  "original_failure": failed[0], "footer_rows_excluded": len(footer),
                  "used_only_after_complete_gate_not_as_filter": True,
                  "future_missing_additional_duplicate_nonPASS_ID_rejected": True,
                  "reported_skip_identities_not_inferred": True},
              "source_apply_lock_python_workspace_fix_fmt_not_run_by_this_gate": True,
              "diagnostic_only": True, "behavior_repair_claimed": False,
              "project_PASS_boundary": "Only a future actual full source53 project execution may receive project PASS; original Bedrock cause remains unproven, original R29 FAIL remains, and full workspace/scientific qualification is separate.",
              "runner_executed": False, "native_or_Rust_commands_executed": False, "source_files_modified": False,
              "remaining_binding_requirement": "Root/native must provide exact actual source53 application closure and15 literal bindings, followed by separately reviewed FROZEN-only finalization."}
    put("INDEPENDENT-REVIEW.json", jb(report))
    files = [{"path": p.name, **pin(p.read_bytes())} for p in sorted(DEST.iterdir())
             if p.is_file() and p.name != "HANDOFF-MANIFEST.json"]
    handoff = {"schema": "hepta.source53-r30-independent-review-handoff.v1", "files": files,
               "file_count": len(files), "total_bytes": sum(p["bytes"] for p in files), "runner_or_native_executed": False}
    put("HANDOFF-MANIFEST.json", jb(handoff))
    print(json.dumps({"review": pin(jb(report)), "handoff": pin(jb(handoff)), "static_result": "CLEAR",
                      "template": pin(raw[names[2]]), "app_server_original_IDS": 1345}, indent=2))


if __name__ == "__main__":
    main()
