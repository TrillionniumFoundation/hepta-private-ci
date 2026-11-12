"""Preserve preparation evidence and build a preimage-checked 13-path delta."""
import ast
import base64
import datetime
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "base-v2"
POST = ROOT / "post"


def identity(data):
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
    }


rows = []
retained = []
patch = []
for source in sorted(POST.rglob("*")):
    if not source.is_file():
        continue
    path = source.relative_to(POST).as_posix()
    before_path = BASE / path
    before = before_path.read_bytes() if before_path.exists() else None
    after = source.read_bytes()
    if before == after:
        retained.append({"path": path, "identity": identity(after)})
        continue
    assert path == "CALLERS.toml" or path.startswith("qa/b4-no-bypass/")
    if path.endswith(".py"):
        ast.parse(after.decode())
    rows.append({
        "path": path,
        "mode": "100644",
        "base": identity(before) if before is not None else None,
        "post": identity(after),
        "postimage_base64": base64.b64encode(after).decode(),
    })
    patch.extend(difflib.unified_diff(
        before.decode().splitlines(keepends=True) if before is not None else [],
        after.decode().splitlines(keepends=True),
        fromfile="a/" + path if before is not None else "/dev/null",
        tofile="b/" + path,
    ))
assert len(rows) == 13
assert len(retained) == 2
(ROOT / "final-v3.patch").write_text("".join(patch))

manifest = tomllib.loads((POST / "CALLERS.toml").read_text())
base_manifest = tomllib.loads((BASE / "CALLERS.toml").read_text())
assert len(manifest["boundary"]) == 534 and len(manifest["protected_file"]) == 399
assert manifest["protected_file"][:390] == base_manifest["protected_file"]
preservation = json.loads((ROOT / "final-v3-expected-qa-preservation.json").read_text())
old = [row for row in preservation if row["base_kind"] != "selection_only_checkpoint"]
assert len(old) == 10
assert sum(row["functions_preserved_byte_for_byte"] for row in old) == 109
attempts = []
for number in (1, 2):
    result = json.loads((ROOT / f"final-v3-mutation-attempt-{number}.json").read_text())
    assert result["source_inputs_unchanged"]
    attempts.append({
        "attempt": number,
        "result": identity((ROOT / f"final-v3-mutation-attempt-{number}.json").read_bytes()),
        "raw": identity((ROOT / f"final-v3-mutation-attempt-{number}.raw.log").read_bytes()),
        "exit_code": result["exit_code"],
        "elapsed_seconds": result["elapsed_seconds"],
        "source_inputs_unchanged": result["source_inputs_unchanged"],
        "timed_out": result["timed_out"],
    })
assert [row["exit_code"] for row in attempts] == [1, 0]
source_rows = json.loads((ROOT / "final-v3-nine-protected-diagnostic.json").read_text())["inputs"]
scripts = [
    {"path": str(path.relative_to(ROOT / "validation-source")), **identity(path.read_bytes())}
    for path in sorted((ROOT / "validation-source/scripts").glob("*.py"))
]
assert len(scripts) == 2
test_files = []
for name in ("test_original_selection_readback_source_closure.py", "test_original_artifact_channel_source_closure.py"):
    path = POST / "qa/b4-no-bypass" / name
    tree = ast.parse(path.read_text())
    tests = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    test_files.append({"path": path.relative_to(POST).as_posix(), "identity": identity(path.read_bytes()), "test_methods": tests})
