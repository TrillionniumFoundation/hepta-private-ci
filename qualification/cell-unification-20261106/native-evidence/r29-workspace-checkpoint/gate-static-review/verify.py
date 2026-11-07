#!/usr/bin/env python3
"""Independent offline AST/byte audit; never imports or executes a gate."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

BASE = Path("/workspace/scratch/08f5efd48967")
PREP = BASE / "source52-workspace-gates-preparation"
OUT = BASE / "source52-r29-independent-static-review"

def require(value, message):
    if not value:
        raise ValueError(message)

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def load(name):
    raw = (PREP / name).read_bytes()
    text = raw.decode()
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    functions = {node.name: "".join(lines[node.lineno - 1:node.end_lineno])
                 for node in tree.body if isinstance(node, ast.FunctionDef)}
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return raw, text, tree, functions, constants

def main():
    handoff_raw = (PREP / "HANDOFF-MANIFEST.json").read_bytes()
    handoff = json.loads(handoff_raw)
    for row in handoff["files"]:
        require(pin((PREP / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}, "handoff pin: " + row["path"])
    require(len(handoff["files"]) == 9, "handoff count")
    new, text, tree, nf, constants = load("native-run-r29-template.py")
    r27, oldtext, otree, of, oldconst = load("references/native-run-r27-template.py")
    r28, ptext, ptree, pf, prodconst = load("references/native-run-r28-template.py")
    require(pin(new)["sha256"] == "4b2d2f5a4f3eb33dfa7f3d744f0d2d322e2e1c1697dfbed45d0047f49dd455b9", "r29 pin")
    require(pin(r27)["sha256"] == "38eb6bf07adf3dadfb919a2fce4d83fa9da519d182f9ba2e6a0f1af06da9d389", "r27 pin")
    require(pin(r28)["sha256"] == "2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb", "r28 pin")
    common = ["require", "sha", "data_pin", "safe_relative", "hex_digest", "write_json", "announce",
              "git", "git_paths", "normalized_files", "source_file_pin", "guard", "lock_prerequisite",
              "load_source", "read_fixed", "read_pinned", "closed_terminal", "r24_failed_prerequisite",
              "r26_failed_prerequisite", "inherited_dependency_check", "apply_prerequisite", "load_baseline",
              "execution_environment", "clean_lines", "review_python", "review_tests"]
    require(all(nf[name] == pf[name] for name in common), "a common r28 function changed")
    require(nf["check_source_bindings"] == pf["check_bindings"].replace("def check_bindings():", "def check_source_bindings():", 1), "source checker changed")
    workspace = ["capture_metadata", "review_workspace", "run_workspace", "main"]
    require(all(nf[name] == of[name].replace("source51", "source52") for name in workspace), "original workspace behavior changed")
    require(all(nf[name] == of[name] for name in ("pinned_read", "verify_pointer")), "shared helpers changed")
    extra = '    require(value["native_head"] == FRAMEWORK_PARENT, "recorded native HEAD mismatch: " + label)\n'
    require(nf["verify_recorded_guard"].count(extra) == 1 and nf["verify_recorded_guard"].replace(extra, "") == of["verify_recorded_guard"], "recorded guard changed beyond HEAD check")
    require(constants["FROZEN"] is False, "not inert")
    unknown = sorted(name for name, value in constants.items() if value is None)
    require(len(unknown) == 21, "future-binding count")
    require(constants["COMMAND"] == ["just", "test", "--locked", "--retries", "0"], "workspace command changed")
    require(constants["METADATA_COMMAND"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"], "fresh metadata command changed")
    require(constants["EXPECTED_WORKSPACE_MEMBER_COUNT"] == 193 and constants["OUTER_TIMEOUT_SECONDS_CONTRACT"] == 9600, "workspace contract changed")
    require(constants["PHASES"] == ("python-runner", "strict", "tests"), "r28 phase order")
    # Compare actual producer dictionary keys with every consumer key, without executing either script.
    producer_dicts = {}
    for call in ast.walk(ptree):
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "write_json" and len(call.args) >= 2 and isinstance(call.args[1], ast.Dict)):
            continue
        label = ast.unparse(call.args[0])
        for suffix, target in (("-preconditions.json", "preconditions"), ("-environment.json", "environment"), ("-complete.json", "complete")):
            if suffix in label:
                keys = {k.value for k in call.args[1].keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
                require(target not in producer_dicts, "ambiguous producer dictionary")
                producer_dicts[target] = keys
    consumer = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "r28_prerequisite")
    key_readback = {}
    for name, available in producer_dicts.items():
        used = {node.slice.value for node in ast.walk(consumer)
                if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == name
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)}
        require(used <= available, "r28 missing producer key: " + name + " / " + repr(used - available))
        key_readback[name] = {"consumer_keys": sorted(used), "all_keys_constructed_by_frozen_r28": True}
    require(set(key_readback) == {"preconditions", "environment", "complete"}, "producer scopes missing")
    report = {
        "schema": "hepta.r29-independent-static-review.v1",
        "conclusion": "STATIC_CLEAR_ACTUAL_SUCCESS_BINDINGS_REQUIRED",
        "template": pin(new), "reference_r27": pin(r27), "reference_r28": pin(r28),
        "handoff": pin(handoff_raw), "handoff_original_files_verified": 9,
        "ast_parsed_without_import_or_execution": True,
        "r28_functions_exact": common,
        "r28_source_binding_checker_only_renamed": True,
        "r27_workspace_functions_only_source_schema_or_comment_identity_changed": workspace,
        "recorded_guard_only_adds_native_head_equals_framework_parent": True,
        "actual_r28_producer_consumer_keys": key_readback,
        "frozen": False, "unknown_bindings": unknown,
        "reviewed_boundaries": [
            "FROZEN, missing literal and optimized-Python barriers precede writes and subprocesses.",
            "Same-source r28 three original phase commands require raw rc0, effective rc0, all source and lock guards, original log/resource pins and reproducible Python32/full1564 baseline acceptance.",
            "All26 phase/environment/precondition/complete originals plus an independent natural outer0 terminal are required; original r24/r26 failures remain failed history.",
            "Apply proof independently rechecks source51 194 retained rows plus the existing newly changed runtime leaf, full195, one parent delta, three source50 deltas and unchanged raw dual locks.",
            "r28 source50-parent/apply/source51-parent and original r26 failed-proof keys match their actual frozen producer.",
            "Fresh cargo metadata must prove193 members equal193 defaults before the original no-p workspace command; old metadata is not reused.",
            "Original natural wait and durable raw rc before output hashing/postguards are unchanged; failures cannot emit complete or erase earlier results.",
            "Parser preserves compile-failure null terminal counts and excludes footer duplicates; no baseline is a test filter.",
            "No apply/stage/lock update/fix/fmt/retry or runner execution occurred in this review."
        ],
        "workspace_command": constants["COMMAND"],
        "metadata_command": constants["METADATA_COMMAND"],
        "outer_budget_seconds": 9600,
        "qualification": "PENDING_FUTURE_ACTUAL_R28_SUCCESS_AND_SEPARATE_R29_EXECUTION",
        "native_written": False, "runner_executed": False, "rust_executed": False,
    }
    OUT.mkdir(exist_ok=True)
    raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    with (OUT / "INDEPENDENT-REVIEW.json").open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"path": str((OUT / "INDEPENDENT-REVIEW.json").relative_to(BASE)), **pin(raw)}))

if __name__ == "__main__":
    main()

