"""Zero-numerical-work admission checks for the N128 first-cycle source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n128-firstcycle-fullstate-20261112-c06d"
KEY = IDENTITY + "-001"
PARENT = "eaaac2a9bd0d3d637406af00b3cbb0ed0edcc1f0"


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
    package = root / "qualification/hcsn_currentstate_n128_firstcycle"
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
    candidate_tree = ast.parse((package / "candidate_cycle.py").read_text())
    oracle_tree = ast.parse((package / "oracle_cycle.py").read_text())
    run_tree = ast.parse((package / "run.py").read_text())
    first_candidate = ast.parse(
        (
            root / "qualification/hcsn_currentstate_n128_firststep/candidate_step.py"
        ).read_text()
    )
    first_oracle = ast.parse(
        (
            root / "qualification/hcsn_currentstate_n128_firststep/oracle_step.py"
        ).read_text()
    )
    if expm_calls(candidate_tree) or expm_calls(oracle_tree) or expm_calls(run_tree):
        raise ValueError("cycle source must use the frozen integral helpers")
    if len(expm_calls(first_candidate)) != 1 or len(expm_calls(first_oracle)) != 1:
        raise ValueError("candidate and oracle integral helper identity")
    oracle_imports = imports(oracle_tree)
    if any(
        name.startswith("qualification.hcsn_currentstate_n128_engineering")
        or name.endswith("candidate_step")
        or name.endswith("candidate_cycle")
        for name in oracle_imports
    ):
        raise ValueError("oracle imports candidate implementation")
    all_imports = imports(candidate_tree) | oracle_imports | imports(run_tree)
    if any(name == "torch" or name.startswith("torch.") for name in all_imports):
        raise ValueError("Torch is outside this bounded experiment")
    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "PASS_ZERO_NUMERICAL_WORK_STATIC_ADMISSION",
        "source_files": len(actual),
        "candidate_helper_expm_call_sites": 1,
        "oracle_helper_expm_call_sites": 1,
        "matrix_exponentials": 0,
        "dynamic_segments": 0,
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
