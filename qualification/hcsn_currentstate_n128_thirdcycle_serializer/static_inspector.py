"""Pre-import inspector for the actual-parent third-cycle serializer stage."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


PACKAGE = Path("qualification/hcsn_currentstate_n128_thirdcycle_serializer")
EXPECTED_PARENT = "5862357788c822f90aa89d488bd496c24e8ed492"
EXPECTED_KEY = "hcsn-n128-thirdcycle-serializer-20261113-c06d-001"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    source = json.loads((root / PACKAGE / "SOURCE.json").read_text())
    request = json.loads((root / PACKAGE / "REQUEST.json").read_text())
    if request["base_source_commit"] != EXPECTED_PARENT or request["unique_execution_key"] != EXPECTED_KEY:
        raise ValueError("frozen identity")
    if request["dynamic_segments"] or request["matrix_exponentials"] or request["torch_operations"] or request["optimizer_updates"]:
        raise ValueError("zero-execution stage")
    actual = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source bytes")
    if actual[str(PACKAGE / "START.bin")] != request["parent_capsule_sha256"]:
        raise ValueError("parent capsule bytes")
    forbidden = {"numpy", "scipy", "torch"}
    for name in source["python_sources"]:
        tree = ast.parse((root / name).read_text(), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = {node.module.split(".")[0]}
            else:
                continue
            if imported & forbidden:
                raise ValueError(f"numerical import forbidden in {name}")
    result = {"all_closed": False, "comparison_coordinates": request["comparison_coordinates"], "dynamic_segments": 0, "identity": request["identity"], "matrix_exponentials": 0, "optimizer_updates": 0, "parent_capsule_sha256": request["parent_capsule_sha256"], "qualification": False, "source_files": len(actual), "status": "PASS_STATIC_THIRDCYCLE_SERIALIZER_ADMISSION_ONLY", "torch_operations": 0, "unique_execution_key": request["unique_execution_key"]}
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
