"""Verify the exact implementation-independence review and bound sources."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_independence_review.review import (
    review_sources,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_independence_review"
EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-independence-review.yml": "f22557d43fb2e8d46edfb234039cf17ffc377b46702055d5b5eba318a36f1c4c",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/README.md": "77cfd86f7ff7abc0739f9360723922a5a56bd2bdb926a8af8295a235a367a2d2",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/REQUEST.json": "4f7e90cdb5901e32e23b335bb8d49c13f7599712564d4b61775e3f5e87054a50",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/__init__.py": "1ed935f05ef80bbf89072c2fafb9918ed48dc2c9af19155bd4a56379373f8c26",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/review.py": "d767f5a361200ffa200934bb603e3864d32355b8c833b46a5a826c0ddda01753",
    "qualification/hcsn_currentstate_n256_uniformization_independence_review/test_review.py": "9755e01b7bebfbc3299e035161708d2d4f5ff101bac9869465adf331aaa9cffc",
}
BOUND = {
    "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py": "0f686be417338f7aa102a8386171798b06a63689acdd043a69e95212655bf3f9",
    "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py": "4213f078e36cd3e296e9301df2d1788c3b9375cf7a911c73c0090fe500f5ab73",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py": "602dcedd5827a35fbee81b51687a8e8bc3f4038f519a308eef3e884d088e2be2",
    "qualification/hcsn_currentstate_n256_uniformization_provider_intent/REQUEST.json": "72cf751d50a43311cc5079e8fe35a5137eafa0f7fed6a0b1a0fcafec40a8b275",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/precision_policy.py": "7298330e00de24a4b823dcf62d344437d14f7f9643327489e81c557ed984ab08",
    "qualification/hcsn_currentstate_n256_uniformization_precision_policy/REQUEST.json": "efedc79f156094b00573db681bd934d0b1e426d667d0365315e0a81ec53edbcd"
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **BOUND}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact review/source mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != EXPECTED:
        raise SystemExit("source-freeze file map mismatch")
    request = json.loads((PACKAGE / "REQUEST.json").read_text())
    if (
        request["implementation_review_source_sha256"]
        != EXPECTED[
            "qualification/hcsn_currentstate_n256_uniformization_independence_review/review.py"
        ]
        or request["implementation_independence_passed"] is not True
        or request["external_reviewer_independence_certified"] is not False
        or request["provider_admitted"] is not False
        or request["numerical_execution_allowed"] is not False
        or request["execution_key"] is not None
        or request["n256_provider_calls"] != 0
    ):
        raise SystemExit("independence-review request gate mismatch")
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
    if not imported_roots <= {"ast", "hashlib", "dataclasses", "pathlib"}:
        raise SystemExit("review has non-standard import")
    result = review_sources(
        ROOT / "qualification/hcsn_currentstate_n256_sparse_dynamic_intent/sparse_dynamic.py",
        ROOT / "qualification/hcsn_currentstate_n256_independent_oracle_intent/independent_oracle.py",
        ROOT / "qualification/hcsn_currentstate_n256_uniformization_provider_intent/provider.py",
    )
    frozen_result = {
        "candidate_algorithm_family": result.candidate_algorithm_family,
        "exact_sources_distinct": result.exact_sources_distinct,
        "external_reviewer_independence_certified": result.external_reviewer_independence_certified,
        "implementation_independence_passed": result.implementation_independence_passed,
        "n256_provider_calls": result.n256_provider_calls,
        "oracle_algorithm_family": result.oracle_algorithm_family,
        "provider_admitted": result.provider_admitted,
        "provider_algorithm_family": result.provider_algorithm_family,
        "provider_standard_library_only": result.provider_standard_library_only,
        "tail_certificates_admitted": result.tail_certificates_admitted,
    }
    if frozen_result != freeze["frozen_result"]:
        raise SystemExit("frozen independence result mismatch")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_IMPLEMENTATION_INDEPENDENCE")


if __name__ == "__main__":
    main()
