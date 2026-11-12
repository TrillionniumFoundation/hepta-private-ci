#!/usr/bin/env python3
"""Validate the new Current13 row delta without editing the source checkout.

This is a rebuilt plan, not the lost 72,732-byte original delta.
Default mode performs schema/input/row verification only. --run-qa additionally
runs the original five Current and three Candidate material source tests in a
temporary overlay using the unchanged repository verifier. No H/native/caller
full-index job is launched by this script.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode = True
import tempfile
import traceback
import unittest

def metadata(data: bytes) -> dict:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }

def require_pin(path: Path, pin: dict) -> bytes:
    data = path.read_bytes()
    actual = metadata(data)
    if any(actual[key] != pin[key] for key in ("bytes", "sha256", "git_blob")):
        raise RuntimeError("exact input mismatch: " + str(path))
    return data

def save(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

def emit_row(kind: str, row: dict) -> str:
    lines = ["[[" + kind + "]]"]
    for key, value in row.items():
        if key != "required_function_order":
            lines.append(key + " = " + json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    for item in row.get("required_function_order", []):
        lines.extend(("", "[[protected_file.required_function_order]]"))
        for key, value in item.items():
            lines.append(key + " = " + json.dumps(value, ensure_ascii=True, separators=(",", ":")))
    return "\n".join(lines) + "\n\n"

def raw_blocks(text: str) -> dict[str, str]:
    starts = list(re.finditer(r"^\[\[(boundary|protected_file)\]\]\n", text, re.M))
    found = {}
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        block = text[match.start():end]
        if match.group(1) == "protected_file":
            import tomllib
            row = tomllib.loads(block)["protected_file"]
            assert len(row) == 1
            if row[0]["path"] in found:
                raise RuntimeError("duplicate protected path")
            found[row[0]["path"]] = block
    return found

def verify_preserved_before(after: dict, before: dict) -> None:
    for key in ("required", "forbidden"):
        old = before.get(key, [])
        if after.get(key, [])[:len(old)] != old:
            raise RuntimeError("old marker order/multiplicity was not preserved: " + key)
    old_functions = [item["function"] for item in before.get("required_function_order", [])]
    new_functions = [item["function"] for item in after.get("required_function_order", [])]
    if new_functions[:len(old_functions)] != old_functions:
        raise RuntimeError("old function protection order lost")

def main() -> int:
    import tomllib
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--delta", type=Path, default=Path(__file__).with_name("CURRENT13_REBUILT_DELTA.json"))
    parser.add_argument("--base-callers", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-qa", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if output == root or root in output.parents:
        raise RuntimeError("output must be outside the tested checkout")
    output.mkdir(parents=True, exist_ok=False)
    delta_bytes = args.delta.read_bytes()
    plan = json.loads(delta_bytes)
    base_path = args.base_callers or root / "CALLERS.toml"
    original = require_pin(base_path, plan["base_manifest"]).decode()
    pins = plan["inputs"] + plan["qa_inputs"] + plan["qa_source_dependencies"] + [plan["verifier"]]
    before_bytes = {}
    for pin in pins:
        before_bytes[pin["path"]] = require_pin(root / pin["path"], pin)
    source_manifest = {path: metadata(data) for path, data in sorted(before_bytes.items())}
    save(output / "input-verification.json", {
        "delta": metadata(delta_bytes),
        "base": metadata(original.encode()),
        "source_files": source_manifest,
        "status": "exact current/QA/dependency bytes matched before verification",
    })
    before = tomllib.loads(original)
    if [len(before["boundary"]), len(before["protected_file"])] != plan["before_counts"]:
        raise RuntimeError("base registry count changed")
    if before["privileged_inventory"]["required_boundary_ids"] != plan["inventory_before"]:
        raise RuntimeError("base inventory order/multiplicity differs")
    blocks = raw_blocks(original)
    expected = copy.deepcopy(before)
    text = original
    for change in plan["protected_replacements"]:
        index = [i for i, row in enumerate(expected["protected_file"]) if row["path"] == change["path"]]
        if len(index) != 1 or expected["protected_file"][index[0]] != change["before"]:
            raise RuntimeError("exact before row mismatch: " + change["path"])
        if blocks[change["path"]] != change["before_raw"] or text.count(change["before_raw"]) != 1:
            raise RuntimeError("exact before row bytes mismatch")
        verify_preserved_before(change["after"], change["before"])
        expected["protected_file"][index[0]] = change["after"]
        text = text.replace(change["before_raw"], emit_row("protected_file", change["after"]), 1)
    if plan["boundary_replacements"]:
        raise RuntimeError("Current13 must not alter an old boundary")
    known_ids = {row["id"] for row in before["boundary"]}
    known_symbols = {row["symbol"] for row in before["boundary"]}
    for row in plan["new_boundaries"]:
        if row["id"] in known_ids or row["symbol"] in known_symbols:
            raise RuntimeError("new boundary collision")
        expected["boundary"].append(row)
        text += emit_row("boundary", row)
    known_paths = {row["path"] for row in before["protected_file"]}
    for row in plan["new_protected_files"]:
        if row["path"] in known_paths:
            raise RuntimeError("new protected path collision")
        expected["protected_file"].append(row)
        text += emit_row("protected_file", row)
    expected["privileged_inventory"]["required_boundary_ids"] = plan["inventory_after"]
    replacement = "required_boundary_ids = " + json.dumps(plan["inventory_after"], separators=(",", ":"))
    if text.count(plan["inventory_before_raw"]) != 1:
        raise RuntimeError("inventory source line not unique")
    text = text.replace(plan["inventory_before_raw"], replacement, 1)
    after = tomllib.loads(text)
    if after != expected:
        raise RuntimeError("serialized plan changed another registry field")
    if [len(after["boundary"]), len(after["protected_file"])] != plan["after_counts"]:
        raise RuntimeError("rebuilt counts differ")
    (output / "CURRENT13_REBUILT_CALLERS.toml").write_text(text)
    (output / "ROWS.before.toml").write_text("".join(c["before_raw"] for c in plan["protected_replacements"]))
    (output / "ROWS.after.toml").write_text(
        "".join(emit_row("protected_file", c["after"]) for c in plan["protected_replacements"])
        + "".join(emit_row("boundary", r) for r in plan["new_boundaries"])
        + "".join(emit_row("protected_file", r) for r in plan["new_protected_files"])
    )
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location("current13_rebuilt_authoritative_proof", root / plan["verifier"]["path"])
    assert spec and spec.loader
    proof = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = proof
    spec.loader.exec_module(proof)
    boundary_rows = proof._boundary_rows(after)
    ids = [row.identifier for row in boundary_rows]
    if len(ids) != len(set(ids)) or ids.count(plan["inventory_additions"][0]) != 1:
        raise RuntimeError("boundary/inventory uniqueness failed")
    protected = [c["after"] for c in plan["protected_replacements"]] + plan["new_protected_files"]
    proof._verify_protected_files(root, {"protected_file": protected})
    current_paths = [
        "cell_q24_training_candidate_readback.rs",
        "cell_q24_training_candidate_wire.rs",
        "cell_q24_training_candidate_current.rs",
        "cell_q24_training_candidate_service.rs",
        "cell_q24_training_bootstrap_candidate.rs",
    ]
    current_paths = ["codex-rs/hepta-agentd/src/" + name for name in current_paths]
    sources = {
        path: proof._strip_cfg_test_items(proof._strip_rust_non_code((root / path).read_text()))
        for path in current_paths
    }
    boundary = next(row for row in boundary_rows if row.identifier == plan["inventory_additions"][0])
    proof._verify_boundary(root, boundary, sources, ())
    for expression in (
        "candidate_current::original_candidate_current_proof_v1(request, material);",
        "original_candidate_current_proof_v1(request, material);",
    ):
        injected = dict(sources)
        injected["codex-rs/hepta-agentd/src/unregistered_current_rebuild.rs"] = (
            "fn bypass(request: &Request, material: &Material) {" + expression + "}"
        )
        try:
            proof._verify_boundary(root, boundary, injected, ())
        except proof.VerificationFailure as error:
            if "unexpected" not in str(error):
                raise
        else:
            raise RuntimeError("unregistered Current caller was accepted")
    save(output / "authoritative-protected-and-caller.json", {
        "status": "PASS", "protected": len(protected),
        "new_boundary": boundary.identifier, "unregistered_caller_forms_rejected": 2,
        "full_rust_index_run": False,
    })
    qa_result = {"status": "NOT_REQUESTED", "expected_original_cases": 8}
    if args.run_qa:
        with tempfile.TemporaryDirectory(prefix="hepta-current13-rebuilt-qa-") as directory:
            overlay = Path(directory)
            (overlay / "scripts").symlink_to(root / "scripts", target_is_directory=True)
            (overlay / "codex-rs").symlink_to(root / "codex-rs", target_is_directory=True)
            (overlay / "CALLERS.toml").write_text(text)
            qa = overlay / "qa/b4-no-bypass"
            qa.mkdir(parents=True)
            for pin in plan["qa_inputs"]:
                (qa / Path(pin["path"]).name).write_bytes(before_bytes[pin["path"]])
            suite = unittest.TestSuite()
            loader = unittest.TestLoader()
            for pin in plan["qa_inputs"]:
                suite.addTests(loader.discover(str(qa), pattern=Path(pin["path"]).name))
            if suite.countTestCases() != 8:
                raise RuntimeError("original Current/material QA coverage is not exactly eight")
            with (output / "source-qa.log").open("w") as log:
                result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
            qa_result = {
                "status": "PASS" if result.wasSuccessful() else "FAIL",
                "tests": result.testsRun, "failures": len(result.failures),
                "errors": len(result.errors), "skipped": len(result.skipped),
                "log": metadata((output / "source-qa.log").read_bytes()),
            }
            save(output / "source-qa.json", qa_result)
            if not result.wasSuccessful() or result.testsRun != 8 or result.skipped:
                raise RuntimeError("exact original eight source cases did not all pass")
    for pin in pins:
        if require_pin(root / pin["path"], pin) != before_bytes[pin["path"]]:
            raise RuntimeError("tested source changed during verification")
    require_pin(base_path, plan["base_manifest"])
    save(output / "result.json", {
        "status": "PASS", "scope": "Current13 rebuilt row plan only",
        "new_identity": True, "lost_original_delta_recovered": False,
        "base_counts": plan["before_counts"], "after_counts": plan["after_counts"],
        "product_changed": False, "global_registry_written": False,
        "source_qa": qa_result, "full_caller_run": False, "native_run": False,
        "ordinary_qualification": 0,
    })
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
