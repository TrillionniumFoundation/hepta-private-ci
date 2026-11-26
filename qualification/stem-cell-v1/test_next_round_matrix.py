import unittest

from next_round_matrix import ARMS, MODALITY_PHASES, REQUIRED_METRICS, build_plan, validate_plan


class NextRoundMatrixTests(unittest.TestCase):
    def test_plan_has_five_required_arms_and_fixed_controls(self):
        plan = build_plan(reader_id="reader-fixed-v1", task_set_id="tasks-fixed-v1")
        validate_plan(plan)
        self.assertEqual(tuple(a["arm_id"] for a in plan["arms"]), ARMS)
        self.assertEqual(tuple(plan["phase_order"]), MODALITY_PHASES)
        self.assertEqual(tuple(plan["required_metrics"]), REQUIRED_METRICS)
        self.assertFalse(plan["promotion_gate"]["production_authorized"])

    def test_split_is_only_candidate_and_ndu_is_explicit(self):
        plan = build_plan(reader_id="r", task_set_id="t")
        by_id = {a["arm_id"]: a for a in plan["arms"]}
        self.assertFalse(by_id["shared_421m_head_no_ndu"]["split"])
        self.assertTrue(by_id["shared_421m_sparse_split_no_ndu"]["split"])
        self.assertTrue(by_id["shared_421m_sparse_split_ndu"]["ndu"])
        self.assertEqual(by_id["shared_421m_sparse_split_ndu"]["modalities"], ["text", "image", "audio"])

    def test_invalid_mutation_is_rejected(self):
        plan = build_plan(reader_id="r", task_set_id="t")
        plan["phase_order"] = ["text", "video", "image", "audio"]
        with self.assertRaises(ValueError):
            validate_plan(plan)


if __name__ == "__main__":
    unittest.main()
