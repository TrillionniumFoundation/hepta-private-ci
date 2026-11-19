"""Reject numerical/model execution dependencies before audit imports."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORTS = {"numpy", "scipy", "torch", "jax", "tensorflow"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__"}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_python(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".")[0] for alias in node.names}
            if names & FORBIDDEN_IMPORTS:
                raise ValueError(f"forbidden import in {path}")
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.split(".")[0] in FORBIDDEN_IMPORTS:
                raise ValueError(f"forbidden import in {path}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_CALLS:
                raise ValueError(f"forbidden call in {path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads((args.package / "REQUEST.json").read_text())
    source = json.loads((args.package / "SOURCE.json").read_text())
    repository_root = args.package.parent.parent
    workflow = repository_root / ".github/workflows/hcsn-currentstate-n128-crossruntime-audit.yml"
    if sha256_file(workflow) != source["workflow_sha256"]:
        raise ValueError("workflow mismatch")
    actual = {}
    for relative, expected in source["files"].items():
        path = args.package / relative
        actual[relative] = sha256_file(path)
        if actual[relative] != expected:
            raise ValueError(f"source mismatch: {relative}")
        if path.suffix == ".py":
            inspect_python(path)
    if request["numerical_calls"] or request["model_calls"] or request["torch_operations"] or request["optimizer_updates"] or request["matrix_exponentials"]:
        raise ValueError("nonzero execution request")
    result = {
        "all_closed": False,
        "files": len(actual),
        "identity": request["identity"],
        "numerical_calls": 0,
        "optimizer_updates": 0,
        "qualification": False,
        "status": "PASS_PREIMPORT_READONLY_BYTE_AUDIT_ADMISSION_ONLY",
        "torch_operations": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
