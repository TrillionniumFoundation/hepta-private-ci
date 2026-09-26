from __future__ import annotations

import unittest

from control_engineering_v2.control_plane import EngineeringError
from control_engineering_v2.mutation_grammar import (
    PROTOCOL_AUTHORITY_DENY_LIST,
    build_mutation_grammar_manifest_v1,
    plasticity_projection_grammar_digest_v1,
)


class MutationGrammarManifestTests(unittest.TestCase):
    def manifest(self, **changes: object):
        values: dict[str, object] = {
            "grammar_id": "grammar:plasticity:1",
            "version": 1,
            "allowed_operations": ["rewire", "bounded_delta", "split"],
            "protected_path_globs": ["docs/security/**", "codex-rs/kernel/**"],
            "maximum_files": 32,
            "maximum_text_bytes": 262_144,
            "maximum_candidates": 16,
            "mandatory_checks": ["strict-clippy", "plasticity-contract"],
        }
        values.update(changes)
        return build_mutation_grammar_manifest_v1(**values)

    def test_manifest_is_canonical_authority_denying_and_projection_exact(self) -> None:
        first = self.manifest()
        second = self.manifest(
            allowed_operations=["split", "bounded_delta", "rewire"],
            protected_path_globs=["codex-rs/kernel/**", "docs/security/**"],
            mandatory_checks=["plasticity-contract", "strict-clippy"],
        )
        self.assertEqual(first, second)
        self.assertEqual(first.authority_deny_list, PROTOCOL_AUTHORITY_DENY_LIST)
        self.assertEqual(
            plasticity_projection_grammar_digest_v1(first), first.semantic_digest
        )
        self.assertEqual(first.protocol_payload()["semanticDigest"], first.semantic_digest)
        self.assertEqual(
            len(first.protocol_payload()["authorityDenyList"]), 17
        )

    def test_each_semantic_change_changes_digest(self) -> None:
        baseline = self.manifest().semantic_digest
        self.assertNotEqual(
            baseline,
            self.manifest(maximum_candidates=15).semantic_digest,
        )
        self.assertNotEqual(
            baseline,
            self.manifest(mandatory_checks=["strict-clippy"]).semantic_digest,
        )
        self.assertNotEqual(
            baseline,
            self.manifest(allowed_operations=["bounded_delta"]).semantic_digest,
        )

    def test_unknown_duplicate_or_unbounded_values_fail_closed(self) -> None:
        for changes in [
            {"allowed_operations": ["grant_authority"]},
            {"allowed_operations": ["bounded_delta", "bounded_delta"]},
            {"protected_path_globs": []},
            {"maximum_files": 0},
            {"maximum_text_bytes": 2 * 1024 * 1024},
            {"maximum_candidates": 33},
            {"mandatory_checks": []},
        ]:
            with self.subTest(changes=changes):
                with self.assertRaises(EngineeringError):
                    self.manifest(**changes)


if __name__ == "__main__":
    unittest.main()
