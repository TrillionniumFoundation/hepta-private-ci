#!/usr/bin/env python3
"""Read only data/AST review. Never imports or executes a native script."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

assert __debug__, "This independent verifier requires non-optimized Python"
ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent
INPUTS = {}


def digest(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def read(path, expected=None):
    path = ROOT / path
    assert path.is_file() and not path.is_symlink(), str(path)
    data = path.read_bytes()
    actual = digest(data)
    if expected:
        for key in ("bytes", "sha256", "git_blob"):
            if key in expected:
                assert actual[key] == expected[key], (str(path), key, actual[key], expected[key])
    rel = str(path.relative_to(ROOT))
    INPUTS[rel] = {"path": rel, **actual}
    return data


def obj(path, expected=None):
    return json.loads(read(path, expected))


def write(name, value):
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
    path = OUT / name
    with path.open("xb") as handle:
        handle.write(data)
    return {"path": str(path.relative_to(ROOT)), **digest(data)}


def assignments(data):
    tree = ast.parse(data)
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            assert name not in result, name
            result[name] = node.value
    return tree, result


def span(data, node):
    lines = data.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    return offsets[node.lineno - 1] + node.col_offset, offsets[node.end_lineno - 1] + node.end_col_offset


def inverse(data, nodes, replacements):
    edits = [(*span(data, nodes[key]), value) for key, value in replacements.items()]
    result = data
    for start, end, value in sorted(edits, reverse=True):
        result = result[:start] + value + result[end:]
    return result


def functions(data, tree):
    return {node.name: data[slice(*span(data, node))]
            for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def verify_terminal(path, prefix, bindings):
    value = obj(path, {"bytes": bindings[prefix + "_TERMINAL_BYTES"],
                       "sha256": bindings[prefix + "_TERMINAL_SHA256"]})
    assert value["job_id"] == bindings[prefix + "_JOB_ID"]
    assert value["state"] == "succeeded" and value["exit_code"] == 0
    for key in ("output_complete", "output_durable", "terminal_publication_confirmed"):
        assert value[key] is True
    for key in ("automatic_retry", "cancelled", "timed_out"):
        assert value[key] is False
    return value


TEMPLATE = "source53-finalize-preparation/native-finalize-source53-template.py"
BOUND = "source53-finalize-binding/native-finalize-source53-bound.py"
FINAL = "source53-finalize-binding/native-finalize-source53.py"
template = read(TEMPLATE, {"bytes": 174038, "sha256": "41c18849f6ebd24b17695051ee9c1c47c38ae207f87bf6c004f76248210fa22d"})
bound = read(BOUND, {"bytes": 181140, "sha256": "204f0183524893e092f0ce87b3ce694b04c5f3d223a6a92c66781b81f4802cac"})
final = read(FINAL, {"bytes": 181139, "sha256": "6f63696d009ee52726a36e96a6abccadc613df62d8bcc0be590644ea40c21dd1"})
bindings = obj("source53-finalize-binding/BINDINGS.json", {"bytes": 9127, "sha256": "5aeb45bf2bbf54254a38615bd36670d80dcc7544ce9abdf1754cb2e113d1ba87"})
ta, tn = assignments(template)
ba, bn = assignments(bound)
fa, fn = assignments(final)
unknown = {key for key, value in tn.items() if isinstance(value, ast.Constant) and value.value is None}
assert unknown == set(bindings) and len(bindings) == 35
assert set(tn) == set(bn) == set(fn)
for key, value in bindings.items():
    assert ast.literal_eval(bn[key]) == value == ast.literal_eval(fn[key]), key
assert ast.literal_eval(tn["FROZEN"]) is False
assert ast.literal_eval(bn["FROZEN"]) is False
assert ast.literal_eval(fn["FROZEN"]) is True
assert inverse(bound, bn, {key: b"None" for key in bindings}) == template
assert inverse(final, fn, {"FROZEN": b"False"}) == bound
tf = functions(template, ta)
assert len(tf) == 62 and tf == functions(bound, ba) == functions(final, fa)

for before, after, patch_name, before_name, after_name in [
    (template, bound, "template-to-bound.patch", "native-finalize-source53-template.py", "native-finalize-source53-bound.py"),
    (bound, final, "bound-to-final.patch", "native-finalize-source53-bound.py", "native-finalize-source53.py"),
]:
    regenerated = "".join(difflib.unified_diff(before.decode().splitlines(keepends=True),
                                            after.decode().splitlines(keepends=True),
                                            fromfile=before_name, tofile=after_name)).encode()
    assert regenerated == read("source53-finalize-binding/" + patch_name)

handoff = obj("source53-finalize-binding/HANDOFF-MANIFEST.json")
for item in handoff["files"] + [handoff["generator"]]:
    read(item["path"], item)
old_bindings = obj("source53-r31-binding/BINDINGS.json")
assert len(old_bindings) == 21 and all(bindings[key] == value for key, value in old_bindings.items())
proposed_tools = obj("source53-formatter-inventory-actual-independent-review/PROPOSED-TOOL-BINDINGS.json")["bindings"]
assert len(proposed_tools) == 7 and all(bindings[key] == value for key, value in proposed_tools.items())

ARCHIVE = "native-validation-results/r31-archive-closed/original/"
R31 = ARCHIVE + "evidence/"
R30 = ARCHIVE + "input/r30-prerequisites/"
assert len(bindings["R31_INPUT_PINS"]) == 18
assert len(bindings["R30_INPUT_PINS"]) == 19
for path, pin in bindings["R31_INPUT_PINS"].items():
    read(R31 + path, pin)
for path, pin in bindings["R30_INPUT_PINS"].items():
    data = read(R30 + path, pin)
    assert data == read("native-validation-results/r30-closed-input/evidence/" + path, pin)
r31_terminal = verify_terminal(R31 + bindings["R31_TERMINAL_NAME"], "R31", bindings)
r30_terminal = verify_terminal(R30 + bindings["R30_TERMINAL_NAME"], "R30", bindings)
apply_terminal = verify_terminal(ARCHIVE + "input/source53-apply-pins/" + bindings["APPLY_TERMINAL_NAME"], "APPLY", bindings)
manifest = obj(ARCHIVE + "input/" + bindings["SOURCE_MANIFEST_NAME"],
               {"bytes": bindings["SOURCE_MANIFEST_BYTES"], "sha256": bindings["SOURCE_MANIFEST_SHA256"]})
apply_complete = obj(ARCHIVE + "input/source53-apply-prerequisites/complete.json",
                     {"bytes": bindings["APPLY_COMPLETE_BYTES"], "sha256": bindings["APPLY_COMPLETE_SHA256"]})
delta = obj(ARCHIVE + "input/source53-apply-prerequisites/input/delta-manifest.json",
            {"bytes": bindings["DELTA_MANIFEST_BYTES"], "sha256": bindings["DELTA_MANIFEST_SHA256"]})
commit, source_tree = bindings["EXPECTED_COMMIT"], bindings["EXPECTED_TREE"]
for document in (manifest, apply_complete, delta):
    assert document["source_commit"] == commit and document["source_tree"] == source_tree
    assert document["diagnostic_only"] is True and document["behavior_repair_claimed"] is False
assert len(manifest["changed_files"]) == manifest["changed_file_count"] == bindings["EXPECTED_CHANGED_COUNT"] == 197
assert sum(item["path"].endswith(".rs") for item in manifest["changed_files"]) == 183
assert apply_complete["actual_changed_file_count"] == 197 and apply_complete["source_guards_pass"] is True
assert apply_complete["dependency_inputs_changed_paths"] == []
assert apply_complete["source_manifest"]["sha256"] == bindings["SOURCE_MANIFEST_SHA256"]
assert apply_complete["delta_manifest"]["sha256"] == bindings["DELTA_MANIFEST_SHA256"]

scopes = {}
for name, pin in bindings["SCOPE_INPUT_PINS"].items():
    scopes[name] = obj("source53-final-scope-preparation/" + name, pin)
assert len(scopes) == 4
selection, packages = scopes["EXPECTED-SELECTION.json"], scopes["PACKAGE-ARGS.json"]
assert (selection["changed_path_count"], selection["rust_count"], selection["python_count"], selection["owner_count"], selection["ci_selector_count"]) == (197, 183, 2, 26, 27)
assert selection["native_HEAD"] == "bef6fa7645df9df12b69fda499e97eed25de6c75"
assert selection["default_formatter_command"] == ["just", "fmt"] and selection["all_flag_used"] is False
assert len(scopes["RUST-FILE-COMMANDS.json"]) == 183 and len(scopes["PRIMARY-SOURCE-PINS.json"]) == 34
assert packages["command"] == ["just", "fix", "--locked"] + packages["package_args"]
assert len(packages["owners"]) == 26 and len(packages["package_args"]) == 52
assert "--all" not in packages["command"] and "--allow-staged" not in packages["recipe_expansion"]
metadata = obj(R31 + "native-workspace-r31-metadata.json", bindings["FRESH_METADATA_PIN"])
assert len(metadata["workspace_members"]) == len(metadata["workspace_default_members"]) == 193
assert set(metadata["workspace_members"]) == set(metadata["workspace_default_members"])
assert packages["fresh_metadata"] == bindings["FRESH_METADATA_PIN"]

inventory = obj("native-validation-results/source53-formatter-tool-inventory-closed/evidence/inventory.json",
                {"bytes": bindings["TOOL_INVENTORY_BYTES"], "sha256": bindings["TOOL_INVENTORY_SHA256"]})
for binding_key, field in [("TOOL_INVENTORY_SCHEMA", "schema"), ("TOOL_INVENTORY_SOURCE_COMMIT", "source_commit"),
                           ("TOOL_INVENTORY_SOURCE_TREE", "source_tree"), ("TOOL_INVENTORY_SOURCE_MANIFEST", "source_manifest")]:
    assert bindings[binding_key] == inventory[field]
assert inventory["inventory_complete"] is True and inventory["source_guard_pass"] is True
assert inventory["workspace_original_exit_code"] == 0 and inventory["workspace_terminal_state"] == "succeeded"
read("source53-formatter-inventory-actual-independent-review/INDEPENDENT-READBACK.json",
     {"bytes": 11367, "sha256": "a459118e1b957ddfdaa0f51400720d06428412fde74c5d89702f8251238f7554"})

raw = obj(R31 + "native-workspace-r31-tests-raw-process-result.json")
receipt = obj(R31 + "native-workspace-r31-tests-receipt.json")
complete = obj(R31 + "native-workspace-r31-complete.json")
review = obj(R31 + "native-workspace-r31-result-review.json")
guard = obj(R31 + "native-workspace-r31-source-post-test-verification.json")
for document in (raw, receipt, complete, review, guard):
    assert document["source_commit"] == commit
for document in (raw, receipt, complete, review):
    assert document["source_tree"] == source_tree
assert raw["command"] == receipt["command"] == complete["command"] == ["just", "test", "--locked", "--retries", "0"]
assert raw["exit_code"] == receipt["exit_code"] == receipt["effective_exit_code"] == complete["workspace_exit"] == complete["effective_exit_code"] == 0
assert receipt["issues"] == [] and receipt["source_guards_pass"] is True and receipt["phase_pass"] is True
assert complete["counts"] == review["terminal_counts"] == {"PASS": 20228, "FAIL": 0, "TIMEOUT": 0}
assert complete["unique_test_count"] == review["terminal_unique_test_count"] == 20228
assert complete["reported_skipped"] == review["reported_skipped"] == 130
assert review["pass"] is True and review["duplicate_execution_ids"] is False
for key in ("baseline_missing", "additional_test_ids", "baseline_not_pass"):
    assert review[key] == []
assert complete["diagnostic_only"] is True and complete["behavior_repair_claimed"] is False
assert guard["pass"] is True and guard["actual_tree"] == guard["expected_tree"] == source_tree
assert guard["native_head"] == selection["native_HEAD"] and guard["changed_file_count"] == 197
for key in ("unstaged_paths", "untracked_paths", "file_mismatches"):
    assert guard[key] == []
for key in ("cargo_lock_sha256", "bazel_lock_sha256"):
    assert guard[key] == manifest[key] == complete[key]
assert receipt["raw_process_result"]["sha256"] == bindings["R31_INPUT_PINS"]["native-workspace-r31-tests-raw-process-result.json"]["sha256"]
assert receipt["log_sha256"] == bindings["R31_INPUT_PINS"]["native-workspace-r31-tests.log"]["sha256"]
assert receipt["resources_sha256"] == bindings["R31_INPUT_PINS"]["native-workspace-r31-tests-resources.txt"]["sha256"]

plan = obj("source53-finalize-binding/SCOPE-UPLOAD-PLAN.json")
scope_dir_node = tn["SCOPE_DIRECTORY"]
scope_dir = ast.literal_eval(scope_dir_node)
assert plan["destination_directory"] == "/home/alex/work/hepta-cell-unified-20261106-a/evidence/" + scope_dir
assert {item["name"] for item in plan["operations"]} == set(bindings["SCOPE_INPUT_PINS"])
for item in plan["operations"]:
    assert item["create_only"] is True and item["overwrite_allowed"] is False
    assert item["target_path"] == plan["destination_directory"] + "/" + item["name"]
    assert item["source"]["bytes"] == bindings["SCOPE_INPUT_PINS"][item["name"]]["bytes"]
    assert item["source"]["sha256"] == bindings["SCOPE_INPUT_PINS"][item["name"]]["sha256"]
    read(item["source"]["path"], item["source"])

report = {
    "schema": "hepta.source53-finalizer-binding-independent-review.v1",
    "conclusion": "STATIC_BINDING_CLEAR",
    "scope": "Narrow actual-literal, full-byte inverse, frozen-function and exact original input review; candidate code was never imported or executed.",
    "template": {"path": TEMPLATE, **digest(template)},
    "bound": {"path": BOUND, **digest(bound)},
    "final": {"path": FINAL, **digest(final)},
    "mechanical": {"literal_count": 35, "template_unknowns_equal_binding_keys": True,
                   "ast_value_spans_inverse_equals_complete_template": True,
                   "final_inverse_only_FROZEN_equals_complete_bound": True,
                   "patches_independently_regenerated_exact": True,
                   "all_top_level_functions_byte_identical": 62,
                   "actual_R31_prior_bindings_preserved": 21,
                   "independent_inventory_bindings_preserved": 7,
                   "no_substring_based_constant_replacement": True},
    "actual_inputs": {"R31_originals": 18, "R30_originals": 19,
                      "R30_archive_bytes_equal_separately_closed_originals": True,
                      "natural_apply_R30_R31_terminals": {"APPLY": apply_terminal["job_id"], "R30": r30_terminal["job_id"], "R31": r31_terminal["job_id"]},
                      "source_commit": commit, "source_tree": source_tree, "changed_files": 197,
                      "source_and_complete_diagnostic_only_preserved": True,
                      "scope_files": 4, "primary_pin_count": 34, "fresh_metadata_members": 193,
                      "fresh_metadata_default_members": 193, "Rust_selection": 183, "Python_selection": 2,
                      "owning_packages": 26, "CI_selectors": 27, "native_HEAD": selection["native_HEAD"],
                      "default_fmt_command": ["just", "fmt"], "all_flag": False,
                      "inventory_actual_readback_reference": "source53-formatter-inventory-actual-independent-review/INDEPENDENT-READBACK.json"},
    "R31_bound_closed_result": {"raw_exit": 0, "effective_exit": 0, "outer_exit": 0,
                                "original_command": raw["command"], "counts": review["terminal_counts"],
                                "reported_skipped": 130, "source_and_dual_lock_postguard_pass": True,
                                "baseline_missing": [], "additional_test_ids": []},
    "boundaries": [
        "This narrow review rehashes the complete R31 log and rows and binds their native closed accounting; it is not a replacement for the separate full-log/archive independent reconstruction.",
        "The earlier scope files retain their historical NOT_EXECUTED and pending labels; actual terminal and inventory inputs are separately bound without changing those frozen source artifacts.",
        "Source53 is diagnostic instrumentation; project/workspace engineering PASS does not prove the original Bedrock cause repaired or grant scientific/model qualification.",
        "Actual native binary identities/version receipts were independently reviewed earlier; this review performs no tool probe. Runtime source, disk, scope, dependency, tool and artifact guards remain required by the unchanged finalizer.",
        "Local upload plan is checked for four exact inputs and create-only paths; actual remote upload is separately documented by the native owner. This review does not perform upload or execution.",
        "No source, index, HEAD, canonical reports, ledger, native state, tests, fix or formatter were changed or executed. Final authorization remains with root."
    ],
    "execution_authorized_by_this_review": False,
    "finalizer_executed_by_this_review": False,
    "blockers": [],
    "input_pin_file": "INPUT-PINS.json"
}
read(str(Path(__file__).relative_to(ROOT)))
pins = write("INPUT-PINS.json", {"schema": "hepta.independent-input-pins.v1", "files": list(INPUTS.values())})
report_pin = write("INDEPENDENT-REVIEW.json", report)
script_pin = {"path": str(Path(__file__).relative_to(ROOT)), **digest(Path(__file__).read_bytes())}
handoff_pin = write("HANDOFF-MANIFEST.json", {"schema": "hepta.source53-finalizer-binding-review-handoff.v1", "conclusion": "STATIC_BINDING_CLEAR", "files": [script_pin, pins, report_pin]})
print(json.dumps({"review": report_pin, "handoff": handoff_pin, "checked_input_files": len(INPUTS)}, indent=2))
