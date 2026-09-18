"""Autonomous envelopes cannot edit or rebind their own admission policy."""
from dataclasses import replace
import unittest
from unittest import mock

from control_engineering_v2.candidate import (
    CandidateEnvelope, Mutation, PROTECTED_PREFIXES, generate_candidates,
    sandbox_candidate,
)
from control_engineering_v2.control_plane import EngineeringError


class CandidatePolicyTests(unittest.TestCase):
    def setUp(self):
        self.envelope = CandidateEnvelope("bounded", "a" * 40, ("src",))
        self.mutation = Mutation("add_file", "src/new.rs", replacement_text="safe")

    def test_mandatory_protection_cannot_be_removed_or_case_aliased(self):
        for protected in PROTECTED_PREFIXES:
            for root in (protected, protected.upper()):
                with self.subTest(root=root):
                    envelope = replace(self.envelope, allowed_paths=(root,), protected_paths=())
                    with self.assertRaisesRegex(EngineeringError, "protected_path|invalid_path"):
                        generate_candidates(envelope, (Mutation("delete_file", root),))

    def test_additional_restrictions_and_segment_boundaries_are_preserved(self):
        envelope = replace(self.envelope, protected_paths=("src/private",))
        with self.assertRaisesRegex(EngineeringError, "protected_path"):
            generate_candidates(envelope, (Mutation("delete_file", "src/private/a.rs"),))
        candidates = generate_candidates(envelope, (self.mutation,))
        self.assertEqual(candidates[0].state, "no_change")
        self.assertEqual(candidates[1].changed_paths, ("src/new.rs",))
        sibling = replace(envelope, allowed_paths=("scripts-extra",))
        self.assertEqual(len(generate_candidates(sibling, (
            Mutation("add_file", "scripts-extra/new.py", replacement_text="pass"),
        ))), 2)


    def test_candidate_can_never_edit_its_own_oracle_paths(self):
        for path in (
            "src/tests/test_feature.py",
            "src/test_feature.py",
            "src/feature_tests.rs",
            "src/__tests__/feature.js",
            "src/fixtures/case.json",
            "src/output.golden",
            "src/feature.test.ts",
            "src/feature.spec.js",
            "src/feature_test.go",
            "src/feature_spec.rb",
            "src/feature_test.cpp",
            "src/contract.feature",
            "src/__snapshots__/feature.snap",
            "src/testdata/fixture.json",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(EngineeringError, "candidate_oracle_path"):
                    generate_candidates(
                        self.envelope,
                        (Mutation("add_file", path, replacement_text="x"),),
                    )

    def test_entire_effective_scope_and_budget_are_bound_to_identity(self):
        original = generate_candidates(self.envelope, (self.mutation,))[1]
        variants = (
            {"allowed_paths": ("src", "extra")},
            {"protected_paths": ("src/private",)},
            {"maximum_candidates": 2},
            {"maximum_changed_files": 2},
            {"maximum_diff_bytes": 4096},
            {"wall_time_seconds": 60},
            {"memory_bytes": 128 * 1024**2},
            {"processes": 2},
            {"require_network_isolation": False},
        )
        for change in variants:
            with self.subTest(change=change):
                envelope = replace(self.envelope, **change)
                new = generate_candidates(envelope, (self.mutation,))[1]
                self.assertNotEqual(original.candidate_id, new.candidate_id)
                with mock.patch("control_engineering_v2.candidate._git") as git:
                    with self.assertRaisesRegex(EngineeringError, "candidate_envelope_mismatch"):
                        sandbox_candidate("/unused", envelope, original, (("true",),))
                    git.assert_not_called()

    def test_equivalent_effective_policies_have_identical_candidates(self):
        original = generate_candidates(self.envelope, (self.mutation,))
        reordered = replace(self.envelope, allowed_paths=("src", "src"),
                            protected_paths=tuple(reversed(PROTECTED_PREFIXES)))
        self.assertEqual(generate_candidates(reordered, (self.mutation,)), original)
        empty = replace(self.envelope, protected_paths=())
        self.assertEqual(generate_candidates(empty, (self.mutation,)), original)

    def test_scope_collections_cannot_be_unbounded_or_interpreted_as_characters(self):
        for paths in ("src", ("src",) * 257, iter(("src",)), None):
            with self.subTest(paths=type(paths).__name__):
                for field in ("allowed_paths", "protected_paths"):
                    with self.assertRaisesRegex(EngineeringError, "invalid_path_scope"):
                        generate_candidates(replace(self.envelope, **{field: paths}), ())


if __name__ == "__main__":
    unittest.main()
