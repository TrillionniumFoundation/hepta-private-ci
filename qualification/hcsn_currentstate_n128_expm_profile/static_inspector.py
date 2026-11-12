"""Zero-numerical-work admission checks for the N128 expm profile source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n128-expm-resource-profile-20261112-c06d"
KEY = IDENTITY + "-002-after-preimport-red"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    package = root / "qualification/hcsn_currentstate_n128_expm_profile"
    request = json.loads((package / "REQUEST.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
    actual = {name: digest(root / name) for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source inventory differs")
    if request["identity"] != IDENTITY or request["unique_execution_key"] != KEY:
        raise ValueError("request identity differs")
    if source["identity"] != IDENTITY or source["unique_execution_key"] != KEY:
        raise ValueError("source identity differs")
    if request["base_source_commit"] != source["parent_head"]:
        raise ValueError("parent head differs")
    if request["operator_identities"] != source["operator_identities"]:
        raise ValueError("operator identities differ")
    tree = ast.parse((package / "profile.py").read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "expm"
    ]
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    if len(calls) != 1:
        raise ValueError("profile source must contain one looped expm call site")
    if {"torch", "subprocess"} & imports:
        raise ValueError("profile source imports a forbidden runtime")
    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "PASS_ZERO_NUMERICAL_WORK_STATIC_ADMISSION",
        "source_files": len(actual),
        "expm_call_sites": len(calls),
        "candidate_imports": 0,
        "matrix_exponentials": 0,
        "dynamic_packet_steps": 0,
        "oracle_calls": 0,
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
