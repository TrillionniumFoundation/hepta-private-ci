"""Pure static/byte readback; never import or execute the finalizer or a gate."""
from pathlib import Path
import ast
import builtins
import copy
import hashlib
import json
import symtable

ROOT = Path(__file__).resolve().parent
EXPECTED_TEMPLATE_SHA = "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d"
EXPECTED_R31_SHA = "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6"
EXPECTED_OLD_SHA = "4e2685dc36f5d714ee0b859394a775f8c93f35f33fe1ef2549e5d40dcc90ea2f"


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def read_source(path, expected_sha):
    raw = path.read_bytes()
    require(pin(raw)["sha256"] == expected_sha, str(path) + " identity changed")
    text = raw.decode("utf-8")
    tree = ast.parse(text, filename=str(path))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    require(len(functions) == sum(isinstance(node, ast.FunctionDef) for node in tree.body), "duplicate function")
    return raw, text, tree, functions


def segment(text, functions, name):
    return ast.get_source_segment(text, functions[name])


def dump(node):
    return ast.dump(node, include_attributes=False)


def schema_dict(function, schema):
    matches = []
    for node in ast.walk(function):
        if isinstance(node, ast.Dict):
            values = {key.value: value for key, value in zip(node.keys, node.values)
                      if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if isinstance(values.get("schema"), ast.Constant) and values["schema"].value == schema:
                matches.append(node)
    require(len(matches) == 1, "ambiguous producer schema: " + schema)
    return matches[0]


def keys(node):
    require(all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in node.keys),
            "producer dictionary unexpectedly includes dynamic keys")
    return {key.value for key in node.keys}


def fields_read(function, variable):
    found = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == variable:
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                found.add(node.slice.value)
    # Include fixed-key loops, including (field, expected-file) pointer pairs.
    for loop in ast.walk(function):
        if not isinstance(loop, ast.For) or not isinstance(loop.iter, (ast.Tuple, ast.List)):
            continue
        if isinstance(loop.target, ast.Name):
            loop_name = loop.target.id
            literals = loop.iter.elts
        elif isinstance(loop.target, ast.Tuple) and isinstance(loop.target.elts[0], ast.Name):
            loop_name = loop.target.elts[0].id
            literals = [item.elts[0] for item in loop.iter.elts if isinstance(item, (ast.Tuple, ast.List))]
        else:
            continue
        reads_variable = any(
            isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
            and node.value.id == variable and isinstance(node.slice, ast.Name)
            and node.slice.id == loop_name
            for statement in loop.body for node in ast.walk(statement)
        )
        if reads_variable:
            found.update(item.value for item in literals if isinstance(item, ast.Constant) and isinstance(item.value, str))
    return found


class UndoDiagnosticAndSource(ast.NodeTransformer):
    """Only undo the declared diagnostic output fields and source label."""
    def visit_Dict(self, node):
        pairs = [(key, value) for key, value in zip(node.keys, node.values)
                 if not (isinstance(key, ast.Constant)
                         and key.value in ("diagnostic_only", "behavior_repair_claimed"))]
        node.keys, node.values = [item[0] for item in pairs], [item[1] for item in pairs]
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            node.value = node.value.replace("source53", "source52")
        return node


raw, text, tree, fn = read_source(ROOT / "native-finalize-source53-template.py", EXPECTED_TEMPLATE_SHA)
r31_raw, r31_text, r31_tree, r31_fn = read_source(ROOT / "references/native-run-r31-template.py", EXPECTED_R31_SHA)
old_raw, old_text, old_tree, old_fn = read_source(ROOT / "references/native-finalize-source52-template-v2.py", EXPECTED_OLD_SHA)
mechanical = json.loads((ROOT / "MECHANICAL-READBACK.json").read_bytes())
require(pin(raw) == mechanical["template"], "mechanical report does not bind this template")
for name in mechanical["same_r31_functions"]:
    require(segment(text, fn, name) == segment(r31_text, r31_fn, name), "R31 helper changed: " + name)
