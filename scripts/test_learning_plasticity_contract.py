#!/usr/bin/env python3
"""Cross-module contract test for control.engineering -> learning.plasticity.

This test intentionally validates the canonical readiness registry and the native
projection together. A prose mention alone cannot satisfy the contract.
"""

from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "docs/readiness/PROTOCOLS.json"
POLICY_SOURCE = ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
GENERATOR_SOURCE = ROOT / "codex-rs/hepta-plasticity/src/generator_v3.rs"
SELF_ITERATION_SOURCE = ROOT / "codex-rs/hepta-agentd/src/plasticity_self_iteration.rs"


class MutationGrammarPlasticityContractTest(unittest.TestCase):
    def setUp(self) -> None:
        registry = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
        self.assertEqual(
            registry["schema"],
            "hepta.implementation-readiness-protocol-registry.v1",
        )
        matches = [
            protocol
            for protocol in registry["protocols"]
            if protocol.get("id") == "MutationGrammarManifestV1"
        ]
        self.assertEqual(len(matches), 1, "grammar protocol must be unique")
        self.protocol = matches[0]
        self.policy_source = POLICY_SOURCE.read_text(encoding="utf-8")
        self.generator_source = GENERATOR_SOURCE.read_text(encoding="utf-8")
        self.iteration_source = SELF_ITERATION_SOURCE.read_text(encoding="utf-8")

    def test_canonical_owner_consumer_and_authority_are_unambiguous(self) -> None:
        protocol = self.protocol
        self.assertEqual(protocol["owner"], "control.engineering")
        self.assertIn("learning.plasticity", protocol["consumers"])
        self.assertEqual(protocol["canonicalEncoding"], "canonical_json_utf8")
        self.assertTrue(protocol["denyUnknownCriticalFields"])
        self.assertEqual(protocol["authorityDelta"], "none")
        self.assertIn("semantic_digest_stable", protocol["invariants"])
        self.assertIn("unknown_critical_fields_rejected", protocol["invariants"])

        fields = {field["name"]: field for field in protocol["fields"]}
        semantic = fields["semanticDigest"]
        self.assertEqual(semantic["type"], "sha256")
        self.assertTrue(semantic["required"])
        self.assertEqual(semantic["maxBytes"], 64)

    def test_native_projection_requires_and_hashes_exact_semantic_digest(self) -> None:
        source = self.policy_source
        required_fragments = (
            "pub mutation_grammar_digest: Digest32",
            "EmptyMutationGrammar",
            "if mutation_grammar_digest.is_zero()",
            "bytes.extend_from_slice(policy.mutation_grammar_digest.as_array())",
            "policy.mutation_grammar_digest.is_zero()",
        )
        for fragment in required_fragments:
            self.assertIn(fragment, source)

        # The generator must verify the typed projection rather than accepting a
        # detached digest as authorization.
        self.assertIn("verify_parameter_mutation_policy_v1", self.generator_source)
        self.assertIn("authorize_parameter_mutation_v1", self.generator_source)
        self.assertIn("profile.mutation_policy.policy_digest", self.generator_source)

    def test_frozen_iteration_binds_same_grammar_digest(self) -> None:
        source = self.iteration_source
        self.assertIn("submission.envelope.grammar_digest", source)
        self.assertIn("coverage.mutation_grammar_digest", source)
        self.assertIn(
            "mutation_policy\n                .mutation_grammar_digest",
            source,
        )
        self.assertIn("frozen parameter iteration", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
