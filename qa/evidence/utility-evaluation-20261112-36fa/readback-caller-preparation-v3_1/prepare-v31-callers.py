"""Append only the reviewed real-literal order to the existing durable row."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
original = (ROOT / "base-v3/CALLERS.toml").read_text()
data = original.encode()
assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == "21b854dd3f1bb245b42f2a57c0fd7685131430b2"
path = "codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs"
before = tomllib.loads(original)
entry = {
    "function": "fn read_original_registry_durable(",
    "sequence": [
        "let manifest = &context.admission.validated_manifest.manifest;",
        '.join("payloads")',
        "let payload = read_candidate_payload(",
        '.join("witnesses")',
        "let actual = read_registry_head_witness(",
        "let registry_after = read_registry_snapshot(",
        "let payload_after = read_candidate_payload(",
        "let fresh = clock()?;",
    ],
    "literal_calls": ['.join("payloads")', '.join("witnesses")'],
    "top_level": [
        "let manifest = &context.admission.validated_manifest.manifest;",
        "let payload = read_candidate_payload(",
        "let registry_after = read_registry_snapshot(",
        "let payload_after = read_candidate_payload(",
        "let fresh = clock()?;",
    ],
}


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(map(toml_value, value)) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(key + " = " + toml_value(item) for key, item in value.items()) + " }"
    raise TypeError(type(value))


marker = 'path = "' + path + '"'
assert original.count(marker) == 1
start = original.rfind("[[protected_file]]", 0, original.index(marker))
end = original.find("\n[[", original.index(marker))
if end < 0:
    end = len(original)
section = original[start:end]
match = re.search(r"(?m)^required_function_order = (.*)$", section)
assert match and match.group(1).endswith("]")
new_value = match.group(1)[:-1] + ", " + toml_value(entry) + "]"
changed = section[:match.start(1)] + new_value + section[match.end(1):]
post = original[:start] + changed + original[end:]
after = tomllib.loads(post)
assert len(after["boundary"]) == 534 and len(after["protected_file"]) == 399
assert len({row["path"] for row in after["protected_file"]}) == 328
modified = []
for index, (old, new) in enumerate(zip(before["protected_file"], after["protected_file"])):
    if old != new:
        assert old["path"] == path
        assert {key: value for key, value in old.items() if key != "required_function_order"} == {key: value for key, value in new.items() if key != "required_function_order"}
        assert new["required_function_order"] == old["required_function_order"] + [entry]
        modified.append(index)
assert len(modified) == 1
assert {key: value for key, value in before.items() if key != "protected_file"} == {key: value for key, value in after.items() if key != "protected_file"}
(ROOT / "post/CALLERS.toml").write_text(post)
(ROOT / "validation-source/CALLERS.toml").write_text(post)
spec = importlib.util.spec_from_file_location("v31_literal_original_verifier", ROOT / "validation-source/scripts/verify_hepta_callers.py")
proof = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = proof
spec.loader.exec_module(proof)
row = after["protected_file"][modified[0]]
checked = proof._verify_protected_files(ROOT / "validation-source", {"protected_file": [row]})
assert checked == [path]
report = {
    "status": "passed_one_row_baseline_diagnostic",
    "base_callers_blob": "21b854dd3f1bb245b42f2a57c0fd7685131430b2",
    "modified_protected_row_zero_based": modified[0],
    "path": path,
    "appended_function_order": entry,
    "all_other_rows_and_metadata_unchanged": True,
    "protected_rows": 399,
    "unique_protected_paths": 328,
    "original_verifier_unchanged": True,
    "full_gate_status": "not_run",
}
(ROOT / "v31-callers-structural-diff.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps({"status": report["status"], "modified_row": modified[0], "bytes": len(post.encode()), "sha256": hashlib.sha256(post.encode()).hexdigest()}))
