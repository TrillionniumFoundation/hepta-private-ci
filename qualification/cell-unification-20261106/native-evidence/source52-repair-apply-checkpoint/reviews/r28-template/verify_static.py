"""Static review only: parse bytes/AST and closed evidence; never import a runner."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
PREP = ROOT / "source52-native-gates-preparation"


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def read(path):
    raw = (ROOT / path).read_bytes()
    return raw, {"path": path, **pin(raw)}


def emit(name, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path = OUT / name
    if path.exists():
        assert path.read_bytes() == raw, f"immutable report differs: {name}"
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": name, **pin(raw)}


def patch_one(raw, patch, reverse=False):
    source = raw.decode().splitlines(keepends=True)
    lines = patch.decode().splitlines(keepends=True)
    out = []
    cursor = 0
    i = 2
    assert lines[0].startswith("--- ") and lines[1].startswith("+++ ")
    while i < len(lines):
        m = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n", lines[i])
        assert m, repr(lines[i])
        start = int(m[3] if reverse else m[1]) - 1
        expected_consumed = int((m[4] if reverse else m[2]) or 1)
        expected_added = int((m[2] if reverse else m[4]) or 1)
        assert start >= cursor
        out.extend(source[cursor:start])
        cursor = start
        i += 1
        consumed = added = 0
        while i < len(lines) and not lines[i].startswith("@@ "):
            prefix, text = lines[i][0], lines[i][1:]
            assert prefix in " +-", repr(lines[i])
            if reverse:
                prefix = {"+": "-", "-": "+", " ": " "}[prefix]
            if prefix in " -":
                assert cursor < len(source) and source[cursor] == text
                cursor += 1
                consumed += 1
            if prefix in " +":
                out.append(text)
                added += 1
            i += 1
        assert consumed == expected_consumed and added == expected_added
    out.extend(source[cursor:])
    return "".join(out).encode()


def functions(raw):
    text = raw.decode()
    module = ast.parse(text)
    return module, {
        node.name: ast.get_source_segment(text, node)
        for node in module.body if isinstance(node, ast.FunctionDef)
    }


old_raw, old_pin = read("source52-native-gates-preparation/source51-r26-reviewed-template.py")
new_raw, new_pin = read("source52-native-gates-preparation/native-run-r28-template.py")
patch_raw, patch_pin = read("source52-native-gates-preparation/r26-r28-inert.patch")
assert new_pin["bytes"] == 53959 and new_pin["sha256"] == "2b8eb323a6072e37892802bf62d1ed4ddb38d07d4829a562093ac27a68c9edcb"
assert old_pin["bytes"] == 46300 and old_pin["sha256"] == "f89ecbf2fe8585b739c3ecc5cb5057b762473ba73a7fea9dd6483213d3f8a6a0"
assert patch_one(old_raw, patch_raw) == new_raw
assert patch_one(new_raw, patch_raw, reverse=True) == old_raw
old_mod, old_functions = functions(old_raw)
new_mod, new_functions = functions(new_raw)
unchanged = sorted(k for k in old_functions if old_functions[k] == new_functions.get(k))
changed = sorted(k for k in old_functions if k in new_functions and old_functions[k] != new_functions[k])
added = sorted(set(new_functions) - set(old_functions))
removed = sorted(set(old_functions) - set(new_functions))
assert len(unchanged) == 21 and len(changed) == 8
assert added == ["r26_failed_prerequisite"] and not removed
assert old_functions["review_tests"].replace("hepta.source51-four-package-closed-readback.v1", "hepta.source52-four-package-closed-readback.v1") == new_functions["review_tests"]
assert old_functions["guard"].replace('result["actual_tree"] == EXPECTED_TREE\n', 'result["actual_tree"] == EXPECTED_TREE\n            and result["native_head"] == FRAMEWORK_PARENT\n') == new_functions["guard"]
imports = lambda mod: [ast.dump(n, include_attributes=False) for n in mod.body if isinstance(n, (ast.Import, ast.ImportFrom))]
assert imports(old_mod) == imports(new_mod)

values = {}
for node in new_mod.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        try:
            values[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass
contract_raw, contract_pin = read("source52-native-gates-preparation/INPUT-CONTRACT.json")
contract = json.loads(contract_raw)
assert values["FROZEN"] is False
unknown = contract["source52_actual_bindings"]
assert len(unknown) == 15 and all(values[k] is None for k in unknown)
assert values["PACKAGES"] == ["codex-cli", "codex-exec-server", "codex-network-proxy", "codex-external-agent-migration"]
assert values["SOURCE51_CHANGED_COUNT"] == 194 and values["BASELINE_COUNT"] == 1564

def phase_ast(mod):
    fn = next(n for n in mod.body if isinstance(n, ast.FunctionDef) and n.name == "run_frozen")
    return ast.dump(next(n.value for n in ast.walk(fn) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "phases" for t in n.targets)), include_attributes=False)

assert phase_ast(old_mod) == phase_ast(new_mod)
main = next(n for n in new_mod.body if isinstance(n, ast.FunctionDef) and n.name == "main")
assert isinstance(main.body[0], ast.Expr) and isinstance(main.body[0].value, ast.Call) and main.body[0].value.func.id == "check_bindings"

handoff_raw, handoff_pin = read("source52-native-gates-preparation/HANDOFF-MANIFEST.json")
handoff = json.loads(handoff_raw)
for row in handoff["files"]:
    assert pin((PREP / row["path"]).read_bytes()) == {k: row[k] for k in ("bytes", "sha256", "git_blob")}

failure_inputs = []
failure_values = {}
for name, expected in values["R26_FAILURE_PINS"].items():
    local_name = "terminal-process-status.json" if name.endswith("terminal-process-status.json") else name
    raw, actual = read("native-validation-results/r26-failure-closed/" + local_name)
    assert actual["bytes"] == expected["bytes"] and actual["sha256"] == expected["sha256"]
    failure_inputs.append({"native_name": name, **actual})
    failure_values[name] = json.loads(raw)
terminal = failure_values["native-source51-project-r26-terminal-process-status.json"]
raw_result = failure_values["native-source51-project-r26-tests-raw-process-result.json"]
receipt = failure_values["native-source51-project-r26-tests-receipt.json"]
post = failure_values["native-source51-project-r26-tests-source-post-verification.json"]
assert terminal["job_id"] == values["R26_JOB_ID"] and terminal["state"] == "failed" and terminal["exit_code"] == 100
assert all(terminal[k] is False for k in ("timed_out", "cancelled", "automatic_retry"))
assert all(terminal[k] is True for k in ("output_complete", "output_durable", "terminal_publication_confirmed"))
assert all(v is False for v in terminal["log_truncated"].values()) and all(v is None for v in terminal["log_errors"].values())
for k in ("command", "cwd", "source_tree", "source_commit", "phase", "exit_code", "start_unix", "end_unix"):
    assert raw_result[k] == receipt[k]
assert raw_result["exit_code"] == receipt["effective_exit_code"] == post["gate_exit_code"] == 100
assert receipt["phase_pass"] is False and receipt["source_guards_pass"] is True and post["pass"] is True
assert post["actual_tree"] == post["expected_tree"] == values["SOURCE51_TREE"]
assert post["changed_file_count"] == 194 and post["native_head"] == values["FRAMEWORK_PARENT"]
assert terminal["at_unix_ms"] / 1000 >= receipt["end_unix"]

apply_raw, apply_pin = read("source52-apply-preparation/native-source52-apply-template.py")
apply_mod = ast.parse(apply_raw.decode())
complete_dicts = []
for node in ast.walk(apply_mod):
    if isinstance(node, ast.Dict):
        literals = {k.value: v.value for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)}
        if literals.get("schema") == "hepta.source52-apply-complete.v1":
            complete_dicts.append(node)
assert len(complete_dicts) == 1
complete_keys = sorted(k.value for k in complete_dicts[0].keys)
required_complete = {
    "source_before_tree", "source_before_commit", "source_tree", "source_commit", "source_manifest", "delta_manifest", "source_postguard",
    "source_guards_pass", "actual_changed_file_count", "prior_changed_file_count", "before_existing_repo_leaf_not_in_prior_changed_manifest",
    "cargo_lock_sha256", "bazel_lock_sha256", "changed_from_source51_paths", "dependency_inputs_changed_paths",
    "bazel_lock_update_executed", "rust_executed", "fix_fmt_executed",
}
assert required_complete <= set(complete_keys)

mechanical = {
    "schema": "hepta.source52-r28-independent-mechanical.v1",
    "scope": "Local Python AST/bytes/closed JSON only; no runner import or execution.",
    "base": old_pin, "template": new_pin, "patch": patch_pin,
    "forward_patch_exact": True, "inverse_patch_exact": True,
    "unchanged_functions": unchanged, "changed_functions_manually_read_in_full": changed,
    "new_functions_manually_read_in_full": added, "removed_functions": removed,
    "imports_unchanged": True, "phase_command_ast_exact": True,
    "review_tests_change": "schema label only", "guard_change": "additional native HEAD == framework parent requirement only",
    "frozen": False, "unknown_bindings": unknown,
    "preparation_handoff": handoff_pin, "handoff_files_verified": len(handoff["files"]),
    "input_contract": contract_pin, "r26_closed_inputs_verified": failure_inputs,
    "apply_template": apply_pin, "apply_complete_keys": complete_keys,
    "runner_executed": False, "rust_executed": False, "native_written": False,
}
mechanical_pin = emit("MECHANICAL-READBACK.json", mechanical)
review = {
    "schema": "hepta.source52-r28-independent-static-review.v1",
    "verdict": "STATIC_CLEAR_PENDING_ACTUAL_BINDINGS_AND_AUTHORIZATION",
    "reviewed_template": new_pin, "mechanical_readback": mechanical_pin,
    "findings": [
        "All 194 source51 changed rows must remain identical in the 195-row source52 manifest; runtime.rs alone is added to the changed-file set, while its original source50/source51 Git leaf is independently checked as an existing 100644 file.",
        "The source51-to-source52 actual Git diff must contain only runtime.rs. The source50-to-source52 diff must contain exactly the old two reviewed Rust leaves plus runtime.rs; build.rs, mode changes, other paths and either raw-lock change are rejected.",
        "The original source50 lock result remains attributed to its original commit/tree. No new source52 Bazel invocation or qualification is asserted. Git diff and all old manifest rows jointly constrain dependency-input inheritance.",
        "The apply52 complete/postguard/delta interfaces match the separately prepared apply executor. Current source/manifest, natural outer0, postguard pins, 194-to-195 count, unchanged dual locks and apply-only scope are required before any gate.",
        "All four pinned r26 historical failure files match the locally recovered original bytes. Natural outer100, raw100, receipt100, phase_pass=false and the source51 guard remain historical failure evidence, never source52 qualification.",
        "The pre-binding barrier is outside the main try block and uses explicit require, FROZEN=False and Python optimization rejection. Fifteen actual source/apply bindings remain None. No gate executes from this template as frozen.",
        "The original Python32, four-package strict and complete four-package tests commands and their cwd AST are unchanged. The 21 common functions, including environment, raw return persistence, natural wait, source guards, Python parser and baseline loader, are byte-identical to the reviewed r26 template.",
        "The tests parser changes only its schema label. Unique execution rows are bounded by Starting and Summary; repeated footer rows are excluded. All 1564 historical IDs must execute PASS after the full unfiltered command, while reported skips retain their original aggregate-only meaning.",
        "Failure or source mismatch stops subsequent phases, retains the source, and cannot emit a successful complete. The runner performs no apply/stage/Bazel/fix/fmt or workspace gate; r29 requires separate future closure and authorization.",
    ],
    "limitations": [
        "This is static review of the unbound inert template, not execution or final binding approval.",
        "The future actual source52 commit/tree/manifest and apply complete/terminal/delta originals must still replace all 15 None constants and undergo independent exact binding review.",
        "The current r26 project result remains FAILED100; no r28, r29 or final fix/fmt pass is claimed.",
    ],
    "blockers_found": [], "native_commands_run": [], "source_files_changed": [],
}
report_pin = emit("INDEPENDENT-REVIEW.json", review)
files = []
for path in sorted(OUT.iterdir()):
    if path.is_file() and path.name != "HANDOFF-MANIFEST.json":
        files.append({"path": path.name, **pin(path.read_bytes())})
handoff_out = emit("HANDOFF-MANIFEST.json", {"schema": "hepta.artifact-handoff.v1", "kind": "independent-static-review-only", "files": files, "file_count": len(files), "total_bytes": sum(x["bytes"] for x in files)})
print(json.dumps({"report": report_pin, "handoff": handoff_out, "unchanged_function_count": len(unchanged), "changed_function_count": len(changed), "new_function_count": len(added), "runner_executed": False}, ensure_ascii=False, indent=2))
