#!/usr/bin/env python3
"""Offline binding and original apply-closure verification; no target import."""
import ast
import hashlib
import json
from pathlib import Path

BASE = Path("/workspace/scratch/08f5efd48967")
BIND = BASE / "native-validation-results/r28-bound-input"
CLOSED = BASE / "native-validation-results/source52-apply-closed"
E = CLOSED / "evidence"
OUT = BASE / "source52-r28-binding-independent-review"
TEMPLATE = BASE / "source52-native-gates-preparation/native-run-r28-template.py"
COMMIT = "1e0910becc37383e6d17ecf861ea844fd07d8862"
TREE = "211f15baff19095e8c98bcea2b0ed99ca2270ade"
PARENT = "e28b0f385ee882f842911044958b2810f62f6379"
PARENT_TREE = "763c8d2b4089f6e9806c3bbb68fa247bc2f6af36"
HEAD = "bef6fa7645df9df12b69fda499e97eed25de6c75"
LEAF = "codex-rs/network-proxy/src/runtime.rs"

def require(value, message):
    if not value:
        raise ValueError(message)

def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}

def assignments(raw):
    nodes = {}
    for n in ast.parse(raw.decode()).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            require(n.targets[0].id not in nodes, "duplicate constant")
            nodes[n.targets[0].id] = n
    return nodes

def span(raw, node):
    lines = raw.splitlines(keepends=True)
    return (sum(map(len, lines[:node.lineno - 1])) + node.col_offset,
            sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset)

