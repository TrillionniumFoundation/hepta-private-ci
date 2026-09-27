"""Regression of affected boundaries, not assertions over registry constants."""
import itertools
import unittest

from scripts.hepta_ci_scope import GROUPS, select


class MultiscaleScopeTests(unittest.TestCase):
    def test_neuron_change_covers_model_receipts_and_generation_recovery(self):
        for leaf in ("runtime.rs", "inference_control.rs", "durable_result_store.rs"):
            with self.subTest(leaf=leaf):
                result = select([f"codex-rs/hepta-neuron/src/{leaf}"])
                self.assertEqual({g for g in GROUPS if result[g]}, {"inference", "learning", "lifecycle"})
                self.assertFalse(result["full_repo"])

    def test_mixed_owner_diff_is_the_union_not_the_last_file(self):
        paths = ["codex-rs/hepta-neuron/src/runtime.rs", "codex-rs/hepta-automation/src/taskflow.rs",
                 "codex-rs/hepta-ndu/src/recursive.rs"]
        for ordering in itertools.permutations(paths):
            result = select(ordering)
            self.assertTrue(all(result[g] for g in GROUPS))
            self.assertFalse(result["full_repo"])

    def test_prose_does_not_expand_a_local_neuron_change(self):
        source = "codex-rs/hepta-neuron/src/runtime.rs"
        self.assertEqual(select([source]), select([source, "docs/modules/neuron.runtime/TECHNICAL.md"]))
        self.assertFalse(select(["docs/modules/neuron.runtime/TECHNICAL.md"])["native"])

    def test_adding_a_changed_file_cannot_remove_a_selected_boundary(self):
        leaves = ["README.md", "codex-rs/hepta-neuron/src/runtime.rs",
                  "codex-rs/hepta-automation/src/taskflow.rs", "codex-rs/hepta-agentd/src/state.rs",
                  "codex-rs/Cargo.lock"]
        for paths in itertools.combinations(leaves, 2):
            union = select(paths)
            for path in paths:
                original = select([path])
                self.assertTrue(all(not original[g] or union[g] for g in original))

    def test_unknown_source_and_full_scope_still_fail_conservative(self):
        self.assertTrue(all(select([], force_full=True).values()))
        self.assertTrue(select(["codex-rs/core/src/unknown.rs"])["full_repo"])


if __name__ == "__main__":
    unittest.main()
