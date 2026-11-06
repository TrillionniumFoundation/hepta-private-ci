#!/usr/bin/env python3
"""Verify only evidence adapters on retained local input; no native/network/ref work."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

def ident(data):
    return {"bytes": len(data), "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(), "sha256": hashlib.sha256(data).hexdigest()}

base = (HERE / "prepare_original.py").read_bytes()
candidate = (HERE / "prepare_candidate.py").read_bytes()
assert ident(base)["git_blob"] == "35b9f129e6a2b582e41c83f5db62b49ae688bb66"
assert (ROOT / "prepare_third_post_audit_delta.py").read_bytes() == base
method = (HERE / "evidence_packet_method.py.txt").read_text()
restored = candidate.decode()
assert restored.count(method) == 1
restored = restored.replace(method, "", 1)
restored = restored.replace(
    '        adapter = component["adapter"]\n        prefix = registry["audit_prefix"] if adapter == "evidence_packet" else registry["prefix"]\n',
    '        prefix = registry["prefix"]\n', 1)
restored = restored.replace(
    '        receipts = {}\n        if adapter == "evidence_packet":\n            receipts = self.verify_evidence_packet(component, registry, prefix, rows, body)\n            rows = [dict(row, git_blob=row["sha"]) for row in rows]\n',
    '        adapter = component["adapter"]\n        receipts = {}\n', 1)
restored = restored.replace(
    '            elif adapter == "evidence_packet":\n                require(receipts[path] == identity(payload), "verified packet bytes changed")\n', "", 1)
assert restored.encode() == base
spec = importlib.util.spec_from_file_location("candidate_adapter", HERE / "prepare_candidate.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
config_path = HERE / "components.ready-07.original.json"
config = json.loads(config_path.read_bytes())
assert len(config["components"]) == 15
builder = module.Builder(ROOT, config_path)
for component in config["components"]:
    builder.import_component(component)
assert len(builder.evidence) == 366
for name, expected in builder.inputs.items():
    assert ident((ROOT / name).read_bytes()) == expected
fmt = next(c for c in config["components"] if c["directory"].endswith("840e8b5-native-format-delivery"))
ci = next(c for c in config["components"] if c["directory"].endswith("17c6b903-ci-cuts-delivery"))
appendix = next(c for c in config["components"] if c["name"] == "final-appendix")
assert appendix["adapter"] == "standard_recipe"
assert fmt["adapter"] == ci["adapter"] == "evidence_packet"

class MutatedRead(module.Builder):
    """Synthetic bad-sidecar controls only; disk and frozen tool originals stay intact."""
    def __init__(self, suffix, change):
        super().__init__(ROOT, config_path)
        self.target = fmt["directory"] + "/" + suffix
        self.change = change

    def read(self, name):
        original = super().read(name)
        if name != self.target:
            return original
        value = json.loads(original)
        self.change(value)
        return module.encoded(value)

def edit_receipt_bytes(value):
    value["records"][0]["full_GET_original"]["structuredContent"]["content"] += "synthetic-invalid-byte"

def edit_receipt_create(value):
    value["create_tree_original"]["structuredContent"]["sha"] = "0" * 40

def remove_receipt(value):
    value["records"].pop()

def edit_registry_bytes(value):
    value["full_GET_original"]["structuredContent"]["content"] += "synthetic-invalid-byte"

def edit_registry_tree(value):
    value["actual_materialization_tree"] = "0" * 40
    value["create_tree_original"]["structuredContent"]["sha"] = "0" * 40

controls = [
    ("receipt_GET_bytes_changed", "registration-receipts-GET-000.local-sidecar.json", edit_receipt_bytes, "packet receipt original full GET differs"),
    ("receipt_create_tree_changed", "registration-receipts-GET-000.local-sidecar.json", edit_receipt_create, "packet receipt original create differs"),
    ("receipt_coverage_missing", "registration-receipts-GET-000.local-sidecar.json", remove_receipt, "incomplete packet receipt-sidecar coverage"),
    ("registry_GET_bytes_changed", "registry-self.actual.json", edit_registry_bytes, "packet original registry full GET differs"),
    ("registry_cumulative_tree_changed_consistently", "registry-self.actual.json", edit_registry_tree, "packet cumulative registry Merkle differs"),
]
negative = []
for name, suffix, change, expected in controls:
    probe = MutatedRead(suffix, change)
    try:
        probe.import_component(fmt)
    except ValueError as exc:
        assert str(exc) == expected, (name, str(exc), expected)
        negative.append({"case": name, "decision": "REJECTED", "reason": str(exc), "mutations": "in-memory synthetic sidecar only"})
    else:
        raise AssertionError("bad evidence accepted: " + name)
assert (ROOT / "prepare_third_post_audit_delta.py").read_bytes() == base
for name, expected in builder.inputs.items():
    assert ident((ROOT / name).read_bytes()) == expected
print(json.dumps({
    "schema": "hepta-final-registry-adapter-independent-partial-verification-v1",
    "base": ident(base), "candidate": ident(candidate),
    "original_source_exactly_recovered_after_reversing_only_adapter_changes": True,
    "root_preparer_unchanged": True,
    "actual_components": len(config["components"]),
    "actual_evidence_paths": len(builder.evidence),
    "actual_unique_blobs": len({row["git_blob"] for row in builder.evidence.values()}),
    "input_files_rehashed_before_after": len(builder.inputs),
    "groups": {row["name"]: row["paths"] for row in builder.origins},
    "appendix_adapter": "standard_recipe",
    "new_packet_adapter": "evidence_packet",
    "materialization_qualification": "Complete cumulative leaf Merkle equals each actual create_tree SHA; no separate tree GET exists or is claimed.",
    "packet_receipt_chains": [
        {"directory": fmt["directory"], "payload": 30, "registration_receipts": 8, "append_paths": 39},
        {"directory": ci["directory"], "payload": 12, "registration_receipts": 3, "append_paths": 16}
    ],
    "negative_controls": negative,
    "root_config_or_preparer_modified": False,
    "frozen_package_modified": False,
    "whole_C4_prepare_executed": False,
    "native_CI_network_ref_PR_operations": False
}, ensure_ascii=False, indent=2))
