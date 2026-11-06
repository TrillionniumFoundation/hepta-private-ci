"""Offline evidence/static review only; never imports or executes an exporter."""
from pathlib import Path
import ast
import builtins
import gzip
import hashlib
import json
import symtable

ROOT = Path("/workspace/scratch/08f5efd48967")
OUT = ROOT / "r31-export-native-independent-review"


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def read(name):
    return (ROOT / name).read_bytes()


def functions(raw):
    source = raw.decode()
    tree = ast.parse(source)
    return tree, {
        node.name: ast.get_source_segment(source, node)
        for node in tree.body if isinstance(node, ast.FunctionDef)
    }


def literals(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                result[node.targets[0].id] = ast.literal_eval(node.value)
            except (TypeError, ValueError):
                pass
    return result


template_name = "source53-r31-export-preparation/export-r31-closed-template.py"
raw = read(template_name)
assert len(raw) == 77450 and pin(raw)["sha256"] == "0a0b60ec209527b03cf54a7d7566409c9714aca13c4423fc8ef9dd0cc88be910"
tree, current = functions(raw)
r30_raw = read("r30-export-preparation/export-r30-closed-template.py")
r31_raw = read("source53-r31-binding/native-run-r31.py")
r30_tree, previous = functions(r30_raw)
r31_tree, producer = functions(r31_raw)
common_r30 = ["require", "sha", "data_pin", "safe_relative", "check_pin", "stable_read", "git",
              "natural_terminal", "source_guard", "recorded_guard", "clean_lines", "check_bindings", "write_new"]
common_r31 = ["review_tests", "review_python", "verify_inherited_guard",
              "review_inherited_tests", "review_original_workspace", "review_workspace"]
assert all(current[name] == previous[name] for name in common_r30)
assert all(current[name] == producer[name] for name in common_r31)
values = literals(tree)
assert values["FROZEN"] is False
assert all(values[name] is None for name in ("TERMINAL_PIN", "CLOSED_ORIGINAL_PINS", "CONTROLLER_ORIGINAL_PINS"))
contract = json.loads(read("native-validation-results/r31-export-contract/CONTRACT.json"))
for key, field in [("COMMIT", "source_commit"), ("TREE", "source_tree"), ("JOB_ID", "job_id"),
                   ("JOB_KEY", "key"), ("PREFIX", "prefix"), ("COMMAND", "workspace_command"),
                   ("METADATA_COMMAND", "metadata_command")]:
    assert values[key] == contract[field]
assert values["R29_WORKSPACE_BASELINE_INPUT_PINS"] == contract["old_workspace_baseline_pins"]
assert values["RUNNER_PIN"] == pin(r31_raw)
suffix_node = next(n for n in tree.body if isinstance(n, ast.Assign)
                   and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "SUCCESS_SUFFIXES")
suffixes = set(ast.literal_eval(suffix_node.value.args[0]))
assert len(suffixes) == 18
assert {values["PREFIX"] + suffix for suffix in suffixes} == set(contract["successful_originals"])
table = symtable.symtable(raw.decode(), template_name, "exec")
defined = {s.get_name() for s in table.get_symbols()}
unknown = set()
def check_symbols(scope):
    for symbol in scope.get_symbols():
        if symbol.is_global() and symbol.is_referenced() and symbol.get_name() not in defined | set(dir(builtins)) | {"__name__"}:
            unknown.add(symbol.get_name())
    for child in scope.get_children():
        check_symbols(child)
check_symbols(table)
assert not unknown, unknown
subprocess_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "subprocess"]
assert len(subprocess_calls) == 1 and subprocess_calls[0].func.attr == "check_output"
assert "allowlist" in current["git"]

pre_raw = read("native-validation-results/r31-start-closed/evidence/native-workspace-r31-preconditions.json")
env_raw = read("native-validation-results/r31-start-closed/evidence/native-workspace-r31-environment.json")
pre, env = json.loads(pre_raw), json.loads(env_raw)
assert pre["source_commit"] == env["source_commit"] == values["COMMIT"]
assert pre["source_tree"] == env["source_tree"] == values["TREE"]
assert pre["diagnostic_only"] is True and pre["behavior_repair_claimed"] is False
assert pre["workspace_test_command"] == values["COMMAND"]
assert env["outer_timeout_seconds_contract"] == 9600
prior_rows = []
for kind, folder, key, prefix, phases, packages in [
    ("r30", "r30-closed-input", "r30_closed_gate_readback", "native-source53-project-r30",
     ["strict", "tests"], ["codex-app-server"]),
    ("r28", "r28-closed-input", "source52_r28_historical_project_gate", "native-source52-project-r28",
     ["python-runner", "strict", "tests"], ["codex-cli", "codex-exec-server", "codex-network-proxy", "codex-external-agent-migration"]),
]:
    proof = pre[key]
    pinned = {x["path"]: x for x in proof["originals"]}
    assert len(pinned) == (19 if kind == "r30" else 26)
    for name, expected in pinned.items():
        observed = read("native-validation-results/" + folder + "/evidence/" + name)
        assert pin(observed) == {k: expected[k] for k in ("bytes", "sha256", "git_blob")}, name
    phase_argv = {}
    args = [value for package in packages for value in ("-p", package)]
    for phase in phases:
        receipt = json.loads(read("native-validation-results/" + folder + "/evidence/" + prefix + "-" + phase + "-receipt.json"))
        expected = (
            ["python3", "-m", "unittest", "discover", "-s", "scripts", "-p", "test_run_nextest*.py", "-v"]
            if phase == "python-runner" else
            ["just", "clippy", "--locked", *args, "--", "-D", "warnings"]
            if phase == "strict" else
            ["just", "test", "--locked", *args, "--retries", "0"]
            if kind == "r28" else ["just", "test", "--locked", "--retries", "0", *args]
        )
        assert receipt["command"] == expected
        assert receipt["exit_code"] == receipt["effective_exit_code"] == 0 and receipt["phase_pass"] is True
        phase_argv[phase] = receipt["command"]
    prior_rows.append({"kind": kind, "source_tree": proof["source_tree"],
                       "original_count": len(pinned), "all_raw_pins_match": True, "phase_commands": phase_argv})

