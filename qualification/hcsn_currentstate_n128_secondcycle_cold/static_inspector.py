"""Zero-numerical-work admission checks for canonical coarse/cold controls."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n128-secondcycle-coarse-cold-20261113-c06d"
KEY = IDENTITY + "-001"
PARENT = "1bf14200490e5b3ca989c092ec170f03f5f16a18"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imports(tree):
    result = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    result.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    package = root / "qualification/hcsn_currentstate_n128_secondcycle_cold"
    request = json.loads((package / "REQUEST.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
    red = json.loads((package / "DEVELOPMENT-RED.json").read_text())
    actual = {name: digest(root / name) for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source inventory differs")
    if request["identity"] != IDENTITY or request["unique_execution_key"] != KEY:
        raise ValueError("request identity differs")
    if source["identity"] != IDENTITY or source["unique_execution_key"] != KEY:
        raise ValueError("source identity differs")
    if request["base_source_commit"] != PARENT or source["parent_head"] != PARENT:
        raise ValueError("parent head differs")
    reference = package / "reference"
    if {name: digest(reference / name) for name in request["reference_capsules"]} != request["reference_capsules"]:
        raise ValueError("#6283 reference capsule differs")
    if len(red["attempts"]) != 2 or red["attempts"][1]["status"] != "DIRECT_SLICE_INVARIANCE_NOT_PASSED":
        raise ValueError("development RED was rewritten")
    candidate_tree = ast.parse((package / "candidate_lane.py").read_text())
    oracle_tree = ast.parse((package / "oracle_lane.py").read_text())
    run_tree = ast.parse((package / "run.py").read_text())
    oracle_imports = imports(oracle_tree)
    if any("candidate" in name for name in oracle_imports):
        raise ValueError("oracle imports candidate implementation")
    all_imports = imports(candidate_tree) | oracle_imports | imports(run_tree)
    if any(name == "torch" or name.startswith("torch.") for name in all_imports):
        raise ValueError("Torch is outside this bounded experiment")
    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "PASS_ZERO_NUMERICAL_WORK_STATIC_ADMISSION",
        "source_files": len(actual),
        "preserved_development_red_attempts": 2,
        "dynamic_segments": 0,
        "matrix_exponentials": 0,
        "coordinate_comparisons": 0,
        "torch_operations": 0,
        "optimizer_updates": 0,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
