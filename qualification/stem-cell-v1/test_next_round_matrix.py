import copy
import unittest

from next_round_matrix import ARMS, MODALITY_PHASES, REQUIRED_METRICS, build_plan, validate_plan


class NextRoundMatrixTests(unittest.TestCase):
    def test_plan_preserves_required_arms_and_adds_explicit_controls(self):
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
        self.assertEqual([a["ndu"] for a in plan["arms"][:5]],
                         [False, False, False, False, True])
        self.assertEqual([a["ndu"] for a in plan["arms"][5:]], [False] * 4)
        self.assertEqual([a["split"] for a in plan["arms"]],
                         [False, False, False, True, True, False, False, False, True])
        self.assertEqual(by_id["shared_421m_sparse_split_ndu"]["modalities"], ["text", "image", "audio"])

    def test_invalid_mutation_is_rejected(self):
        plan = build_plan(reader_id="r", task_set_id="t")
        plan["phase_order"] = ["text", "video", "image", "audio"]
        with self.assertRaises(ValueError):
            validate_plan(plan)

    def test_fair_split_and_direct_initialization_controls(self):
        plan = build_plan(reader_id="r", task_set_id="t")
        arms = plan["arms"]
        self.assertEqual([a["total_head_budget_params"] for a in arms[:7]],
                         [32_000_000] * 7)
        direct, split = arms[6], arms[3]
        for key in ("logical_cells", "cell_head_budget_params",
                    "total_head_budget_params", "active_cells_per_round_cap"):
            self.assertEqual(direct[key], split[key])
        self.assertEqual((direct["initial_logical_cells"], direct["split"]), (32, False))
        self.assertEqual((split["initial_logical_cells"], split["split"]), (16, True))
        self.assertEqual([a["total_head_budget_params"] for a in arms[7:]],
                         [64_000_000, 64_000_000])

    def test_every_arm_flag_and_budget_mutation_fails_even_with_new_digest(self):
        from next_round_matrix import _digest
        original = build_plan(reader_id="r", task_set_id="t")
        for i in range(len(ARMS)):
            for field in ("ndu", "split", "cell_head_budget_params",
                          "logical_cells", "total_head_budget_params"):
                with self.subTest(arm=i, field=field):
                    plan = copy.deepcopy(original)
                    old = plan["arms"][i][field]
                    plan["arms"][i][field] = not old if type(old) is bool else old + 1
                    plan.pop("plan_id")
                    plan["plan_id"] = _digest(plan)
                    with self.assertRaises(ValueError):
                        validate_plan(plan)

    def test_bool_integer_substitution_and_evidence_forgery_fail(self):
        for mutation in ("integer_bool", "evidence", "unknown", "missing"):
            with self.subTest(mutation=mutation):
                plan = build_plan(reader_id="r", task_set_id="t")
                if mutation == "integer_bool":
                    plan["arms"][0]["ndu"] = 0
                elif mutation == "evidence":
                    plan["evidence_status"]["real_421m_weights_loaded"] = True
                elif mutation == "unknown":
                    plan["override"] = "allow"
                else:
                    del plan["fixed_controls"]
                with self.assertRaises(ValueError):
                    validate_plan(plan)

    def test_all_contrasts_require_observed_work_not_equal_steps(self):
        plan = build_plan(reader_id="r", task_set_id="t")
        self.assertFalse(plan["fixed_controls"]["matched_steps_imply_matched_compute"])
        for contrast in plan["contrasts"]:
            self.assertTrue(contrast["requires_measured_compute_match"])
            self.assertEqual(contrast["actual_match_status"], "unobserved")
        self.assertEqual(len(plan["contrasts"]), 8)

    def test_identity_binds_complete_plan_and_changes_with_inputs(self):
        from next_round_matrix import _digest
        plan = build_plan(reader_id="r", task_set_id="t")
        identity = plan.pop("plan_id")
        self.assertEqual(identity, _digest(plan))
        identities = {build_plan(reader_id=r, task_set_id=t, seed=s)["plan_id"]
                      for r, t, s in (("r", "t", 1), ("s", "t", 1),
                                      ("r", "u", 1), ("r", "t", 2))}
        self.assertEqual(len(identities), 4)

    def test_legacy_empty_and_bad_inputs_rejected(self):
        for bad in (None, {}, {"schema": "hepta.neuron.next-round-matrix.v1"}):
            with self.assertRaises(ValueError):
                validate_plan(bad)
        for seed in (True, 0, -1, 1.0):
            with self.assertRaises(ValueError):
                build_plan(reader_id="r", task_set_id="t", seed=seed)


if __name__ == "__main__":
    unittest.main()