def main():
    inputs = {}
    def read(path):
        raw = path.read_bytes()
        inputs[str(path.relative_to(BASE))] = pin(raw)
        return raw
    template = read(TEMPLATE)
    bound = read(BIND / "native-run-r28-bound.py")
    final = read(BIND / "native-run-r28.py")
    bindings_raw = read(BIND / "ACTUAL-BINDINGS.json")
    bindings = json.loads(bindings_raw)
    require(pin(template)["sha256"] == "2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb", "template pin")
    require(pin(bound) == {"bytes": 54456, "sha256": "721b922a7fb4ee6988f5df2ec45210b4e716d3f94d010615813624cb52c7759a", "git_blob": pin(bound)["git_blob"]}, "bound pin")
    require(len(final) == 54455 and pin(final)["sha256"] == "a7b64eb8ff8ec2b5bc75ae836e3ff423ce31ee86d5c4daf64b7543a8fa7aae9e", "final pin")
    tn, bn, fn = assignments(template), assignments(bound), assignments(final)
    unknown = {name for name, n in tn.items() if isinstance(n.value, ast.Constant) and n.value.value is None}
    require(len(unknown) == 15 and set(bindings) == unknown, "exact fifteen bindings")
    require(ast.literal_eval(tn["FROZEN"].value) is False and ast.literal_eval(bn["FROZEN"].value) is False and ast.literal_eval(fn["FROZEN"].value) is True, "frozen states")
    replacements = []
    for name in unknown:
        require(ast.literal_eval(bn[name].value) == bindings[name], "binding literal: " + name)
        a,b = span(bound,bn[name]); x,y = span(template,tn[name])
        replacements.append((a,b,template[x:y]))
    restored = bound
    for a,b,raw in sorted(replacements,reverse=True):
        restored = restored[:a] + raw + restored[b:]
    require(restored == template, "bound changed beyond fifteen assignments")
    require(bound.count(b"FROZEN = False") == 1 and final == bound.replace(b"FROZEN = False",b"FROZEN = True",1), "final changed beyond one frozen flip")
    require(bindings["EXPECTED_COMMIT"] == COMMIT and bindings["EXPECTED_TREE"] == TREE and bindings["EXPECTED_CHANGED_COUNT"] == 195, "actual source identity")
    originals = {}
    for label in ("APPLY_COMPLETE", "APPLY_TERMINAL", "DELTA_MANIFEST"):
        raw = read(E / bindings[label + "_NAME"])
        require(len(raw) == bindings[label + "_BYTES"] and pin(raw)["sha256"] == bindings[label + "_SHA256"], label + " bound original pin")
        originals[label] = json.loads(raw)
    complete, terminal, delta = (originals[k] for k in ("APPLY_COMPLETE","APPLY_TERMINAL","DELTA_MANIFEST"))
    source_raw = read(E / bindings["SOURCE_MANIFEST_NAME"])
    require(pin(source_raw)["sha256"] == bindings["SOURCE_MANIFEST_SHA256"], "manifest binding")
    require(source_raw == (BASE / "source52-preparation/native-candidate-r28-source.json").read_bytes(), "actual full manifest differs from root input")
    source = json.loads(source_raw)
    require(source["source_commit"] == COMMIT and source["source_tree"] == TREE and source["source_parent_commit"] == PARENT, "manifest identity")
    require(len(source["changed_files"]) == 195 and len({r["path"] for r in source["changed_files"]}) == 195, "full manifest size/duplicate")
    require(complete["schema"] == "hepta.source52-apply-complete.v1" and complete["source_commit"] == COMMIT and complete["source_tree"] == TREE, "complete identity")
    require(complete["source_before_commit"] == PARENT and complete["source_before_tree"] == PARENT_TREE, "complete parent")
    require(complete["source_manifest"] == {"path": bindings["SOURCE_MANIFEST_NAME"], **pin(source_raw)}, "complete manifest pointer")
    delta_raw = (E / bindings["DELTA_MANIFEST_NAME"]).read_bytes()
    require(complete["delta_manifest"] == {"path": bindings["DELTA_MANIFEST_NAME"], **pin(delta_raw)}, "complete delta pointer")
    require(delta_raw == (BASE / "source52-preparation/source52-actual-delta-manifest.json").read_bytes(), "actual delta differs from root input")
    require(complete["source_guards_pass"] is True and complete["prior_changed_file_count"] == 194 and complete["actual_changed_file_count"] == 195, "complete scope")
    require(complete["changed_from_source51_paths"] == [LEAF] and complete["dependency_inputs_changed_paths"] == [], "complete parent delta")
    for key in ("before_existing_repo_leaf_not_in_prior_changed_manifest", "source51_original_changed_manifest_rows_unchanged"):
        require(complete[key] is True, "complete existing leaf proof")
    require(complete["native_git_head"] == HEAD, "complete native HEAD")
    for key in ("bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"):
        require(complete[key] is False, "apply phase scope")
    post_raw = read(E / complete["source_postguard"]["path"])
    require(complete["source_postguard"] == {"path": complete["source_postguard"]["path"], **pin(post_raw)}, "postguard pointer")
    post = json.loads(post_raw)
    require(post["schema"] == "hepta.source52-apply-postguard.v1" and post["pass"] is True, "postguard status")
    require(post["source_commit"] == COMMIT and post["actual_tree"] == post["expected_tree"] == TREE and post["native_head"] == HEAD, "postguard identity")
    require(post["actual_changed_file_count"] == 195 and post["changed_path_set_matches"] is True and set(post["changed_paths"]) == {r["path"] for r in source["changed_files"]}, "postguard full scope")
    require(post["unstaged_paths"] == post["untracked_paths"] == post["file_mismatches"] == [], "postguard residue")
    for key in ("cargo_lock_sha256", "bazel_lock_sha256"):
        require(post[key] == complete[key] == source[key] == ast.literal_eval(tn[key.upper()].value), "dual-lock mismatch")
    require(terminal["job_id"] == bindings["APPLY_JOB_ID"] == "1a1b1e474a3-fc05-7b5b" and terminal["state"] == "succeeded" and terminal["exit_code"] == 0, "outer terminal")
    for key in ("output_complete","output_durable","terminal_publication_confirmed"):
        require(terminal[key] is True, "outer closure")
    for key in ("automatic_retry","cancelled","timed_out"):
        require(terminal[key] is False, "outer non-natural termination")
    require((E / bindings["APPLY_TERMINAL_NAME"]).read_bytes() == read(CLOSED / "controller/terminal-process-status.json"), "terminal original copies differ")
    phase_rcs = {}
    previous_end = None
    for phase, argv in (
        ("apply-check", ["git","apply","--check","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source52-apply/input/candidate.patch"]),
        ("apply", ["git","apply","/home/alex/work/hepta-cell-unified-20261106-a/evidence/native-source52-apply/input/candidate.patch"]),
        ("stage-exact-paths", ["git","add","--",LEAF]),
    ):
        folder = E / "native-source52-apply"
        raw = json.loads(read(folder / (phase + "-raw-process-result.json")))
        receipt = json.loads(read(folder / (phase + "-receipt.json")))
        require(all(receipt[k] == v for k,v in raw.items()), "original raw/receipt mismatch")
        require(raw["command"] == argv and raw["exit_code"] == 0 and raw["wait_exception"] is None, "original Git command/exit")
        require(raw["cwd"] == "/home/alex/work/hepta-cell-unified-20261106-a/source", "original Git cwd")
        require(previous_end is None or raw["started_unix"] >= previous_end, "Git phase ordering")
        previous_end = raw["ended_unix"]
        for stream in ("stdout", "stderr"):
            require(receipt[stream] == pin(read(folder / (phase + "-" + stream + ".log"))), "original Git output pin")
        phase_rcs[phase] = raw["exit_code"]
    require(terminal["at_unix_ms"]/1000 >= previous_end, "outer terminal before original stage end")
    report = {
        "schema": "hepta.source52-r28-binding-independent-review.v1",
        "conclusion": "STATIC_BOUND_AND_FINAL_CLEAR",
        "inputs": inputs,
        "fifteen_literal_values_equal_actual_bound_inputs": True,
        "fifteen_assignment_inverse_restores_entire_reviewed_template": True,
        "final_only_frozen_flip": True,
        "actual_source": {"commit": COMMIT, "tree": TREE, "parent": PARENT, "changed_paths": 195},
        "apply_original_job": terminal["job_id"], "apply_natural_outer_exit": 0,
        "three_original_git_exit_codes": phase_rcs,
        "apply_full_source_postguard_and_dual_locks": "PASS_ORIGINAL_RECEIPT",
        "source52_apply_is_rust_qualification": False,
        "runtime_command_executed_by_reviewer": False,
        "runner_imported_or_executed_by_reviewer": False,
        "r28_terminal_results": None,
        "science": "HOLD", "authority": "DENY_ALL",
    }
    OUT.mkdir(exist_ok=True)
    data = (json.dumps(report,indent=2,sort_keys=True)+"\n").encode()
    with (OUT/"INDEPENDENT-REVIEW.json").open("xb") as f:f.write(data)
    print(json.dumps({"path":str((OUT/"INDEPENDENT-REVIEW.json").relative_to(BASE)),**pin(data)}))
if __name__ == "__main__":
    main()

