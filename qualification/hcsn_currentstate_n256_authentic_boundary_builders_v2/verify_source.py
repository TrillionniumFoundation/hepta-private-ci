"""Verify the complete v2 source freeze and its failure provenance."""

import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_authentic_boundary_builders_v2 import static_inspector


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def verify():
    request = json.loads((HERE / "REQUEST.json").read_text())
    freeze = json.loads((HERE / "SOURCE_FREEZE.json").read_text())
    if request["parent_commit"] != "acff46363f2543e1b62250edffdc5fe1255682fc":
        raise ValueError("parent attempt")
    repair = request["repair"]
    if repair["attempt001_result"] != "RED" or repair["attempt001_audit_status"] != "INCOMPLETE":
        raise ValueError("attempt001 provenance")
    if repair["attempt001_output_containers"] != 0 or request["future_attempt002_key"] is not None:
        raise ValueError("execution boundary")
    if request["execution_allowed"] or request["numerical_execution_allowed"]:
        raise ValueError("source-only boundary")
    for relative, expected in freeze["files"].items():
        if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
            raise ValueError(f"source identity: {relative}")
    static_inspector.verify()
    return "PASS_V2_SOURCE_FREEZE"


if __name__ == "__main__":
    print(verify())
