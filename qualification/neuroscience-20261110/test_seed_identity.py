"""Fail-closed seed custody identity preflight; synthetic only, not attestation."""
import unittest
from dataclasses import replace
from factorial import ContractError, evaluate_core_ndu
from test_factorial import panel, required, h


class DeclaredSeedIdentityTests(unittest.TestCase):
    def test_two_seed_labels_cannot_reuse_training_seed_digest(self):
        rows = [replace(x, training_seed_digest=h("one-training-seed")) for x in panel(seeds=2)]
        with self.assertRaisesRegex(ContractError, "training seed"):
            evaluate_core_ndu(rows, required_cells=required())

    def test_one_seed_label_cannot_swap_training_digest_by_episode(self):
        rows = [replace(x, training_seed_digest=h("swapped-seed"))
                if x.episode_id == "ep1" else x
                for x in panel(seeds=2, episodes=("ep0", "ep1"))]
        with self.assertRaisesRegex(ContractError, "training seed"):
            evaluate_core_ndu(rows, required_cells=required())

    def test_one_seed_label_cannot_swap_training_digest_by_density(self):
        rows = [replace(x, training_seed_digest=h("dense-other-training"))
                if x.feedback_density == "dense" and x.seed == 0 else x
                for x in panel(seeds=2)]
        with self.assertRaisesRegex(ContractError, "training seed"):
            evaluate_core_ndu(rows, required_cells=required())

    def test_two_seed_labels_cannot_reuse_future_eval_seed_digest(self):
        rows = [replace(x, evaluation_seed_digest=h("shared-B-evaluation-seed"))
                for x in panel(seeds=2)]
        with self.assertRaisesRegex(ContractError, "evaluation seed"):
            evaluate_core_ndu(rows, required_cells=required())

    def test_one_seeds_evaluation_digest_cannot_alias_other_training_seed(self):
        rows = [replace(x, evaluation_seed_digest=h("training-seed:0"))
                if x.seed == 1 else x for x in panel(seeds=2)]
        with self.assertRaisesRegex(ContractError, "training/evaluation seed"):
            evaluate_core_ndu(rows, required_cells=required())

    def test_distinct_eval_seed_per_episode_for_same_training_seed_allowed(self):
        rows = [replace(x, evaluation_seed_digest=h(f"eval:{x.seed}:ep1"))
                if x.episode_id == "ep1" else x
                for x in panel(seeds=2, episodes=("ep0", "ep1"))]
        result = evaluate_core_ndu(rows, required_cells=required())
        self.assertEqual(result["coverage"]["matched_blocks"], 8)
        self.assertEqual(result["research_posture"], "HOLD_NO_GO")


if __name__ == "__main__":
    unittest.main()