metadata_raw = gzip.decompress(read("source53-final-scope-preparation/input/native-workspace-r31-metadata.json.gz"))
scope_raw = read("source53-final-scope-preparation/input/native-workspace-r31-scope.json")
metadata, scope = json.loads(metadata_raw), json.loads(scope_raw)
receipt = json.loads(read("native-validation-results/r31-start-closed/evidence/native-workspace-r31-metadata-receipt.json"))
assert receipt["stdout"] == pin(metadata_raw) and receipt["exit_code"] == 0
members, defaults = metadata["workspace_members"], metadata["workspace_default_members"]
packages = {x["id"]: x for x in metadata["packages"]}
assert len(members) == len(defaults) == 193 and set(members) == set(defaults)
assert scope["workspace_members"] == [{"id": x, "name": packages[x]["name"], "manifest_path": packages[x]["manifest_path"]} for x in members]
assert scope["workspace_default_members"] == [{"id": x, "name": packages[x]["name"]} for x in defaults]
assert scope["metadata"] == {"path": "native-workspace-r31-metadata.json", **pin(metadata_raw)}
assert scope["source_commit"] == values["COMMIT"] and scope["source_tree"] == values["TREE"]

report = {
    "schema": "hepta.r31-export-independent-static-review.v1",
    "conclusion": "STATIC_CLEAR_REMAINS_INERT",
    "exporter": {"path": template_name, **pin(raw)},
    "r30_reference": pin(r30_raw),
    "actual_r31_producer": pin(r31_raw),
    "common_r30_helpers_byte_exact": common_r30,
    "common_r31_parser_guard_functions_byte_exact": common_r31,
    "ast_and_symbol_table_pass": True,
    "undefined_global_references": sorted(unknown),
    "successful_original_set_exact": contract["successful_originals"],
    "unknown_future_maps_preserved": ["TERMINAL_PIN", "CLOSED_ORIGINAL_PINS", "CONTROLLER_ORIGINAL_PINS"],
    "current_closed_startup": {"preconditions": pin(pre_raw), "environment": pin(env_raw),
                               "metadata": pin(metadata_raw), "scope": pin(scope_raw)},
    "prior_actual_raw_originals_rehashed": prior_rows,
    "manual_review": [
        "Current 197 raw source, index, native HEAD and dual locks are checked before and after; read files are rehashed before create-only archive.",
        "R30 source53 strict/full actual 19 originals remain distinct from historical source52 R28 26 originals; historical argv order was compared with original receipts.",
        "Four original R29 complete baseline files are preserved and reparsed; exact20228 is an acceptance condition after the original unfiltered command.",
        "Actual current metadata is rebuilt in original ID order; its fresh raw result and receipt are checked against R30's natural terminal time.",
        "Raw test exit, receipt effective exit and original controller exit stay distinct. Missing originals or compilation without Starting/Summary retain null accounting and readback_errors.",
        "Successful closure requires exactly18 actual originals, complete, natural outer0 and exact full PASS. Failure branches use only actual existing originals and retain incomplete/error.",
        "Controller chunks use next_offset-offset, size >= next_offset, hex/text identity and contiguous reconstructed totals; eof is not treated as job termination.",
        "All new preserve/readback/export functions were read in full. Archive success is explicitly distinct from engineering qualification, and diagnostic_only remains true.",
    ],
    "candidate_imported_or_executed": False,
    "rust_metadata_formatter_or_native_source_action": False,
    "active_r31_log_read_by_this_review": False,
    "execution_authorized": False,
}
encoded = (json.dumps(report, indent=2) + "\n").encode()
with (OUT / "INDEPENDENT-REVIEW.json").open("xb") as stream:
    stream.write(encoded)
print(json.dumps({"report": "r31-export-native-independent-review/INDEPENDENT-REVIEW.json", **pin(encoded)}))
