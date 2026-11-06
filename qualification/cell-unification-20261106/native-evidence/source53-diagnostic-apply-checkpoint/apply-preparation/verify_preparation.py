#!/usr/bin/env python3
"""Read-only static/data verification of the inert preparation, not its execution."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

DEST = Path(__file__).resolve().parent
ROOT = DEST.parent
UNBOUND = ["EXPECTED_COMMIT", "EXPECTED_TREE", "EXPECTED_CHANGED_COUNT", "INPUT_BYTES", "INPUT_SHA256",
           "SOURCE53_MANIFEST_PIN", "DELTA_MANIFEST_PIN", "CANDIDATE_PINS"]
COMMON = ["require", "pin", "safe_relative", "digest", "validate_pin", "write_new", "write_json", "announce",
          "git", "git_paths", "normalized_files", "source_raw"]


def need(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def jb(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def put(name, raw):
    path = DEST / name
    if path.exists():
        need(path.read_bytes() == raw, "refuse overwrite: " + name)
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return pin(raw)


def functions(raw):
    text = raw.decode()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    return tree, {n.name: "".join(lines[n.lineno - 1:n.end_lineno]).encode()
                  for n in tree.body if isinstance(n, ast.FunctionDef)}


def assignments(tree):
    output = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                output[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return output


def main():
    old = (DEST / "references/native-source52-apply-template.py").read_bytes()
    new = (DEST / "native-source53-apply-template.py").read_bytes()
    need(pin(new)["sha256"] == "cf5b74eaa8532166fe8a29386982aeaaca4a579cf37fa227c2d3f31ba04fab2d", "template changed during review")
    old_ast, old_functions = functions(old)
    new_ast, new_functions = functions(new)
    settings = assignments(new_ast)
    need(settings["FROZEN"] is False and all(settings[n] is None for n in UNBOUND), "inert bindings changed")
    need(sum(v is None for v in settings.values()) == 8, "unexpected unbound field count")
    common = []
    for name in COMMON:
        need(old_functions[name] == new_functions[name], "shared function differs: " + name)
        common.append({"name": name, **pin(new_functions[name])})
    regenerated = "".join(difflib.unified_diff(old.decode().splitlines(keepends=True), new.decode().splitlines(keepends=True),
                                            fromfile="a/native-source52-apply-template.py", tofile="b/native-source53-apply-template.py")).encode()
    need(regenerated == (DEST / "source52-to-source53-template.patch").read_bytes(), "whole-file template diff differs")
    main_node = next(n for n in new_ast.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    first = main_node.body[0]
    need(isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
         and isinstance(first.value.func, ast.Name) and first.value.func.id == "check_bindings", "main does not reject inert state first")
    calls = [node for node in ast.walk(main_node) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == "run_git_phase"]
    calls.sort(key=lambda n: n.lineno)
    need([ast.literal_eval(n.args[0]) for n in calls] == ["apply-check", "apply", "stage-exact-paths"], "Git mutation sequence changed")
    for name in ("system", "exec", "eval", "kill", "terminate", "import_module"):
        forbidden = [n for n in ast.walk(new_ast) if isinstance(n, ast.Call)
                     and ((isinstance(n.func, ast.Name) and n.func.id == name)
                          or (isinstance(n.func, ast.Attribute) and n.func.attr == name))]
        need(not forbidden, "forbidden dynamic/native operation: " + name)
    phase = new_functions["run_git_phase"].decode()
    need(phase.index('write_json(R / (name + "-raw-process-result.json"), raw)')
         < phase.index('pin((R / (name + "-stdout.log")).read_bytes())'), "true return code is not durable before hashing")
    durable = new_functions["write_new"].decode()
    need("os.O_EXCL" in durable and "stream.flush()" in durable
         and "os.fsync(stream.fileno())" in durable and "os.fsync(directory)" in durable, "durable create-only write weakened")
    check = new_functions["check_bindings"].decode()
    need("sys.flags.optimize == 0" in check and "PYTHONOPTIMIZE" in check, "Python optimization rejection absent")
    complete_keys = []
    for node in ast.walk(main_node):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "complete" for t in node.targets):
            need(isinstance(node.value, ast.Dict), "complete is not a literal object")
            complete_keys = [ast.literal_eval(k) for k in node.value.keys]
    required = {"source_before_tree", "source_before_commit", "source_tree", "source_commit", "source_manifest",
                "delta_manifest", "source_postguard", "source_guards_pass", "prior_changed_file_count",
                "actual_changed_file_count", "changed_from_source52_paths", "dependency_inputs_changed_paths",
                "before_existing_repo_leaves_not_in_prior_changed_manifest", "diagnostic_only", "behavior_repair_claimed",
                "cargo_lock_sha256", "bazel_lock_sha256", "bazel_lock_update_executed", "rust_executed", "fix_fmt_executed"}
    need(required <= set(complete_keys), "r30 complete interface missing fields")
    need("before_existing_repo_leaf_not_in_prior_changed_manifest" not in complete_keys, "singular key remained")
    failure_dir = DEST / "references/r29"
    names = {suffix: "native-workspace-r29-" + suffix for suffix in ("terminal-process-status.json", "tests-raw-process-result.json",
             "tests-receipt.json", "source-post-test-verification.json")}
    originals = {suffix: json.loads((failure_dir / name).read_bytes()) for suffix, name in names.items()}
    terminal, raw, receipt, post = (originals[n] for n in names)
    need(terminal["job_id"] == settings["R29_JOB_ID"] and terminal["exit_code"] == raw["exit_code"]
         == receipt["exit_code"] == receipt["effective_exit_code"] == 100, "original failed100 differs")
    need(raw["command"] == receipt["command"] == ["just", "test", "--locked", "--retries", "0"]
         and raw["phase"] == receipt["phase"] == "workspace-tests", "original no-p workspace contract differs")
    need(receipt["source_guards_pass"] and post["pass"] and post["changed_file_count"] == 195
         and post["actual_tree"] == settings["SOURCE52_TREE"] and post["native_head"] == settings["FRAMEWORK_PARENT"], "original baseline source guard differs")
    need(receipt["workspace_member_count"] == receipt["workspace_default_member_count"] == 193
         and receipt["packages_argument"] is None, "original193 scope differs")
    root_proof_raw = (failure_dir / "ROOT-ARCHIVE-READBACK.json").read_bytes()
    root_proof = json.loads(root_proof_raw)
    need(root_proof["original_workspace_exit"] == root_proof["effective_workspace_exit"] == root_proof["original_outer_exit"] == 100
         and root_proof["source_count"] == 195 and root_proof["source_tree"] == settings["SOURCE52_TREE"], "root prior full archive closure differs")
    derived = json.loads((DEST / "MANIFEST-DERIVATION-READBACK.json").read_bytes())
    need(derived["source_count"] == 197 and derived["rust_count"] == 183 and derived["owner_count"] == 26
         and derived["ci_selector_count"] == 27 and derived["actual_Git_payloads_rehashed"] == 18, "derived source scope differs")
    for name in ("build_inert_template.py", "derive_source53_inputs.py", "verify_preparation.py"):
        ast.parse((DEST / name).read_text())
    report = {"schema": "hepta.source53-apply-static-readback.v1", "status": "STATIC_PREPARATION_CLEAR_NOT_EXECUTED",
              "template": pin(new), "reference_template": pin(old), "complete_template_diff": pin(regenerated),
              "AST_passed": True, "runner_imported_or_executed": False,
              "shared_functions_byte_identical": common, "shared_function_count": len(common),
              "FROZEN": False, "unbound_names": UNBOUND, "unbound_count": 8,
              "original_r29_failed100_preserved": True, "original_no_p193_command": raw["command"],
              "original_r29_source_guard_pass": True, "source52_count": 195, "source53_count": 197,
              "root_full_archive_closure_prior_review": pin(root_proof_raw),
              "root_full_archive_proof_scope": "Prior local provenance and root authorization input; this runner does not fabricate or claim a new remote read of the root report.",
              "runtime_four_original_failure_pins": settings["R29_FAILURE_PINS"],
              "two_existing_baseline_leaves_separately_hash_checked": True,
              "old195_full_objects_and_raw_JSON_slices_required": True,
              "seven_regular_member_exact_set_required": True,
              "before_and_after_member_pins_and_patch_inverse_required": True,
              "three_original_git_commands": ["git apply --check <exact candidate.patch>", "git apply <exact candidate.patch>",
                                               "git add -- <exact two reviewed paths>"],
              "raw_git_returncode_create_only_flush_fsync_before_log_hashing": True,
              "live_source_and_both_lock_guards_before_and_after": True,
              "failure_state_and_diff_preserved_no_reset": True,
              "complete_fields": complete_keys,
              "diagnostic_only": True, "behavior_repair_claimed": False,
              "gate_boundary": "A future source53 project PASS describes that actual diagnostic source only. It cannot establish the original timeout cause repaired or substitute for workspace/scientific qualification.",
              "native_apply_executed": False, "Rust_tests_lock_fix_fmt_executed": False,
              "root_final_input_review_and_later_native_binding_required": True}
    put("STATIC-READBACK.json", jb(report))
    files = []
    for path in sorted(DEST.rglob("*")):
        need(not path.is_symlink(), "unexpected symlink in new preparation")
        if path.is_file() and path.name != "HANDOFF-MANIFEST.json":
            files.append({"path": str(path.relative_to(DEST)), **pin(path.read_bytes())})
    handoff = {"schema": "hepta.source53-apply-preparation-handoff.v1", "status": "FROZEN_INERT_PREPARATION_ROOT_REVIEW_INPUT_CANDIDATE",
               "source_before_commit": settings["SOURCE52_COMMIT"], "source_before_tree": settings["SOURCE52_TREE"],
               "actual_source53_commit": derived["source_commit"], "actual_source53_tree": derived["source_tree"],
               "native_source53_application_claimed": False, "diagnostic_only": True, "behavior_repair_claimed": False,
               "FROZEN_in_executor": False, "future_binding_count": 8,
               "file_count": len(files), "total_bytes": sum(f["bytes"] for f in files), "files": files}
    put("HANDOFF-MANIFEST.json", jb(handoff))
    print(json.dumps({"template": pin(new), "static_readback": pin(jb(report)), "handoff": pin(jb(handoff)),
                      "files": len(files), "status": "INERT_STATIC_CLEAR"}, indent=2))


if __name__ == "__main__":
    main()
