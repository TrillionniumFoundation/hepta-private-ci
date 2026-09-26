#!/usr/bin/env python3
"""Cross-module contract test for control.engineering → learning.plasticity.

This test proves that the canonical readiness protocol, the concrete
control.engineering producer and the Rust plasticity projection agree on one exact,
authority-free grammar semantic digest. It intentionally does not claim wire
round-trip equivalence between the Python manifest and Rust-native proposal types.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
CONTROL_ROOT = ROOT / "tools" / "hepta-engineering-control"
sys.path.insert(0, str(CONTROL_ROOT))

from control_engineering_v2.mutation_grammar import (  # noqa: E402
    PROTOCOL_AUTHORITY_DENY_LIST,
    build_mutation_grammar_manifest_v1,
    plasticity_projection_grammar_digest_v1,
)


class LearningPlasticityGrammarContractTests(unittest.TestCase):
    def protocol(self) -> dict[str, object]:
        registry = json.loads(
            (ROOT / "docs/readiness/PROTOCOLS.json").read_text(encoding="utf-8")
        )
        matches = [
            item
            for item in registry["protocols"]
            if item.get("id") == "MutationGrammarManifestV1"
        ]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def manifest(self, *, reverse: bool = False, maximum_candidates: int = 16):
        operations = ["bounded_delta", "split", "merge", "rewire"]
        paths = ["docs/security/**", "codex-rs/kernel/**"]
        checks = ["strict-clippy", "plasticity-contract", "agentd-process-e2e"]
        if reverse:
            operations.reverse()
            paths.reverse()
            checks.reverse()
        return build_mutation_grammar_manifest_v1(
            grammar_id="grammar:learning-plasticity:contract-v1",
            version=1,
            allowed_operations=operations,
            protected_path_globs=paths,
            maximum_files=32,
            maximum_text_bytes=262_144,
            maximum_candidates=maximum_candidates,
            mandatory_checks=checks,
        )

    def test_canonical_protocol_has_one_authority_free_owner_and_consumer(self) -> None:
        protocol = self.protocol()
        self.assertEqual(protocol["owner"], "control.engineering")
        self.assertIn("learning.plasticity", protocol["consumers"])
        self.assertEqual(protocol["canonicalEncoding"], "canonical_json_utf8")
        self.assertIs(protocol["denyUnknownCriticalFields"], True)
        self.assertEqual(protocol["authorityDelta"], "none")
        fields = [field["name"] for field in protocol["fields"]]
        self.assertEqual(
            fields,
            [
                "grammarId",
                "version",
                "allowedOperations",
                "protectedPathGlobs",
                "maximumFiles",
                "maximumTextBytes",
                "maximumCandidates",
                "authorityDenyList",
                "mandatoryChecks",
                "semanticDigest",
            ],
        )
        deny_field = next(
            field for field in protocol["fields"] if field["name"] == "authorityDenyList"
        )
        self.assertEqual(tuple(deny_field["items"]["values"]), PROTOCOL_AUTHORITY_DENY_LIST)

    def test_control_producer_is_order_independent_and_semantically_complete(self) -> None:
        first = self.manifest()
        reordered = self.manifest(reverse=True)
        changed = self.manifest(maximum_candidates=15)
        self.assertEqual(first.semantic_digest, reordered.semantic_digest)
        self.assertNotEqual(first.semantic_digest, changed.semantic_digest)
        self.assertEqual(
            plasticity_projection_grammar_digest_v1(first), first.semantic_digest
        )
        self.assertEqual(first.protocol_payload()["semanticDigest"], first.semantic_digest)

    def test_rust_projection_binds_the_same_digest_and_exact_learnable_set(self) -> None:
        policy = (
            ROOT / "codex-rs/hepta-plasticity/src/parameter_mutation_policy_v1.rs"
        ).read_text(encoding="utf-8")
        coverage = (
            ROOT / "codex-rs/hepta-plasticity/src/generator_coverage_v1.rs"
        ).read_text(encoding="utf-8")
        coordinator = (
            ROOT / "codex-rs/hepta-agentd/src/plasticity_iteration_coordinator.rs"
        ).read_text(encoding="utf-8")
        for needle in [
            "pub mutation_grammar_digest: Digest32",
            "EmptyMutationGrammar",
            "bytes.extend_from_slice(policy.mutation_grammar_digest.as_array())",
        ]:
            self.assertIn(needle, policy)
        for needle in [
            "pub expected_learnable_parameter_set_digest: Digest32",
            "pub mutation_grammar_digest: Digest32",
            "GeneratorCoverageTerminalV1",
        ]:
            self.assertIn(needle, coverage)
        for needle in [
            "mutation_grammar_digest",
            "self.context.envelope.grammar_digest",
            "ParameterMutationSurfaceV1::LearnableParameter",
            "expected != request.coverage.expected_parameter_ids",
        ]:
            self.assertIn(needle, coordinator)


if __name__ == "__main__":
    unittest.main()
