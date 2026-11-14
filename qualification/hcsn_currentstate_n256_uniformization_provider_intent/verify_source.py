"""Verify the exact source-only uniformization provider and bound parents."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_provider_intent.provider import (
    REQUIRED_CERTIFICATIONS,
    SparseSubgenerator,
    stable_poisson_window,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_provider_intent"

EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-provider-intent.yml": "1bf43f8008458f3e3a589202ea140d6361ea5f52fc1ea72b23235eaf06c57b13",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/README.md": "f6b8b0ee37bd596cd1bcda12ff89fc12940280b24eef284664dbd642d922e573",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json": "72cf751d50a43311cc5079e8fe35a5137eafa0f7fed6a0b1a0fcafec40a8b275",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/__init__.py": "df5a8bc65a23df18c9f30f1778ed6539de2f43567997472213560036a65c061b",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py": "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/test_provider.py": "299d7ec6b3a730b276fde18f9b56d8a4e3ba9f16bc18975331e75283529dc307",
}
PARENTS = {
    "qualification/hcsn_currentstate_n256_uniformization_contract/REQUEST.json": "f17c8e718686ce34cb984457facf3eae3b921824ec17bdfec3f39313d2314a90",
    "qualification/hcsn_currentstate_n256_uniformization_contract/SOURCE_FREEZE.json": "988bac11a1806fc797eb5b562c1b4b3ad63dd9a9861628ac29fefc1e4e31768f",
    "qualification/hcsn_currentstate_n256_uniformization_contract/stiffness_review.py": "4ead22435bc776a2266d0d051281b4a6960c5714888d930a64ca63e721ae8041",
    "qualification/hcsn_currentstate_n256_exact_generator_review/generator_review.py": "0beb616f348826e26591e60a4029b37b34091e257fbc5dd4c002409657c0e266",
    "qualification/hcsn_currentstate_n256_exact_generator_review/REQUEST.json": "e6af46b63a700a794997e7a620bb972bb2accd5ea032ffd8ba6c4c74ffb41908",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/EVENTS.jsonl": "e84d6ca273236341f6bd138bff9c199758fb8cf4ed43a0550ca3e77ff8076d0a",
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}
ALLOWED_IMPORTS = {"hashlib", "json", "math", "dataclasses", "pathlib"}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **PARENTS}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact source/input mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["provider_source_sha256"] != EXPECTED[
            "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py"
        ]
        or request["numerical_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["provider_admitted"] is not False
        or request["provider_admission_sha256"] is not None
        or request["n256_provider_calls"] != 0
        or request["tail_certificates_admitted"] != 0
        or any(value is not None for value in request["required_external_freeze"].values())
    ):
        raise SystemExit("source-only request is not fail closed")

    source = (PACKAGE / "provider.py").read_text()
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if not imports <= ALLOWED_IMPORTS:
        raise SystemExit("provider has a non-standard or inherited import")
    if any(
        isinstance(node, ast.FunctionDef) and node.name in {"run", "run_n256", "execute_n256"}
        for node in ast.walk(tree)
    ):
        raise SystemExit("provider exposes an N256 execution entry")

    operator = SparseSubgenerator.from_rows(
        (((0, -2.0), (1, 2.0)), ((1, 0.0),))
    )
    window = stable_poisson_window(13461.075, 13460)
    result = {
        "certification_claims_required": len(REQUIRED_CERTIFICATIONS),
        "large_stiffness_fixture_last_weight_hex": window.weights[-1].hex(),
        "large_stiffness_fixture_tail_upper_hex": window.tail_upper.hex(),
        "n256_provider_calls": 0,
        "provider_admitted": False,
        "provider_schema": request["provider_schema"],
        "synthetic_operator_identity": operator.identity,
        "tail_certificates_admitted": 0,
    }
    if result != freeze["frozen_result"]:
        raise SystemExit("frozen provider-source result mismatch")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_PROVIDER_SOURCE")


if __name__ == "__main__":
    main()