require(len(mechanical["same_r31_functions"]) == 44, "shared helper scope differs")
for name in mechanical["same_old_finalizer_functions"]:
    require(segment(text, fn, name) == segment(old_text, old_fn, name), "old finalizer helper changed: " + name)
require(len(mechanical["same_old_finalizer_functions"]) == 6, "old exact helper scope differs")
normalized_old_functions = ["snapshot_indexed_source", "mutation_guard", "preserve_failed_source", "run_final_phase", "main"]
for name in normalized_old_functions:
    restored = UndoDiagnosticAndSource().visit(copy.deepcopy(fn[name]))
    require(dump(restored) == dump(old_fn[name]), "old mutation mechanics changed: " + name)

scope_text = segment(text, fn, "load_final_scope")
scope_inverse = scope_text.replace("source53", "source52").replace("r31", "r29").replace("197", "195").replace("183", "181")
scope_inverse = scope_inverse.replace('        "diagnostic_only": True, "behavior_repair_claimed": False,\n', '')
require(scope_inverse == segment(old_text, old_fn, "load_final_scope"), "scope has an undeclared transformation")
require(segment(text, fn, "verify_default_format_selection").replace("183", "181")
        == segment(old_text, old_fn, "verify_default_format_selection"), "default formatter algorithm changed")
tool_inverse = segment(text, fn, "verify_tools").replace(
    'inventory["schema"] == TOOL_INVENTORY_SCHEMA',
    'inventory["schema"] == "hepta.source51-formatter-readonly-inventory.v1"',
).replace("actual current-source formatter tool inventory source mismatch", "historical formatter tool inventory source mismatch").replace(
    "inventory_bound_to_current_source53_observation", "inventory_not_relabelled_as_source52_observation",
)
require(tool_inverse == segment(old_text, old_fn, "verify_tools"), "tool byte/version/venv checks changed")

