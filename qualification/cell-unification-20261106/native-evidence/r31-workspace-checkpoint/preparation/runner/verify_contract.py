"""Offline AST/byte/interface review only; never import or execute a runner."""
from pathlib import Path
import ast
import builtins
import hashlib
import json
import symtable

HERE = Path(__file__).resolve().parent
WORK = HERE.parent


def need(value, message):
    if not value:
        raise RuntimeError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def read_module(path):
    raw = path.read_bytes()
    text = raw.decode()
    parsed = ast.parse(text)
    lines = text.splitlines(keepends=True)
    nodes = {node.name: node for node in parsed.body if isinstance(node, ast.FunctionDef)}
    functions = {name: "".join(lines[node.lineno - 1:node.end_lineno]) for name, node in nodes.items()}
    constants = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return raw, text, parsed, nodes, functions, constants


def dictionary_keys(node):
    return {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def assigned_dict(node, name):
    matches = [part.value for part in ast.walk(node) if isinstance(part, ast.Assign)
               and isinstance(part.value, ast.Dict)
               and any(isinstance(target, ast.Name) and target.id == name for target in part.targets)]
    need(len(matches) == 1, "producer dictionary assignment is ambiguous: " + name)
    return dictionary_keys(matches[0])


def output_dict(node, suffix):
    matches = []
    for part in ast.walk(node):
        if not (isinstance(part, ast.Call) and isinstance(part.func, ast.Name)
                and part.func.id == "write_json" and len(part.args) >= 2 and isinstance(part.args[1], ast.Dict)):
            continue
        first = part.args[0]
        if isinstance(first, ast.BinOp) and isinstance(first.right, ast.Constant) and first.right.value == suffix:
            matches.append(part.args[1])
    need(len(matches) == 1, "producer output dictionary is ambiguous: " + suffix)
    return dictionary_keys(matches[0])


def read_keys(node, name):
    return {part.slice.value for part in ast.walk(node) if isinstance(part, ast.Subscript)
            and isinstance(part.value, ast.Name) and part.value.id == name
            and isinstance(part.slice, ast.Constant) and isinstance(part.slice.value, str)}


def main():
    raw, text, parsed, nodes, functions, constants = read_module(HERE / "native-run-r31-template.py")
    producer_raw, _, _, producer_nodes, producer_functions, _ = read_module(HERE / "references/native-run-r30-template-v2.py")
    old_raw, _, _, _, old_functions, _ = read_module(HERE / "references/native-run-r29-actual.py")
    need(pin(raw)["sha256"] == "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6", "r31 candidate changed")
    need(pin(producer_raw)["sha256"] == "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b", "producer changed")
    need(pin(old_raw)["sha256"] == "26bb2c31806895b19410f290e1f20232ee3be2dbe09321e081857dddefac1fa2", "actual r29 changed")
    common = [name for name in producer_functions if name not in {"check_bindings", "run_phase", "run_frozen", "main"}]
    need(len(common) == 27 and all(functions[name] == producer_functions[name] for name in common),
         "r30 common function bytes differ")
    need(functions["check_source_bindings"] == producer_functions["check_bindings"].replace(
        "def check_bindings():", "def check_source_bindings():"), "source checker changed beyond its name")
    symbols = symtable.symtable(text, "native-run-r31-template.py", "exec")
    defined = {item.get_name() for item in symbols.get_symbols()
               if item.is_assigned() or item.is_imported() or item.is_namespace()}
    unknown = []
    def scan(table):
        for item in table.get_symbols():
            if (item.is_global() and item.is_referenced() and item.get_name() not in defined
                    and item.get_name() not in dir(builtins) and item.get_name() != "__name__"):
                unknown.append({"scope": table.get_name(), "name": item.get_name()})
        for child in table.get_children():
            scan(child)
    scan(symbols)
    need(not unknown, "unresolved global names")
    need(constants["FROZEN"] is False and len([key for key, value in constants.items() if value is None]) == 21,
         "inert future bindings changed")
    need(constants["COMMAND"] == ["just", "test", "--locked", "--retries", "0"], "workspace command changed")
    need(constants["METADATA_COMMAND"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
         "fresh metadata command changed")
    need(constants["EXPECTED_WORKSPACE_MEMBER_COUNT"] == 193 and constants["OUTER_TIMEOUT_SECONDS_CONTRACT"] == 9600,
         "workspace scope/budget changed")
    need("output.flush()" in functions["write_json"] and "os.fsync(output.fileno())" in functions["write_json"],
         "durable raw JSON write absent")
    need(functions["write_json"].index("output.write(raw)") < functions["write_json"].index("output.flush()")
         < functions["write_json"].index("os.fsync(output.fileno())") < functions["write_json"].index("return "),
         "raw JSON flush/fsync order differs")
    new_phase_core = functions["run_workspace"].split("    pre = guard(files)\n", 1)[1].split("    acceptance_pin, review = None, None\n", 1)[0]
    old_phase_core = old_functions["run_workspace"].split("    pre = guard(files)\n", 1)[1].split("    acceptance_pin, review = None, None\n", 1)[0]
    need(new_phase_core == old_phase_core, "original command/natural wait/raw-first/postguard core changed")
    need(functions["main"].splitlines()[1].strip().startswith("check_bindings()"), "binding barrier not first")
    need("and not missing and not additional and not unsuccessful" in functions["review_workspace"],
         "workspace exact old ID set acceptance absent")
    need(functions["review_original_workspace"] == old_functions["review_workspace"].replace(
        "def review_workspace(", "def review_original_workspace(").replace(
        "EXPECTED_TREE", "SOURCE52_TREE").replace("EXPECTED_COMMIT", "SOURCE52_COMMIT"),
        "historical full-log parser changed beyond name/source constants")
    consumer = nodes["r30_prerequisite"]
    produced = {
        "raw": assigned_dict(producer_nodes["run_phase"], "raw_result"),
        "receipt": assigned_dict(producer_nodes["run_phase"], "receipt"),
        "pre": output_dict(producer_nodes["run_frozen"], "-preconditions.json"),
        "environment": output_dict(producer_nodes["run_frozen"], "-environment.json"),
        "complete": output_dict(producer_nodes["run_frozen"], "-complete.json"),
    }
    consumed = {name: read_keys(consumer, name) for name in produced}
    dynamic_pre_keys = []
    for part in ast.walk(consumer):
        if (isinstance(part, ast.For) and isinstance(part.target, ast.Tuple)
                and [getattr(item, "id", None) for item in part.target.elts] == ["key", "expected"]
                and isinstance(part.iter, ast.Tuple)):
            dynamic_pre_keys.extend(row.elts[0].value for row in part.iter.elts)
    consumed["pre"].update(dynamic_pre_keys)
    for name in produced:
        need(consumed[name] <= produced[name], "consumer expects absent producer field: " + name + "/" + repr(consumed[name] - produced[name]))
    shared_phase_keys = {"phase", "command", "cwd", "source_tree", "source_commit", "exit_code",
                         "start_unix", "end_unix"}
    need(shared_phase_keys <= produced["raw"] and shared_phase_keys <= produced["receipt"],
         "shared raw/receipt equality fields absent")
    schema_pairs = [
        "hepta.source53-project-preconditions.v1", "hepta.source53-project-environment.v1",
        "hepta.source53-project-gates-complete.v1", "hepta.native-gate-receipt.v2",
        "hepta.native-raw-process-result.v1",
    ]
    for schema in schema_pairs:
        need(schema in functions["r30_prerequisite"] and schema in producer_raw.decode(), "producer/consumer schema differs")
    expected_names = ["native-source53-project-r30" + suffix for suffix in (
        "-environment.json", "-preconditions.json", "-source-pre-verification.json",
        "-source-final-verification.json", "-complete.json")]
    for phase in ("strict", "tests"):
        stem = "native-source53-project-r30-" + phase
        expected_names.extend(stem + suffix for suffix in (
            ".log", "-resources.txt", "-raw-process-result.json", "-receipt.json",
            "-source-pre-verification.json", "-source-post-verification.json"))
    expected_names.extend(("native-source53-project-r30-tests-result-review.json",
                           "native-source53-project-r30-tests-test-results.json"))
    need(len(expected_names) == len(set(expected_names)) == 19, "success-original contract duplicate/count error")
    original_dir = WORK / "native-validation-results/r29-archive-closed/original"
    inherited_originals = {}
    for name, expected in constants["R28_INPUT_PINS"].items():
        data = (original_dir / "input/r28-prerequisites" / name).read_bytes()
        need(len(data) == expected["bytes"] and pin(data)["sha256"] == expected["sha256"], "fixed R28 original mismatch: " + name)
        inherited_originals[name] = json.loads(data) if name.endswith(".json") else None
    need(len(inherited_originals) == 26, "historical R28 contract count differs")
    for phase in ("python-runner", "strict", "tests"):
        stem = "native-source52-project-r28-" + phase
        receipt = inherited_originals[stem + "-receipt.json"]
        need(receipt["source_tree"] == constants["SOURCE52_TREE"]
             and receipt["source_commit"] == constants["SOURCE52_COMMIT"]
             and receipt["exit_code"] == receipt["effective_exit_code"] == 0
             and receipt["source_guards_pass"] is True, "R28 phase/source contract differs")
    for name, expected in constants["R29_WORKSPACE_BASELINE_INPUT_PINS"].items():
        data = (original_dir / "evidence" / name).read_bytes()
        need(len(data) == expected["bytes"] and pin(data)["sha256"] == expected["sha256"], "old workspace baseline pin differs")
    report = {
        "schema": "hepta.source53-r31-producer-consumer-static-readback.v1",
        "template": pin(raw), "actual_r29_runner": pin(old_raw), "r30_producer_v2": pin(producer_raw),
        "actual_local_ast_and_symtable_parse": True, "unbound_global_names": unknown,
        "exact_r30_common_functions": common, "exact_r30_common_function_count": len(common),
        "source_binding_checker_only_renamed": True,
        "original_r29_command_wait_raw_first_and_postguard_core_exact": True,
        "write_json_same_create_only_bytes_then_flush_fsync": True,
        "r30_success_originals": expected_names,
        "r30_terminal_name_contract": "native-source53-project-r30-terminal-process-status.json",
        "producer_fields": {name: sorted(keys) for name, keys in produced.items()},
        "consumer_fields": {name: sorted(keys) for name, keys in consumed.items()},
        "consumer_fields_all_exist_in_exact_producer": True,
        "schema_pairs": schema_pairs, "future_r30_originals_not_fabricated_or_read": True,
        "actual_historical_r28_original_count_and_pins_checked": 26,
        "r28_historical_source52_phase_schema_preserved": True,
        "r29_original_full_log_rows_readback_metadata_pins_checked": True,
        "exact1345_r30_post_gate_and_exact20228_workspace_post_gate": True,
        "actual_commands_never_receive_baseline_ids": True,
        "fresh_current_metadata193_required": True,
        "workspace_command": constants["COMMAND"], "metadata_command": constants["METADATA_COMMAND"],
        "outer_timeout_seconds_contract": constants["OUTER_TIMEOUT_SECONDS_CONTRACT"],
        "frozen": False, "unknown_binding_count": 21,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "qualification": "INERT_STATIC_PREPARATION_ONLY",
        "runner_imported_or_executed": False,
        "native_rust_metadata_formatter_or_git_executed": False,
        "current_or_prior_formal_evidence_modified": False,
    }
    target = HERE / "PRODUCER-CONSUMER-READBACK.json"
    with target.open("xb") as output:
        output.write((json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"report": pin(target.read_bytes()), "contract": "STATIC_CLEAR", "r30_originals": 19,
                      "r28_historical_originals": 26, "r30_same_functions": len(common)}))


if __name__ == "__main__":
    main()