packet = {
    "format": "hepta.original-channel-registration-preparation.v3",
    "base_source_sha": "b29869e856d08db1bfb066116a9c443376ccc57d",
    "integrated_source_sha": "e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd",
    "requires_preparation_manifest_blob": "ef16e7f1a1e413bdda7ea44e353e94edbb8f40db",
    "requires_callers_blob": "317da5f28fbc1cf2556fa5935bb846dce8c7c2cb",
    "full_source_tree": None,
    "prohibited": ["apply_without_exact_preimages", "production_rust_changes", "verifier_changes", "authority_changes", "ref_updates", "claim_full_gate_pass"],
    "files": rows,
}
packet_bytes = (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode()
(ROOT / "final-v3-packet.json").write_bytes(packet_bytes)
encoded = base64.b64encode(gzip.compress(packet_bytes, mtime=0)) + b"\n"
(ROOT / "final-v3-packet.json.gz.base64").write_bytes(encoded)
assert len(encoded) < 1048576
summary = {
    "format": "hepta.original-channel-registration-manifest.v3",
    "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "status": "prepared_for_review_not_frozen_source",
    "base_source_sha": packet["base_source_sha"],
    "integrated_source_sha": packet["integrated_source_sha"],
    "requires_preparation_manifest_blob": packet["requires_preparation_manifest_blob"],
    "requires_callers_blob": packet["requires_callers_blob"],
    "selection_only_checkpoint_manifest_blob": "5d9b8c96b7f01cca615f3af7503f196ba69013d6",
    "full_source_tree": None,
    "callers": identity((POST / "CALLERS.toml").read_bytes()),
    "structural_diff": json.loads((ROOT / "final-v3-ast-diff.json").read_text()),
    "files": [{k: value for k, value in row.items() if k != "postimage_base64"} for row in rows],
    "retained_v2_files": retained,
    "production_rust_mutations": [],
    "verifier_source_mutations": [],
    "workflow_mutations": [],
    "authority_granted": False,
    "new_artifact_dependency_scope": [row["path"] for row in json.loads((ROOT / "artifact-protected-rows.json").read_text())],
    "qa_preservation": preservation,
    "old_v2_qa_affected": {"files": 10, "functions_byte_and_ast_identical": 109, "changed_ast_field": "EXPECTED member literals only"},
    "selection_checkpoint_qa_functions_byte_and_ast_identical": 12,
    "new_source_closure_files": test_files,
    "discovery": {
        "workflow_path": ".github/workflows/hepta-daemon-learning-native.yml",
        "workflow_blob": "72d4b247d90dde972ac592b2d568cd6e470f97ff",
        "command": "python3 scripts/hepta_ci_exec.py --timeout-seconds 600 --minimum-tests 1 --output $RUNNER_TEMP/daemon-learning-records/source-closure.json -- python3 -m unittest discover -s qa/b4-no-bypass -p '*source_closure.py' -v",
        "new_file_names_match_unchanged_glob": True,
        "entrypoint_changed": False,
    },
    "source_inputs": source_rows,
    "original_verifier_scripts": scripts,
    "actual_preparation_validation": {
        "baseline_protected_rows": 9,
        "original_function": "_verify_protected_files",
        "mutation_methods_run": 21,
        "selection_mutation_methods": 8,
        "artifact_mutation_methods": 13,
        "passed_final_attempt": 2,
        "attempts": attempts,
        "prior_failure": "One new QA marker matched both real clock checks; uniqueness assertion failed. Replaced it with two exact independent counterexamples. No assertion or method was removed; original failed log and QA retained.",
        "full_rust_membership_methods": "not_run_in_partial_view",
        "full_source_gate": "not_run",
        "full_caller_gate": "not_run",
        "runtime_tests": "not_run",
    },
    "external_running_diagnostic": "Separate all-534/all-390 diagnostic is bound to v2, not this preparation; its results are not inherited.",
    "audit_blobs": {
        "selection": "7fb2fd1ef668e38163917fcc2b23a2036967566d",
        "artifact_callers": "a36b1e0596a80ebb55aa163fb2719a245fc5f5ee",
        "artifact_dependencies": "52a3bb7fcbfa97ab02b2ce5ca047860d19fcd21c",
    },
    "patch": identity((ROOT / "final-v3.patch").read_bytes()),
    "packet": identity(encoded),
    "packet_decoded": identity(packet_bytes),
    "required_integration_step": "Add the exact final CALLERS SHA256 to the existing large-blob allowlist, freeze a new actual source head, and execute the original gates. No allowance is changed here.",
    "limits": [
        "Source marker/mutation checks do not execute the mutated Rust.",
        "No new signatures, actors, authority or deployed learning-loop qualification are manufactured.",
        "No full caller or source gate result is assigned to a preparation or another source version.",
        "Protection is scoped to the reviewed functions and direct dependencies, not all Artifact code.",
        "Independent A/B/C, external objective and cost contract, actual material availability and cold recovery remain separate acceptance requirements.",
    ],
}
(ROOT / "final-v3-manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
artifact_paths = [
    "README-v3.md", "final-v3-manifest.json", "final-v3-packet.json.gz.base64", "final-v3.patch",
    "final-v3-ast-diff.json", "final-v3-expected-qa-preservation.json", "artifact-protected-rows.json",
    "final-v3-nine-protected-diagnostic.json", "final-v3-mutation-attempt-1.raw.log",
    "final-v3-mutation-attempt-1.json", "final-v3-mutation-attempt-2.raw.log",
    "final-v3-mutation-attempt-2.json", "artifact-qa-attempt-1.py", "run-final-v3-mutations.py",
    "prepare-final-v3.py", "package-final-v3.py",
]
upload = [{"key": path, "path": str(ROOT / path), **identity((ROOT / path).read_bytes())} for path in artifact_paths]
upload += [{"key": "post/" + row["path"], "path": str(POST / row["path"]), **row["post"]} for row in rows]
(ROOT / "final-v3-upload-entries.json").write_text(json.dumps(upload, indent=2) + "\n")
print(json.dumps({
    "manifest": identity((ROOT / "final-v3-manifest.json").read_bytes()),
    "packet": identity(encoded), "packet_decoded": identity(packet_bytes),
    "patch": identity((ROOT / "final-v3.patch").read_bytes()),
    "files": len(rows), "retained_files": len(retained),
    "callers": summary["callers"], "upload_entries": len(upload),
}, sort_keys=True))
