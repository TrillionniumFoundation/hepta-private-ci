"""Pre-import admission inspector for the bounded third-cycle numerical stage."""

import argparse
import ast
import hashlib
import json
from pathlib import Path


PACKAGE = Path("qualification/hcsn_currentstate_n128_thirdcycle_numeric")
PARENT = "49d392fef517120195f5d52f51de199b3f86843d"
KEY = "hcsn-n128-thirdcycle-numeric-20261113-c06d-001"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def imports(path):
    result = set()
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(args.root)
    request = json.loads((root / PACKAGE / "REQUEST.json").read_text())
    source = json.loads((root / PACKAGE / "SOURCE.json").read_text())
    red = json.loads((root / PACKAGE / "DEVELOPMENT-RED.json").read_text())
    cost = json.loads((root / PACKAGE / "DEVELOPMENT-COST.json").read_text())
    if request["base_source_commit"] != PARENT or request["unique_execution_key"] != KEY:
        raise ValueError("frozen identity")
    if source["parent_head"] != PARENT or source["unique_execution_key"] != KEY:
        raise ValueError("source identity")
    actual = {name: digest(root / name) for name in source["source_sha256"]}
    if actual != source["source_sha256"]:
        raise ValueError("source inventory")
    if actual[str(PACKAGE / "START.bin")] != request["parent_capsule_sha256"]:
        raise ValueError("parent capsule bytes")
    if len(red["attempts"]) != 2 or [row["candidate_matrix_exponentials"] for row in red["attempts"]] != [18, 14]:
        raise ValueError("development failures missing")
    if red["precommitted"] or red["qualification"]:
        raise ValueError("development RED mislabeled")
    if not cost["post_development"] or cost["precommitted"] or cost["qualification"]:
        raise ValueError("development GREEN mislabeled")
    if request["parent_static_prospective_coordinates"] != 984136:
        raise ValueError("parent static negative changed")
    if request["comparison_coordinates_per_pair"] != 1151028:
        raise ValueError("complete denominator")
    if request["parent_static_omitted_pending_packets"] != 4:
        raise ValueError("omitted packet correction")
    candidate_imports = imports(root / PACKAGE / "candidate_numeric.py")
    oracle_imports = imports(root / PACKAGE / "oracle_numeric.py")
    if "qualification.hcsn_currentstate_n128_thirdcycle_numeric.oracle_numeric" in candidate_imports:
        raise ValueError("candidate imports oracle")
    if "qualification.hcsn_currentstate_n128_thirdcycle_numeric.candidate_numeric" in oracle_imports:
        raise ValueError("oracle imports candidate")
    if "qualification.hcsn_currentstate_n128_engineering.candidate" in oracle_imports:
        raise ValueError("oracle imports candidate core")
    if request["torch_operations"] or request["optimizer_updates"]:
        raise ValueError("unexpected training calls")
    result = {
        "all_closed": False,
        "comparison_coordinates_per_pair": request["comparison_coordinates_per_pair"],
        "development_red_attempts": len(red["attempts"]),
        "identity": request["identity"],
        "optimizer_updates": 0,
        "parent_static_prospective_coordinates": request["parent_static_prospective_coordinates"],
        "qualification": False,
        "source_files": len(actual),
        "status": "PASS_PREIMPORT_THIRDCYCLE_NUMERIC_ADMISSION_ONLY",
        "torch_operations": 0,
        "unique_execution_key": request["unique_execution_key"],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
