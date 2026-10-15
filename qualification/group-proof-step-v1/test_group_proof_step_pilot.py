import unittest
from group_proof_step import counterfactual_panel, parse_public
from group_proof_step_pilot import execute_campaign, make_cohort


class PilotTests(unittest.TestCase):
    def test_source_partition_and_independent_labels(self):
        train = make_cohort(41, "train", 24)
        test = make_cohort(41, "test", 24)
        self.assertFalse({r[2] for r in train} & {r[2] for r in test})
        self.assertEqual({r[1] for r in test}, {chr(65 + i) for i in range(8)})
        for text, answer, group, _ in test:
            self.assertEqual(parse_public(text).source_group_sha256, group)
            self.assertEqual(set(counterfactual_panel(text)), {
                "full", "question_only", "critical_removed", "distractor_removed", "truth_flipped"})

    def test_heldout_policy_causal_contract(self):
        report = execute_campaign(47, train_count=24, test_count=12)
        self.assertEqual(report["training"]["train_source_count"], 24)
        self.assertEqual(len(report["observations"]), 2 * 5 * 12)
        self.assertFalse(report["production_promotion_permitted"])
        for arm in ("question_only", "critical_removed"):
            self.assertEqual(report["summary"]["trained"][arm]["abstain"], 12)


if __name__ == "__main__":
    unittest.main()
