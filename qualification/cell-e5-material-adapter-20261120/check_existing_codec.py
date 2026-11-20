"""Check unchanged pure codec parsing against bound original four reference functions."""

import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace


def main(root, provenance, output):
    codec_path = provenance / "replacement_codec.py"
    bindings_path = provenance / "old-four-BINDINGS.json"
    assert hashlib.sha256(codec_path.read_bytes()).hexdigest() == "e1147a8d02624ca87b4a1f2f3345b034664b11b074f29787cb4b34085d4058c3"
    assert hashlib.sha256(bindings_path.read_bytes()).hexdigest() == "e31e0b541cf37be504c4a045e3c0c46ad8052feebd0f0e1c908b1de5b3ea3266"
    spec = importlib.util.spec_from_file_location("unchanged_pure_replacement_codec", codec_path)
    codec = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(codec)
    bindings = json.loads(bindings_path.read_bytes())
    targets = {x["project_id"]: (x["path"], x["function"], x["optional_constant"]) for x in bindings}

    def constant_name(node):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            return node.target.id
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            return node.targets[0].id
        return None

    # Only parse_payload is called. This trusted-target proxy does not execute
    # native_module(), source_binding(), action_from_bound_before() or verify().
    bound_target = SimpleNamespace(TARGETS=targets, constant_name=constant_name)
    materials = [json.loads(x.read_bytes()) for x in sorted((root / "materials").glob("*.json"))]
    results = []
    for binding in bindings:
        row = next(x for x in materials if x["project_id"] == binding["project_id"])
        patch = next(x for x in row["runtime_patches"] if x["path"] == binding["path"])
        before = (root / "blobs" / patch["before"]["sha256"]).read_bytes()
        after = (root / "blobs" / patch["after"]["sha256"]).read_bytes()
        assert hashlib.sha256(before).hexdigest() == binding["original_source_sha256"]
        old = binding["function_old"]
        assert hashlib.sha256(old.encode()).hexdigest() == binding["function_old_sha256"]
        before_text, after_text = before.decode(), after.decode()
        assert before_text.count(old) == 1 and before_text.index(old) == binding["function_start_character"]
        tree = ast.parse(after_text)
        functions = [x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == binding["function"]]
        assert len(functions) == 1
        function = codec.node_span(after_text, functions[0])[2]
        constants = [x for x in tree.body if binding["optional_constant"] and constant_name(x) == binding["optional_constant"]]
        constant = codec.node_span(after_text, constants[0])[2] if constants else ""
        answer = "```python\n" + function + constant + "```\n"
        parsed_function, parsed_constant = codec.parse_payload(row["project_id"], answer, bound_target)
        reconstructed = before_text.replace(old, parsed_function, 1)
        if parsed_constant:
            anchor = binding["constant_slot"]["anchor_old"]
            assert reconstructed.count(anchor) == 1
            reconstructed = reconstructed.replace(anchor, parsed_constant + anchor, 1)
        assert reconstructed.encode() == after
        results.append({"project_id": row["project_id"], "pure_original_parser_accepted": True,
                        "exact_after_reconstruction": True, "raw_reference_payload_bytes": len(answer.encode()),
                        "original_maximum_raw_bytes": codec.MAXIMUM_RAW_BYTES})
    result = {"schema": "hepta.e5-existing-codec-reference-readback.v1", "sources": results,
              "scope": "Unchanged pure parser plus frozen original four target proxy; full native codec guard and verifier not invoked",
              "new_native_children": 0, "model_calls": 0, "training_updates": 0,
              "new_projects_admitted_to_old_codec": 0, "gradient_execution_admitted": False}
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    main(args.root, args.provenance, args.output)
