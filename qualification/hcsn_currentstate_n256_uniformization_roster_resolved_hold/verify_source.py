"""Verify exact roster originals and the separately frozen child HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_roster_resolved_hold.roster_hold import (
    REMAINING_FIELDS,
    validate_roster_resolved_hold,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = (
    ROOT / "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold"
)
EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-roster-resolved-hold.yml": "2149d1c856434ab34d9f209bc8098e390f122fdfaec9a5323b83c0c047b74646",
    "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/README.md": "3b870a18b5a767d02fffa2dff2ae63ca2bbec88a60b384036cc1777ba1e9862c",
    "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/REQUEST.json": "029402a1ac56d47c28939671ed083b1fec1780b4c60d3db4621a20fbd4a1eb13",
    "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/__init__.py": "13e1bac18287ee78732390fd8cc1f6c81658883375afd09873dc2f38f03688b2",
    "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/roster_hold.py": "54fd88a0c9f5b598c51fc8a9953f85afc528f04b25735c885120f1575bbabfaf",
    "qualification/hcsn_currentstate_n256_uniformization_roster_resolved_hold/test_roster_hold.py": "893c4797d5121523697dc278f1769a7c8b62f610fb2f1e83eec1e668c59ab043",
}
BOUND = {
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/admission_contract.py": "ebbfec0ad5f1c8756ffbbfd33a5511d98a83889efc8b5e85c00230fe14a05ad9",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json": "f23d01dfb08e5f6278b0dba6125f6c22cb0d5c08e80423ce810b65e46f53b3d7",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/review.py": "c98a37af47515038cc5574801241ed2cce7bf5c205aae2bb207acbcbe26d4860",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/REQUEST.json": "03f352e3aaf5eb299c3e30825f878829148a4aac48764654badbf23fa545060f",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/OPERATOR_ROSTER.json": "407e0227fe6bc50dc284993a8dcb7f7335c61f9e2399ad9d3bf4d7be5f031cbb",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/SEGMENT_ROSTER.jsonl": "c8326917f1a1dfbfb52b9794f2379b6ef4b6090d6f900b9b2e18da9c347306e1",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **BOUND}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact roster-resolved HOLD source mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    parent = json.loads(
        (
            ROOT
            / "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json"
        ).read_text()
    )
    roster = json.loads(
        (
            ROOT
            / "qualification/hcsn_currentstate_n256_operator_segment_roster/REQUEST.json"
        ).read_text()
    )
    if not validate_roster_resolved_hold(request, parent, roster):
        raise SystemExit("roster-resolved child did not preserve HOLD")
    if (
        request["parent_admission_request_sha256"]
        != BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json"
        ]
        or request["roster_request_sha256"]
        != BOUND[
            "qualification/hcsn_currentstate_n256_operator_segment_roster/REQUEST.json"
        ]
        or request["operator_roster_file_sha256"]
        != BOUND[
            "qualification/hcsn_currentstate_n256_operator_segment_roster/OPERATOR_ROSTER.json"
        ]
        or request["segment_roster_file_sha256"]
        != BOUND[
            "qualification/hcsn_currentstate_n256_operator_segment_roster/SEGMENT_ROSTER.jsonl"
        ]
        or len(REMAINING_FIELDS)
        != freeze["frozen_result"]["remaining_missing_external_evidence_count"]
        or sum(value is not None for value in request["evidence_state"].values())
        != freeze["frozen_result"]["resolved_evidence_count"]
        or sum(request["work_counts"].values())
        != freeze["frozen_result"]["work_calls"]
    ):
        raise SystemExit("roster-resolved frozen result mismatch")
    tree = ast.parse((PACKAGE / "roster_hold.py").read_text())
    imported_roots = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported_roots.update(
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported_roots != {"re"}:
        raise SystemExit("roster-resolved HOLD has an unapproved import")
    forbidden = {"expm", "expm_multiply", "solve_ivp", "backward", "step"}
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("roster-resolved HOLD exposes a forbidden call")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_ROSTER_RESOLVED_HOLD")


if __name__ == "__main__":
    main()
