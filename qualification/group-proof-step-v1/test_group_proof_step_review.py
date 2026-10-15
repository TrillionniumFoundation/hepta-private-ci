"""Independent reviewer negative tests, never importing the training oracle."""
import copy
import unittest

from group_proof_step_pilot import execute_campaign
from group_proof_step_review import Invalid, audit


class IndependentReviewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = {
            "schema": "hepta.group.proof-step-three-seed.v1",
            "production_promotion_permitted": False,
            "runs": [execute_campaign(seed, train_count=128, test_count=64)
                     for seed in (41, 47, 53)]}

    def test_actual_replay(self):
        result = audit(self.report)
        self.assertEqual(len(result["runs"]), 3)
        self.assertEqual(result["runs"][0]["cases"], 64)
        self.assertFalse(result["real_multimodal_or_NDU_gain"])

    def mutate(self, modifier):
        value = copy.deepcopy(self.report)
        modifier(value)
        with self.assertRaises(Invalid):
            audit(value)

    def test_changed_public_fact_rejected(self):
        self.mutate(lambda v: v["runs"][0]["source_cases"][0].__setitem__(
            "source_text", v["runs"][0]["source_cases"][0]["source_text"] + "\nn45 has class A."))

    def test_spoofed_score_rejected(self):
        self.mutate(lambda v: v["runs"][0]["summary"]["trained"]["full"].__setitem__("correct", 0))

    def test_spoofed_ground_truth_rejected(self):
        self.mutate(lambda v: v["runs"][1]["source_cases"][0].__setitem__("constructor_label", "Z"))

    def test_duplicated_observation_rejected(self):
        self.mutate(lambda v: v["runs"][0]["observations"].__setitem__(1, v["runs"][0]["observations"][0]))

    def test_wrong_intervention_hash_rejected(self):
        self.mutate(lambda v: v["runs"][0]["observations"][2].__setitem__("source_sha256", "0" * 64))

    def test_unseen_policy_claim_rejected(self):
        self.mutate(lambda v: v["runs"][0]["observations"][0].__setitem__("policy", "native_fbsde"))

    def test_training_lineage_mutation_rejected(self):
        self.mutate(lambda v: v["runs"][0]["training"].__setitem__("trained_weights", [9.0] * 5))

    def test_production_authority_rejected(self):
        self.mutate(lambda v: v["runs"][0].__setitem__("authority", "GRANT"))

    def test_wall_clock_edit_rejected(self):
        self.mutate(lambda v: v["runs"][2]["observations"][7].__setitem__("wall_ns", -1))


if __name__ == "__main__":
    unittest.main()
