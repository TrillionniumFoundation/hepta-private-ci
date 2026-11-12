"""Freeze a four-path delta and its actual, separately scoped evidence."""
import ast
import base64
import datetime
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent
BASE = ROOT / "base-v3"
POST = ROOT / "post"


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


files = []
patch = []
unchanged = []
for target in sorted(POST.rglob("*")):
    if not target.is_file():
        continue
    path = target.relative_to(POST).as_posix()
    original = (BASE / path).read_bytes()
    post = target.read_bytes()
    if original == post:
        unchanged.append({"path": path, **identity(post)})
        continue
    if path.endswith(".py"):
        ast.parse(post.decode())
    files.append({"path": path, "mode": "100644", "base": identity(original), "post": identity(post), "postimage_base64": base64.b64encode(post).decode()})
    patch.extend(difflib.unified_diff(original.decode().splitlines(keepends=True), post.decode().splitlines(keepends=True), fromfile="a/" + path, tofile="b/" + path))
assert {row["path"] for row in files} == {
    "CALLERS.toml",
    "qa/b4-no-bypass/test_original_artifact_channel_source_closure.py",
    "qa/b4-no-bypass/test_original_selection_readback_source_closure.py",
    "qa/b4-no-bypass/test_original_training_readback_source_closure.py",
}
(ROOT / "v31.patch").write_text("".join(patch))
base = tomllib.loads((BASE / "CALLERS.toml").read_text())
post = tomllib.loads((POST / "CALLERS.toml").read_text())
assert base["boundary"] == post["boundary"] and len(post["boundary"]) == 534
assert len(post["protected_file"]) == 399
assert len({row["path"] for row in post["protected_file"]}) == 328
assert len({row["path"] for row in post["protected_file"][:390]}) == 319
assert base["protected_file"][:398] == post["protected_file"][:398]
assert {key: value for key, value in base.items() if key != "protected_file"} == {key: value for key, value in post.items() if key != "protected_file"}
cache = json.loads((ROOT / "v31-caller-cache-audit.json").read_text())
gap = json.loads((ROOT / "v3-literal-gap-observation.json").read_text())
runs = [json.loads((ROOT / f"v31-literal-mutation-attempt-{number}.json").read_text()) for number in (1, 2)]
assert all(run["exit_code"] == 0 and run["source_inputs_unchanged"] and not run["timed_out"] for run in runs)
packet = {
    "format": "hepta.original-channel-registration-preparation.v3.1",
    "requires_preparation_manifest_blob": "911b0ae279c4e552224985ea2d6df23b6cebe6be",
    "requires_callers_blob": "21b854dd3f1bb245b42f2a57c0fd7685131430b2",
    "base_source_sha": "b29869e856d08db1bfb066116a9c443376ccc57d",
    "integrated_source_sha": "e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd",
    "full_source_tree": None,
    "prohibited": ["apply_without_exact_preimages", "production_rust_changes", "verifier_changes", "authority_changes", "budget_changes", "ref_updates", "claim_full_gate_pass"],
    "files": files,
}
raw = (json.dumps(packet, sort_keys=True, separators=(",", ":")) + "\n").encode()
(ROOT / "v31-packet.json").write_bytes(raw)
encoded = base64.b64encode(gzip.compress(raw, mtime=0)) + b"\n"
(ROOT / "v31-packet.json.gz.base64").write_bytes(encoded)
assert len(encoded) < 1048576
manifest = {
    "format": "hepta.original-channel-registration-manifest.v3.1",
    "status": "prepared_for_review_not_frozen_source",
    "prepared_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "requires_preparation_manifest_blob": packet["requires_preparation_manifest_blob"],
    "requires_callers_blob": packet["requires_callers_blob"],
    "base_source_sha": packet["base_source_sha"], "integrated_source_sha": packet["integrated_source_sha"],
    "full_source_tree": None,
    "files": [{key: value for key, value in row.items() if key != "postimage_base64"} for row in files],
    "unchanged_v3_preparation_files": unchanged,
    "callers": identity((POST / "CALLERS.toml").read_bytes()),
    "callers_structural_diff": json.loads((ROOT / "v31-callers-structural-diff.json").read_text()),
    "counts": {"boundary_rows": 534, "protected_rows": 399, "unique_protected_paths": 328, "v2_inherited_protected_rows": 390, "v2_inherited_unique_paths": 319, "rows_removed_or_deduplicated": 0, "boundary_membership_changes_from_v3": 0},
    "terminology_correction": "v3 README's 'protected files' count means rows. Duplicate protected rows were always retained; v3.1 explicitly records both rows and unique paths.",
    "v3_gap_actual_observation": gap,
    "v3_gap_blobs": {"observation": "568047b7d61e15707165abd4a500a70229a29f8f", "raw": "4a594b64826b3da438944278edf0055fc90041c9", "run": "ea19c60806d737be2288ae695d29bd6e591c7a19", "script": "9abcb5b7312fc46225edec88aaf0bb33c3f309f9"},
    "independent_v3_review_blob": "a57cc5e29f5922bf0db164900ff5642873a56c16",
    "literal_protection": {
        "directories": "Original verifier function-local literal_calls, original ordered real-code positions, unchanged complete-body constraint.",
        "filename_templates": "New narrow source-closure QA checks actual raw first arguments at the two real format! spans inside the one real function; the original verifier is unchanged and still does not support macro literal_calls.",
        "checks_not_claimed": ["general Rust parsing", "all dependency security", "runtime source-path behavior", "actor authorization", "full gate"],
        "unchanged_generic_fallback_limit": "Generic read_response<'a> retains file-level ordered stripped-body protection; it does not receive the original function-order unique-function/nested-function checks and is not claimed equivalent to the 37 non-generic function constraints.",
    },
    "actual_literal_mutation_runs": [
        {"attempt": number, "result": identity((ROOT / f"v31-literal-mutation-attempt-{number}.json").read_bytes()), "raw": identity((ROOT / f"v31-literal-mutation-attempt-{number}.raw.log").read_bytes()), "exit_code": run["exit_code"], "elapsed_seconds": run["elapsed_seconds"], "source_inputs_unchanged": run["source_inputs_unchanged"], "timed_out": run["timed_out"]}
        for number, run in zip((1, 2), runs)
    ],
    "final_actual_run": {"attempt": 2, "test_methods": 2, "directory_negative_cases": 6, "filename_negative_cases": 8, "skipped": 0},
    "cache_and_scope_audit": cache,
    "full_membership_methods_executed": 0,
    "historical_results_not_inherited": ["v2 scoped registered-path mutations", "v3 21-method source-mutation run", "separate full-source four-boundary diagnostic", "running all-534/all-390 v2 diagnostic", "e8 complete gates"],
    "source_closure_entrypoint": {"workflow_blob": "72d4b247d90dde972ac592b2d568cd6e470f97ff", "glob": "*source_closure.py", "budget_seconds": 600, "entrypoint_changed": False, "budget_changed": False},
    "source_inputs": runs[-1]["source_inputs_before"],
    "production_rust_mutations": [], "verifier_mutations": [], "authority_granted": False,
    "full_source_gate": "not_run", "full_caller_gate": "not_run", "runtime_tests": "not_run",
    "patch": identity((ROOT / "v31.patch").read_bytes()), "packet": identity(encoded), "packet_decoded": identity(raw),
    "required_integration": "Root must register the exact final CALLERS hash in the original allowlist, freeze a real new source head and execute the original gates. Static costs do not establish 600-second completion.",
}
(ROOT / "v31-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
artifacts = [
    "README-v31.md", "v31-manifest.json", "v31-packet.json.gz.base64", "v31.patch",
    "v31-callers-structural-diff.json", "v31-caller-cache-audit.json",
    "v3-literal-gap-observation.json", "v3-literal-gap.raw.log", "v3-literal-gap-run.json", "reproduce-v3-literal-gap.py",
    "v31-literal-mutation-attempt-1.raw.log", "v31-literal-mutation-attempt-1.json",
    "v31-literal-mutation-attempt-2.raw.log", "v31-literal-mutation-attempt-2.json",
    "v31-artifact-qa-attempt-1.py", "run-v31-literal-mutations.py", "prepare-v31-callers.py", "audit-v31-caller-cache.py", "package-v31.py",
]
entries = [{"key": path, "path": str(ROOT / path), **identity((ROOT / path).read_bytes())} for path in artifacts]
entries += [{"key": "post/" + row["path"], "path": str(POST / row["path"]), **row["post"]} for row in files]
(ROOT / "v31-upload-entries.json").write_text(json.dumps(entries, indent=2) + "\n")
print(json.dumps({"manifest": identity((ROOT / "v31-manifest.json").read_bytes()), "packet": identity(encoded), "packet_decoded": identity(raw), "callers": manifest["callers"], "files": len(files), "upload_entries": len(entries)}, sort_keys=True))
