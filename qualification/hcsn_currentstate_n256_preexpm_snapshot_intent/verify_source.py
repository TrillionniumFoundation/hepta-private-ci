"""Verify the frozen source and all exact inputs without numerical execution."""

import ast
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stream_body(path):
    tree = ast.parse(path.read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_stream_action"
    )
    return ast.dump(ast.Module(body=function.body[:-1], type_ignores=[]), include_attributes=False)


def verify():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    if request["identity"] != freeze["identity"]:
        raise ValueError("identity")
    if request["parent_head"] != freeze["parent_head"]:
        raise ValueError("parent")
    for category in ("source", "bound_dependencies"):
        for relative, expected in freeze[category].items():
            if _sha(ROOT / relative) != expected:
                raise ValueError(f"frozen bytes: {relative}")
    oracle = ROOT / (
        "qualification/hcsn_currentstate_n256_firststep_dense_oracle_source/"
        "dense_oracle.py"
    )
    candidate = ROOT / (
        "qualification/hcsn_currentstate_n256_dense_compatible_firststep_intent/"
        "candidate.py"
    )
    if _stream_body(oracle) != _stream_body(candidate):
        raise ValueError("current stream-action bodies diverge")
    if request["work"] != {
        "boundary_decodes": 3,
        "preexpm_augmented_builds": 6,
        "preexpm_seed_builds": 6,
        "dynamic_steps": 0,
        "expm_actions": 0,
        "scipy_imports": 0,
        "torch_calls": 0,
        "optimizer_steps": 0,
    }:
        raise ValueError("work denominator")
    if freeze["source_branch_execution_count"] != 0:
        raise ValueError("source branch executed")
    if freeze["cause_of_6901_red"] != "UNKNOWN" or freeze["all_closed"] is not False:
        raise ValueError("historical state")
    return {
        "status": "SOURCE_FROZEN",
        "frozen_source_files": len(freeze["source"]),
        "bound_dependency_files": len(freeze["bound_dependencies"]),
        "stream_action_ast_equal": True,
        "source_branch_execution_count": 0,
        "all_closed": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
