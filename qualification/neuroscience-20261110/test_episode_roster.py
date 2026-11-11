"""Adversarial preflight: equal counts must not substitute future-B episode labels.

All inputs are synthetic and self-declared; passing is not owner/evaluator attestation.
"""
from dataclasses import replace
import unittest
from factorial import ContractError, evaluate_core_ndu
from test_factorial import panel, required


class EpisodeRosterGateTests(unittest.TestCase):
    def test_equal_counts_cannot_hide_seed_specific_episode_substitution(self):
        rows = panel(seeds=2, densities=("sparse",), episodes=("ep0", "ep1"))
        rows = [replace(r, episode_id="replaced_ep1")
                if r.seed == 1 and r.episode_id == "ep1" else r for r in rows]
        with self.assertRaisesRegex(ContractError, "episode roster"):
            evaluate_core_ndu(rows, required_cells=required(("sparse",)))

    def test_matching_episodes_per_seed_are_accepted_without_claiming_attestation(self):
        report = evaluate_core_ndu(
            panel(seeds=2, densities=("sparse",), episodes=("ep0", "ep1")),
            required_cells=required(("sparse",)),
        )
        self.assertEqual(report["coverage"]["matched_blocks"], 4)
        self.assertEqual(report["research_posture"], "HOLD_NO_GO")

    def test_independently_declared_cell_rosters_may_differ(self):
        rows = panel(seeds=2, episodes=("ep0", "ep1"))
        rows = [replace(r, episode_id="dense_ep1")
                if r.feedback_density == "dense" and r.episode_id == "ep1"
                else r for r in rows]
        report = evaluate_core_ndu(rows, required_cells=required())
        self.assertEqual(report["coverage"]["matched_blocks"], 8)
        self.assertEqual(report["authority"], "DENY_ALL")


if __name__ == "__main__":
    unittest.main()