assignments = {node.targets[0].id: node.value for node in tree.body
               if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
none_names = sorted(name for name, value in assignments.items() if isinstance(value, ast.Constant) and value.value is None)
require(len(none_names) == 35 and none_names == mechanical["unknown_binding_names"], "future binding list changed")
require(isinstance(assignments["FROZEN"], ast.Constant) and assignments["FROZEN"].value is False, "template is executable")
require(isinstance(fn["main"].body[0], ast.Expr)
        and isinstance(fn["main"].body[0].value, ast.Call)
        and fn["main"].body[0].value.func.id == "check_final_bindings", "main must check before any output")
require(isinstance(fn["check_final_bindings"].body[0], ast.Expr)
        and fn["check_final_bindings"].body[0].value.func.id == "check_bindings", "source and False barriers no longer first")
require("capture_metadata" not in fn and "run_workspace" not in fn and "run_frozen" not in fn,
        "finalizer must not include a gate/metadata executor")
require('require(FROZEN is True' in segment(text, fn, "check_source_bindings")
        and 'sys.flags.optimize == 0' in segment(text, fn, "check_source_bindings"), "inert/optimization barrier changed")

module_symbols = symtable.symtable(text, str(ROOT / "native-finalize-source53-template.py"), "exec")
bound = {symbol.get_name() for symbol in module_symbols.get_symbols()
         if symbol.is_assigned() or symbol.is_imported() or symbol.is_namespace()}
builtin_names = set(dir(builtins)) | {"__name__", "__file__"}
unresolved = []
def inspect_symbols(table):
    for symbol in table.get_symbols():
        if symbol.is_referenced() and symbol.is_global() and symbol.get_name() not in bound | builtin_names:
            unresolved.append([table.get_name(), symbol.get_name()])
    for child in table.get_children():
        inspect_symbols(child)
inspect_symbols(module_symbols)
require(not unresolved, "unresolved globals: " + repr(unresolved))
for node in ast.walk(tree):
    if isinstance(node, ast.Dict):
        literal_keys = [key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
        require(len(literal_keys) == len(set(literal_keys)), "duplicate literal dictionary key")

contracts = [
    ("environment", "run_frozen", "hepta.source53-workspace-environment.v1", "env_record"),
    ("preconditions", "run_frozen", "hepta.source53-workspace-preconditions.v1", "pre"),
    ("metadata_raw", "capture_metadata", "hepta.native-raw-process-result.v1", "meta_result"),
    ("metadata_receipt", "capture_metadata", "hepta.native-metadata-receipt.v1", "meta_receipt"),
    ("scope", "capture_metadata", "hepta.source53-current-default-workspace-scope.v1", None),
    ("workspace_raw", "run_workspace", "hepta.native-raw-process-result.v1", "raw_result"),
    ("workspace_receipt", "run_workspace", "hepta.native-workspace-gate-receipt.v2", "receipt"),
    ("complete", "run_workspace", "hepta.source53-default-workspace-complete.v1", "complete"),
]
contract_readback = []
consumer = fn["r31_prerequisite"]
common_raw_receipt = {"source_tree", "source_commit", "command", "cwd", "exit_code", "start_unix", "end_unix"}
for label, producer_name, schema, variable in contracts:
    producer = schema_dict(r31_fn[producer_name], schema)
    producer_keys = keys(producer)
    consumer_keys = fields_read(consumer, variable) if variable else keys(schema_dict(consumer, schema))
    if label in {"metadata_raw", "metadata_receipt", "workspace_raw", "workspace_receipt"}:
        consumer_keys |= common_raw_receipt
    if label in {"workspace_raw", "workspace_receipt"}:
        consumer_keys.add("phase")
    require(consumer_keys <= producer_keys, "consumer reads absent producer keys: " + label + repr(consumer_keys - producer_keys))
    contract_readback.append({
        "record": label, "schema": schema, "producer_function": producer_name,
        "producer_line": producer.lineno, "producer_keys": sorted(producer_keys),
        "consumer_function": "r31_prerequisite", "consumer_keys_checked": sorted(consumer_keys),
        "missing_keys": [],
    })

# Scope is regenerated in original metadata order, not sorted by the reader.
scope_producer = schema_dict(r31_fn["capture_metadata"], "hepta.source53-current-default-workspace-scope.v1")
scope_consumer = schema_dict(consumer, "hepta.source53-current-default-workspace-scope.v1")
require('stem = PREFIX + "-metadata"' in segment(r31_text, r31_fn, "capture_metadata"),
        "metadata filename producer changed")
scope_producer_text = ast.unparse(scope_producer).replace("stem + '.json'", "PREFIX + '-metadata.json'")
scope_consumer_text = ast.unparse(scope_consumer)
require(scope_producer_text == scope_consumer_text, "fresh scope reconstruction differs from producer")

# Closed originals are a fixed 18-file set, not made up from later snapshots.
suffixes = ast.literal_eval(fn["r31_required_names"].body[0].value.generators[0].iter)
require(len(suffixes) == len(set(suffixes)) == 18, "R31 input population differs")
require("-complete.json" in suffixes and "-tests.log" in suffixes and "-metadata.json" in suffixes,
        "missing successful original inputs")
require('len(R30_INPUT_PINS) == 19' in segment(text, fn, "check_bindings"), "R30 complete original population differs")
require(len(ast.literal_eval(assignments["R28_INPUT_PINS"])) == 26,
        "historical R28 original population differs")

mutation = fn["run_final_phase"]
raw_line = min(node.lineno for node in ast.walk(mutation) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == "final_write"
               and isinstance(node.args[0], ast.BinOp)
               and isinstance(node.args[0].right, ast.Constant)
               and node.args[0].right.value == "-raw-process-result.json")
derived_read_line = min(node.lineno for node in ast.walk(mutation) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == "read_bytes")
require(raw_line < derived_read_line, "derived readback precedes durable original raw result")
require('os.fsync(output.fileno())' in segment(text, fn, "final_write")
        and 'os.fsync(output.fileno())' in segment(text, fn, "write_json"), "durable writes changed")
require('if rc == 0 and not issues:' in segment(text, fn, "run_final_phase"), "failure must not stage")
require('subsequent_phases_allowed' in segment(text, fn, "preserve_failed_source"), "failed state retention missing")
require('"post_source_tree_bound": False' in segment(text, fn, "preserve_failed_source"), "stale index treated as post tree")
run_text = segment(text, fn, "run_finalization")
require(run_text.index("r31_prerequisite(") < run_text.index("run_final_phase("), "mutation before gate proof")
require(run_text.count("run_final_phase(") == 2 and run_text.count("if code:\n        return code") == 2,
        "unexpected phase or failure continuation")
require('"fix", scope["fix_command"]' in run_text and '"format", ["just", "fmt"]' in run_text,
        "original fix/default fmt changed")
require('"qualification_transferred_to_mutated_tree": False' in run_text
        and '"post_fix_or_format_tests_executed": False' in run_text,
        "final tree incorrectly receives tested-source qualification")

literal_commands = []
for node in ast.walk(tree):
    if isinstance(node, (ast.List, ast.Tuple)):
        values = [item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        require("--allow-staged" not in values and "--all" not in values, "extra formatter/fixer flag")
        if values and values[0] in {"just", "cargo", "git", "uv", "rustfmt"}:
            literal_commands.append({"line": node.lineno, "literal_parts": values})

report = {
    "schema": "hepta.source53-finalizer-static-contract-readback.v1",
    "classification": "INERT_PREPARATION_ONLY_NOT_EXECUTION_OR_QUALIFICATION",
    "template": pin(raw), "reference_r31": pin(r31_raw), "reference_finalizer52_v2": pin(old_raw),
    "static_python_ast_and_symtable_executed": True,
    "target_imported_or_executed": False, "synthetic_gate_results_used": False,
    "native_rust_metadata_fix_fmt_git_or_tool_query_executed": False,
    "FROZEN": False, "none_binding_count": len(none_names), "none_bindings": none_names,
    "byte_identical_r31_functions": mechanical["same_r31_functions"],
    "byte_identical_old_finalizer_functions": mechanical["same_old_finalizer_functions"],
    "old_mutation_function_ast_equal_after_only_source_label_and_diagnostic_fields_removed": normalized_old_functions,
    "old_scope_exact_inverse": {"source": "52 to 53", "fresh_metadata": "R29 to R31", "paths": [195, 197],
                                "rust": [181, 183], "owners": [26, 26], "python": [2, 2]},
    "default_HEAD_formatter_selector_exact_except_183_count": True,
    "tool_checks_exact_except_new_current_inventory_binding": True,
    "producer_consumer": contract_readback,
    "scope_dictionary_exact_producer_expression_after_expanding_metadata_filename_stem": True,
    "required_r31_original_suffixes": list(suffixes),
    "successful_r30_original_count": 19, "historical_r28_original_count": 26,
    "all_gate_originals_and_natural_outer_zero_required_before_fix": True,
    "workspace_population_exact_20228_post_execution_only": True,
    "project_population_exact_1345_post_execution_only": True,
    "historical_source52_r28_not_source53_qualification": True,
    "original_R29_R26_R24_failures_retained": True,
    "future_scope_fresh_metadata_and_source53_tools_not_present_or_claimed": True,
    "mutation_raw_write_line": raw_line, "first_derived_output_read_line": derived_read_line,
    "raw_and_json_create_only_flush_fsync_preserved": True,
    "original_fix_26_then_default_fmt_no_after_tests": True,
    "failed_command_or_guard_retains_source_and_stops_next_phase": True,
    "native_HEAD_expected": "bef6fa7645df9df12b69fda499e97eed25de6c75",
    "diagnostic_only": True, "behavior_repair_claimed": False,
    "final_formatted_tree_qualification_transferred": False,
    "literal_command_inventory_for_review_only": literal_commands,
    "unresolved_global_symbols": unresolved, "duplicate_literal_dictionary_keys": [],
}
out = ROOT / "STATIC-CONTRACT-READBACK.json"
payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
with out.open("xb") as stream:
    stream.write(payload)
print(json.dumps({"result": "STATIC_CLEAR", "report": out.name, **pin(payload)}, ensure_ascii=False))
