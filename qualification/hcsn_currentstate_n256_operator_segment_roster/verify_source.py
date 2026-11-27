"""Verify exact source, originals, canonical rosters, and preserved HOLD."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_operator_segment_roster import review


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_operator_segment_roster"
EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-operator-segment-roster.yml": "87145549d4f263b9162731014caf6d04540ee2000d23c43046f5c0ef1695f8cf",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/OPERATOR_ROSTER.json": "407e0227fe6bc50dc284993a8dcb7f7335c61f9e2399ad9d3bf4d7be5f031cbb",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/README.md": "819fc92c60ab5b98ca2ec9ce45c95b20f7fe4a987ad41b9a387e240dcd7c5d89",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/REQUEST.json": "03f352e3aaf5eb299c3e30825f878829148a4aac48764654badbf23fa545060f",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/SEGMENT_ROSTER.jsonl": "c8326917f1a1dfbfb52b9794f2379b6ef4b6090d6f900b9b2e18da9c347306e1",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/__init__.py": "3e53483d2d645d77bf989dd653f5f4a55dab837f89daa5e09e95ca7e4b1ff077",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/review.py": "c98a37af47515038cc5574801241ed2cce7bf5c205aae2bb207acbcbe26d4860",
    "qualification/hcsn_currentstate_n256_operator_segment_roster/test_review.py": "5eb2dd96d08154df7e4174ed0759a2d30344d5b35e62a8a4c552e04c751d3711",
}
BOUND = {
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/admission_contract.py": "ebbfec0ad5f1c8756ffbbfd33a5511d98a83889efc8b5e85c00230fe14a05ad9",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json": "f23d01dfb08e5f6278b0dba6125f6c22cb0d5c08e80423ce810b65e46f53b3d7",
    "qualification/hcsn_currentstate_n256_engineering/candidate.py": "91c55d87fd993c9d01d1b1e98ba855bf171dfd74f2bdc12bd94fc23d9dc7a9d3",
    "qualification/hcsn_currentstate_n128_engineering/candidate.py": "0152e168cd3c5581517522b972276f6317c907eb740a09adb5219a9e820a09ad",
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/SUMMARY.json": "e3e21bd9f21940e22738b8f06b9b50333d82a923a6d46894316c242b88dd122f",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/PACKET_ROSTER.jsonl": "cc5a9199c076215d2f808f0974cc201d34954eafebafea1bf955c929eb36dc1c",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/CAPSULES.json": "eebc5a010c935c9ca5fc3daaa1716733907f34039c7e3ae4e4bf8fff8ef441f8",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/EVENTS.jsonl": "e84d6ca273236341f6bd138bff9c199758fb8cf4ed43a0550ca3e77ff8076d0a",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **BOUND}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact operator/segment roster source mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    admission = json.loads(
        (
            ROOT
            / "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json"
        ).read_text()
    )
    operators = json.loads((PACKAGE / "OPERATOR_ROSTER.json").read_text())
    segments = [
        json.loads(line)
        for line in (PACKAGE / "SEGMENT_ROSTER.jsonl").read_text().splitlines()
    ]
    if (
        review._digest(review._canonical(operators))
        != request["operator_roster_sha256"]
        or review._digest(review._canonical(segments))
        != request["segment_roster_sha256"]
        or request["operator_roster_sha256"]
        != review.EXPECTED_OPERATOR_ROSTER_SHA256
        or request["segment_roster_sha256"]
        != review.EXPECTED_SEGMENT_ROSTER_SHA256
    ):
        raise SystemExit("canonical operator/segment roster identity mismatch")
    counts = request["work_counts"]
    if (
        len(operators) != counts["unique_operators"]
        or counts["unique_operators"] != 4
        or len(segments) != counts["transition_segments"]
        or counts["transition_segments"] != 45
        or sum(item["nnz"] for item in operators) != counts["operator_nnz"]
        or sum(item["csr_bytes"] for item in operators)
        != counts["unique_sparse_operator_bytes"]
        or sum(len(item["emitted"]) for item in segments)
        != counts["emitted_templates"]
        or any(counts[name] != 0 for name in (
            "dynamic_calls",
            "matrix_exponential_calls",
            "model_calls",
            "optimizer_calls",
            "oracle_calls",
            "provider_calls",
            "serializer_calls",
            "torch_calls",
        ))
        or request["numerical_execution_allowed"] is not False
        or request["provider_admitted"] is not False
        or request["largegrid_qualification"] is not False
        or request["all_closed"] is not False
        or request["execution_key"] is not None
    ):
        raise SystemExit("operator/segment roster HOLD or count mismatch")
    if (
        admission["missing_external_evidence"]["operator_roster_sha256"]
        is not None
        or admission["missing_external_evidence"]["segment_roster_sha256"]
        is not None
        or admission["provider_admitted"] is not False
        or admission["numerical_execution_allowed"] is not False
        or admission["execution_key"] is not None
    ):
        raise SystemExit("parent provider-admission HOLD was rewritten")
    tree = ast.parse((PACKAGE / "review.py").read_text())
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
    if not imported_roots <= {
        "collections",
        "dataclasses",
        "fractions",
        "hashlib",
        "json",
        "pathlib",
        "qualification",
    }:
        raise SystemExit("operator/segment review has an unapproved import")
    forbidden = {"expm", "expm_multiply", "solve_ivp", "backward", "step"}
    names = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    names.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name))
    if names & forbidden:
        raise SystemExit("operator/segment review exposes a forbidden call")
    print("PASS_CURRENTSTATE_N256_OPERATOR_SEGMENT_ROSTER")


if __name__ == "__main__":
    main()
