"""Verify the exact source-only precision policy and provider parent."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_precision_policy.precision_policy import (
    COMPONENT_FIELDS,
    ORIGINAL_SCALED_ERROR_LIMIT,
    REQUIRED_SCIENTIFIC_CERTIFICATIONS,
    outward_nonnegative_sum,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_precision_policy"
EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-precision-policy.yml": "fcfb0f9f3601fcade34fd7154d6d220fe2375423d3c3f6202bc7aa5e12ebd9bb",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/README.md": "323632c7a97d69bf99f7693df05a833a09c4729cb73e76e6c946242b15ec1f2f",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/REQUEST.json": "efedc79f156094b00573db681bd934d0b1e426d667d0365315e0a81ec53edbcd",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/__init__.py": "d85ca7548ff300c4cd461b5162b37c15ad67f4e28c34c6070db8b52a6e3f07fe",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py": "7298330e00de24a4b823dcf62d344437d14f7f9643327489e81c557ed984ab08",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/test_precision_policy.py": "dabc07048dc3372de1ce790e58f039c32d64b833b2ca9311676e7311332326f2",
}
PARENTS = {
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py": "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json": "72cf751d50a43311cc5079e8fe35a5137eafa0f7fed6a0b1a0fcafec40a8b275",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/SOURCE_FREEZE.json": "27ad5b29b87c9bfae91b812b23e4b9fe191ae4f649c96fed43fe5f24ba1543e3",
    "qualification/hcsn_currentstate_n256_uniformization_contract/stiffness_review.py": "4ead22435bc776a2266d0d051281b4a6960c5714888d930a64ca63e721ae8041"
}
ALLOWED_IMPORTS = {"hashlib", "json", "math", "dataclasses"}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **PARENTS}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact source/parent mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["precision_policy_source_sha256"]
        != EXPECTED[
            "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py"
        ]
        or request["provider_source_sha256"] != PARENTS[
            "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py"
        ]
        or request["numerical_execution_allowed"] is not False
        or request["provider_admitted"] is not False
        or request["certificate_records_admitted"] != 0
        or request["n256_provider_calls"] != 0
    ):
        raise SystemExit("precision-policy request is not fail closed")
    source = (PACKAGE / "precision_policy.py").read_text()
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
        raise SystemExit("precision policy has non-standard import")
    result = {
        "component_fields": len(COMPONENT_FIELDS),
        "example_outward_sum_fp64_hex": outward_nonnegative_sum((0.001,) * 5).hex(),
        "n256_provider_calls": 0,
        "original_scaled_error_limit_fp64_hex": ORIGINAL_SCALED_ERROR_LIMIT.hex(),
        "provider_admitted": False,
        "required_scientific_certifications": len(REQUIRED_SCIENTIFIC_CERTIFICATIONS),
        "tail_certificates_admitted": 0,
    }
    if result != freeze["frozen_result"]:
        raise SystemExit("frozen precision-policy result mismatch")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_PRECISION_POLICY")


if __name__ == "__main__":
    main()
