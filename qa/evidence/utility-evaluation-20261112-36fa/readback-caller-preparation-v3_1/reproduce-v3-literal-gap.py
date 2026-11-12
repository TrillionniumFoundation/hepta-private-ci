"""Record the real v3 source-protection gap without changing repository source."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
VIEW = ROOT / "validation-source"
for cache in VIEW.rglob("__pycache__"):
    shutil.rmtree(cache)
spec = importlib.util.spec_from_file_location("v3_literal_gap_original_proof", VIEW / "scripts/verify_hepta_callers.py")
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
path = "codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs"
original = (VIEW / path).read_text()
manifest = tomllib.loads((ROOT / "base-v3/CALLERS.toml").read_text())
rows = [row for row in manifest["protected_file"] if row["path"] == path]
assert len(rows) == 1


def identity(text):
    data = text.encode()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_blob_sha": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}


def function_mask(text):
    code = proof._strip_cfg_test_items(proof._strip_rust_non_code(text))
    marker = "fn read_original_registry_durable("
    assert code.count(marker) == 1
    start = code.index(marker)
    end = proof._rust_item_end(code, start)
    return code[start:end + 1]


cases = [("unchanged_v3_baseline", original, rows)]
for old, new in (
    ('"payloads"', '"payloade"'),
    ('"witnesses"', '"witnessed"'),
    ('"{}-{}.bin"', '"{}+{}.bin"'),
    ('"{}-{}.witness"', '"{}+{}.witness"'),
):
    assert len(old) == len(new) and original.count(old) == 1
    changed = original.replace(old, new, 1)
    cases.append(("same_length_" + old, changed, rows))
    if "{}" in old:
        raw_only = copy.deepcopy(rows)
        raw_only[0]["required"].append(old)
        cases.append(("raw_required_spoofed_by_comment_" + old, changed + "\n// " + old + "\n", raw_only))
        cases.append(("raw_required_spoofed_by_unrelated_constant_" + old, changed + "\nconst UNUSED_FILENAME_TEMPLATE: &str = " + old + ";\n", raw_only))
observations = []
for name, changed, protected in cases:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / path
        target.parent.mkdir(parents=True)
        target.write_text(changed)
        try:
            proof._verify_protected_files(root, {"protected_file": protected})
            accepted = True
            error = None
        except proof.VerificationFailure as failure:
            accepted = False
            error = str(failure)
    item = {"case": name, "accepted_by_original_verifier": accepted,
            "same_actual_function_mask_as_v3": function_mask(changed) == function_mask(original),
            "source": identity(changed), "raw_required_only_experiment": protected is not rows,
            "error": error}
    observations.append(item)
    print(json.dumps(item, sort_keys=True), flush=True)
assert len(observations) == 9 and all(case["accepted_by_original_verifier"] for case in observations)
report = {
    "status": "v3_literal_gap_actually_reproduced",
    "scope": "original source verifier on one exact Rust file; no Rust execution or full gate",
    "v3_manifest_blob": "911b0ae279c4e552224985ea2d6df23b6cebe6be",
    "v3_callers_blob": "21b854dd3f1bb245b42f2a57c0fd7685131430b2",
    "source_path": path, "source": identity(original),
    "observations": observations,
    "finding": "Same-length directory and format literals are masked from function-body guards. Raw required alone also accepts unchanged literals retained in comments or unrelated code.",
    "not_claimed": ["runtime behavior", "full source-closure", "full caller acceptance", "authority"],
}
(ROOT / "v3-literal-gap-observation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": report["status"], "cases": len(observations), "production_source_changed": False}))
