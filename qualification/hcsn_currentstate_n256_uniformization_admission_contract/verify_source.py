"""Verify the exact provider-admission contract and its parent identities."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_admission_contract.admission_contract import (
    HASH_FIELDS,
    require_current_hold,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_admission_contract"
EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-admission-contract.yml": "307ecff23c90b1d789c0ad8d4fd213b21ea44d41231d9cba61c2cd4549831148",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/README.md": "b813bb4c4faf1b557c00f42dbbb4d995dfae828310e101c5e3e68e0add768024",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/REQUEST.json": "f23d01dfb08e5f6278b0dba6125f6c22cb0d5c08e80423ce810b65e46f53b3d7",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/__init__.py": "308f68f6560c054b1a41b9126edd266ee7f9cc5bd9fe6d15ab86761c4857ad46",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/admission_contract.py": "ebbfec0ad5f1c8756ffbbfd33a5511d98a83889efc8b5e85c00230fe14a05ad9",
    "qualification/hcsn_currentstate_n256_uniformization_admission_contract/test_contract.py": "622cee5d5aa478fecfeed02e047b7de219a0798433a9aff873ae448042aecf72",
}
BOUND = {
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py": "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json": "72cf751d50a43311cc5079e8fe35a5137eafa0f7fed6a0b1a0fcafec40a8b275",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py": "7298330e00de24a4b823dcf62d344437d14f7f9643327489e81c557ed984ab08",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/REQUEST.json": "efedc79f156094b00573db681bd934d0b1e426d667d0365315e0a81ec53edbcd",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/review.py": "d767f5a361200ffa200934bb603e3864d32355b8c833b46a5a826c0ddda01753",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/REQUEST.json": "4f7e90cdb5901e32e23b335bb8d49c13f7599712564d4b61775e3f5e87054a50",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **BOUND}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact admission-contract/source mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if request["provider_admission_contract_source_sha256"] != EXPECTED[
        "qualification/hcsn_currentstate_n256_uniformization_admission_contract/admission_contract.py"
    ]:
        raise SystemExit("admission-contract source identity mismatch")
    parent_expected = {
        "provider_source_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py"
        ],
        "provider_request_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json"
        ],
        "precision_policy_source_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py"
        ],
        "precision_policy_request_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_precision_policy/REQUEST.json"
        ],
        "implementation_review_source_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_independence_review/review.py"
        ],
        "implementation_review_request_sha256": BOUND[
            "qualification/hcsn_currentstate_n256_uniformization_independence_review/REQUEST.json"
        ],
    }
    if request["parent_identities"] != parent_expected:
        raise SystemExit("admission-contract parent map mismatch")
    if not require_current_hold(request):
        raise SystemExit("current request did not preserve HOLD")
    if (
        len(HASH_FIELDS) != freeze["frozen_result"]["required_future_hash_count"]
        or len(request["missing_external_evidence"])
        != freeze["frozen_result"]["missing_external_evidence_count"]
        or request["implementation_independence_passed"] is not True
        or request["external_reviewer_independence_certified"] is not False
        or request["provider_admitted"] is not False
        or request["n256_provider_calls"] != 0
        or request["numerical_execution_allowed"] is not False
        or request["execution_key"] is not None
    ):
        raise SystemExit("admission-contract frozen gate mismatch")
    tree = ast.parse((PACKAGE / "admission_contract.py").read_text())
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
    if not imported_roots <= {"hashlib", "json", "re", "dataclasses"}:
        raise SystemExit("admission contract has non-standard import")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_ADMISSION_CONTRACT")


if __name__ == "__main__":
    main()
