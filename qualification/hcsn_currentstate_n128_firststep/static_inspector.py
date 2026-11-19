"""Zero-numerical-work admission checks for the N128 first-step source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n128-firststep-fullstate-20261112-c06d"
KEY = IDENTITY + "-001"
PARENT = "df2da40353696a4bd2f23c9bb7efa92b5cbc4fbf"


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


def expm_calls(tree):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "expm"
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    package = root / "qualification/hcsn_currentstate_n128_firststep"
    request = json.loads((package / "REQUEST.json").read_text())
    source = json.loads((package / "SOURCE.json").read_text())
    actual = {name: digest(root / name) for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source inventory differs")
    if request["identity"] != IDENTITY or request["unique_execution_key"] != KEY:
        raise ValueError("request identity differs")
    if source["identity"] != IDENTITY or source["unique_execution_key"] != KEY:
        raise ValueError("source identity differs")
    if request["base_source_commit"] != PARENT or source["parent_head"] != PARENT:
        raise ValueError("parent head differs")
    candidate_tree = ast.parse((package / "candidate_step.py").read_text())
    oracle_tree = ast.parse((package / "oracle_step.py").read_text())
    compare_tree = ast.parse((package / "compare.py").read_text())
    run_tree = ast.parse((package / "run.py").read_text())
    candidate_imports = imports(candidate_tree)
    oracle_imports = imports(oracle_tree)
    all_imports = (
        candidate_imports | oracle_imports | imports(compare_tree) | imports(run_tree)
    )
    if len(expm_calls(candidate_tree)) != 1 or len(expm_calls(oracle_tree)) != 1:
        raise ValueError("candidate and oracle must each contain one expm call site")
    if any(
        name.startswith("qualification.hcsn_currentstate_n128_engineering")
        for name in oracle_imports
    ):
        raise ValueError("oracle imports candidate implementation")
    if any(name == "torch" or name.startswith("torch.") for name in all_imports):
        raise ValueError("Torch is outside this bounded experiment")
    if "subprocess" in all_imports:
        raise ValueError("numerical child orchestration belongs to the workflow")
    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "PASS_ZERO_NUMERICAL_WORK_STATIC_ADMISSION",
        "source_files": len(actual),
        "candidate_expm_call_sites": 1,
        "oracle_expm_call_sites": 1,
        "matrix_exponentials": 0,
        "dynamic_packet_steps": 0,
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
