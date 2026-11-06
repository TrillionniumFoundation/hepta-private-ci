#!/usr/bin/env python3
"""Read-only hash/AST/receipt verification; never imports or executes the exporter."""
import ast
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
DRAFT = WORKSPACE / "w1/h4-content-reference-draft"
H3 = WORKSPACE / "w1/h3-elf-export"

def record(path):
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}

def parsed(path):
    return ast.parse(path.read_text())

code = DRAFT / "archive_reference.py"
code_info = record(code)
assert code_info["sha256"] == "ce96de09dc981311753d37312c1b254751cce3b40c4f950f603303a523508425"
tree = parsed(code)
pin = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
           and any(isinstance(target, ast.Name) and target.id == "PINNED_PARENT" for target in node.targets))
base = H3 / "export_h3_retained_images.py"
base_tree = parsed(base)
functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
base_functions = {node.name: node for node in base_tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
ast_claim = json.loads((DRAFT / "inherited-io-functions-ast-check.json").read_text())
assert len(ast_claim["identical_function_asts"]) == 14
assert ast_claim["base_sha256"] == record(base)["sha256"] == pin["exporter_sha256"]
assert ast_claim["draft_sha256"] == code_info["sha256"]
asts = {name: ast.dump(functions[name], include_attributes=False) == ast.dump(base_functions[name], include_attributes=False)
        for name in ast_claim["identical_function_asts"]}
assert all(asts.values()) and asts == ast_claim["identical_function_asts"]

completion_path = H3 / "H3-export-completion.json"
index_path = H3 / "H3-actual-export-index.json"
plan_path = H3 / "H3-export-plan.json"
completion = json.loads(completion_path.read_text())
index = json.loads(index_path.read_text())
assert record(completion_path)["sha256"] == pin["completion_sha256"]
assert record(index_path)["sha256"] == pin["index_sha256"] and record(index_path)["bytes"] == pin["index_bytes"]
assert record(plan_path)["sha256"] == pin["plan_sha256"]
assert completion["status"] == "COMPLETE" and completion["phase"] == pin["phase"] == "H3"
assert completion["archive_bytes"] == pin["archive_bytes"] and completion["archive_sha256"] == pin["archive_sha256"]
assert completion["archive_index_sha256"] == pin["index_sha256"]
for name in ("source_commit", "source_tree", "plan_sha256", "exporter_sha256"):
    assert index[name] == pin[name]
assert len(index["files"]) == pin["images"] == 11
assert sum(row["bytes"] for row in index["files"]) == pin["image_bytes"] == 1674575368
assert len(index["embedded_metadata_files"]) + len(index["files"]) + 1 == pin["members"] == 16
for row in index["files"]:
    assert row["name"] == "H3/elf/" + row["sha256"] + ".elf"
    assert row["role"] in ("complete-recorded-test-image", "complete-live-daemon-image") and "representation" not in row
assert not index.get("partial_prefix_representations") and not index.get("parents") and not index.get("parent_reference")

receipt_path = DRAFT / "utility-attempt1-receipt.json"
receipt = json.loads(receipt_path.read_text())
for name in ("archive_reference.py", "test_archive_reference.py"):
    actual = record(DRAFT / name)
    assert actual["sha256"] == receipt[name]["sha256"] and actual["bytes"] == receipt[name]["bytes"]
for name in ("stdout", "stderr"):
    actual = record(Path(receipt[name]["path"]))
    assert actual["sha256"] == receipt[name]["sha256"] and actual["bytes"] == receipt[name]["bytes"]
stderr = Path(receipt["stderr"]["path"]).read_text()
results = re.findall(r"^(test_[a-z0-9_]+) \([^\n]+\) \.\.\. ok$", stderr, re.M)
declared = [node.name for node in ast.walk(parsed(DRAFT / "test_archive_reference.py"))
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
assert len(results) == len(declared) == len(set(results)) == 8 and set(results) == set(declared)
assert receipt["exit_code"] == 0 and receipt["timed_out"] is False and "Ran 8 tests in 0.369s\n\nOK" in stderr
design_path = WORKSPACE / "w1/h4-content-reference-design/design.json"
assert record(design_path)["sha256"] == "2dda5331ddd89f70164686f6ed229afca6c4bfa4236b118740a6d529098a9565"
delivery_path = DRAFT / "cloud-delivery-manifest.json"
delivery = json.loads(delivery_path.read_text())
for row in delivery["files"]:
    actual = record(Path(row["path"]))
    assert actual["sha256"] == row["sha256"] and actual["bytes"] == row["bytes"]

inputs = [code, DRAFT / "test_archive_reference.py", DRAFT / "inherited-io-functions-ast-check.json",
          receipt_path, DRAFT / "utility-attempt1.stdout", DRAFT / "utility-attempt1.stderr",
          DRAFT / "README.md", delivery_path, design_path, base, completion_path, index_path, plan_path]
report = {
    "schema": "H4-reference-draft-independent-input-verification-v1",
    "files": [record(path) for path in inputs], "pinned_parent": pin,
    "inherited_function_ast_equal": asts, "utility_names": results,
    "utility_wrapper_elapsed_seconds": receipt["elapsed_seconds"], "utility_unittest_reported_seconds": 0.369,
    "utility_scope": receipt["scope"], "utility_reexecuted_by_reviewer": False,
    "parent_native_outcome": index["original_run_outcome"],
    "actual_parent_archive_bytes_read_by_reviewer": 0, "actual_h4_bytes_read_by_reviewer": 0,
    "actual_h4_inventory_plan_request_present": False,
    "scope": "Local metadata/source/receipt bytes only. The fixed parent archive was not downloaded or re-read by this audit; future exporter and consumer must each execute their actual full-byte protocols."
}
(ROOT / "input-verification.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"verified_inputs": len(inputs), "ast_equal": len(asts), "utility_cases": len(results),
                  "parent_images": len(index["files"]), "parent_members": pin["members"],
                  "no_export_or_consume_executed": True}, indent=2))
