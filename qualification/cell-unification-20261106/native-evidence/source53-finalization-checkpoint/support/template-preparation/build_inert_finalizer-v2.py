"""Build the source53 finalizer text/AST only, never execute any runner."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent
OLD = WORK / "source52-finalize-preparation/native-finalize-source52-template-v2.py"
R31 = WORK / "source53-r31-preparation/native-run-r31-template.py"
OLD_SHA = "4e2685dc36f5d714ee0b859394a775f8c93f35f33fe1ef2549e5d40dcc90ea2f"
R31_SHA = "83aa49f02eca55b409d7685f6719765a46de1ccf3bea84f357cd4d352c06fab6"


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def put(path, raw):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as output:
        output.write(raw)
    return {"path": path, **pin(raw)}


def obj(path, value):
    return put(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode())


def change(text, old, new, count=1):
    if text.count(old) != count:
        raise RuntimeError("unexpected source occurrence: " + repr(old))
    return text.replace(old, new)


def module(raw):
    text = raw.decode()
    parsed = ast.parse(text)
    lines = text.splitlines(keepends=True)
    functions = {node.name: "".join(lines[node.lineno - 1:node.end_lineno])
                 for node in parsed.body if isinstance(node, ast.FunctionDef)}
    constants = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return text, parsed, functions, constants


CHECK_FINAL = r'''
def check_final_bindings():
    check_bindings()  # Current source53/apply/R30, False/None/-O barriers first.
    require(isinstance(R31_JOB_ID, str) and bool(R31_JOB_ID)
            and R31_JOB_ID not in (R30_JOB_ID, R29_JOB_ID, R28_JOB_ID, R26_JOB_ID,
                                  APPLY_JOB_ID, LOCK_JOB_ID, R24_JOB_ID),
            "actual separately closed r31 job missing/reused")
    require(R31_TERMINAL_NAME == PREFIX + "-terminal-process-status.json"
            and hex_digest(R31_TERMINAL_SHA256, 64)
            and type(R31_TERMINAL_BYTES) is int and R31_TERMINAL_BYTES > 0,
            "r31 natural terminal pin is missing")
    require(isinstance(R31_INPUT_PINS, dict) and set(R31_INPUT_PINS) == set(r31_required_names())
            and len(R31_INPUT_PINS) == 18, "all18 successful original r31 files required")
    for name, expected in R31_INPUT_PINS.items():
        safe_relative(name)
        require(set(expected) == {"bytes", "sha256"}
                and type(expected["bytes"]) is int and expected["bytes"] >= 0
                and hex_digest(expected["sha256"], 64), "invalid r31 original pin")
        require(not name.startswith(FINALIZATION_DIRECTORY + "/"), "input/output collision")
    require(isinstance(SCOPE_INPUT_PINS, dict) and set(SCOPE_INPUT_PINS) == {
        "EXPECTED-SELECTION.json", "PACKAGE-ARGS.json", "RUST-FILE-COMMANDS.json", "PRIMARY-SOURCE-PINS.json",
    }, "four newly frozen source53/freshR31 scope inputs required")
    for name, expected in SCOPE_INPUT_PINS.items():
        safe_relative(name)
        require(set(expected) == {"bytes", "sha256"} and type(expected["bytes"]) is int
                and expected["bytes"] > 0 and hex_digest(expected["sha256"], 64), "invalid frozen scope pin")
    require(SCOPE_INPUT_PINS["PRIMARY-SOURCE-PINS.json"] == PRIMARY_SOURCE_PINS_IDENTITY,
            "unchanged34 formatter/dependency primary pins differ")
    require(isinstance(FRESH_METADATA_PIN, dict) and set(FRESH_METADATA_PIN) == {"bytes", "sha256", "git_blob"}
            and type(FRESH_METADATA_PIN["bytes"]) is int and FRESH_METADATA_PIN["bytes"] > 0
            and hex_digest(FRESH_METADATA_PIN["sha256"], 64)
            and hex_digest(FRESH_METADATA_PIN["git_blob"], 40), "actual freshR31 metadata pin missing")
    safe_relative(TOOL_INVENTORY_NAME)
    require(type(TOOL_INVENTORY_BYTES) is int and TOOL_INVENTORY_BYTES > 0
            and hex_digest(TOOL_INVENTORY_SHA256, 64), "actual formatter tool inventory pin missing")
    require(TOOL_INVENTORY_SCHEMA == "hepta.source53-formatter-readonly-inventory.v1",
            "new current-source53 read-only inventory schema must be bound")
    require(TOOL_INVENTORY_SOURCE_COMMIT == EXPECTED_COMMIT and TOOL_INVENTORY_SOURCE_TREE == EXPECTED_TREE
            and TOOL_INVENTORY_SOURCE_MANIFEST == {"bytes": SOURCE_MANIFEST_BYTES, "sha256": SOURCE_MANIFEST_SHA256},
            "tool inventory cannot be relabelled from an older source")
    require(EXPECTED_CHANGED_COUNT == 197 and DIAGNOSTIC_ONLY is True,
            "this prepared finalizer is only for diagnostic source53")
'''


PRECONDITIONS_REPLACEMENT = r'''
    require(pre["source_manifest"] == source_pin and pre["r30_closed_gate_readback"] == r30_proof
            and pre["source52_r28_historical_project_gate"] == historical_r28_proof
            and pre["historical_project_pass_substitutes_for_r30"] is False
            and pre["source50_lock_originals_and_outer_terminal"] == lock_pins
            and pre["source50_root_manifest"] == source50_pin
            and pre["source51_historical_manifest"] == source51_pin
            and pre["source52_parent_manifest"] == source52_pin
            and pre["source53_apply"] == apply_proof
            and pre["original_r24_failed_100_provenance"] == r24_failed_pins
            and pre["original_r26_failed_100_provenance"] == r26_failed_pins
            and pre["original_r29_failed_100_provenance"] == r29_failed_pins,
            "r31 prerequisite proof does not match independent full-chain replay")
    require(pre["cargo_lock_sha256"] == CARGO_LOCK_SHA256 and pre["bazel_lock_sha256"] == BAZEL_LOCK_SHA256,
            "r31 precondition locks mismatch")
    require(pre["source50_lock_inherited_only_for_unchanged_dependency_inputs"] is True
            and pre["source53_bazel_lock_update_executed"] is False
            and pre["r25_remains_blocked_and_unexecuted"] is True
            and pre["r27_remains_blocked_and_unexecuted"] is True
            and pre["older_source_results_are_not_qualification_for_this_source"] is True,
            "historical failure or lock inheritance was relabelled")
    require(pre["prior_source52_workspace"] == "FAILED_100_20227_PASS_1_FAIL_0_TIMEOUT_130_REPORTED_SKIP",
            "historical r29 failure changed")
    require(pre["original_r29_workspace_baseline"] == workspace_baseline_proof
            and pre["workspace_baseline_used_as_filter"] is False
            and pre["workspace_baseline_exact_set_required_after_complete_execution"] is True,
            "r31 old identity population must remain post-gate acceptance only")
    for field in ("patch_application_performed", "lock_update_performed", "python_suite_reexecuted",
                  "fix_fmt_executed", "behavior_repair_claimed"):
        require(pre[field] is False, "r31 unexpected mutation or qualification: " + field)
    require(pre["diagnostic_only"] is True and pre["workspace_test_command"] == COMMAND,
            "r31 diagnostic classification/original no-p command changed")
'''


RUN_FINALIZATION = r'''
def run_finalization():
    require(not FINAL_OUTPUT.exists(), "create-only finalization already has evidence; no automatic retry")
    require(shutil.disk_usage(T).free > MIN_FREE_BYTES, "insufficient free space before finalization")
    FINAL_OUTPUT.mkdir(exist_ok=False)
    generated, lock_pins = lock_prerequisite()
    (files, source_pin, source50_files, source50_pin, source51_files,
     source51_pin, source52_files, source52_pin) = load_source(generated)
    require(source_pin["bytes"] == SOURCE_MANIFEST_BYTES, "source manifest byte count differs")
    r24_failed_pins = r24_failed_prerequisite()
    r26_failed_pins = r26_failed_prerequisite()
    r29_failed_pins = r29_failed_prerequisite()
    apply_proof = apply_prerequisite(files, source_pin, source50_files, source51_files, source52_files)
    baseline, baseline_pin = load_baseline()
    r30_proof, prior_environment = r30_prerequisite(
        baseline, source_pin, baseline_pin, lock_pins, source50_pin, source51_pin,
        source52_pin, apply_proof, r24_failed_pins, r26_failed_pins, r29_failed_pins,
    )
    historical_baseline, historical_baseline_pin = load_inherited_baseline()
    historical_apply = historical_source52_apply_prerequisite(source52_pin)
    historical_r28_proof, historical_environment = r28_inherited_prerequisite(
        historical_baseline, source52_pin, historical_baseline_pin, lock_pins,
        source50_pin, source51_pin, historical_apply, r24_failed_pins, r26_failed_pins,
    )
    require(historical_environment["selection"] == prior_environment["selection"]
            and historical_environment["approved_prerequisite_env_pin"]
            == prior_environment["approved_prerequisite_env_pin"],
            "historical r28/current r30 environment or prerequisite inputs differ")
    workspace_baseline, workspace_baseline_proof = load_workspace_baseline()
    r31_proof, metadata, workspace_environment = r31_prerequisite(
        r30_proof, prior_environment, historical_r28_proof, workspace_baseline, workspace_baseline_proof,
        source_pin, lock_pins, source50_pin, source51_pin, source52_pin, apply_proof,
        r24_failed_pins, r26_failed_pins, r29_failed_pins,
    )
    initial = guard(files)
    require(initial["pass"] and initial["native_head"] == FRAMEWORK_PARENT,
            "pre-finalization actual source/HEAD/dual-lock guard failed")
    scope = load_final_scope(metadata, files, r31_proof["fresh_metadata"])
    selection_before = indexed_source_check(EXPECTED_TREE, files, scope)
    env, selection, prerequisite_env_pin = execution_environment()
    require(selection == workspace_environment["selection"]
            and prerequisite_env_pin == workspace_environment["approved_prerequisite_env_pin"],
            "finalizer base environment differs from the successful original workspace gate")
    formatter, tool_proof = verify_tools(env)
    env.update(formatter)  # Only the same three approved task-local formatter keys.
    final_write("preconditions.json", {
        "schema": "hepta.source53-finalization-preconditions.v1",
        "tested_source_commit": EXPECTED_COMMIT, "tested_source_tree": EXPECTED_TREE,
        "source_manifest": source_pin, "native_head": FRAMEWORK_PARENT,
        "source_paths": len(files), "initial_guard": initial,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "source53_apply_and_original_gates": r31_proof, "fresh_metadata_scope": scope,
        "source52_r28_historical_project_gate": historical_r28_proof,
        "historical_project_pass_substitutes_for_r30_or_r31": False,
        "default_formatter_selection": selection_before,
        "tool_readback": tool_proof, "environment_selection": selection,
        "approved_prerequisite_env_pin": prerequisite_env_pin, "formatter_env": formatter,
        "sequence": ["source52 historical r28 retained", "completed source53 r30 app-server",
                     "completed source53 original r31 no-p workspace", "original scoped just fix",
                     "original default just fmt"],
        "post_fix_or_format_tests_executed": False, "no_all_flag_or_HEAD_change": True,
        "no_extra_allow_staged": True,
        "unexpected_scope_or_dependency_change_stops_for_review": True,
        "diagnostic_only": True, "behavior_repair_claimed": False,
    })
    pre = snapshot_indexed_source(EXPECTED_TREE, "tested-pre-fix-source", files, scope)
    code, fixed_tree, fixed_files, fix_receipt = run_final_phase(
        "fix", scope["fix_command"], EXPECTED_TREE, files, scope, env, set(scope["rust_paths"]),
    )
    if code:
        return code
    fixed = snapshot_indexed_source(fixed_tree, "post-fix-source", fixed_files, scope)
    verify_default_format_selection(scope)  # No fallback to --all or a new HEAD.
    code, formatted_tree, formatted_files, format_receipt = run_final_phase(
        "format", ["just", "fmt"], fixed_tree, fixed_files, scope, env,
        set(scope["rust_paths"]) | set(scope["python_paths"]),
    )
    if code:
        return code
    final = snapshot_indexed_source(formatted_tree, "final-post-format-source", formatted_files, scope)
    final_patch = create_final_bytes(
        "tested-to-final.patch",
        git("diff", "--binary", "--full-index", "--no-ext-diff", "--no-renames", EXPECTED_TREE, formatted_tree),
    )
    final_write("complete.json", {
        "schema": "hepta.source53-finalization-complete.v1",
        "tested_source_commit": EXPECTED_COMMIT, "tested_source_tree": EXPECTED_TREE,
        "final_formatted_tree": formatted_tree, "final_formatted_commit": None,
        "tested": pre, "after_fix": fixed, "after_format": final,
        "fix_receipt": fix_receipt, "format_receipt": format_receipt,
        "tested_to_final_patch": final_patch,
        "cargo_lock_sha256": CARGO_LOCK_SHA256, "bazel_lock_sha256": BAZEL_LOCK_SHA256,
        "original_gate_source_retained_separately_from_final_tree": True,
        "post_fix_or_format_tests_executed": False, "qualification_transferred_to_mutated_tree": False,
        "native_HEAD": FRAMEWORK_PARENT, "remote_refs_changed": False,
        "publication": "SOURCE_ARTIFACT_ONLY_PENDING_ROOT_REVIEW",
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "original_r29_failure_relabelled_as_pass": False,
    })
    announce({"phase": "finalization-complete", "tested_tree": EXPECTED_TREE,
              "fixed_tree": fixed_tree, "formatted_tree": formatted_tree,
              "post_fix_or_format_tests_executed": False,
              "diagnostic_only": True, "behavior_repair_claimed": False})
    return 0
'''


def main():
    old_raw, r31_raw = OLD.read_bytes(), R31.read_bytes()
    if pin(old_raw)["sha256"] != OLD_SHA or pin(r31_raw)["sha256"] != R31_SHA:
        raise RuntimeError("fixed finalizer/producer input mismatch")
    old, _, old_functions, old_constants = module(old_raw)
    r31, r31_ast, r31_functions, _ = module(r31_raw)
    first_def = min(node.lineno for node in r31_ast.body if isinstance(node, ast.FunctionDef))
    header = "".join(r31.splitlines(keepends=True)[:first_def - 1])
    first_doc = ast.get_source_segment(r31, r31_ast.body[0])
    header = change(header, first_doc,
                    '"""INERT source53 final scoped fix followed by original default fmt.\n\n'
                    'Actual current-source R30 app-server and R31 default workspace full PASS,\n'
                    'natural outer0, fresh R31 metadata, exact frozen scope and actual tools\n'
                    'must all be separately bound. R28 remains historical source52 evidence;\n'
                    'R29/R26/R24 failures are preserved. FROZEN=False and None bindings block\n'
                    'every read, output and child process. No tests/metadata/lock-update run\n'
                    'here. Exactly scoped original fix then default fmt may run only after\n'
                    'explicit reviewed final binding; no after-tests or qualification transfer.\n'
                    'The tested source is diagnostic-only and no behavior repair is claimed.\n'
                    '"""')
    header += "\nimport io\nimport tarfile\n\n"
    extra = {
        "FINALIZATION_DIRECTORY": "native-source53-finalization",
        "SCOPE_DIRECTORY": "native-source53-finalizer-input", "SCOPE_INPUT_PINS": None,
        "FRESH_METADATA_PIN": None,
        "R31_JOB_ID": None, "R31_TERMINAL_NAME": None, "R31_INPUT_PINS": None,
        "R31_TERMINAL_SHA256": None, "R31_TERMINAL_BYTES": None,
        "PRIMARY_SOURCE_PINS_IDENTITY": old_constants["SCOPE_INPUT_PINS"]["PRIMARY-SOURCE-PINS.json"],
        "FORMATTER_ENV_NAME": old_constants["FORMATTER_ENV_NAME"],
        "FORMATTER_ENV_BYTES": old_constants["FORMATTER_ENV_BYTES"],
        "FORMATTER_ENV_SHA256": old_constants["FORMATTER_ENV_SHA256"],
        "TOOL_INVENTORY_NAME": None, "TOOL_INVENTORY_BYTES": None, "TOOL_INVENTORY_SHA256": None,
        "TOOL_INVENTORY_SCHEMA": None, "TOOL_INVENTORY_SOURCE_COMMIT": None,
        "TOOL_INVENTORY_SOURCE_TREE": None, "TOOL_INVENTORY_SOURCE_MANIFEST": None,
    }
    header += "# No future workspace, scope or tool observation is fabricated.\n"
    header += "\n".join(name + " = " + repr(value) for name, value in extra.items()) + "\n"
    header += "FINAL_OUTPUT = E / FINALIZATION_DIRECTORY\n"
    common = []
    parts = [header]
    for name, function in r31_functions.items():
        if name in {"capture_metadata", "run_workspace", "run_frozen", "main"}:
            continue
        parts.append(function)
        common.append(name)
    parts.append(old_functions["r29_required_names"].replace("r29_required_names", "r31_required_names"))
    parts.extend([CHECK_FINAL, old_functions["final_write"], old_functions["create_final_bytes"]])
    prerequisite = old_functions["r29_prerequisite"].replace("r29", "r31").replace("R29_", "R31_").replace("source52", "source53")
    prerequisite = prerequisite.replace("r28_proof", "r30_proof").replace("successful r28", "successful r30")
    prerequisite = change(prerequisite,
        "def r31_prerequisite(r30_proof, prior_environment, source_pin, lock_pins,\n"
        "                     source50_pin, source51_pin, apply_proof, r24_failed_pins, r26_failed_pins):",
        "def r31_prerequisite(r30_proof, prior_environment, historical_r28_proof, workspace_baseline,\n"
        "                     workspace_baseline_proof, source_pin, lock_pins, source50_pin, source51_pin,\n"
        "                     source52_pin, apply_proof, r24_failed_pins, r26_failed_pins, r29_failed_pins):")
    start = prerequisite.index('    require(pre["source_manifest"] == source_pin')
    stop = prerequisite.index('    verify_pointer(pre["initial_source_guard"]', start)
    prerequisite = prerequisite[:start] + PRECONDITIONS_REPLACEMENT.strip("\n") + "\n" + prerequisite[stop:]
    prerequisite = change(prerequisite,
        '            "r31 protection/outer budget changed")',
        '            "r31 protection/outer budget changed")\n'
        '    require(env_record["diagnostic_only"] is True and env_record["behavior_repair_claimed"] is False,\n'
        '            "r31 environment diagnostic classification changed")')
    prerequisite = change(prerequisite,
        '        "all_platforms_features_external_services_qualified": False,',
        '        "all_platforms_features_external_services_qualified": False,\n'
        '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    prerequisite = change(prerequisite,
        '            "r31 original workspace selection changed")',
        '            "r31 original workspace selection changed")\n'
        '    require(receipt["original_r29_workspace_baseline"] == workspace_baseline_proof\n'
        '            and receipt["test_ids_used_as_filter"] is False\n'
        '            and receipt["exact_old_test_id_set_required"] is True\n'
        '            and receipt["diagnostic_only"] is True and receipt["behavior_repair_claimed"] is False,\n'
        '            "r31 diagnostic/exact-old-ID receipt contract changed")')
    prerequisite = change(prerequisite,
        'rows, review = review_workspace(log_raw, {packages[identity]["name"] for identity in members})',
        'rows, review = review_workspace(log_raw, {packages[identity]["name"] for identity in members}, workspace_baseline)')
    prerequisite = change(prerequisite,
        '            "r31 completion scope/count/qualification mismatch")',
        '            "r31 completion scope/count/qualification mismatch")\n'
        '    require(complete["original_r29_workspace_baseline"] == workspace_baseline_proof\n'
        '            and complete["exact_old_test_id_set_observed_pass"] is True\n'
        '            and complete["test_ids_used_as_filter"] is False\n'
        '            and complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False\n'
        '            and complete["original_r29_failure_relabelled_as_pass"] is False,\n'
        '            "r31 completion relabelled original failure or diagnostic source")')
    prerequisite = prerequisite.replace("r28_terminal", "r30_terminal").replace("R28_TERMINAL_", "R30_TERMINAL_")
    # The earlier successful-r28 to successful-r30 replacement already covers this timing message.
    prerequisite = change(prerequisite,
        '        "source53_apply_and_project_chain": r30_proof,',
        '        "source53_apply_and_project_chain": r30_proof,\n'
        '        "source52_r28_historical_project_gate": historical_r28_proof,\n'
        '        "historical_project_pass_substitutes_for_r30_or_r31": False,\n'
        '        "original_r29_workspace_baseline": workspace_baseline_proof,\n'
        '        "exact_old_test_id_set_observed_pass": True,\n'
        '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(prerequisite)
    parts.extend([old_functions["working_file_pin"], old_functions["frozen_context_check"]])
    scope = old_functions["load_final_scope"].replace("source52", "source53").replace("r29", "r31")
    scope = scope.replace("== 195", "== 197").replace("== 181", "== 183").replace('"rust_count": 181', '"rust_count": 183')
    scope = change(scope,
        '        "prepared_per_file_command_count": len(commands),',
        '        "prepared_per_file_command_count": len(commands),\n'
        '        "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(scope)
    selection = old_functions["verify_default_format_selection"].replace("181", "183")
    parts.append(selection)
    tools = old_functions["verify_tools"]
    tools = change(tools,
        'inventory["schema"] == "hepta.source51-formatter-readonly-inventory.v1"',
        'inventory["schema"] == TOOL_INVENTORY_SCHEMA')
    tools = tools.replace("historical formatter tool inventory", "actual current-source formatter tool inventory")
    tools = change(tools,
        '        "inventory_not_relabelled_as_source52_observation": True,',
        '        "inventory_bound_to_current_source53_observation": True,')
    parts.append(tools)
    unchanged_final_helpers = ["indexed_source_check", "stage_phase_changes"]
    for name in ("indexed_source_check", "snapshot_indexed_source", "mutation_guard",
                 "preserve_failed_source", "stage_phase_changes", "run_final_phase"):
        function = old_functions[name].replace("source52", "source53")
        if name == "snapshot_indexed_source":
            function = change(function,
                '        "source_snapshot_complete": True,',
                '        "source_snapshot_complete": True,\n'
                '        "diagnostic_only": True, "behavior_repair_claimed": False,')
        elif name == "mutation_guard":
            function = change(function,
                '        "issues": [], "working_source_files": [],',
                '        "issues": [], "working_source_files": [],\n'
                '        "diagnostic_only": True, "behavior_repair_claimed": False,')
        elif name == "preserve_failed_source":
            function = change(function,
                '        "qualification": False, "post_fix_or_format_tests_executed": False,',
                '        "qualification": False, "post_fix_or_format_tests_executed": False,\n'
                '        "diagnostic_only": True, "behavior_repair_claimed": False,')
        elif name == "run_final_phase":
            function = change(function,
                '        "post_fix_or_format_tests_executed": False,\n    })',
                '        "post_fix_or_format_tests_executed": False,\n'
                '        "diagnostic_only": True, "behavior_repair_claimed": False,\n    })')
            function = change(function,
                '                "post_fix_or_format_tests_executed": False,',
                '                "post_fix_or_format_tests_executed": False,\n'
                '                "diagnostic_only": True, "behavior_repair_claimed": False,')
            function = change(function,
                '        "free_bytes_after": shutil.disk_usage(T).free,',
                '        "free_bytes_after": shutil.disk_usage(T).free,\n'
                '        "diagnostic_only": True, "behavior_repair_claimed": False,')
            function = change(function,
                '\n            "post_fix_or_format_tests_executed": False,',
                '\n            "post_fix_or_format_tests_executed": False,\n'
                '            "diagnostic_only": True, "behavior_repair_claimed": False,')
        parts.append(function)
    parts.append(RUN_FINALIZATION)
    final_main = old_functions["main"].replace("source52", "source53")
    final_main = change(final_main,
        '                    "post_fix_or_format_tests_executed": False,',
        '                    "post_fix_or_format_tests_executed": False,\n'
        '                    "diagnostic_only": True, "behavior_repair_claimed": False,')
    parts.append(final_main)
    output = "\n\n".join(part.strip("\n") for part in parts) + '\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'
    raw = output.encode()
    _, parsed, result_functions, result_constants = module(raw)
    if len(result_functions) != sum(isinstance(node, ast.FunctionDef) for node in parsed.body):
        raise RuntimeError("duplicate generated function name")
    for name in common:
        if result_functions[name] != r31_functions[name]:
            raise RuntimeError("R31 helper changed: " + name)
    old_same = ["final_write", "create_final_bytes", "working_file_pin", "frozen_context_check", *unchanged_final_helpers]
    for name in old_same:
        if result_functions[name] != old_functions[name]:
            raise RuntimeError("old finalizer mechanics changed: " + name)
    unknown = sorted(name for name, value in result_constants.items() if value is None)
    if result_constants["FROZEN"] is not False or len(unknown) != 35:
        raise RuntimeError("unexpected inert binding count: " + repr(unknown))
    created = [put("references/native-finalize-source52-template-v2.py", old_raw),
               put("references/native-run-r31-template.py", r31_raw),
               put("native-finalize-source53-template.py", raw)]
    diff = "".join(difflib.unified_diff(old.splitlines(keepends=True), output.splitlines(keepends=True),
                                     fromfile="source52/native-finalize-source52-template-v2.py",
                                     tofile="source53/native-finalize-source53-template.py"))
    created.append(put("source52-source53-finalizer.patch", diff.encode()))
    created.append(obj("MECHANICAL-READBACK.json", {
        "schema": "hepta.source53-finalizer-mechanical.v1", "template": pin(raw),
        "old_finalizer_v2": pin(old_raw), "r31_producer": pin(r31_raw),
        "same_r31_functions": common, "same_r31_function_count": len(common),
        "same_old_finalizer_functions": old_same,
        "ast_parse_executed": True, "runner_imported_or_executed": False,
        "inert_frozen": False, "unknown_binding_count": len(unknown), "unknown_binding_names": unknown,
        "r31_required_originals": 18, "r30_required_originals": 19, "r28_historical_originals": 26,
        "expected_source_paths": 197, "expected_rust_paths": 183, "expected_python_paths": 2,
        "expected_fix_owners": 26, "after_fix_or_format_tests": False,
        "source53_diagnostic_classification_preserved": True,
        "future_gate_metadata_tool_or_scope_evidence_fabricated": False,
        "native_rust_git_metadata_formatter_executed": False,
    }))
    print(json.dumps({"created": created, "common_functions": len(common), "unknown_bindings": len(unknown)}, indent=2))


if __name__ == "__main__":
    main()
