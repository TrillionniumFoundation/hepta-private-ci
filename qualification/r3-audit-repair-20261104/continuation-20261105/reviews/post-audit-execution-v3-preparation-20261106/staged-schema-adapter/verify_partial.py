#!/usr/bin/env python3
"""Import the 16 frozen components only; do not prepare or write C4 outputs."""
import ast
import copy
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys


def identity(b):
    return {"bytes": len(b), "git_blob": hashlib.sha1(
        b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest(),
        "sha256": hashlib.sha256(b).hexdigest()}


def main(root, here):
    original = (here / "prepare_original.py").read_bytes()
    candidate = (here / "prepare_candidate.py").read_bytes()
    assert len(original) == 40614
    assert identity(original)["git_blob"] == "2782624228f94b9ff693811cab418d205a37cf5e"
    assert (root / "prepare_third_post_audit_delta.py").read_bytes() == original
    old_ast, new_ast = ast.parse(original), ast.parse(candidate)
    old_builder = next(n for n in old_ast.body if isinstance(n, ast.ClassDef) and n.name == "Builder")
    new_builder = next(n for n in new_ast.body if isinstance(n, ast.ClassDef) and n.name == "Builder")
    old_method = next(n for n in old_builder.body if isinstance(n, ast.FunctionDef) and n.name == "verify_evidence_packet")
    index = next(i for i, n in enumerate(new_builder.body)
                 if isinstance(n, ast.FunctionDef) and n.name == "verify_evidence_packet")
    new_builder.body[index] = old_method
    assert ast.dump(new_ast, include_attributes=False) == ast.dump(old_ast, include_attributes=False)
    patch = "".join(difflib.unified_diff(original.decode().splitlines(True), candidate.decode().splitlines(True),
        fromfile="a/prepare_third_post_audit_delta.py", tofile="b/prepare_third_post_audit_delta.py")).encode()
    assert patch == (here / "candidate.patch").read_bytes()
    check = here / "patch-check"
    check.mkdir(exist_ok=True)
    target = check / "prepare_third_post_audit_delta.py"
    target.write_bytes(original)
    patch_commands = []
    for args, expected in [(["--check"], original), ([], candidate),
                           (["--reverse", "--check"], candidate), (["--reverse"], original)]:
        command = ["git", "apply", *args, str(here / "candidate.patch")]
        result = subprocess.run(command, cwd=check, capture_output=True, timeout=20)
        assert result.returncode == 0 and result.stdout == result.stderr == b""
        assert target.read_bytes() == expected
        patch_commands.append({"argv": command, "exit_code": result.returncode,
                               "stdout_bytes": len(result.stdout), "stderr_bytes": len(result.stderr)})
    config_name = "third-post-audit-inputs/components.final-pre-review-01.json"
    config_raw = (root / config_name).read_bytes()
    assert config_raw == (here / "components.original.json").read_bytes()
    source_config = json.loads(config_raw)
    config = json.loads((here / "components.partial.json").read_bytes())
    expected = copy.deepcopy(source_config)
    expected["components"][-1]["receipt_sidecars"] = [
        f"registration-receipts-GET-{i:03d}.local-sidecar.json" for i in range(7)]
    assert config == expected and len(config["components"]) == 16
    spec = importlib.util.spec_from_file_location("staged_candidate", here / "prepare_candidate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = module.Builder(root, here / "components.partial.json")
    before_sizes = []
    for component in config["components"]:
        before = len(builder.evidence)
        builder.import_component(component)
        before_sizes.append({"name": component["name"], "paths": len(builder.evidence) - before,
                             "adapter": component["adapter"], "registry": component["registry_blob"]})
    assert len(builder.evidence) == 475
    assert builder.outputs == {}
    for path, expected_identity in builder.inputs.items():
        assert identity((root / path).read_bytes()) == expected_identity
    component = config["components"][-1]
    directory = component["directory"]
    registry_body = (root / directory / "registry.actual.json").read_bytes()
    registry = json.loads(registry_body)

    class InjectedBuilder(module.Builder):
        def __init__(self, edits):
            super().__init__(root, here / "components.partial.json")
            self.edits = edits

        def read_json(self, name, pin=None):
            obj, body = super().read_json(name, pin)
            if name in self.edits:
                obj = copy.deepcopy(obj)
                self.edits[name](obj)
            return obj, body

    def reject(name, registry_edit=None, component_edit=None, local_edits=None):
        reg, comp = copy.deepcopy(registry), copy.deepcopy(component)
        if registry_edit:
            registry_edit(reg)
        if component_edit:
            component_edit(comp)
        subject = InjectedBuilder(local_edits or {})
        try:
            subject.verify_evidence_packet(comp, reg, reg["audit_prefix"], reg["files"], registry_body)
        except (ValueError, KeyError, TypeError) as exc:
            assert not subject.outputs
            return {"case": name, "rejected": True, "exception": type(exc).__name__, "reason": str(exc)}
        raise AssertionError("malformed metadata was accepted: " + name)

    negatives = [
        reject("payload_batch_disconnected_base", registry_edit=lambda reg:
               reg["materialization_originals"]["payload_create_tree_batches"][1].__setitem__("base_tree_sha", "0" * 40)),
        reject("payload_batch_duplicate_path", registry_edit=lambda reg:
               reg["materialization_originals"]["payload_create_tree_batches"][0]["paths"].__setitem__(
                   1, reg["materialization_originals"]["payload_create_tree_batches"][0]["paths"][0])),
        reject("payload_batch_wrong_actual_Merkle", registry_edit=lambda reg:
               reg["materialization_originals"]["payload_create_tree_batches"][0]["full_tool_return"]["structuredContent"].__setitem__("sha", "1" * 40)),
        reject("receipt_first_batch_wrong_payload_parent", registry_edit=lambda reg:
               reg["materialization_originals"]["receipt_create_tree_batches"][0].__setitem__("base_tree_sha", "2" * 40)),
        reject("payload_full_GET_record_missing", local_edits={
            directory + "/registration-payloads-026.actual.json": lambda obj: obj["records"].pop()}),
        reject("receipt_batch_original_array_not_equal", local_edits={
            directory + "/registration-receipts-GET-000.local-sidecar.json":
            lambda obj: obj["all_receipt_create_batches_original"].pop()}),
        reject("last_receipt_sidecar_omitted", component_edit=lambda comp: comp["receipt_sidecars"].pop()),
        reject("arbitrary_glob_selector", component_edit=lambda comp:
               comp.__setitem__("receipt_sidecars", ["registration-receipts-GET-*.local-sidecar.json"])),
    ]
    assert (root / "prepare_third_post_audit_delta.py").read_bytes() == original
    assert (root / config_name).read_bytes() == config_raw
    output = {
        "schema": "hepta-staged-evidence-packet-adapter-partial-verification-v1",
        "result": "PASS", "scope": "Import 16 actual components only; no prepare(), C4 output, network, CI, ref or native operation.",
        "baseline": identity(original), "candidate": identity(candidate), "patch": identity(patch),
        "only_changed_AST_method": "Builder.verify_evidence_packet",
        "all_other_methods_and_module_logic_unchanged": True,
        "forward_reverse_patch_commands": patch_commands,
        "original_config": identity(config_raw),
        "candidate_config": identity((here / "components.partial.json").read_bytes()),
        "only_config_addition": {"component": component["name"], "receipt_sidecars": component["receipt_sidecars"]},
        "component_results": before_sizes, "components": len(before_sizes),
        "evidence_paths": len(builder.evidence),
        "unique_evidence_blobs": len({v["git_blob"] for v in builder.evidence.values()}),
        "read_and_rehashed_inputs": len(builder.inputs),
        "payload_tree": registry["materialization_Merkle_proof"]["final_payload_tree"],
        "payload_and_receipt_tree": registry["materialization_Merkle_proof"]["final_payload_and_receipt_tree"],
        "staged_phase_counts": [p["new_paths"] for p in registry["materialization_Merkle_proof"]["phases"]],
        "negative_controls": negatives, "root_preparer_and_config_unchanged": True,
        "all_read_inputs_rehashed_unchanged": True,
        "tree_full_GET_claimed": False, "whole_candidate_or_native_acceptance_granted": False,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2) + "\n", end="")


if __name__ == "__main__":
    assert len(sys.argv) == 2
    main(Path(sys.argv[1]).resolve(), Path(__file__).resolve().parent)
