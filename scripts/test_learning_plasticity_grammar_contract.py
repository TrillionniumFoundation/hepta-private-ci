#!/usr/bin/env python3
"""Cross-module contract test for control.engineering mutation grammar projection.

The canonical JSON protocol is owned by control.engineering. learning.plasticity
consumes exactly its required SHA-256 semanticDigest as an integrity/provenance
binding, then applies an artifact/window-scoped typed allowlist. This test prevents
schema drift from turning the digest into an optional, differently encoded or
authority-bearing value and prevents the native projection/coordinator from silently
stopping consumption of that field.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTOCOLS = ROOT / "docs/readiness/PROTOCOLS.json"
POLICY = ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
COORDINATOR = ROOT / "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs"


class MutationGrammarProjectionContractTest(unittest.TestCase):
    def canonical_protocol(self) -> dict:
        registry = json.loads(PROTOCOLS.read_text(encoding="utf-8"))
        matches = [
            item
            for item in registry["protocols"]
            if item.get("id") == "MutationGrammarManifestV1"
        ]
        self.assertEqual(len(matches), 1, "canonical grammar protocol must be unique")
        return matches[0]

    def test_control_engineering_schema_exposes_one_required_semantic_digest(self) -> None:
        protocol = self.canonical_protocol()
        self.assertEqual(protocol["owner"], "control.engineering")
        self.assertIn("learning.plasticity", protocol["consumers"])
        self.assertEqual(protocol["canonicalEncoding"], "canonical_json_utf8")
        self.assertIs(protocol["denyUnknownCriticalFields"], True)
        self.assertEqual(protocol["authorityDelta"], "none")

        semantic = [
            field for field in protocol["fields"] if field.get("name") == "semanticDigest"
        ]
        self.assertEqual(len(semantic), 1)
        self.assertEqual(
            semantic[0],
            {
                "name": "semanticDigest",
                "type": "sha256",
                "required": True,
                "maxBytes": 64,
            },
        )
        self.assertIn("semantic_digest_stable", protocol["invariants"])
        self.assertIn("unknown_critical_fields_rejected", protocol["invariants"])
        self.assertIn("authority_delta_none", protocol["invariants"])

    def test_native_projection_consumes_digest_once_and_binds_policy_identity(self) -> None:
        source = POLICY.read_text(encoding="utf-8")
        self.assertEqual(
            len(re.findall(r"pub mutation_grammar_digest: Digest32", source)), 1
        )
        self.assertIn(
            "bytes.extend_from_slice(policy.mutation_grammar_digest.as_array());",
            source,
        )
        self.assertIn(
            "ParameterMutationPolicyErrorV1::EmptyMutationGrammar", source
        )
        self.assertIn(
            "rule.surface != ParameterMutationSurfaceV1::LearnableParameter", source
        )

    def test_iteration_envelope_grammar_must_equal_native_projection(self) -> None:
        source = COORDINATOR.read_text(encoding="utf-8")
        binding = re.compile(
            r"request\.generator_profile\.mutation_policy\.mutation_grammar_digest\s*"
            r"!=\s*iteration\.envelope\.grammar_digest"
        )
        self.assertRegex(source, binding)
        self.assertIn(
            'Binding(\n                "iteration objective or mutation grammar",',
            source,
        )


if __name__ == "__main__":
    unittest.main()
