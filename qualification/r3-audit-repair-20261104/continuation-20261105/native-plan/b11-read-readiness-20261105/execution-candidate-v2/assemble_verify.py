"""Compose frozen source proposals without executing the product or runner."""

import ast
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import yaml


ROOT = Path(__file__).resolve().parent
V1 = ROOT.parent / "execution-candidate-v1"
RUST = ROOT.parent
ARCH = Path("architecture-audit/b11-acl-repair-20261105/counterfactual-workflow-v3").resolve()
CONTROL = ".github/scripts/run_b11_acl_identity_counterfactual.py"
RUNNER = ".github/scripts/run_b11_read_acl_readiness.py"
OLD_PIN = "25def4386ea08bb72a7605cc113117f31fffcd1b"
NEW_PIN = "3680db31233e47ba7fad99f31a7019c4536288bb"


def identity(body):
    return {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            "blob": hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()}


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def save(name, value):
    write(ROOT / name, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def patch(rows):
    result = []
    for row in rows:
        path, before, after = row["path"], row["before"], row["after"]
        result.append(f"diff --git a/{path} b/{path}\n")
        if before is None:
            result.append("new file mode 100644\n")
        result.append(f"index {identity(before)['blob'] if before is not None else '0'*40}..{identity(after)['blob']}" + (" 100644\n" if before is not None else "\n"))
        result.extend(difflib.unified_diff((before or b"").decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
                                         fromfile=f"a/{path}" if before is not None else "/dev/null", tofile=f"b/{path}"))
    return "".join(result).encode()


def source_rows(rows):
    return [{"path": row["path"], "cohort": row["cohort"],
             "preimage": identity(row["before"]) if row["before"] is not None else None,
             "postimage": identity(row["after"]),
             "local_preimage": str(ROOT / "source" / row["path"]) if row["before"] is not None else None,
             "local_postimage": str(ROOT / "candidate" / row["path"])} for row in rows]


v1_map = json.loads((V1 / "source-map.json").read_text())
execution = []
for row in v1_map["files"]:
    before = Path(row["local_preimage"]).read_bytes() if row["preimage"] is not None else None
    after = Path(row["local_postimage"]).read_bytes()
    assert identity(after) == row["postimage"]
    if row["path"] == RUNNER:
        assert after.count(OLD_PIN.encode()) == 1
        old_runner = after
        after = after.replace(OLD_PIN.encode(), NEW_PIN.encode())
    execution.append({"path": row["path"], "before": before, "after": after, "cohort": "execution-v2"})

rust_map = json.loads((RUST / "source-map.json").read_text())
rust_rows = []
for index, row in enumerate(rust_map["files"]):
    before = Path(row["local_preimage"]).read_bytes() if row["preimage"] is not None else None
    after = Path(row["local_postimage"]).read_bytes()
    assert identity(after) == row["postimage"]
    if before is not None:
        assert identity(before) == row["preimage"]
        original = json.loads((ROOT / "originals" / f"api-readiness-preimage-{index}.json").read_text())["structuredContent"]
        assert original["sha"] == row["preimage"]["blob"] and original["content"].encode() == before
    rust_rows.append({"path": row["path"], "before": before, "after": after, "cohort": "readiness-rust-0a80"})
directory = json.loads((ROOT / "originals/api-readiness-preimage-2.json").read_text())["structuredContent"]
directory_entries = json.loads(directory["content"])
assert not any(row["name"] == "read_acl_mutex_tests.rs" for row in directory_entries)

control_before = (ARCH / "source" / CONTROL).read_bytes()
control_after = (ARCH / "candidate" / CONTROL).read_bytes()
assert identity(control_before)["blob"] == OLD_PIN
assert identity(control_after)["blob"] == NEW_PIN
assert control_before == (V1 / "source" / CONTROL).read_bytes()
control_row = {"path": CONTROL, "before": control_before, "after": control_after, "cohort": "counterfactual-v3-3680"}
all_rows = rust_rows + execution + [control_row]
assert len({row["path"] for row in all_rows}) == len(all_rows) == 7
for row in all_rows:
    if row["before"] is not None:
        write(ROOT / "source" / row["path"], row["before"])
    write(ROOT / "candidate" / row["path"], row["after"])

new_runner = next(row["after"] for row in execution if row["path"] == RUNNER)
write(ROOT / "v1-to-v2-consumer-pin.delta.patch", patch([
    {"path": RUNNER, "before": old_runner, "after": new_runner}]))
write(ROOT / "execution.patch", patch(execution))
write(ROOT / "combined-seven-paths.patch", patch(all_rows))
save("source-map.json", {"base_head": v1_map["base_head"], "base_tree": v1_map["base_tree"], "files": source_rows(execution),
                         "required_readiness_patch": v1_map["required_readiness_patch"], "required_control_postimage": identity(control_after)})
save("combined-source-map.json", {"base_head": v1_map["base_head"], "base_tree": v1_map["base_tree"], "files": source_rows(all_rows)})

def functions(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body
            if isinstance(node, ast.FunctionDef) and node.name != "main"}

assert functions(control_before.decode()) == functions(control_after.decode())
assert new_runner == old_runner.replace(OLD_PIN.encode(), NEW_PIN.encode())
for row in execution:
    if row["path"] != RUNNER:
        assert row["after"] == (V1 / "candidate" / row["path"]).read_bytes()
for row in [*execution, control_row]:
    if row["path"].endswith(".py"):
        compile(ast.parse(row["after"]), row["path"], "exec")
workflow = next(row for row in execution if row["path"].endswith(".yml"))
yaml.load(workflow["after"], Loader=yaml.BaseLoader)

commands = []
def run_git(directory, arguments):
    argv = ["git", "-c", "core.autocrlf=false", *arguments]
    result = subprocess.run(argv, cwd=directory, capture_output=True, check=False)
    commands.append({"argv": argv, "cwd": str(directory), "exit_code": result.returncode,
                     "stdout": result.stdout.decode(), "stderr": result.stderr.decode()})
    assert result.returncode == 0


with tempfile.TemporaryDirectory(prefix="b11-readiness-combined-v2-", dir=ROOT) as temporary:
    isolated = Path(temporary)
    run_git(isolated, ["init", "-q"])
    for row in all_rows:
        if row["before"] is not None:
            write(isolated / row["path"], row["before"])
    stages = [RUST / "read-readiness.patch", V1 / "execution.patch", ROOT / "v1-to-v2-consumer-pin.delta.patch", ARCH / "full.patch"]
    stage_rows = []
    for stage in stages:
        run_git(isolated, ["apply", "--check", str(stage)])
        run_git(isolated, ["apply", str(stage)])
        stage_rows.append({"path": str(stage), **identity(stage.read_bytes())})
    for row in all_rows:
        assert (isolated / row["path"]).read_bytes() == row["after"]
    combined = ROOT / "combined-seven-paths.patch"
    run_git(isolated, ["apply", "--reverse", "--check", str(combined)])
    run_git(isolated, ["apply", "--reverse", str(combined)])
    for row in all_rows:
        actual = isolated / row["path"]
        assert (actual.read_bytes() == row["before"]) if row["before"] is not None else not actual.exists()
    run_git(isolated, ["apply", "--check", str(combined)])
    run_git(isolated, ["apply", str(combined)])
    for row in all_rows:
        assert (isolated / row["path"]).read_bytes() == row["after"]

def counts(path):
    lines = path.read_text().splitlines()
    return {"added": sum(line.startswith("+") and not line.startswith("+++") for line in lines),
            "deleted": sum(line.startswith("-") and not line.startswith("---") for line in lines)}


combined_counts = counts(ROOT / "combined-seven-paths.patch")
assert sum(combined_counts.values()) < 500
receipt = {"status": "STATIC_COMPOSITION_PASSED_NO_PRODUCT_EXECUTION", "observed_at_utc": datetime.now(timezone.utc).isoformat(),
           "checks": {"V1_files_unchanged": True, "only_consumer_pin_changes_from_V1": True,
                      "all_9_control_non_main_functions_byteequal": list(functions(control_after.decode())),
                      "helper_consumes_same_terminal_and_restore_interfaces": True,
                      "fixed_0f_readiness_preimages_actual_API_equal": True, "new_Rust_test_absent_in_fixed_0f_directory": True,
                      "workflow_and_collector_exactly_V1_posts": True, "python_ast_compile_only_and_yaml_parse": True,
                      "four_stage_real_git_check_apply_matches_seven_posts": True,
                      "combined_real_reverse_check_reverse_check_apply_matches_seven_posts": True},
           "stages": stage_rows, "git_commands": commands,
           "execution_counts": counts(ROOT / "execution.patch"), "consumer_pin_delta_counts": counts(ROOT / "v1-to-v2-consumer-pin.delta.patch"),
           "combined_counts": combined_counts,
           "combined_patch": identity((ROOT / "combined-seven-paths.patch").read_bytes()),
           "not_executed": ["new helper runner", "V3 counterfactual", "Windows", "Cargo", "Bazel", "shell workflow"],
           "external_review_of_V3_control": "c4ff565c7d003890d6ad42420ec18e802053f467"}
save("static-composition-verification.json", receipt)
print(json.dumps({"static": identity((ROOT / "static-composition-verification.json").read_bytes()),
                  "execution": identity((ROOT / "execution.patch").read_bytes()),
                  "delta": identity((ROOT / "v1-to-v2-consumer-pin.delta.patch").read_bytes()),
                  "combined": identity((ROOT / "combined-seven-paths.patch").read_bytes()), "counts": combined_counts,
                  "runner": identity(new_runner)}))
