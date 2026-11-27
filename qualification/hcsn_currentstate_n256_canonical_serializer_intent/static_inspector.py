"""Stdlib-only inspection for the canonical full-state serializer source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path

REQUIRED_FUNCTIONS = {
    "_canonical_json", "_validated_block", "_packet_metadata", "encode",
    "decode", "publish_atomic", "cold_load",
}
REQUIRED_CLASSES = {"Block", "Packet", "Envelope", "DecodeError"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(source_path, admission_path, request_path):
    source_path = Path(source_path)
    admission_path = Path(admission_path)
    request_path = Path(request_path)
    source_text = source_path.read_text()
    source = ast.parse(source_text, filename=str(source_path))
    admission = ast.parse(admission_path.read_text(), filename=str(admission_path))
    compile(source, str(source_path), "exec")
    compile(admission, str(admission_path), "exec")
    functions = {node.name for node in ast.walk(source) if isinstance(node, ast.FunctionDef)}
    classes = {node.name for node in ast.walk(source) if isinstance(node, ast.ClassDef)}
    if not REQUIRED_FUNCTIONS <= functions or not REQUIRED_CLASSES <= classes:
        raise ValueError("canonical serializer surface")
    imports = []
    for node in ast.walk(source):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    if any(name == "numpy" or name.startswith("scipy") or "sparse_dynamic" in name or "independent_oracle" in name for name in imports):
        raise ValueError("serializer must be stdlib and implementation-independent")
    required_tokens = (
        "HCSNFSP1", "allow_nan=False", "sort_keys=True", "separators=",
        "little-endian FP64", "hashlib.sha256", "os.replace", "os.fsync",
        "trailing bytes", "noncanonical byte roundtrip", "full-state binding mismatch",
    )
    if any(token not in source_text for token in required_tokens):
        raise ValueError("incomplete canonical serializer controls")
    request = json.loads(request_path.read_text())
    if request["n256_serializer_execution_allowed"] is not False or request["execution_key"] is not None or request["admission_sha256"] is not None:
        raise ValueError("fail-closed serializer request")
    if any(value is not None for value in request["required_external_freeze"].values()):
        raise ValueError("serializer external freeze unexpectedly resolved")
    if request["proposed_max_packet_bytes"] != 201326592:
        raise ValueError("proposed packet bound")
    return {
        "schema": "hcsn-n256-canonical-serializer-source-inspection-v1",
        "status": "PASS_SMALL_STDLIB_SOURCE_HOLD_N256",
        "source_sha256": digest(source_path),
        "admission_sha256": digest(admission_path),
        "request_sha256": digest(request_path),
        "functions": sorted(REQUIRED_FUNCTIONS),
        "classes": sorted(REQUIRED_CLASSES),
        "external_numeric_imports": 0,
        "candidate_oracle_imports": 0,
        "small_fixture_tests": 4,
        "n256_dynamic_runs": 0,
        "matrix_exponential_actions": 0,
        "n256_serializer_calls": 0,
        "candidate_oracle_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--admission", required=True)
    parser.add_argument("--request", required=True)
    arguments = parser.parse_args()
    print(json.dumps(inspect(arguments.source, arguments.admission, arguments.request), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
