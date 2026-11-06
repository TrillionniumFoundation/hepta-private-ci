"""Read-only AST/byte review of an inert runner; never import or execute it."""
from pathlib import Path
import ast
import copy
import difflib
import hashlib
import json


ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent
PREP = ROOT / "source53-finalize-preparation"


def pin(raw):
    return {
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest(),
    }


def read(path):
    raw = (ROOT / path).read_bytes()
    return raw, {"path": path, **pin(raw)}


def write(name, value):
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    with (OUT / name).open("xb") as stream:
        stream.write(raw)
    return {"path": name, **pin(raw)}


def parse(raw):
    text = raw.decode("utf-8")
    tree = ast.parse(text)
    funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert len(funcs) == sum(isinstance(node, ast.FunctionDef) for node in tree.body)
    return text, tree, funcs


def source(text, node):
    return ast.get_source_segment(text, node)


def named_calls(node, name):
    return sorted(
        (call for call in ast.walk(node) if isinstance(call, ast.Call)
         and isinstance(call.func, ast.Name) and call.func.id == name),
        key=lambda call: (call.lineno, call.col_offset),
    )


def literal_assignments(tree):
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def dict_items(node):
    return {key.value: value for key, value in zip(node.keys, node.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)}


def schema_dict(functions, function, schema, phase=None):
    matches = []
    for node in ast.walk(functions[function]):
        if not isinstance(node, ast.Dict):
            continue
        fields = dict_items(node)
        actual = fields.get("schema")
        if not isinstance(actual, ast.Constant) or actual.value != schema:
            continue
        if phase is not None:
            actual_phase = fields.get("phase")
            if not isinstance(actual_phase, ast.Constant) or actual_phase.value != phase:
                continue
        matches.append(node)
    assert len(matches) == 1, (function, schema, phase, len(matches))
    return matches[0]


class ScopeStem(ast.NodeTransformer):
    """Only expand the producer's known metadata filename expression."""
    def visit_BinOp(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.op, ast.Add) and isinstance(node.left, ast.Name)
                and node.left.id == "stem" and isinstance(node.right, ast.Constant)
                and node.right.value == ".json"):
            return ast.BinOp(left=ast.Name(id="PREFIX", ctx=ast.Load()), op=ast.Add(),
                             right=ast.Constant(value="-metadata.json"))
        return node


class IgnoreClassificationOnly(ast.NodeTransformer):
    """Compare known finalization control flow, preserving all operational AST."""
    def visit_Constant(self, node):
        if isinstance(node.value, str):
            return ast.Constant(value=node.value.replace("source52", "source53"))
        return node

    def visit_Dict(self, node):
        node = self.generic_visit(node)
        pairs = [(key, value) for key, value in zip(node.keys, node.values)
                 if not (isinstance(key, ast.Constant)
                         and key.value in ("diagnostic_only", "behavior_repair_claimed"))]
        node.keys = [key for key, _ in pairs]
        node.values = [value for _, value in pairs]
        return node


def normalized(node):
    return ast.dump(IgnoreClassificationOnly().visit(copy.deepcopy(node)), include_attributes=False)


