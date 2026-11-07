"""Create-only local documentation and manifest for the already reviewed inert text."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

ROOT = Path(__file__).resolve().parent
WORK = ROOT.parent


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}


def create(name, raw):
    target = ROOT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as stream:
        stream.write(raw)
    return {"path": name, **pin(raw)}


def write_json(name, value):
    return create(name, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


scope = json.loads((ROOT / "SCOPE-DEPENDENCY-RISK-AUDIT.json").read_bytes())
mechanical = json.loads((ROOT / "MECHANICAL-READBACK.json").read_bytes())
contract_readback = json.loads((ROOT / "STATIC-CONTRACT-READBACK.json").read_bytes())
template = (ROOT / "native-finalize-source53-template.py").read_bytes()
assert pin(template) == mechanical["template"] == contract_readback["template"]
assert mechanical["inert_frozen"] is False and mechanical["unknown_binding_count"] == 35
old = (ROOT / "references/native-finalize-source52-template-v2.py").read_bytes()
expected_patch = "".join(difflib.unified_diff(
    old.decode().splitlines(True), template.decode().splitlines(True),
    fromfile="source52/native-finalize-source52-template-v2.py",
    tofile="source53/native-finalize-source53-template.py",
)).encode()
assert expected_patch == (ROOT / "source52-source53-finalizer.patch").read_bytes()

reference_specs = [
    ("source53-native-gates-preparation/native-run-r30-template-v2.py", "references/native-run-r30-template-v2.py", "current producer template, inert", "a4bb18b0f2d2af63625e7ee6629df9f5a42f47c684bd8e4a72125b62b05d2c0b"),
    ("source53-native-gates-preparation/INPUT-CONTRACT.json", "references/R30-INPUT-CONTRACT.json", "producer contract, not execution", None),
    ("source53-apply-preparation/derived/native-candidate-r30-source.json", "references/source53-registered-source-manifest.json", "actual registered source53 manifest; no gate qualification", scope["source53_manifest"]["sha256"]),
    ("source53-apply-preparation/references/source52-actual-manifest.json", "references/source52-parent-source-manifest.json", "historical source52 parent", scope["source52_manifest"]["sha256"]),
    ("source52-finalize-preparation/input/PRIMARY-SOURCE-PINS.json", "references/unchanged-34-primary-source-pins.json", "unchanged original formatter and Cargo inputs", "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3"),
    ("source52-finalize-preparation/references/formatter-env-original.json", "references/formatter-env-original.json", "original three approved task-local formatter keys", "8881726a60b0881a3ebaff02997a6fb0abae955b585821c70a0ed8789f243b28"),
    ("source52-finalize-preparation/references/source51-tool-inventory-original.json", "references/HISTORICAL-source51-tool-inventory.json", "historical reference only; cannot populate source53 inventory bindings", "8924f181213ef957deb4c6ffa82a6194d29ea5df81fe2b435fd23a5239e0d764"),
]
references = []
for original, target, purpose, expected in reference_specs:
    raw = (WORK / original).read_bytes()
    if expected is not None:
        assert pin(raw)["sha256"] == expected
    references.append({"original_path": original, "attachment": create(target, raw), "classification": purpose})
write_json("REFERENCE-PINS.json", {
    "schema": "hepta.source53-finalizer-reference-pins.v1", "files": references,
    "historical_tool_inventory_claimed_as_current": False,
    "future_R30_R31_or_tool_records_copied_or_created": False,
})

module = ast.parse(template.decode())
functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
r31_suffixes = list(ast.literal_eval(functions["r31_required_names"].body[0].value.generators[0].iter))
future_categories = {
    "registered_current_source_binding": ["EXPECTED_COMMIT", "EXPECTED_TREE", "EXPECTED_CHANGED_COUNT", "SOURCE_MANIFEST_NAME", "SOURCE_MANIFEST_BYTES", "SOURCE_MANIFEST_SHA256"],
    "actual_source53_apply_binding": ["APPLY_COMPLETE_NAME", "APPLY_COMPLETE_SHA256", "APPLY_COMPLETE_BYTES", "APPLY_TERMINAL_NAME", "APPLY_TERMINAL_SHA256", "APPLY_TERMINAL_BYTES", "APPLY_JOB_ID", "DELTA_MANIFEST_NAME", "DELTA_MANIFEST_SHA256", "DELTA_MANIFEST_BYTES"],
    "future_R30_successful_gate_binding": ["R30_INPUT_PINS", "R30_JOB_ID", "R30_TERMINAL_NAME", "R30_TERMINAL_SHA256", "R30_TERMINAL_BYTES"],
    "future_R31_successful_workspace_binding": ["R31_INPUT_PINS", "R31_JOB_ID", "R31_TERMINAL_NAME", "R31_TERMINAL_SHA256", "R31_TERMINAL_BYTES"],
    "fresh_R31_scope_binding": ["SCOPE_INPUT_PINS", "FRESH_METADATA_PIN"],
    "actual_source53_tool_inventory_binding": ["TOOL_INVENTORY_NAME", "TOOL_INVENTORY_BYTES", "TOOL_INVENTORY_SHA256", "TOOL_INVENTORY_SCHEMA", "TOOL_INVENTORY_SOURCE_COMMIT", "TOOL_INVENTORY_SOURCE_TREE", "TOOL_INVENTORY_SOURCE_MANIFEST"],
}
assert sorted(name for group in future_categories.values() for name in group) == mechanical["unknown_binding_names"]
future = {
    "schema": "hepta.source53-finalizer-future-input-contract.v1",
    "classification": "EXPECTED_REQUIREMENTS_NOT_OBSERVED_FUTURE_RESULTS",
    "template": pin(template), "FROZEN": False, "unknown_binding_count": 35,
    "bindings": {group: {name: None for name in names} for group, names in future_categories.items()},
    "known_registered_source_for_later_separate_binding": {
        "commit": scope["source53_registered_commit"], "tree": scope["source53_registered_tree"],
        "manifest": scope["source53_manifest"], "count": 197,
        "diagnostic_only": True, "behavior_repair_claimed": False,
        "registered_commit_is_not_native_HEAD": True,
    },
    "R30": {
        "prefix": "native-source53-project-r30", "successful_original_count": 19,
        "terminal_name": "native-source53-project-r30-terminal-process-status.json",
        "current_source53_strict_and_original_full_project_required": True,
        "phases": ["strict", "tests"], "expected_executed_identity_count": 1345,
        "expected_set": "source53-app-server-r29-baseline.json: binary + name",
        "exact_set_rejects_missing_or_additional_ids": True,
        "baseline_is_test_selector": False, "natural_outer_zero_required": True,
        "observed_terminal_or_result_claimed_here": None,
    },
    "R31": {
        "prefix": "native-workspace-r31", "successful_original_count": 18,
        "required_originals": ["native-workspace-r31" + suffix for suffix in r31_suffixes],
        "terminal_name": "native-workspace-r31-terminal-process-status.json",
        "fresh_metadata_command": ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
        "workspace_command": ["just", "test", "--locked", "--retries", "0"],
        "members_and_defaults": 193, "expected_executed_identity_count": 20228,
        "exact_set_from_original_R29_raw_log_is_post_execution_only": True,
        "baseline_is_test_selector": False, "natural_outer_zero_required": True,
        "deadline_features_skip_retry_rules_unchanged": True,
        "observed_terminal_or_result_claimed_here": None,
    },
    "historical_prerequisites": {
        "source52_R28": "26 original files plus natural outer0; Python32 and four-package 1564 PASS read back independently",
        "source52_R28_substitutes_for_current_R30_or_R31": False,
        "source50_lock": "seven originals plus natural outer0; both lock bytes remain fixed, Rust-only inheritance separately checked",
        "original_failed_R29_R26_R24": "original raw, receipts, guards and failed outer results retained and checked as failed",
        "original_failed_R29_relabelled_as_PASS": False,
    },
    "scope_files": {
        "destination_directory": "native-source53-finalizer-input",
        "EXPECTED-SELECTION.json": {
            "required_schema": "hepta.source53-final-formatter-selection.v1",
            "source_paths": 197, "rust_paths": 183, "python_paths": 2,
            "fix_owners": 26, "CI_selectors": 27, "extra_CI_owner_not_fixed": "codex-hepta-control-plane",
            "fresh_source53_r31_metadata_verified": "must become true only after actual current R31 metadata readback",
            "native_HEAD": "bef6fa7645df9df12b69fda499e97eed25de6c75",
            "native_created_commit_checkout_claimed": False,
        },
        "PACKAGE-ARGS.json": {"required_schema": "hepta.source53-final-fix-packages.v1", "owners": scope["unchanged_owner_names"], "fresh_metadata": "actual R31 full bytes/SHA256/Gitblob pin, presently unknown"},
        "RUST-FILE-COMMANDS.json": {"shape": "183 entries regenerated from exact current metadata ownership and original format.py algorithm", "edition": "2024", "skip_children": True},
        "PRIMARY-SOURCE-PINS.json": {"unchanged_original_count": 34, "bytes": 13098, "sha256": "afc57e362890925d5628947a95dd1f719816996d0b26b2fef101dbcf827e7dd3"},
        "four_files_materialized_as_future_evidence_here": False,
    },
    "tool_inventory": {
        "required_schema": "hepta.source53-formatter-readonly-inventory.v1",
        "future_record_pin_and_source_fields": None,
        "required_source_manifest_fields": ["bytes", "sha256"],
        "actual_source_commit_tree_must_equal_bound_source53": True,
        "native_observation_deferred_until_stable_gap_after_R31_closes": True,
        "must_not_run_uv_run_sync_install_fix_fmt_to_collect_inventory": True,
        "existing_source51_inventory_is_reference_only": references[-1],
        "required_tool_names": ["just", "python3", "uv", "rustfmt-1.96.0", "ruff"],
        "expected_version_strings_inherited_from_original_preparation": {
            "just": "just 1.58.0\n", "python3": "Python 3.14.4\n", "uv": "uv 0.11.3 (x86_64-unknown-linux-gnu)\n",
            "rustfmt-1.96.0": "rustfmt 1.9.0-stable (ac68faa20c 2026-05-25)\n", "ruff": "ruff 0.15.13\n",
        },
        "actual_current_tool_availability_or_versions_claimed": False,
        "actual_executable_resolution_bytes_mode_symlink_venv_and_PATH_shim_rechecked_before_each_phase": True,
    },
    "last_mutating_commands_after_all_future_proofs": {
        "cwd": "/home/alex/work/hepta-cell-unified-20261106-a/source/codex-rs",
        "fix": scope["expected_fix_command"], "format": ["just", "fmt"],
        "allow_staged_added": False, "all_or_base_override_added": False,
        "fix_may_change_only": "current183 Rust paths", "format_may_change_only": "same183 Rust and two scripts Python files",
        "after_fix_or_format_tests": False, "qualification_transferred_to_changed_final_tree": False,
        "any_nonzero_raw_result_or_guard_issue": "retain raw result/log/resources/diff and working bytes; stop before next phase",
    },
}
write_json("FUTURE-INPUT-CONTRACT.json", future)
write_json("PREPARATION.json", {
    "schema": "hepta.source53-finalizer-inert-preparation.v1", "template": pin(template),
    "status": "PREPARED_FOR_INDEPENDENT_STATIC_REVIEW_ONLY", "FROZEN": False,
    "scope_risk_audit": {"path": "SCOPE-DEPENDENCY-RISK-AUDIT.json", **pin((ROOT / "SCOPE-DEPENDENCY-RISK-AUDIT.json").read_bytes())},
    "static_contract_readback": {"path": "STATIC-CONTRACT-READBACK.json", **pin((ROOT / "STATIC-CONTRACT-READBACK.json").read_bytes())},
    "patch": {"path": "source52-source53-finalizer.patch", **pin(expected_patch)},
    "source53_known_registered_identity": {"commit": scope["source53_registered_commit"], "tree": scope["source53_registered_tree"]},
    "diagnostic_only": True, "behavior_repair_claimed": False,
    "actual_execution_bindings_intentionally_unknown": mechanical["unknown_binding_names"],
    "historical_scope_audit_is_fresh_R31_evidence": False,
    "source53_tool_inventory_available": False,
    "executed_only": ["local scope/byte reader", "local text generation", "AST/symtable/producer-consumer static verifier"],
    "not_executed": ["finalizer import or invocation", "native job", "Rust", "Cargo metadata", "fix", "fmt", "Git process", "tool version query", "upload"],
    "unchanged": ["old source52 finalizer", "source53 R30/R31 templates", "canonical source", "formal root reports", "INDEX", "ledger"],
    "local_preparation_attempt_history": {
        "first_builder_exit": 1, "first_builder_failure_before_template_or_reference_outputs": True,
        "first_builder_error": "redundant text replacement assertion; not a source/gate/runtime failure",
        "second_builder_exit": 0, "static_verifier_exit": 0,
        "original_failed_builder_and_tool_result_retained": True,
    },
})
assert (ROOT / "README.md").is_file()
files = []
for path in sorted(ROOT.rglob("*")):
    if path.is_file():
        assert not path.is_symlink()
        files.append({"path": path.relative_to(ROOT).as_posix(), **pin(path.read_bytes())})
manifest = {
    "schema": "hepta.source53-finalizer-preparation-handoff.v1",
    "classification": "FROZEN_TEXT_INERT_EXECUTION_BLOCKED_PENDING_REAL_INPUTS",
    "template": {"path": "native-finalize-source53-template.py", **pin(template)},
    "FROZEN": False, "unknown_binding_count": 35,
    "diagnostic_only": True, "behavior_repair_claimed": False,
    "files": files, "listed_file_count": len(files), "listed_bytes": sum(row["bytes"] for row in files),
    "manifest_itself_excluded_from_files": True,
    "native_rust_metadata_fix_fmt_or_upload_executed": False,
    "future_gate_scope_or_tool_evidence_fabricated": False,
}
handoff = write_json("HANDOFF-MANIFEST.json", manifest)
for row in files:
    assert pin((ROOT / row["path"]).read_bytes()) == {key: row[key] for key in ("bytes", "sha256", "git_blob")}
print(json.dumps({"handoff": handoff, "files_including_handoff": len(files) + 1,
                  "bytes_including_handoff": manifest["listed_bytes"] + handoff["bytes"],
                  "template": pin(template), "execution": "PREPARATION_ONLY"}, ensure_ascii=False))
