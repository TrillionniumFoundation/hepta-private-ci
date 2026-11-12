"""Static call/caching audit; does not execute a repository membership method."""
import ast
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
POST = ROOT / "post"
BASE = ROOT / "base-v3"
VIEW = ROOT / "validation-source"
spec = importlib.util.spec_from_file_location("v31_cache_audit_original_proof", VIEW / "scripts/verify_hepta_callers.py")
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
manifest = tomllib.loads((POST / "CALLERS.toml").read_text())
boundaries = {row.identifier: row for row in proof._boundary_rows(manifest)}


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def functions(text):
    return {node.name: (ast.get_source_segment(text, node), ast.dump(node, include_attributes=False), node) for node in ast.walk(ast.parse(text)) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def assertions(node):
    return Counter(ast.dump(item, include_attributes=False) for item in ast.walk(node) if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute) and isinstance(item.func.value, ast.Name) and item.func.value.id == "self" and item.func.attr.startswith("assert"))


specifications = (
    ("training", "test_original_training_readback_source_closure.py", "test_exact_read_only_edges_do_not_admit_another_typed_or_qualified_caller"),
    ("selection", "test_original_selection_readback_source_closure.py", "test_exact_readback_edges_use_complete_rust_collection_and_reject_another_caller"),
    ("artifact", "test_original_artifact_channel_source_closure.py", "test_exact_original_channel_membership_uses_all_rust_and_rejects_another_caller"),
)
reports = []
for kind, filename, method in specifications:
    path = "qa/b4-no-bypass/" + filename
    old_text = (BASE / path).read_text()
    new_text = (POST / path).read_text()
    old_functions = functions(old_text)
    new_functions = functions(new_text)
    module_spec = importlib.util.spec_from_file_location("v31_audit_" + kind, POST / path)
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[module_spec.name] = module
    # Import only: no unittest method is invoked.
    # The file resolves scripts from its prospective repository root, so load
    # the exact same bytes under the existing preparation view instead.
    view_spec = importlib.util.spec_from_file_location("v31_audit_view_" + kind, VIEW / path)
    module = importlib.util.module_from_spec(view_spec)
    sys.modules[view_spec.name] = module
    view_spec.loader.exec_module(module)
    expected = module.EXPECTED if isinstance(module.EXPECTED, dict) else {"learning_original_owner_command_channel": module.EXPECTED}
    admitted = module.ADMITTED if isinstance(module.ADMITTED, dict) else {"learning_original_owner_command_channel": module.ADMITTED}
    row_reports = []
    for key in expected:
        boundary = boundaries[key]
        negatives = 2 if boundary.receiver_type else 1
        missing = len(admitted[key])
        purity = []
        if boundary.receiver_type:
            target = boundary.receiver_type
            name = boundary.symbol.rsplit("::", 1)[-1]
            attempts = (
                f"fn bypass(owner: &{target}) {{ owner.{name}(); }}",
                f"fn bypass(owner: &{target}) {{ {target}::{name}(owner); }}",
            )
            for attempt in attempts:
                assert re.search(r"\b(?:struct|type|use|enum|union|impl|as)\b", attempt) is None
                fields = proof.authority_fields({"only-injected-pure-function.rs": attempt}, target)
                assert not fields and not fields.aliases
                purity.append({"code": attempt, "no_field_or_alias_declaration_keywords": True,
                               "original_single_file_fields": 0, "original_single_file_aliases": 0,
                               "scope": "purity of controlled injection, not repository caller closure"})
        row_reports.append({
            "boundary": key, "receiver_type": boundary.receiver_type,
            "baseline_verifications": 1, "unexpected_caller_verifications": negatives,
            "missing_actual_caller_verifications": missing,
            "total_original_boundary_calls": 1 + negatives + missing,
            "old_type_index_builds": (1 + negatives + missing) if boundary.receiver_type else 0,
            "new_full_baseline_or_missing_type_index_builds": (1 + missing) if boundary.receiver_type else 0,
            "new_single_file_purity_index_builds": negatives if boundary.receiver_type else 0,
            "pure_injection_cases": purity,
        })
    before_assertions = assertions(old_functions[method][2])
    after_assertions = assertions(new_functions[method][2])
    assert not (before_assertions - after_assertions), (kind, before_assertions - after_assertions)
    for symbol in ("EXPECTED", "ADMITTED"):
        def assignment(text):
            return next(node for node in ast.parse(text).body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == symbol for target in node.targets))
        assert ast.dump(assignment(old_text), include_attributes=False) == ast.dump(assignment(new_text), include_attributes=False)
    old_path_union = {path for key in expected for path in (boundaries[key].definition_path, *boundaries[key].product_callers)}
    reports.append({
        "kind": kind, "path": path, "method": method,
        "base": identity(old_text.encode()), "post": identity(new_text.encode()),
        "old_collection": "48-path EXPECTED definition/product-caller subset" if kind == "training" else "complete original _source_files collection",
        "old_training_subset_actual_paths": len(old_path_union) if kind == "training" else None,
        "new_collection": "complete original _source_files(ROOT, source_roots); unchanged source masks and original ignored fragments",
        "complete_collection_invocations": 1,
        "cache_scope": "one method's one immutable complete baseline source_index and receiver type; only proven pure function append cases reuse its fields; every actual file removal gets a fresh cache",
        "cross_method_or_cross_source_cache": False,
        "all_original_assertion_call_asts_retained": True,
        "expected_and_admitted_asts_unchanged": True,
        "method_executed_in_preparation": False,
        "changed_old_functions": [name for name in old_functions if old_functions[name][:2] != new_functions.get(name, (None, None))[:2]],
        "unchanged_old_function_count": sum(old_functions[name][:2] == new_functions.get(name, (None, None))[:2] for name in old_functions),
        "added_functions": [name for name in new_functions if name not in old_functions],
        "rows": row_reports,
    })

