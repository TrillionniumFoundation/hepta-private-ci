#!/usr/bin/env python3
"""Cross-owner contract test for control.engineering -> learning.plasticity.

The canonical MutationGrammarManifestV1 remains owned by control.engineering.
learning.plasticity consumes only an artifact/window-bound parameter projection
whose digest is carried through generation, coverage and the Agentd coordinator.
This test intentionally inspects both the canonical registry and the native Rust
projection so either side cannot drift while the other side still compiles.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "docs/readiness/PROTOCOLS.json"
POLICY = ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
GENERATOR = ROOT / "codex-rs/hepta-plasticity/src/generator_v3.rs"
COVERAGE = ROOT / "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs"
COORDINATOR = ROOT / "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs"


class MutationGrammarProjectionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
        protocols = {
            protocol["id"]: protocol for protocol in registry.get("protocols", [])
        }
        cls.protocol = protocols["MutationGrammarManifestV1"]
        cls.policy = POLICY.read_text(encoding="utf-8")
        cls.generator = GENERATOR.read_text(encoding="utf-8")
        cls.coverage = COVERAGE.read_text(encoding="utf-8")
        cls.coordinator = COORDINATOR.read_text(encoding="utf-8")

    def test_canonical_owner_consumer_and_authority_are_unambiguous(self) -> None:
        protocol = self.protocol
        self.assertEqual(protocol["owner"], "control.engineering")
        self.assertIn("learning.plasticity", protocol["consumers"])
        self.assertEqual(protocol["canonicalEncoding"], "canonical_json_utf8")
        self.assertTrue(protocol["denyUnknownCriticalFields"])
        self.assertEqual(protocol["authorityDelta"], "none")
        self.assertIn("authority_delta_none", protocol["invariants"])
        self.assertIn("semantic_digest_stable", protocol["invariants"])

    def test_manifest_exposes_one_required_semantic_digest(self) -> None:
        semantic_fields = [
            field
            for field in self.protocol["fields"]
            if field.get("name") == "semanticDigest"
        ]
        self.assertEqual(len(semantic_fields), 1)
        self.assertEqual(semantic_fields[0]["type"], "sha256")
        self.assertTrue(semantic_fields[0]["required"])

    def test_native_projection_binds_context_and_protected_surfaces(self) -> None:
        required_policy_tokens = (
            "pub mutation_grammar_digest: Digest32",
            "pub selected_artifact_digest: Digest32",
            "pub window: ProposalWindowV2",
            "ParameterMutationSurfaceV1::LearnableParameter",
            "Self::Authority",
            "Self::Evaluator",
            "Self::Deletion",
            "Self::RuntimeTopology",
            "Self::Credential",
            "ParameterMutationPolicyErrorV1::ProtectedSurface",
            "ParameterMutationPolicyErrorV1::ArtifactMismatch",
            "ParameterMutationPolicyErrorV1::WindowMismatch",
        )
        for token in required_policy_tokens:
            self.assertIn(token, self.policy)

    def test_generation_coverage_and_product_coordinator_share_digest(self) -> None:
        self.assertIn("verify_parameter_mutation_policy_v1", self.generator)
        self.assertIn("authorize_parameter_mutation_v1", self.generator)
        self.assertIn(
            "profile.mutation_policy.mutation_grammar_digest",
            self.coverage,
        )
        self.assertIn(
            "request.envelope.grammar_digest\n            != product.generator_profile.mutation_policy.mutation_grammar_digest",
            self.coordinator,
        )
        self.assertIn(
            "coverage_draft.mutation_grammar_digest != request.envelope.grammar_digest",
            self.coordinator,
        )


if __name__ == "__main__":
    unittest.main()
