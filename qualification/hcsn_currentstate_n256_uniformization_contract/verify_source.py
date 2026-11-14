"""Verify the exact frozen N256 stiffness contract and inherited originals."""

import ast
import hashlib
import json
from pathlib import Path

from qualification.hcsn_currentstate_n256_uniformization_contract.stiffness_review import (
    review_frozen_stiffness,
)


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "qualification/hcsn_currentstate_n256_uniformization_contract"
GENERATOR = ROOT / "qualification/hcsn_currentstate_n256_exact_generator_review"
ORIGINALS = ROOT / "qualification/hcsn_n256_new_export/evidence/attempt001"
EVENTS = ROOT / "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/EVENTS.jsonl"

EXPECTED = {
    ".github/workflows/hcsn-currentstate-n256-uniformization-contract.yml": "da457c82f32bfd2252e08ae15af3679007b1d341e4793074efc7fefa6fbd01f0",
    "qualification/hcsn_currentstate_n256_uniformization_contract/README.md": "bd95d943ccdea35e3ada1b51a1d0685349a06ad9ba4f4bbe3daa9b1a785c9721",
    "qualification/hcsn_currentstate_n256_uniformization_contract/REQUEST.json": "4931815ec2b24f292ec40e589e338809cca60f1af817e99d2ea6b4220ee0d255",
    "qualification/hcsn_currentstate_n256_uniformization_contract/SOURCE_FREEZE.json": "bd1d15eeac5bca1b796db98a63e96afe6b16980e68f9ad7a55e65594741c2d3d",
    "qualification/hcsn_currentstate_n256_uniformization_contract/__init__.py": "34d86e6686e0a573c4890a7975d41136ba9ed95e663bb48063272e49139afd24",
    "qualification/hcsn_currentstate_n256_uniformization_contract/stiffness_review.py": "4ead22435bc776a2266d0d051281b4a6960c5714888d930a64ca63e721ae8041",
    "qualification/hcsn_currentstate_n256_uniformization_contract/test_contract.py": "545af14904d882c11498d9e81f4989bad84047c2e9e6ffc32f158c2da97dfcb0",
}
INHERITED = {
    "qualification/hcsn_currentstate_n256_exact_generator_review/generator_review.py": "0beb616f348826e26591e60a4029b37b34091e257fbc5dd4c002409657c0e266",
    "qualification/hcsn_currentstate_n256_exact_generator_review/REQUEST.json": "e6af46b63a700a794997e7a620bb972bb2accd5ea032ffd8ba6c4c74ffb41908",
    "qualification/hcsn_currentstate_n256_roster/evidence/source-266dfe6/attempt001/EVENTS.jsonl": "e84d6ca273236341f6bd138bff9c199758fb8cf4ed43a0550ca3e77ff8076d0a",
    "qualification/hcsn_n256_new_export/evidence/attempt001/METADATA.json": "88e84dd3aea396d34c7e2dd08d31f2e30bf694c20516dccde57e6dd1b0c2a3c6",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.json": "360b4bf446e853209c58cdb3faded74d9114d872cfb9c730b220d14cef670f9c",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_PHASE.json": "790fabee8825dbd4361f157f56d78641430fe50b9134cd2cb7b02b51b93fe548",
    "qualification/hcsn_n256_new_export/evidence/attempt001/N256_STATE.npz.b64": "926191319021c51421dd15d76c66c3b5c6d2efef0f28af3f76c893065a49dbeb",
}


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path, expected in {**EXPECTED, **INHERITED}.items():
        if _digest(ROOT / path) != expected:
            raise SystemExit(f"exact source/input mismatch: {path}")
    freeze = json.loads((PACKAGE / "SOURCE_FREEZE.json").read_text())
    if freeze["files"] != {path: digest for path, digest in EXPECTED.items() if not path.endswith("SOURCE_FREEZE.json")}:
        raise SystemExit("source-freeze file map mismatch")
    source = (PACKAGE / "stiffness_review.py").read_text()
    tree = ast.parse(source)
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    imported.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    if imported & {"numpy", "scipy", "torch"}:
        raise SystemExit("numeric provider import present")
    for forbidden in ("expm_multiply", "sparse_dynamic_intent", "independent_oracle_intent"):
        if forbidden in source:
            raise SystemExit(f"forbidden provider reference: {forbidden}")
    certificate = review_frozen_stiffness(
        GENERATOR / "generator_review.py",
        GENERATOR / "REQUEST.json",
        EVENTS,
        ORIGINALS / "METADATA.json",
        ORIGINALS / "N256_STATE.json",
        ORIGINALS / "N256_PHASE.json",
        ORIGINALS / "N256_STATE.npz.b64",
    )
    expected_result = freeze["frozen_result"]
    actual_result = {
        "cold_segments": certificate.cold_segments,
        "generator_rows": certificate.generator_rows,
        "maximum_poisson_intensity_fraction": certificate.maximum_poisson_intensity_fraction,
        "maximum_segment_duration_fraction": certificate.maximum_segment_duration_fraction,
        "provider_admitted": certificate.provider_admitted,
        "ratio_tail_precondition_minimum_recurrence_terms": certificate.ratio_tail_precondition_minimum_recurrence_terms,
        "tail_certificates_admitted": certificate.tail_certificates_admitted,
        "transition_segments": certificate.transition_segments,
        "uniformization_rate_integer": certificate.uniformization_rate_integer,
    }
    if actual_result != expected_result:
        raise SystemExit("frozen stiffness result mismatch")
    if any(
        (
            certificate.dynamic_calls,
            certificate.matrix_exponential_calls,
            certificate.poisson_recurrence_calls,
            certificate.candidate_calls,
            certificate.oracle_calls,
            certificate.model_calls,
            certificate.optimizer_calls,
        )
    ):
        raise SystemExit("zero-work counter mismatch")
    print("PASS_CURRENTSTATE_N256_UNIFORMIZATION_CONTRACT")


if __name__ == "__main__":
    main()