v2_root = Path("/tmp/hepta-training-readback-retention-v2-eufwhtak")
v2_manifest = json.loads((v2_root / "manifest-v2.json").read_text())
original_preservation = []
for entry in v2_manifest["existing_qa_function_preservation"]:
    path = entry["path"]
    old = functions((v2_root / "base" / path).read_text())
    new = functions((POST / path).read_text())
    assert len(old) == entry["original_function_count"]
    assert all(old[name][:2] == new[name][:2] for name in old)
    original_preservation.append({"path": path, "functions_byte_and_ast_identical": len(old)})
assert len(original_preservation) == 9 and sum(row["functions_byte_and_ast_identical"] for row in original_preservation) == 95
totals = {
    "complete_source_collections_after": 3,
    "original_verify_boundary_calls_after": sum(row["total_original_boundary_calls"] for report in reports for row in report["rows"]),
    "old_type_index_builds_selection_full_plus_training_subset": sum(row["old_type_index_builds"] for report in reports for row in report["rows"]),
    "new_full_source_type_index_builds": sum(row["new_full_baseline_or_missing_type_index_builds"] for report in reports for row in report["rows"]),
    "new_single_file_purity_index_builds": sum(row["new_single_file_purity_index_builds"] for report in reports for row in report["rows"]),
}
assert totals["original_verify_boundary_calls_after"] == 39
assert totals["new_full_source_type_index_builds"] == 12
assert totals["new_single_file_purity_index_builds"] == 12
result = {
    "format": "hepta.source-closure-caller-cache-audit.v3.1",
    "status": "static_review_and_controlled_injection_purity_check_only",
    "unchanged_original_verifier": [identity((VIEW / "scripts" / name).read_bytes()) for name in ("verify_hepta_callers.py", "hepta_typed_callers.py")],
    "algorithmic_reasoning": [
        "authority_fields only adds aliases via target-as and type-alias declarations, closing transitively over existing aliases; the exact injected functions contain none of those declaration tokens.",
        "After alias normalization, authority_fields only adds fields by matching struct declarations; the injected functions contain no struct/type/impl/use/enum/union declarations.",
        "The existing complete source_index entries are copied without mutation, so all pre-existing alias and field contributions remain identical.",
        "The QA additionally checks controlled injections through the original one-file authority_fields and checks _declared_aliases for every already-known target/alias before reusing the complete baseline cache.",
        "Removing a real source could remove aliases or fields. Such negative cases always pass a new empty cache to the original full verifier.",
        "The original _verify_boundary still traverses each complete source_index and enforces exact observed==expected for every baseline and negative case.",
    ],
    "reports": reports, "totals": totals,
    "original_nine_qa_95_functions": original_preservation,
    "historical_identity_exception": "Only the newly authored v2 Training membership method and newly authored v3 Selection membership method change. Historical v2/v3 byte-preservation evidence is retained, not rewritten. All original nine QA files' 95 functions remain unchanged.",
    "timing": {"budget_seconds": 600, "budget_changed": False, "full_gate_measured": False,
               "warning": "Training coverage expands from a subset to all Rust. Counts alone cannot establish faster total time or compliance with the unchanged 600-second gate."},
    "full_source_gate": "not_run", "full_caller_gate": "not_run", "runtime_tests": "not_run",
}
(ROOT / "v31-caller-cache-audit.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps({"status": result["status"], "totals": totals, "original_existing_functions_preserved": 95, "complete_membership_methods_run": 0}))