def main():
    handoff_raw = (PREP / "HANDOFF-MANIFEST.json").read_bytes()
    handoff = json.loads(handoff_raw)
    assert handoff["classification"] == "FROZEN_TEXT_INERT_EXECUTION_BLOCKED_PENDING_REAL_INPUTS"
    assert handoff["FROZEN"] is False and handoff["unknown_binding_count"] == 35
    listed = handoff["files"]
    assert len(listed) == handoff["listed_file_count"] == 28
    assert len({row["path"] for row in listed}) == len(listed)
    for row in listed:
        path = Path(row["path"])
        assert not path.is_absolute() and ".." not in path.parts
        target = PREP / path
        assert target.is_file() and not target.is_symlink()
        assert pin(target.read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
    assert sum(row["bytes"] for row in listed) == handoff["listed_bytes"]

    paths = {
        "finalizer": "source53-finalize-preparation/native-finalize-source53-template.py",
        "r31": "source53-r31-preparation/native-run-r31-template.py",
        "r30": "source53-native-gates-preparation/native-run-r30-template-v2.py",
        "old_finalizer": "source52-finalize-preparation/native-finalize-source52-template-v2.py",
    }
    expected = {
        "finalizer": (174038, "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d"),
        "r31": (124806, "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6"),
        "r30": (60715, "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b"),
        "old_finalizer": (129529, "4e2685dc36f5d714ee0b859394a775f8c93f35f33fe1ef2549e5d40dcc90ea2f"),
    }
    inputs, parsed = {}, {}
    for key, path in paths.items():
        raw, inputs[key] = read(path)
        assert (len(raw), inputs[key]["sha256"]) == expected[key]
        parsed[key] = parse(raw)
    text, tree, functions = parsed["finalizer"]
    constants = literal_assignments(tree)
    unknown = sorted(name for name, value in constants.items() if value is None)
    assert len(unknown) == 35 and constants["FROZEN"] is False
    assert constants["DIAGNOSTIC_ONLY"] is True
    assert constants["COMMAND"] == ["just", "test", "--locked", "--retries", "0"]
    assert constants["METADATA_COMMAND"] == ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"]
    assert constants["EXPECTED_WORKSPACE_MEMBER_COUNT"] == 193
    assert constants["FRAMEWORK_PARENT"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
    assert constants["R28_PREFIX"] == "native-source52-project-r28"
    assert constants["R30_PREFIX"] == "native-source53-project-r30"
    assert constants["PREFIX"] == "native-workspace-r31"

    shared = {}
    for key in ("r31", "r30", "old_finalizer"):
        other_text, _, other_funcs = parsed[key]
        identical = sorted(name for name in functions.keys() & other_funcs.keys()
                           if source(text, functions[name]) == source(other_text, other_funcs[name]))
        shared[key] = identical
    assert len(shared["r31"]) == 44 and len(shared["r30"]) == 27
    critical_old = ["final_write", "create_final_bytes", "working_file_pin",
                    "frozen_context_check", "indexed_source_check", "stage_phase_changes"]
    assert set(critical_old) <= set(shared["old_finalizer"])
    normalized_functions = ["snapshot_indexed_source", "mutation_guard", "preserve_failed_source", "run_final_phase"]
    for name in normalized_functions:
        assert normalized(functions[name]) == normalized(parsed["old_finalizer"][2][name]), name

    patch_raw = (PREP / "source52-source53-finalizer.patch").read_bytes()
    regenerated = "".join(difflib.unified_diff(
        parsed["old_finalizer"][0].splitlines(keepends=True), text.splitlines(keepends=True),
        fromfile="source52/native-finalize-source52-template-v2.py",
        tofile="source53/native-finalize-source53-template.py",
    )).encode()
    assert regenerated == patch_raw

    producer = parsed["r31"][2]
    consumer = functions["r31_prerequisite"]
    interfaces = {
        "env_record": ("run_frozen", "hepta.source53-workspace-environment.v1", None),
        "pre": ("run_frozen", "hepta.source53-workspace-preconditions.v1", None),
        "meta_result": ("capture_metadata", "hepta.native-raw-process-result.v1", "workspace-metadata"),
        "meta_receipt": ("capture_metadata", "hepta.native-metadata-receipt.v1", None),
        "scope": ("capture_metadata", "hepta.source53-current-default-workspace-scope.v1", None),
        "raw_result": ("run_workspace", "hepta.native-raw-process-result.v1", "workspace-tests"),
        "receipt": ("run_workspace", "hepta.native-workspace-gate-receipt.v2", None),
        "complete": ("run_workspace", "hepta.source53-default-workspace-complete.v1", None),
    }
    field_checks = []
    for variable, (function, schema, phase) in interfaces.items():
        generated = schema_dict(producer, function, schema, phase)
        fields = dict_items(generated)
        accessed = sorted({node.slice.value for node in ast.walk(consumer)
                           if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                           and node.value.id == variable and isinstance(node.slice, ast.Constant)
                           and isinstance(node.slice.value, str)})
        assert set(accessed) <= set(fields), (variable, set(accessed) - set(fields))
        field_checks.append({"consumer": variable, "producer_function": function,
                             "producer_line": generated.lineno, "schema": schema,
                             "phase": phase, "literal_accessed_fields": accessed,
                             "producer_fields": sorted(fields), "missing_fields": []})
    produced_scope = schema_dict(producer, "capture_metadata", "hepta.source53-current-default-workspace-scope.v1")
    expected_scope = schema_dict(functions, "r31_prerequisite", "hepta.source53-current-default-workspace-scope.v1")
    assert ast.dump(ScopeStem().visit(copy.deepcopy(produced_scope)), include_attributes=False) == ast.dump(expected_scope, include_attributes=False)

    main_body = functions["main"].body
    assert isinstance(main_body[0], ast.Expr) and isinstance(main_body[0].value, ast.Call)
    assert isinstance(main_body[0].value.func, ast.Name) and main_body[0].value.func.id == "check_final_bindings"
    assert "sys.flags.optimize == 0" in source(text, functions["check_source_bindings"])
    assert "PYTHONOPTIMIZE" in source(text, functions["check_source_bindings"])
    assert "require(FROZEN is True" in source(text, functions["check_source_bindings"])
    assert all(name not in functions for name in ("capture_metadata", "run_workspace", "run_frozen", "run_phase"))
    subprocess_calls = []
    for name, function in functions.items():
        for call in ast.walk(function):
            if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "subprocess"):
                subprocess_calls.append({"function": name, "line": call.lineno,
                                         "expression": source(text, call)})
    assert {item["function"] for item in subprocess_calls} == {"git", "stage_phase_changes", "run_final_phase"}
    assert len(subprocess_calls) == 3
    forbidden_calls = [(node.lineno, node.func.attr) for node in ast.walk(tree)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and node.func.attr in ("terminate", "kill", "killpg")]
    assert not forbidden_calls
    phase = functions["run_final_phase"]
    phase_text = source(text, phase)
    assert phase_text.index('raw_pin = final_write(label + "-raw-process-result.json"') < phase_text.index('log.read_bytes()')
    assert phase_text.index('raw_pin = final_write(label + "-raw-process-result.json"') < phase_text.index('announce({**raw_result')
    assert phase_text.index('raw_pin = final_write(label + "-raw-process-result.json"') < phase_text.index('mutation_guard(')
    assert 'if rc == 0 and not issues:' in phase_text
    assert 'after_tree, after_files, stage_pin = None, None, None' in phase_text
    final_write_text = source(text, functions["final_write"])
    assert final_write_text.index('path.open("xb")') < final_write_text.index('output.write(raw)') < final_write_text.index('output.flush()') < final_write_text.index('os.fsync(output.fileno())')
    calls = named_calls(functions["run_finalization"], "run_final_phase")
    assert len(calls) == 2 and [ast.literal_eval(call.args[0]) for call in calls] == ["fix", "format"]
    assert ast.dump(calls[0].args[1], include_attributes=False) == ast.dump(ast.parse('scope["fix_command"]', mode="eval").body, include_attributes=False)
    assert ast.literal_eval(calls[1].args[1]) == ["just", "fmt"]
    snapshots = named_calls(functions["run_finalization"], "snapshot_indexed_source")
    assert len(snapshots) == 3
    assert [ast.literal_eval(call.args[1]) for call in snapshots] == ["tested-pre-fix-source", "post-fix-source", "final-post-format-source"]

    parent_raw, parent_pin = read("source53-finalize-preparation/references/source52-parent-source-manifest.json")
    actual_raw, actual_pin = read("source53-finalize-preparation/references/source53-registered-source-manifest.json")
    parent, actual = json.loads(parent_raw), json.loads(actual_raw)
    before = {row["path"]: row for row in parent["changed_files"]}
    after = {row["path"]: row for row in actual["changed_files"]}
    assert len(before) == len(parent["changed_files"]) == 195
    assert len(after) == len(actual["changed_files"]) == 197
    assert all(after[path] == row for path, row in before.items())
    added = sorted(after.keys() - before.keys())
    assert added == sorted(constants["ALLOWED_SOURCE53_DELTA"])
    assert sum(path.endswith(".rs") for path in after) == 183
    assert len(after) - sum(path.endswith(".rs") for path in after) == 14
    primary_raw, primary_pin = read("source53-finalize-preparation/references/unchanged-34-primary-source-pins.json")
    assert {key: primary_pin[key] for key in ("bytes", "sha256")} == constants["PRIMARY_SOURCE_PINS_IDENTITY"]
    primary = json.loads(primary_raw)
    assert isinstance(primary, list) and len(primary) == 34 and len({row["path"] for row in primary}) == 34
    assert len([row for row in primary if row["path"].endswith("/Cargo.toml") and row["path"] != "original/codex-rs/Cargo.toml"]) == 26
    assert not set(added) & {row["path"].removeprefix("original/") for row in primary}

    result = {
        "schema": "hepta.source53-finalizer-independent-static-mechanical.v1",
        "classification": "STATIC_ONLY_NO_RUNNER_EXECUTION",
        "template": inputs["finalizer"], "input_scripts": inputs,
        "reviewed_handoff": {"path": "source53-finalize-preparation/HANDOFF-MANIFEST.json", **pin(handoff_raw)},
        "handoff_listed_files_verified": len(listed), "handoff_listed_bytes_verified": handoff["listed_bytes"],
        "ast_parse_pass": True, "FROZEN": False, "unknown_binding_count": len(unknown), "unknown_bindings": unknown,
        "byte_identical_functions": shared,
        "critical_old_helpers_byte_identical": critical_old,
        "old_finalization_operational_ast_equal_after_schema_and_classification_only_normalization": normalized_functions,
        "exact_diff_regeneration": {"path": "source53-finalize-preparation/source52-source53-finalizer.patch", **pin(patch_raw)},
        "r31_producer_consumer_literal_field_checks": field_checks,
        "r31_scope_dictionary_expression_equal_after_only_known_filename_stem_expansion": True,
        "separate_closure_file_counts": {"current_r30": 19, "current_r31": 18, "historical_source52_r28": 26},
        "original_natural_outer_terminal_required_for_each_current_gate": True,
        "subprocess_call_sites": subprocess_calls, "no_test_or_metadata_executor_function_copied": True,
        "no_kill_or_terminate_calls": True,
        "phase_order": ["fix", "format"], "snapshots": ["tested-pre-fix-source", "post-fix-source", "final-post-format-source"],
        "raw_result_durable_write_before_announce_output_hashing_or_postguard": True,
        "source_manifest_static_derivation": {
            "parent_manifest": parent_pin, "source53_manifest": actual_pin,
            "old195_rows_all_unchanged": True, "only_added_paths": added,
            "changed_paths": 197, "rust_paths": 183, "other_paths": 14,
            "unchanged_primary_pins": primary_pin, "primary_pin_count": 34, "owning_manifest_count": 26,
            "fresh_r31_metadata_generated_or_claimed": False,
            "future_fresh_scope_must_still_be_bound_and_recomputed": True,
        },
        "tool_inventory": {"future_source53_schema_required": True, "old_source51_inventory_is_historical_only": True,
                           "current_inventory_generated_or_claimed": False},
        "rust_native_metadata_finalizer_formatter_git_or_network_executed": False,
        "runner_imported_or_executed": False,
        "authorization_to_run": False,
    }
    output = write("MECHANICAL-READBACK.json", result)
    print(json.dumps(output))


if __name__ == "__main__":
    main()
