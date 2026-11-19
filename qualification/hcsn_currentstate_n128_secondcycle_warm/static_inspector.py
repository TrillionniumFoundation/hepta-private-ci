"""Zero-numerical-work admission checks for the N128 second-cycle source."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


IDENTITY = "hcsn-n128-secondcycle-warm-20261112-c06d"
KEY = IDENTITY + "-001"
PARENT = "85c73b040448bc58929e40118d533a5ea65705e2"
START_SHA256 = "833474bcdaf45c7787a2869fa86efbad2f8b22fdb0c88d0fbcbef1764f8a72a9"


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


def calls(tree, name):
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    package = root / "qualification/hcsn_currentstate_n128_secondcycle_warm"
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
    if digest(package / "START.bin") != START_SHA256:
        raise ValueError("#6282 terminal capsule differs")
    if (
        red["status"] != "KILLED_137_NO_RESULT"
        or red["cause"] != "UNKNOWN"
        or red["admission"] is not False
    ):
        raise ValueError("development RED was rewritten")
    candidate_tree = ast.parse((package / "candidate_warm.py").read_text())
    oracle_tree = ast.parse((package / "oracle_warm.py").read_text())
    run_tree = ast.parse((package / "run.py").read_text())
    helper_candidate = ast.parse(
        (
            root / "qualification/hcsn_currentstate_n128_firststep/candidate_step.py"
        ).read_text()
    )
    helper_oracle = ast.parse(
        (
            root / "qualification/hcsn_currentstate_n128_firststep/oracle_step.py"
        ).read_text()
    )
    if calls(candidate_tree, "expm") or calls(oracle_tree, "expm") or calls(run_tree, "expm"):
        raise ValueError("continuation must use frozen integral helpers")
    if len(calls(helper_candidate, "expm")) != 1 or len(calls(helper_oracle, "expm")) != 1:
        raise ValueError("candidate and oracle integral helper identity")
    oracle_imports = imports(oracle_tree)
    if any(
        name.startswith("qualification.hcsn_currentstate_n128_engineering")
        or name.endswith("candidate_step")
        or name.endswith("candidate_cycle")
        or name.endswith("candidate_warm")
        for name in oracle_imports
    ):
        raise ValueError("oracle imports candidate implementation")
    all_imports = imports(candidate_tree) | oracle_imports | imports(run_tree)
    if any(name == "torch" or name.startswith("torch.") for name in all_imports):
        raise ValueError("Torch is outside this bounded experiment")
    if calls(candidate_tree, "coordinate_lines") or calls(run_tree, "coordinate_lines"):
        raise ValueError("unbounded coordinate materialization reintroduced")
    result = {
        "identity": IDENTITY,
        "unique_execution_key": KEY,
        "status": "PASS_ZERO_NUMERICAL_WORK_STATIC_ADMISSION",
        "source_files": len(actual),
        "preserved_development_red": True,
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
