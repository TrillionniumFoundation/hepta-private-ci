"""Independent static-source and result review; imports no candidate plan module."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


FORBIDDEN_IMPORTS = {"numpy", "scipy", "torch"}
FORBIDDEN_CALLS = {
    "expm",
    "solve_ivp",
    "backward",
    "step",
    "load_state_dict",
    "dump",
    "load",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def review(source_path, result_path):
    source_path = Path(source_path)
    result_path = Path(result_path)
    tree = ast.parse(source_path.read_text())
    imports = set()
    calls = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                calls.add(function.id)
            elif isinstance(function, ast.Attribute):
                calls.add(function.attr)
    if imports & FORBIDDEN_IMPORTS:
        raise ValueError("forbidden numerical import")
    if calls & FORBIDDEN_CALLS:
        raise ValueError("forbidden numerical call")

    result = json.loads(result_path.read_text())
    expected_counts = {
        "dynamic_runs": 0,
        "matrix_exponentials": 0,
        "oracle_numeric_calls": 0,
        "serializer_numeric_calls": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
        "training_runs": 0,
    }
    if (
        result["schema"] != "hcsn-n256-streaming-fullstate-static-plan-v1"
        or result["status"] != "PASS_STREAM_STORAGE_HOLD_DYNAMIC"
        or result["admission"] != "HOLD_NO_NUMERICAL_EXECUTION"
        or result["conceptual_fp64_coordinates"] != 18_225_028
        or result["conceptual_coordinate_denominator_unchanged"] is not True
        or result["preservation"]["storage_caps_satisfied"] is not True
        or result["execution_counts"] != expected_counts
        or result["largegrid_qualification"] is not False
        or result["all_closed"] is not False
    ):
        raise ValueError("static result contract")
    return {
        "schema": "hcsn-n256-streaming-fullstate-independent-review-v1",
        "status": "PASS_STATIC_REVIEW_HOLD_DYNAMIC",
        "source_sha256": digest(source_path),
        "result_sha256": digest(result_path),
        "imports": sorted(imports),
        "forbidden_imports_present": sorted(imports & FORBIDDEN_IMPORTS),
        "forbidden_calls_present": sorted(calls & FORBIDDEN_CALLS),
        "conceptual_fp64_coordinates": result["conceptual_fp64_coordinates"],
        "candidate_container_bytes": result["candidate_structured"]["container_bytes"],
        "oracle_payload_bytes": result["oracle_stream"]["payload_bytes"],
        "total_preserved_bytes": result["preservation"]["total_bytes"],
        "execution_counts": expected_counts,
        "largegrid_qualification": False,
        "all_closed": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    payload = json.dumps(review(args.source, args.result), indent=2, sort_keys=True) + "\n"
    if args.output:
        Path(args.output).write_text(payload)
    print(payload, end="")


if __name__ == "__main__":
    main()
